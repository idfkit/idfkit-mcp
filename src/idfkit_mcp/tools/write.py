"""Model creation and editing tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from idfkit_mcp.errors import safe_tool
from idfkit_mcp.serializers import serialize_object
from idfkit_mcp.state import get_state

_MUTATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)
_SAVE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@safe_tool
def new_model(version: str | None = None) -> dict[str, Any]:
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

    return {"status": "created", "version": version_string(ver)}


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
    return serialize_object(obj)


@safe_tool
def batch_add_objects(objects: list[dict[str, Any]]) -> dict[str, Any]:
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

    results: list[dict[str, Any]] = []
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

    return {"total": len(objects), "success": success_count, "errors": error_count, "results": results}


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

    if object_type not in doc:
        return {"error": f"No objects of type '{object_type}' in the model."}

    obj = doc.get_collection(object_type).get(name)
    if obj is None:
        return {"error": f"Object '{name}' not found in '{object_type}'."}

    for field_name, value in fields.items():
        setattr(obj, field_name, value)

    return serialize_object(obj)


@safe_tool
def remove_object(object_type: str, name: str, force: bool = False) -> dict[str, Any]:
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

    if object_type not in doc:
        return {"error": f"No objects of type '{object_type}' in the model."}

    obj = doc.get_collection(object_type).get(name)
    if obj is None:
        return {"error": f"Object '{name}' not found in '{object_type}'."}

    if not force:
        referencing = doc.get_referencing(name)
        if referencing:
            refs = [{"object_type": r.obj_type, "name": r.name} for r in referencing]
            return {
                "error": "Object is referenced by other objects. Use force=True to remove anyway.",
                "referenced_by": refs,
            }

    doc.removeidfobject(obj)
    return {"status": "removed", "object_type": object_type, "name": name}


@safe_tool
def rename_object(object_type: str, old_name: str, new_name: str) -> dict[str, Any]:
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

    return {
        "status": "renamed",
        "object_type": object_type,
        "old_name": old_name,
        "new_name": new_name,
        "references_updated": ref_count,
    }


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

    obj = doc.copyidfobject(doc.get_collection(object_type)[name], new_name=new_name)
    return serialize_object(obj)


@safe_tool
def save_model(file_path: str | None = None, output_format: Literal["idf", "epjson"] = "idf") -> dict[str, Any]:
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
        return {"error": "No file path specified and no original path available."}

    if output_format == "epjson":
        write_epjson(doc, path)
    else:
        write_idf(doc, path)

    state.file_path = path
    return {"status": "saved", "file_path": str(path), "format": output_format}


# Annotations are defined after functions to avoid forward-reference errors.
_TOOL_REGISTRY = [
    (new_model, _MUTATE),
    (add_object, _MUTATE),
    (batch_add_objects, _MUTATE),
    (update_object, _MUTATE),
    (remove_object, _DESTRUCTIVE),
    (rename_object, _MUTATE),
    (duplicate_object, _MUTATE),
    (save_model, _SAVE),
]


def register(mcp: FastMCP) -> None:
    """Register write tools on the MCP server."""
    for func, hints in _TOOL_REGISTRY:
        mcp.tool(annotations=hints)(func)
