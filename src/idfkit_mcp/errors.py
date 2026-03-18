"""Unified error formatting for MCP tool responses."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from mcp.server.fastmcp.exceptions import ToolError

_T = TypeVar("_T")


def safe_tool(func: Callable[..., _T]) -> Callable[..., _T]:
    """Convert exceptions into MCP ``ToolError`` instances.

    Decorator for MCP tool functions that catches all exceptions and
    re-raises them as ``ToolError`` with a human-readable message.
    The MCP SDK surfaces these to clients via ``isError=True`` responses.
    """

    @wraps(func)
    def wrapper(*args: object, **kwargs: object) -> _T:
        try:
            return func(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(format_error(e)) from e

    return wrapper


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
