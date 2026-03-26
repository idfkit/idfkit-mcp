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


class ToolExecutionMiddleware(Middleware):
    """Bind session state, normalize errors, and log tool execution."""

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

        with session_scope_from_context(fastmcp_context) as session_id:
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
