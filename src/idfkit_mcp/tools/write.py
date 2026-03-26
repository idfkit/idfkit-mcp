"""Model creation and editing tools."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from idfkit_mcp.errors import safe_tool
from idfkit_mcp.models import (
    BatchAddResult,
    ClearSessionResult,
    NewModelResult,
    RemoveObjectResult,
    RenameObjectResult,
    SaveModelResult,
)
from idfkit_mcp.serializers import serialize_object
from idfkit_mcp.state import get_state
from idfkit_mcp.tools import resolve_object

logger = logging.getLogger(__name__)

_MUTATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)
_SAVE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@safe_tool
def new_model(version: str | None = None) -> NewModelResult:
    """Create a new empty EnergyPlus model.

    Use this to start building a model from scratch.

    Args:
        version: EnergyPlus version as "X.Y.Z" (default: latest).
    """
    from idfkit import LATEST_VERSION, new_document, version_string

    ver = LATEST_VERSION
    if version is not None:
        parts = version.split(".")
        ver = (int(parts[0]), int(parts[1]), int(parts[2]))

    doc = new_document(version=ver)
    state = get_state()
    state.document = doc
    state.schema = doc.schema
    state.file_path = None
    state.simulation_result = None

    logger.info("Created new model (version=%s)", version_string(ver))
    return NewModelResult(status="created", version=version_string(ver))


@safe_tool
def add_object(object_type: str, name: str = "", fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add a new object to the model.

    Use this to create a single EnergyPlus object. Call describe_object_type first
    to see valid fields for this type.

    Args:
        object_type: The EnergyPlus object type (e.g. "Zone", "Material").
        name: Object name (empty string for unnamed types).
        fields: Field values as {field_name: value}.
    """
    state = get_state()
    doc = state.require_model()
    kwargs = fields or {}
    obj = doc.add(object_type, name, **kwargs)
    logger.info("Added %s %r", object_type, name)
    logger.debug("add_object fields: %s", kwargs)
    return serialize_object(obj)


@safe_tool
def batch_add_objects(objects: list[dict[str, Any]]) -> BatchAddResult:
    """Add multiple objects to the model in a single call.

    Use this when creating multiple objects at once for efficiency — building a zone
    requires many related objects. Each entry should have: object_type (required),
    name (optional), fields (optional). Continues on individual failures and reports
    per-object results.

    Args:
        objects: List of dicts with keys: object_type, name, fields.
    """
    state = get_state()
    doc = state.require_model()

    results: list[dict[str, object]] = []
    success_count = 0
    error_count = 0

    for i, spec in enumerate(objects):
        try:
            obj_type = spec.get("object_type")
            if not obj_type:
                results.append({"index": i, "error": "Missing 'object_type'"})
                error_count += 1
                continue

            obj_name: str = spec.get("name", "")
            obj_fields: dict[str, Any] = spec.get("fields") or {}
            obj = doc.add(obj_type, obj_name, **obj_fields)
            results.append({"index": i, **serialize_object(obj, brief=True)})
            success_count += 1
        except Exception as e:
            results.append({"index": i, "error": str(e)})
            error_count += 1

    logger.info("Batch add: %d total, %d success, %d errors", len(objects), success_count, error_count)
    if error_count:
        logger.warning("batch_add_objects: %d/%d objects failed", error_count, len(objects))
    return BatchAddResult(total=len(objects), success=success_count, errors=error_count, results=results)


