"""Compact output schemas for the graph tools (SC-010, research R-12).

FastMCP dereferences every ``$ref`` before listing a tool, so a response model that nests shared
sub-models (``ObjectKey`` in every ``NodeUse`` and ``FlowEdge``) is copied out in full at each use.
``HVACTrace`` listed that way cost about 2,000 tokens of ``tools/list``, more than every new tool of
the feature is allowed together. The MCP SDK also checks the schema itself against the metaschema
on every call, on the server and again on the client, so a large schema is slow as well as costly.

A compact schema keeps what an agent reads before calling: the top-level fields, their JSON types
and which are required. Nested objects are listed as objects, and array items as objects, with no
field lists. The schema is derived from the model, so it cannot drift from it. The server still
builds every response through the Pydantic model, which types every nested field, and the tool's
documentation page gives the full shape.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel

_SCALARS = frozenset({"string", "integer", "number", "boolean", "null"})


def _kind(prop: dict[str, Any]) -> dict[str, Any]:
    """Reduce one property schema to its JSON type, with object and array contents left open."""
    if "anyOf" in prop:
        types: list[str] = []
        for alt in cast("list[dict[str, Any]]", prop["anyOf"]):
            reduced = _kind(alt)
            kind = reduced.get("type")
            if isinstance(kind, str) and kind not in types:
                types.append(kind)
        return {"type": types[0] if len(types) == 1 else types}
    if "$ref" in prop or "properties" in prop or prop.get("type") == "object":
        return {"type": "object"}
    kind = prop.get("type")
    if kind == "array":
        items = cast("dict[str, Any]", prop.get("items", {}))
        item_kind = _kind(items).get("type") if items else None
        return {"type": "array", "items": {"type": item_kind}} if item_kind else {"type": "array"}
    if "enum" in prop:
        return {"enum": prop["enum"]}
    if "const" in prop:
        return {"const": prop["const"]}
    if isinstance(kind, str) and kind in _SCALARS:
        return {"type": kind}
    return {}


def compact_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The top level of *model*'s serialisation schema, nested contents left open."""
    full = model.model_json_schema(mode="serialization")
    properties = cast("dict[str, dict[str, Any]]", full.get("properties", {}))
    return {
        "type": "object",
        "properties": {name: _kind(prop) for name, prop in properties.items()},
        "required": list(full.get("required", [])),
    }
