"""Unified error formatting for MCP tool responses."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any


def safe_tool(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Convert exceptions into MCP-friendly error dicts.

    Decorator for MCP tool functions that catches all exceptions and returns
    structured error responses instead of raising.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return format_error(e)

    return wrapper


def format_error(error: Exception) -> dict[str, Any]:
    """Convert an exception into a structured error dict for tool responses."""
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
        return {"error": "Validation failed", "details": str(error)}
    if isinstance(error, KeyError):
        return {"error": f"Not found: {error}"}
    if isinstance(error, EnergyPlusNotFoundError):
        return {
            "error": "EnergyPlus not found",
            "suggestion": "Install EnergyPlus or set the ENERGYPLUS_DIR environment variable.",
        }
    if isinstance(error, SchemaNotFoundError):
        return {"error": f"Schema not found: {error}"}
    if isinstance(error, VersionNotFoundError):
        return {"error": f"Version not found: {error}"}
    if isinstance(error, UnknownObjectTypeError):
        return {"error": f"Unknown object type: {error}"}
    if isinstance(error, DuplicateObjectError):
        return {"error": f"Duplicate object: {error}"}
    if isinstance(error, SimulationError):
        return {"error": f"Simulation error: {error}"}
    if isinstance(error, RuntimeError):
        return {"error": str(error)}
    return {"error": f"{type(error).__name__}: {error}"}
