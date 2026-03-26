"""Unified error formatting, logging, and session management for MCP tools."""

from __future__ import annotations

import inspect
import json
import logging
import time
import typing
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

_T = TypeVar("_T")

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


# ---------------------------------------------------------------------------
# Tool decorator
# ---------------------------------------------------------------------------


def safe_tool(func: Callable[..., _T]) -> Callable[..., _T]:
    """Decorator for MCP tool functions.

    Wraps each tool invocation with:

    1. **Per-session state** — extracts the MCP session ID from an
       auto-injected ``Context`` and sets the ``contextvars`` token so
       that :func:`~idfkit_mcp.state.get_state` returns the correct
       per-session :class:`~idfkit_mcp.state.ServerState`.
    2. **Error handling** — catches all exceptions and re-raises them as
       ``ToolError`` with a human-readable message.
    3. **Logging** — emits structured log lines for every call with tool
       name, session ID, wall-clock timing (ms), and truncated payloads.
    """

    @wraps(func)
    def wrapper(*args: object, **kwargs: object) -> _T:
        # Pop the Context injected by FastMCP (not visible to clients).
        ctx = kwargs.pop("ctx", None)
        if ctx is not None:
            from idfkit_mcp.state import set_session_from_context

            session_id = set_session_from_context(ctx)
        else:
            session_id = "local"

        tool_name = func.__name__
        logger.debug(
            "CALL %s | session=%s | %s",
            tool_name,
            session_id,
            _summarize_kwargs(dict(kwargs)),  # type: ignore[arg-type]
        )

        start = time.monotonic()
        try:
            result = func(*args, **kwargs)
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
        else:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug(
                "OK   %s | session=%s | %.1fms | %s",
                tool_name,
                session_id,
                elapsed_ms,
                _summarize_result(result),
            )
            return result

    # Build a fully-resolved signature for the wrapper that includes a
    # ``ctx: Context`` parameter.  We must resolve string annotations
    # (from ``from __future__ import annotations``) using the ORIGINAL
    # function's module globals — the wrapper lives in errors.py which
    # does not have the tool-specific return types in scope.
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = {}

    sig = inspect.signature(func)
    resolved_params = [
        param.replace(annotation=hints.get(name, param.annotation)) for name, param in sig.parameters.items()
    ]
    resolved_params.append(inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context))

    wrapper.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=resolved_params,
        return_annotation=hints.get("return", sig.return_annotation),
    )

    return wrapper  # type: ignore[return-value]


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
