"""Schema exploration tools — work without a loaded model."""

from __future__ import annotations

import functools
import logging
from typing import Annotated

from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

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


# Cache schema introspection results keyed by (object_type, schema_id).
# Schema objects are singletons per version, so id() is a stable key.
@functools.lru_cache(maxsize=256)
def _cached_describe(obj_type: str, schema_id: int) -> dict[str, object]:
    """Cache-wrapped schema introspection and serialization."""
    from idfkit.introspection import describe_object_type as _describe

    from idfkit_mcp.state import get_state as _gs

    schema = _gs().get_or_load_schema(None)
    # Validate that the schema id still matches (defensive)
    if id(schema) != schema_id:
        schema = _gs().get_or_load_schema(None)
    desc = _describe(schema, obj_type)
    return serialize_object_description(desc)


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


@tool(annotations=_READ_ONLY)
def list_object_types(
    group: Annotated[str | None, Field(description='Filter to a group (e.g. "Thermal Zones and Surfaces").')] = None,
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y.Z".')] = None,
    limit: Annotated[int, Field(description="Max type names to include.")] = 50,
) -> ListObjectTypesResult:
    """Browse object types grouped by category. Filter by group to list individual types."""
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


@tool(annotations=_READ_ONLY)
def describe_object_type(
    object_type: Annotated[str, Field(description='Object type name (e.g. "Zone", "Material").')],
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y.Z".')] = None,
) -> DescribeObjectTypeResult:
    """Field schema with types, constraints, defaults, and references. Call before adding objects."""
    from idfkit.docs import docs_url_for_object

    state = get_state()
    ver_tuple = _parse_version(version)
    schema = state.get_or_load_schema(ver_tuple)
    logger.debug("describe_object_type: %s version=%s", object_type, version)

    # Use cache for the expensive introspection + serialization step
    data = dict(_cached_describe(object_type, id(schema)))

    doc_url = _get_doc_url(object_type, ver_tuple, schema, docs_url_for_object)
    data["doc_url"] = doc_url
    return DescribeObjectTypeResult.model_validate(data)


@tool(annotations=_READ_ONLY)
def search_schema(
    query: Annotated[str, Field(description="Case-insensitive substring match.")],
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y.Z".')] = None,
    limit: Annotated[int, Field(description="Maximum results to return.")] = 10,
) -> SearchSchemaResult:
    """Find object types by name or description."""
    from idfkit.docs import docs_url_for_object

    limit = min(limit, 30)

    if not query.strip():
        return SearchSchemaResult.model_validate({"query": query, "count": 0, "limit": limit, "matches": []})

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
                "memo": memo[:60] if memo else None,
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


@tool(annotations=_READ_ONLY)
def get_available_references(
    object_type: Annotated[str, Field(description="Object type containing the reference field.")],
    field_name: Annotated[str, Field(description="Field name to check.")],
) -> AvailableReferencesResult:
    """List valid names for a reference field (e.g. zone_name)."""
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
