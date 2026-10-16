"""Unified error formatting, logging, and session management for MCP tools."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any, cast

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext

logger = logging.getLogger("idfkit_mcp")

_PAYLOAD_MAX_LEN = 500
"""Maximum characters for truncated payload logging."""

_MUTATION_TOOLS: frozenset[str] = frozenset({
    "add_object",
    "batch_add_objects",
    "update_object",
    "remove_object",
    "rename_object",
    "duplicate_object",
    "new_model",
    "load_model",
    "convert_osm_to_idf",
})


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _summarize_kwargs(kwargs: dict[str, Any]) -> str:
    """Summarize tool input kwargs for log output, truncated."""
    try:
        s = json.dumps(kwargs, default=str)
    except Exception:
        s = str(kwargs)
    return s if len(s) <= _PAYLOAD_MAX_LEN else s[:_PAYLOAD_MAX_LEN] + "…"


def _summarize_result(result: object) -> str:
    """Summarize tool result for log output, truncated."""
    try:
        s = json.dumps(result, default=str)  # type: ignore[reportArgumentType]
    except Exception:
        s = str(result)
    return s if len(s) <= _PAYLOAD_MAX_LEN else s[:_PAYLOAD_MAX_LEN] + "…"


def _summarize_tool_result(result: object) -> str:
    """Summarize a FastMCP tool result for logging."""
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return _summarize_result(structured)
    content = getattr(result, "content", None)
    if content is not None:
        return _summarize_result(content)
    return _summarize_result(result)


def _is_expected(cause: BaseException | None) -> bool:
    """Whether a tool failure's cause is an anticipated error rather than a server defect.

    Anticipated: no cause, a ToolError, an idfkit error, a RuntimeError (the session
    preconditions, such as no model loaded, raise RuntimeError), or a pydantic
    ValidationError (arguments that do not match the tool's schema).
    """
    from idfkit.exceptions import IdfKitError
    from pydantic import ValidationError

    return cause is None or isinstance(cause, (ToolError, IdfKitError, RuntimeError, ValidationError))


class FastMCPToolErrorLogFilter(logging.Filter):
    """Drop FastMCP's own per-call tool and resource error records.

    FastMCP logs every exception raised by a tool or a resource with its traceback before
    re-raising it. ``ToolExecutionMiddleware`` logs each failure once, with the traceback only
    when the cause is a defect, so FastMCP's record is a duplicate.
    """

    _PREFIXES = ("Error calling tool ", "Error validating tool ", "Error reading resource ")

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith(self._PREFIXES)


def _mutation_summary(tool_name: str, result: object) -> str | None:
    """Extract a short human-readable summary from a mutation tool result."""
    structured = getattr(result, "structured_content", None)
    if not isinstance(structured, Mapping):
        return None
    fields = cast(Mapping[str, Any], structured)
    # Prefer named fields that identify what changed
    for key in ("name", "new_name", "file_path", "version", "status"):
        val = fields.get(key)
        if val:
            object_type = fields.get("object_type")
            if object_type and key in ("name", "new_name"):
                return f"{tool_name}: {object_type} {key}={val}"
            return f"{tool_name}: {key}={val}"
    # Fall back to success/error counts for batch operations
    success = fields.get("success")
    errors = fields.get("errors")
    if success is not None and errors is not None:
        return f"{tool_name}: {success} succeeded, {errors} failed"
    return None


class ToolExecutionMiddleware(Middleware):
    """Bind session state, normalize errors, and log tool execution."""

    async def on_read_resource(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        from idfkit_mcp.state import session_scope_from_context

        with session_scope_from_context(context.fastmcp_context, context.message) as session_id:
            logger.debug("READ resource | session=%s | %s", session_id, context.message.uri)
            try:
                return await call_next(context)
            except Exception as e:
                cause = e.__cause__ if e.__cause__ is not None else e
                logger.warning(
                    "FAIL resource %s | session=%s | %s",
                    context.message.uri,
                    session_id,
                    error_text(cause),
                    exc_info=None if _is_expected(cause) else cause,
                )
                raise

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        from idfkit_mcp.state import session_scope_from_context

        fastmcp_context = context.fastmcp_context
        tool_name = context.message.name
        raw_tool_args = context.message.arguments
        if isinstance(raw_tool_args, Mapping):
            typed_tool_args = cast(Mapping[object, Any], raw_tool_args)
            tool_args: dict[str, Any] = {str(key): value for key, value in typed_tool_args.items()}
        else:
            tool_args = {}

        with session_scope_from_context(fastmcp_context, context.message) as session_id:
            logger.debug(
                "CALL %s | session=%s | %s",
                tool_name,
                session_id,
                _summarize_kwargs(tool_args),
            )

            start = time.monotonic()
            try:
                result = await call_next(context)
            except ToolError as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                # FastMCP wraps an exception raised inside a tool as
                # ``ToolError("Error calling tool '<name>': {e}")``. Re-map the original cause of
                # that wrapper only, so that idfkit errors carry their documented category and
                # readable text, while a ToolError the tool raised itself keeps its message.
                cause = e.__cause__
                wrapped = str(e).startswith(f"Error calling tool {tool_name!r}:")
                mapped = (
                    ToolError(format_error(cause))
                    if wrapped and isinstance(cause, Exception) and not isinstance(cause, ToolError)
                    else e
                )
                # An expected tool error is a result for the agent, not a server fault: log
                # one line without a traceback. Any other wrapped cause is a defect, and keeps
                # its traceback.
                logger.warning(
                    "FAIL %s | session=%s | %.1fms | %s",
                    tool_name,
                    session_id,
                    elapsed_ms,
                    mapped,
                    exc_info=None if _is_expected(cause) else cause,
                )
                if mapped is e:
                    raise
                raise mapped from cause
            except Exception as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                error_msg = format_error(e)
                logger.warning(
                    "ERR  %s | session=%s | %.1fms | %s",
                    tool_name,
                    session_id,
                    elapsed_ms,
                    error_msg,
                    exc_info=None if _is_expected(e) else e,
                )
                raise ToolError(error_msg) from e

            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug(
                "OK   %s | session=%s | %.1fms | %s",
                tool_name,
                session_id,
                elapsed_ms,
                _summarize_tool_result(result),
            )

            if tool_name in _MUTATION_TOOLS:
                from idfkit_mcp.state import get_state

                summary = _mutation_summary(tool_name, result)
                get_state().record_change(tool_name, summary)

            return result


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------


def format_error(error: Exception) -> str:
    """Convert an exception into a human-readable error string for tool responses."""
    from idfkit.exceptions import (
        DuplicateObjectError,
        EnergyPlusNotFoundError,
        SchemaNotFoundError,
        SimulationError,
        UnknownObjectTypeError,
        ValidationFailedError,
        VersionNotFoundError,
    )

    if isinstance(error, ValidationFailedError):
        return f"Validation failed: {error}"
    if isinstance(error, UnknownObjectTypeError):
        return error_text(error)
    if isinstance(error, DuplicateObjectError):
        return f"{error_text(error)}. It already exists in the model; use update_object to change its fields."
    if isinstance(error, KeyError):
        return f"Not found: {error_text(error)}"
    if isinstance(error, EnergyPlusNotFoundError):
        return "EnergyPlus not found. Install EnergyPlus or set the ENERGYPLUS_DIR environment variable."
    if isinstance(error, SchemaNotFoundError):
        return f"Schema not found: {error}"
    if isinstance(error, VersionNotFoundError):
        return f"Version not found: {error}"
    if isinstance(error, SimulationError):
        return f"Simulation error: {error}"
    if isinstance(error, RuntimeError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def error_text(error: BaseException) -> str:
    """Return an exception's message as written, without ``KeyError``'s quoting.

    ``str(KeyError("msg"))`` is the repr of its argument, which wraps the message in
    quotes and escapes its newlines. Several idfkit exceptions subclass ``KeyError``.
    """
    if isinstance(error, KeyError) and len(error.args) == 1 and isinstance(error.args[0], str):
        return error.args[0]
    return str(error)


def tool_error(message: str, **extra: object) -> ToolError:
    """Build a ``ToolError`` with optional structured detail.

    Extra keyword arguments are appended as a JSON snippet so that
    clients can still parse structured information from the error text.
    """
    if extra:
        return ToolError(f"{message}\n{json.dumps(extra, default=str)}")
    return ToolError(message)
