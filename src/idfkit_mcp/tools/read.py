"""Model reading and inspection tools."""

from __future__ import annotations

import logging
from typing import Annotated, Any, cast

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
from idfkit_mcp.models import (
    ConvertOsmResult,
    GroupSummary,
    ListObjectsResult,
    ModelSummary,
    ReferencesResult,
    SearchObjectsResult,
)
from idfkit_mcp.serializers import serialize_object
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_LOAD = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=_LOAD)
def load_model(
    file_path: Annotated[str, Field(description="Path to the IDF or epJSON file.")],
    version: Annotated[str | None, Field(description='Version override as "X.Y.Z".')] = None,
) -> ModelSummary:
    """Open an IDF or epJSON file as the active model."""
    from pathlib import Path

    from idfkit import load_epjson, load_idf

    state = get_state()
    path = Path(file_path)
    ver = None
    if version is not None:
        parts = version.split(".")
        ver = (int(parts[0]), int(parts[1]), int(parts[2]))

    if path.suffix.lower() in (".epjson", ".json"):
        doc = load_epjson(str(path), version=ver)
    else:
        doc = load_idf(str(path), version=ver)

    state.document = doc
    state.schema = doc.schema
    state.file_path = path
    state.simulation_result = None
    state.save_session()

    logger.info("Loaded model %s (version=%s, objects=%d)", path, doc.version, len(list(doc.all_objects)))
    return build_model_summary(doc, state)


@mcp.tool(annotations=_LOAD)
def convert_osm_to_idf(
    osm_path: Annotated[str, Field(description="Source .osm path.")],
    output_path: Annotated[str, Field(description="Output .idf path.")],
    allow_newer_versions: Annotated[bool, Field(description="Allow newer OSM versions.")] = True,
    overwrite: Annotated[bool, Field(description="Overwrite existing output.")] = False,
) -> ConvertOsmResult:
    """Convert an OSM model to IDF and load it."""
    from pathlib import Path

    from idfkit import load_idf

    try:
        import openstudio  # type: ignore[import-untyped]
    except ImportError:
        raise ToolError(
            "OpenStudio SDK not available. "
            "Reinstall 'idfkit-mcp' in this environment, or use the Docker image where dependencies are preinstalled."
        ) from None
    openstudio = cast(Any, openstudio)

    input_path = Path(osm_path)
    out_path = Path(output_path)

    if input_path.suffix.lower() != ".osm":
        raise ToolError(f"Input file must have .osm extension: '{input_path}'.")
    if not input_path.exists():
        raise ToolError(f"Input OSM file not found: '{input_path}'.")
    if not input_path.is_file():
        raise ToolError(f"Input OSM path is not a file: '{input_path}'.")

    if out_path.suffix.lower() != ".idf":
        raise ToolError(f"Output file must have .idf extension: '{out_path}'.")
    if out_path.exists() and not overwrite:
        raise ToolError(f"Output file already exists: '{out_path}'. Set overwrite=True to replace it.")
    if not out_path.parent.exists():
        raise ToolError(f"Output directory does not exist: '{out_path.parent}'.")

    # OpenStudio's C++ ForwardTranslator writes warnings directly to fd 1
    # (C-level stdout), which corrupts the MCP stdio JSON-RPC stream.
    # Redirect fd 1 → fd 2 (stderr) during translation to keep the transport clean.
    import os

    saved_fd = os.dup(1)
    os.dup2(2, 1)
    try:
        version_translator = openstudio.osversion.VersionTranslator()
        version_translator.setAllowNewerVersions(allow_newer_versions)
        optional_model = version_translator.loadModel(openstudio.path(str(input_path)))
        if optional_model.empty():
            raise ToolError(f"Failed to load OSM model: '{input_path}'.")

        model = optional_model.get()
        forward_translator = openstudio.energyplus.ForwardTranslator()
        workspace = forward_translator.translateModel(model)

        saved = workspace.save(openstudio.path(str(out_path)), overwrite)
        if not saved:
            raise ToolError(f"Failed to save translated IDF to '{out_path}'.")
    finally:
        os.dup2(saved_fd, 1)
        os.close(saved_fd)

    doc = load_idf(str(out_path))
    state = get_state()
    state.document = doc
    state.schema = doc.schema
    state.file_path = out_path
    state.simulation_result = None
    state.save_session()
    logger.info("Converted OSM %s -> %s", input_path, out_path)

    version_getter = getattr(openstudio, "openStudioVersion", None)
    openstudio_version = str(version_getter()) if callable(version_getter) else "unknown"

    summary = build_model_summary(doc, state)
    return ConvertOsmResult(
        **summary.model_dump(),
        status="converted",
        osm_path=str(input_path),
        output_path=str(out_path),
        openstudio_version=openstudio_version,
        allow_newer_versions=allow_newer_versions,
        translator_warnings_count=len(version_translator.warnings()) + len(forward_translator.warnings()),
        translator_errors_count=len(version_translator.errors()) + len(forward_translator.errors()),
    )


