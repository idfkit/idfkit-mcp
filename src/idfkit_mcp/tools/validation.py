"""Model validation tools."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from idfkit_mcp.errors import safe_tool
from idfkit_mcp.models import CheckReferencesResult, ValidationResult
from idfkit_mcp.serializers import serialize_validation_result
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@safe_tool
def validate_model(object_types: list[str] | None = None, check_references: bool = True) -> ValidationResult:
    """Validate the loaded model against the EnergyPlus schema.

    Use this after making modifications to check for errors before simulation.

    Args:
        object_types: Only validate specific types (default: all).
        check_references: Whether to check reference integrity (default: True).
    """
    from idfkit import validate_document

    state = get_state()
    doc = state.require_model()
    if not list(doc.all_objects):
        logger.warning("validate_model: model has no objects")
    result = validate_document(doc, check_references=check_references, object_types=object_types)
    data = serialize_validation_result(result, version=doc.version)  # type: ignore[arg-type]
    logger.info(
        "Validation complete: %d errors, %d warnings",
        data.get("error_count", 0),
        data.get("warning_count", 0),
    )
    return ValidationResult.model_validate(data)


@safe_tool
def check_references(limit: int = 100) -> CheckReferencesResult:
    """Check for dangling references in the loaded model.

    Use this to find references that point to non-existent objects.

    Args:
        limit: Maximum number of dangling references to return (default 100).
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

    total = len(dangling)
    if total:
        logger.warning("Found %d dangling reference(s)", total)
    else:
        logger.info("No dangling references found")
    limited = dangling[:limit]
    return CheckReferencesResult.model_validate({
        "dangling_count": total,
        "returned": len(limited),
        "dangling_references": limited,
    })


# Annotations are defined after functions to avoid forward-reference errors.
_TOOL_REGISTRY = [
    (validate_model, _READ_ONLY),
    (check_references, _READ_ONLY),
]


def register(mcp: FastMCP) -> None:
    """Register validation tools on the MCP server."""
    for func, hints in _TOOL_REGISTRY:
        mcp.tool(annotations=hints, structured_output=True)(func)
