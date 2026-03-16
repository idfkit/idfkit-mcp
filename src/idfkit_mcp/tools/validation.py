"""Model validation tools."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp.server.fastmcp import FastMCP

from idfkit_mcp.errors import format_error
from idfkit_mcp.serializers import serialize_validation_result
from idfkit_mcp.state import get_state


def _safe_tool(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Convert exceptions into MCP-friendly error dicts."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return format_error(e)

    return wrapper


def register(mcp: FastMCP) -> None:
    """Register validation tools on the MCP server."""
    mcp.tool()(validate_model)
    mcp.tool()(check_references)


@_safe_tool
def validate_model(object_types: list[str] | None = None, check_references: bool = True) -> dict[str, Any]:
    """Validate the loaded model against the EnergyPlus schema.

    Args:
        object_types: Only validate specific types (default: all).
        check_references: Whether to check reference integrity (default: True).
    """
    from idfkit import validate_document

    state = get_state()
    doc = state.require_model()
    result = validate_document(doc, check_references=check_references, object_types=object_types)
    return serialize_validation_result(result)


@_safe_tool
def check_references() -> dict[str, Any]:
    """Check for dangling references in the loaded model.

    Returns a list of references that point to non-existent objects.
    """
    state = get_state()
    doc = state.require_model()

    valid_names: set[str] = set()
    for collection in doc.collections.values():
        for obj in collection:
            if obj.name:
                valid_names.add(obj.name.upper())

    dangling: list[dict[str, str]] = []
    for obj, field_name, target in doc.references.get_dangling_references(valid_names):
        dangling.append({
            "source_type": obj.obj_type,
            "source_name": obj.name,
            "field": field_name,
            "missing_target": target,
        })

    return {"dangling_count": len(dangling), "dangling_references": dangling}
