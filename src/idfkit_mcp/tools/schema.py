"""Schema exploration tools — work without a loaded model."""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
from idfkit_mcp.errors import tool_error
from idfkit_mcp.models import (
    AvailableReferencesResult,
    DescribeObjectTypeResult,
    GroupInfo,
    ListObjectTypesResult,
    SearchSchemaResult,
)
from idfkit_mcp.serializers import serialize_object_description
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _parse_version(version: str | None) -> tuple[int, int, int] | None:
    """Parse a 'X.Y.Z' version string into a tuple, or return None."""
    if version is None:
        return None
    parts = version.split(".")
    if len(parts) != 3:
        msg = f"Version must be in 'X.Y.Z' format, got '{version}'"
        raise ValueError(msg)
    return (int(parts[0]), int(parts[1]), int(parts[2]))


@mcp.tool(annotations=_READ_ONLY)
def list_object_types(
    group: Annotated[str | None, Field(description='Filter to a group (e.g. "Thermal Zones and Surfaces").')] = None,
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y.Z".')] = None,
    limit: Annotated[int, Field(description="Max type names to include.")] = 50,
) -> ListObjectTypesResult:
    """Browse available EnergyPlus object types. Filter by group to see individual types."""
    limit = min(limit, 100)

    state = get_state()
    schema = state.get_or_load_schema(_parse_version(version))

    groups: dict[str, list[str]] = {}
    for obj_type in schema.object_types:
        g = schema.get_group(obj_type) or "Ungrouped"
        if group is not None and g.lower() != group.lower():
            continue
        groups.setdefault(g, []).append(obj_type)

    total_types = sum(len(v) for v in groups.values())
    truncated = group is None and total_types > limit
    logger.debug("list_object_types: group=%s total=%d truncated=%s", group, total_types, truncated)

    if truncated:
        groups_result = {g: GroupInfo(count=len(types)) for g, types in sorted(groups.items())}
    else:
        groups_result = {g: GroupInfo(count=len(types), types=types) for g, types in sorted(groups.items())}

    return ListObjectTypesResult(total_types=total_types, truncated=truncated, groups=groups_result)


@mcp.tool(annotations=_READ_ONLY)
def describe_object_type(
    object_type: Annotated[str, Field(description='Object type name (e.g. "Zone", "Material").')],
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y.Z".')] = None,
) -> DescribeObjectTypeResult:
    """Get the full field schema: names, types, constraints, defaults, references, and doc URL."""
    from idfkit.docs import docs_url_for_object
    from idfkit.introspection import describe_object_type as _describe

    state = get_state()
    ver_tuple = _parse_version(version)
    schema = state.get_or_load_schema(ver_tuple)
    desc = _describe(schema, object_type)
    logger.debug("describe_object_type: %s version=%s", object_type, version)
    data = serialize_object_description(desc)

    doc_url = _get_doc_url(object_type, ver_tuple, schema, docs_url_for_object)
    data["doc_url"] = doc_url
    return DescribeObjectTypeResult.model_validate(data)


@mcp.tool(annotations=_READ_ONLY)
def search_schema(
    query: Annotated[str, Field(description="Case-insensitive substring match.")],
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y.Z".')] = None,
    limit: Annotated[int, Field(description="Maximum results to return.")] = 10,
) -> SearchSchemaResult:
    """Search for object types by name or description. Use describe_object_type for full details."""
    from idfkit.docs import docs_url_for_object

    limit = min(limit, 30)

    state = get_state()
    ver_tuple = _parse_version(version)
    schema = state.get_or_load_schema(ver_tuple)
    query_lower = query.lower()

    matches: list[dict[str, str | None]] = []
    for obj_type in schema.object_types:
        memo = schema.get_object_memo(obj_type) or ""
        if query_lower in obj_type.lower() or query_lower in memo.lower():
            obj_group = schema.get_group(obj_type) or "Ungrouped"
            doc_url = _get_doc_url(obj_type, ver_tuple, schema, docs_url_for_object)
            matches.append({
                "object_type": obj_type,
                "group": obj_group,
                "memo": memo[:100] if memo else None,
                "doc_url": doc_url,
            })
            if len(matches) >= limit:
                break

    logger.debug("search_schema: query=%r matched=%d/%d", query, len(matches), limit)
    return SearchSchemaResult.model_validate({
        "query": query,
        "count": len(matches),
        "limit": limit,
        "matches": matches,
    })


@mcp.tool(annotations=_READ_ONLY)
def get_available_references(
    object_type: Annotated[str, Field(description="Object type containing the reference field.")],
    field_name: Annotated[str, Field(description="Field name to check.")],
) -> AvailableReferencesResult:
    """Get valid object names for a reference field (e.g. zone_name, construction_name)."""
    state = get_state()
    doc = state.require_model()
    schema = state.require_schema()

    object_lists = schema.get_field_object_list(object_type, field_name)
    if not object_lists:
        raise tool_error(f"Field '{field_name}' on '{object_type}' is not a reference field.")

    available: dict[str, list[str]] = {}
    for list_name in object_lists:
        provider_types = schema.get_types_providing_reference(list_name)
        names: list[str] = []
        for ptype in provider_types:
            if ptype in doc:
                for obj in doc.get_collection(ptype):
                    if obj.name:
                        names.append(obj.name)
        if names:
            available[list_name] = sorted(names)

    all_names = sorted({n for names in available.values() for n in names})
    logger.debug("get_available_references: %s.%s found %d names", object_type, field_name, len(all_names))
    return AvailableReferencesResult(
        object_type=object_type,
        field_name=field_name,
        available_names=all_names,
        by_reference_list=available,
    )


def _get_doc_url(
    obj_type: str,
    ver_tuple: tuple[int, int, int] | None,
    schema: object,
    docs_url_for_object: object,
) -> str | None:
    """Resolve a docs.idfkit.com URL for an object type, returning None on failure."""
    from idfkit.versions import LATEST_VERSION

    try:
        result = docs_url_for_object(obj_type, ver_tuple or LATEST_VERSION, schema)  # type: ignore[operator]
    except Exception:
        return None
    else:
        return result.url if result else None  # type: ignore[union-attr]


# Annotations are defined after functions to avoid forward-reference errors.