@mcp.tool(annotations=_READ_ONLY)
def list_objects(
    object_type: Annotated[str, Field(description='EnergyPlus object type (e.g. "Zone").')],
    limit: Annotated[int, Field(description="Maximum objects to return.")] = 50,
) -> ListObjectsResult:
    """List objects of a type with names and required fields."""
    limit = min(limit, 200)

    state = get_state()
    doc = state.require_model()

    if object_type not in doc:
        raise ToolError(f"No objects of type '{object_type}' in the model.")

    collection = doc.get_collection(object_type)
    total = len(collection)
    objects = [serialize_object(obj, schema=state.schema, brief=True) for obj in list(collection)[:limit]]

    logger.debug("list_objects: type=%s total=%d returned=%d", object_type, total, len(objects))
    return ListObjectsResult(object_type=object_type, total=total, returned=len(objects), objects=objects)


@mcp.tool(annotations=_READ_ONLY)
def search_objects(
    query: Annotated[str, Field(description="Case-insensitive substring match on name and string fields.")],
    object_type: Annotated[str | None, Field(description="Restrict search to a specific type.")] = None,
    limit: Annotated[int, Field(description="Maximum results to return.")] = 20,
) -> SearchObjectsResult:
    """Find objects by name or field value substring match."""
    limit = min(limit, 100)

    state = get_state()
    doc = state.require_model()
    query_lower = query.lower()

    matches: list[dict[str, str]] = []
    for obj in doc.all_objects:
        if object_type is not None and obj.obj_type != object_type:
            continue
        if _matches_query(obj, query_lower):
            matches.append({"object_type": obj.obj_type, "name": obj.name})
            if len(matches) >= limit:
                break

    logger.debug("search_objects: query=%r type=%s matched=%d", query, object_type, len(matches))
    return SearchObjectsResult.model_validate({"query": query, "count": len(matches), "matches": matches})


def build_references(doc: Any, name: str) -> ReferencesResult:
    """Build a bidirectional references result for a given object name."""
    referencing = doc.get_referencing(name)
    referenced_by = [{"object_type": obj.obj_type, "name": obj.name} for obj in referencing]

    references: list[str] = []
    target_obj = _find_object_by_name(doc, name)
    if target_obj is not None:
        refs = doc.get_references(target_obj)
        references = sorted(refs)

    return ReferencesResult.model_validate({
        "name": name,
        "referenced_by": referenced_by,
        "referenced_by_count": len(referenced_by),
        "references": references,
        "references_count": len(references),
    })


def build_model_summary(doc: Any, state: Any) -> ModelSummary:
    """Build a model summary."""
    from idfkit import version_string

    groups: dict[str, dict[str, int]] = {}
    total_objects = 0
    zone_count = 0

    for obj_type, collection in doc.items():
        count = len(collection)
        total_objects += count
        if obj_type == "Zone":
            zone_count = count
        schema = state.schema
        obj_group = schema.get_group(obj_type) if schema else "Unknown"
        obj_group = obj_group or "Ungrouped"
        groups.setdefault(obj_group, {})[obj_type] = count

    return ModelSummary(
        version=version_string(doc.version),
        file_path=str(state.file_path) if state.file_path else None,
        total_objects=total_objects,
        zone_count=zone_count,
        groups={g: GroupSummary(count=sum(v.values()), types=v) for g, v in sorted(groups.items())},
    )


def _matches_query(obj: Any, query_lower: str) -> bool:
    """Check if an object matches a search query."""
    if query_lower in obj.name.lower():
        return True
    return any(isinstance(value, str) and query_lower in value.lower() for value in obj.data.values())


def _find_object_by_name(doc: Any, name: str) -> Any:
    """Find any object by name across all types using collection index."""
    name_upper = name.upper()
    for collection in doc.collections.values():
        obj = collection.get(name)
        if obj is not None:
            return obj
        # Fallback: case-insensitive scan within this collection only
        for obj in collection:
            if obj.name.upper() == name_upper:
                return obj
    return None
