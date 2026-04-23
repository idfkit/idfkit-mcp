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


def _mutation_summary(tool_name: str, result: object) -> str | None:
    """Extract a short human-readable summary from a mutation tool result."""
    structured = getattr(result, "structured_content", None)
    if structured is None:
        return None
    # Prefer named fields that identify what changed
    for key in ("name", "new_name", "file_path", "version", "status"):
        val = getattr(structured, key, None)
        if val:
            return f"{tool_name}: {key}={val}"
    # Fall back to success/error counts for batch operations
    success = getattr(structured, "success", None)
    errors = getattr(structured, "errors", None)
    if success is not None and errors is not None:
        return f"{tool_name}: {success} succeeded, {errors} failed"
    return None


class ToolExecutionMiddleware(Middleware):
    """Bind session state, normalize errors, and log tool execution."""

    async def on_read_resource(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        from idfkit_mcp.state import session_scope_from_context

        with session_scope_from_context(context.fastmcp_context, context.message) as session_id:
            logger.debug("READ resource | session=%s | %s", session_id, context.message.uri)
            return await call_next(context)

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
            except ToolError:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.warning(
                    "FAIL %s | session=%s | %.1fms",
                    tool_name,
                    session_id,
                    elapsed_ms,
                    exc_info=True,
                )
                raise
            except Exception as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                error_msg = format_error(e)
                logger.exception(
                    "ERR  %s | session=%s | %.1fms | %s",
                    tool_name,
                    session_id,
                    elapsed_ms,
                    error_msg,
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
    if isinstance(error, KeyError):
        return f"Not found: {error}"
    if isinstance(error, EnergyPlusNotFoundError):
        return "EnergyPlus not found. Install EnergyPlus or set the ENERGYPLUS_DIR environment variable."
    if isinstance(error, SchemaNotFoundError):
        return f"Schema not found: {error}"
    if isinstance(error, VersionNotFoundError):
        return f"Version not found: {error}"
    if isinstance(error, UnknownObjectTypeError):
        return f"Unknown object type: {error}"
    if isinstance(error, DuplicateObjectError):
        return f"Duplicate object: {error}"
    if isinstance(error, SimulationError):
        return f"Simulation error: {error}"
    if isinstance(error, RuntimeError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def tool_error(message: str, **extra: object) -> ToolError:
    """Build a ``ToolError`` with optional structured detail.

    Extra keyword arguments are appended as a JSON snippet so that
    clients can still parse structured information from the error text.
    """
    if extra:
        return ToolError(f"{message}\n{json.dumps(extra, default=str)}")
    return ToolError(message)
