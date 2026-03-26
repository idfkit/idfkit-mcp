"""Schema exploration tools — work without a loaded model."""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

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


def list_object_types(group: str | None = None, version: str | None = None, limit: int = 50) -> ListObjectTypesResult:
    """Discover available EnergyPlus object types, optionally filtered by group.

    Use this to browse what object types exist before creating objects.

    When the total exceeds the limit, type names are omitted and only group
    names with counts are returned.  Filter by group to see individual types.

    Args:
        group: Filter to a specific IDD group (e.g. "Thermal Zones and Surfaces").
        version: EnergyPlus version as "X.Y.Z" (default: latest or loaded model version).
        limit: Maximum number of type names to include (default 50).

    Returns:
        Groups with their object type names (or counts only when truncated).
    """
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
    truncated = total_types > limit
    logger.debug("list_object_types: group=%s total=%d truncated=%s", group, total_types, truncated)

    if truncated:
        groups_result = {g: GroupInfo(count=len(types)) for g, types in sorted(groups.items())}
    else:
        groups_result = {g: GroupInfo(count=len(types), types=types) for g, types in sorted(groups.items())}

    return ListObjectTypesResult(total_types=total_types, truncated=truncated, groups=groups_result)


def describe_object_type(object_type: str, version: str | None = None) -> DescribeObjectTypeResult:
    """Get the full field schema for an EnergyPlus object type.

    Use this before creating or editing objects to learn valid fields and constraints.
    Returns field names, types, constraints, defaults, references, memo, and a
    documentation URL for the object on docs.idfkit.com.

    Args:
        object_type: The object type name (e.g. "Zone", "Material").
        version: EnergyPlus version as "X.Y.Z" (default: latest or loaded model version).
    """
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


def search_schema(query: str, version: str | None = None, limit: int = 50) -> SearchSchemaResult:
    """Search for EnergyPlus object types by name or description.

    Use this to find the right object type when you know a keyword but not the exact name.
    Each match includes a ``doc_url`` linking to the object's page on docs.idfkit.com.

    Args:
        query: Search string (case-insensitive substring match).
        version: EnergyPlus version as "X.Y.Z" (default: latest or loaded model version).
        limit: Maximum number of results to return (default 50).
    """
    from idfkit.docs import docs_url_for_object

    limit = min(limit, 50)

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
                "memo": memo[:200] if memo else None,
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


def get_available_references(object_type: str, field_name: str) -> AvailableReferencesResult:
    """Get valid object names for a reference field from the loaded model.

    Use this to find valid values when setting reference fields like zone_name,
    construction_name, etc.

    Args:
        object_type: The object type containing the field.
        field_name: The field name to check.
    """
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
_TOOL_REGISTRY = [
    (list_object_types, _READ_ONLY),
    (describe_object_type, _READ_ONLY),
    (search_schema, _READ_ONLY),
    (get_available_references, _READ_ONLY),
]


def register(mcp: FastMCP) -> None:
    """Register schema tools on the MCP server."""
    for func, hints in _TOOL_REGISTRY:
        mcp.tool(annotations=hints)(func)
