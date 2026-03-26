"""MCP tool modules for idfkit."""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError


def resolve_object(doc: Any, object_type: str, name: str) -> Any:
    """Look up an object by type and name, handling singletons correctly.

    Singleton EnergyPlus object types (e.g. SimulationControl, GlobalGeometryRules)
    have no name field — their name is always ``""``.  These objects are not indexed
    by name in ``IDFCollection``, so a regular ``collection.get(name)`` always
    returns ``None``.  This helper detects singletons via the schema and falls back
    to ``collection.first()``.
    """
    if object_type not in doc:
        raise ToolError(f"No objects of type '{object_type}' in the model.")

    collection = doc.get_collection(object_type)
    schema = doc.schema

    # Singleton types have no name field in the schema
    if schema is not None and not schema.has_name(object_type):
        obj = collection.first()
        if obj is None:
            raise ToolError(f"No '{object_type}' object in the model.")
        return obj

    obj = collection.get(name)
    if obj is None:
        raise ToolError(f"Object '{name}' not found in '{object_type}'.")
    return obj