@safe_tool
def update_object(object_type: str, name: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Update fields on an existing object.

    Use this to modify field values on an object already in the model.

    Args:
        object_type: The EnergyPlus object type.
        name: The object name.
        fields: Fields to update as {field_name: value}.
    """
    state = get_state()
    doc = state.require_model()
    obj = resolve_object(doc, object_type, name)

    for field_name, value in fields.items():
        setattr(obj, field_name, value)

    logger.info("Updated %s %r (%d fields)", object_type, name, len(fields))
    logger.debug("update_object fields: %s", fields)
    return serialize_object(obj)


@safe_tool
def remove_object(object_type: str, name: str, force: bool = False) -> RemoveObjectResult:
    """Remove an object from the model.

    Use this to delete an object. Refuses removal if other objects reference it
    unless force=True.

    Args:
        object_type: The EnergyPlus object type.
        name: The object name.
        force: If True, remove even if referenced by other objects.
    """
    state = get_state()
    doc = state.require_model()
    obj = resolve_object(doc, object_type, name)

    if not force:
        ref_name = obj.name or name
        referencing = doc.get_referencing(ref_name)
        if referencing:
            refs = [{"object_type": r.obj_type, "name": r.name} for r in referencing]
            raise ToolError(
                f"Object is referenced by other objects. Use force=True to remove anyway.\n{json.dumps(refs)}"
            )

    doc.removeidfobject(obj)
    logger.info("Removed %s %r", object_type, obj.name)
    return RemoveObjectResult(status="removed", object_type=object_type, name=obj.name)


@safe_tool
def rename_object(object_type: str, old_name: str, new_name: str) -> RenameObjectResult:
    """Rename an object and update all references to it.

    Use this to change an object's name while keeping the model consistent.

    Args:
        object_type: The EnergyPlus object type.
        old_name: Current object name.
        new_name: New object name.
    """
    state = get_state()
    doc = state.require_model()

    referencing_before = doc.get_referencing(old_name)
    ref_count = len(referencing_before)

    doc.rename(object_type, old_name, new_name)
    logger.info("Renamed %s %r -> %r (%d references updated)", object_type, old_name, new_name, ref_count)

    return RenameObjectResult(
        status="renamed",
        object_type=object_type,
        old_name=old_name,
        new_name=new_name,
        references_updated=ref_count,
    )


@safe_tool
def duplicate_object(object_type: str, name: str, new_name: str) -> dict[str, Any]:
    """Duplicate an existing object with a new name.

    Use this to copy an object as a starting point for a similar one.

    Args:
        object_type: The EnergyPlus object type.
        name: The source object name.
        new_name: The name for the duplicate.
    """
    state = get_state()
    doc = state.require_model()
    source = resolve_object(doc, object_type, name)

    obj = doc.copyidfobject(source, new_name=new_name)
    logger.info("Duplicated %s %r as %r", object_type, name, new_name)
    return serialize_object(obj)


@safe_tool
def save_model(file_path: str | None = None, output_format: Literal["idf", "epjson"] = "idf") -> SaveModelResult:
    """Save the model to a file.

    Use this to persist changes to disk in IDF or epJSON format.

    Args:
        file_path: Output path. If None, uses the original load path.
        output_format: Output format: "idf" or "epjson".
    """
    from pathlib import Path

    from idfkit import write_epjson, write_idf

    state = get_state()
    doc = state.require_model()

    if file_path is not None:
        path = Path(file_path)
    elif state.file_path is not None:
        path = state.file_path
    else:
        raise ToolError("No file path specified and no original path available.")

    if path.exists():
        logger.warning("Overwriting existing file: %s", path)

    if output_format == "epjson":
        write_epjson(doc, path)
    else:
        write_idf(doc, path)

    state.file_path = path
    state.save_session()
    logger.info("Saved model to %s (format=%s)", path, output_format)
    return SaveModelResult(status="saved", file_path=str(path), format=output_format)


@safe_tool
def clear_session() -> ClearSessionResult:
    """Clear the persisted session and reset all state.

    Use this to start fresh when the restored model or simulation results are
    stale or unwanted.  Does not delete any model or simulation files on disk.
    """
    state = get_state()
    state.clear_session()
    return ClearSessionResult(status="cleared")


# ---------------------------------------------------------------------------
# Tool registry - tools returning dynamic EnergyPlus objects stay
# unstructured; all others get ``structured_output=True``.
# ---------------------------------------------------------------------------

_STRUCTURED_TOOLS = [
    (new_model, _MUTATE),
    (batch_add_objects, _MUTATE),
    (remove_object, _DESTRUCTIVE),
    (rename_object, _MUTATE),
    (save_model, _SAVE),
    (clear_session, _DESTRUCTIVE),
]

_UNSTRUCTURED_TOOLS = [
    (add_object, _MUTATE),
    (update_object, _MUTATE),
    (duplicate_object, _MUTATE),
]


def register(mcp: FastMCP) -> None:
    """Register write tools on the MCP server."""
    for func, hints in _STRUCTURED_TOOLS:
        mcp.tool(annotations=hints, structured_output=True)(func)
    for func, hints in _UNSTRUCTURED_TOOLS:
        mcp.tool(annotations=hints, structured_output=False)(func)
