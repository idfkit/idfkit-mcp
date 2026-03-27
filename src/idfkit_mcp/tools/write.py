"""Model creation and editing tools."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
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


@mcp.tool(annotations=_MUTATE)
def new_model(
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y.Z" (default: latest).')] = None,
) -> NewModelResult:
    """Create a new empty EnergyPlus model."""
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


@mcp.tool(annotations=_MUTATE, output_schema=None)
def add_object(
    object_type: Annotated[str, Field(description='EnergyPlus object type (e.g. "Zone", "Material").')],
    name: Annotated[str, Field(description="Object name (empty for unnamed types).")] = "",
    fields: Annotated[dict[str, Any] | None, Field(description="Field values as {field_name: value}.")] = None,
) -> dict[str, Any]:
    """Add a new object. Call describe_object_type first to see valid fields."""
    state = get_state()
    doc = state.require_model()
    kwargs = fields or {}
    obj = doc.add(object_type, name, **kwargs)
    logger.info("Added %s %r", object_type, name)
    logger.debug("add_object fields: %s", kwargs)
    return serialize_object(obj)


@mcp.tool(annotations=_MUTATE)
def batch_add_objects(
    objects: Annotated[list[dict[str, Any]], Field(description="List of dicts with keys: object_type, name, fields.")],
) -> BatchAddResult:
    """Add multiple objects in one call. Continues on failures and reports per-object results."""
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


@mcp.tool(annotations=_MUTATE, output_schema=None)
def update_object(
    object_type: Annotated[str, Field(description="EnergyPlus object type.")],
    name: Annotated[str, Field(description="Object name.")],
    fields: Annotated[dict[str, Any], Field(description="Fields to update as {field_name: value}.")],
) -> dict[str, Any]:
    """Update fields on an existing object."""
    state = get_state()
    doc = state.require_model()
    obj = resolve_object(doc, object_type, name)

    for field_name, value in fields.items():
        setattr(obj, field_name, value)

    logger.info("Updated %s %r (%d fields)", object_type, name, len(fields))
    logger.debug("update_object fields: %s", fields)
    return serialize_object(obj)


@mcp.tool(annotations=_DESTRUCTIVE)
def remove_object(
    object_type: Annotated[str, Field(description="EnergyPlus object type.")],
    name: Annotated[str, Field(description="Object name.")],
    force: Annotated[bool, Field(description="Remove even if referenced by other objects.")] = False,
) -> RemoveObjectResult:
    """Remove an object. Refuses if other objects reference it unless force=True."""
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


@mcp.tool(annotations=_MUTATE)
def rename_object(
    object_type: Annotated[str, Field(description="EnergyPlus object type.")],
    old_name: Annotated[str, Field(description="Current object name.")],
    new_name: Annotated[str, Field(description="New object name.")],
) -> RenameObjectResult:
    """Rename an object and update all references to it."""
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


@mcp.tool(annotations=_MUTATE, output_schema=None)
def duplicate_object(
    object_type: Annotated[str, Field(description="EnergyPlus object type.")],
    name: Annotated[str, Field(description="Source object name.")],
    new_name: Annotated[str, Field(description="Name for the duplicate.")],
) -> dict[str, Any]:
    """Duplicate an existing object with a new name."""
    state = get_state()
    doc = state.require_model()
    source = resolve_object(doc, object_type, name)

    obj = doc.copyidfobject(source, new_name=new_name)
    logger.info("Duplicated %s %r as %r", object_type, name, new_name)
    return serialize_object(obj)


@mcp.tool(annotations=_SAVE)
def save_model(
    file_path: Annotated[str | None, Field(description="Output path (default: original load path).")] = None,
    output_format: Annotated[Literal["idf", "epjson"], Field(description="Output format.")] = "idf",
) -> SaveModelResult:
    """Save the model to disk in IDF or epJSON format."""
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


@mcp.tool(annotations=_DESTRUCTIVE)
def clear_session() -> ClearSessionResult:
    """Clear the persisted session and reset all state. Does not delete files on disk."""
    state = get_state()
    state.clear_session()
    return ClearSessionResult(status="cleared")


# ---------------------------------------------------------------------------
# Tool registry - tools returning dynamic EnergyPlus objects stay
# unstructured; all others get ``structured_output=True``.
# ---------------------------------------------------------------------------
