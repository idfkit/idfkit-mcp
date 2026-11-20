"""Zone properties tool — typed summary of zone geometry, surfaces, constructions, and HVAC."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Literal

from fastmcp.tools import tool
from idfkit import IDFObject
from idfkit.document import AnyIDFDocument
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.models import GetZonePropertiesResult, SurfaceTypeCounts, ZoneProperties
from idfkit_mcp.state import get_state

if TYPE_CHECKING:
    from idfkit.document import AnyBuildingSurfaceDetailed

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Keyed by the schema's spelling, in which idfkit reads every choice whatever case the file used.
_SURFACE_TYPE_MAP: dict[Literal["Wall", "Floor", "Ceiling", "Roof"], str] = {
    "Wall": "walls",
    "Floor": "floors",
    "Ceiling": "ceilings",
    "Roof": "roofs",
}


def _zone_geometry(
    doc: AnyIDFDocument, zone_name: str, has_surfaces: bool
) -> tuple[float | None, float | None, float | None]:
    """Return (floor_area_m2, volume_m3, height_m) or (None, None, None) if no surfaces."""
    if not has_surfaces:
        return None, None, None
    try:
        from idfkit.geometry import calculate_zone_floor_area, calculate_zone_height, calculate_zone_volume

        area = calculate_zone_floor_area(doc, zone_name)
        vol = calculate_zone_volume(doc, zone_name)
        height = calculate_zone_height(doc, zone_name)
        return (
            round(area, 3) if area > 0 else None,
            round(vol, 3) if vol > 0 else None,
            round(height, 3) if height > 0 else None,
        )
    except Exception:
        logger.debug("Could not compute geometry for zone '%s'", zone_name, exc_info=True)
        return None, None, None


def _zone_surfaces(doc: AnyIDFDocument, refs: set[IDFObject]) -> list[AnyBuildingSurfaceDetailed]:
    """The zone's BuildingSurface:Detailed objects, typed as every EnergyPlus release declares them."""
    collection = doc["BuildingSurface:Detailed"]
    surfaces: list[AnyBuildingSurfaceDetailed] = []
    for obj in refs:
        if obj.obj_type != "BuildingSurface:Detailed":
            continue
        surface = collection.get(obj.name)
        if surface is not None:
            surfaces.append(surface)
    return surfaces


def _surface_counts(surfaces: list[AnyBuildingSurfaceDetailed]) -> SurfaceTypeCounts:
    """Count a zone's surfaces by type; one with no surface type counts as other."""
    counts = SurfaceTypeCounts()
    for surface in surfaces:
        # surface_type is required, so reading it blank raises; get() returns None instead.
        has_type = surface.get("surface_type") is not None
        bucket = _SURFACE_TYPE_MAP.get(surface.surface_type, "other") if has_type else "other"
        setattr(counts, bucket, getattr(counts, bucket) + 1)
    return counts


def _fenestration_counts(doc: AnyIDFDocument, surfaces: list[AnyBuildingSurfaceDetailed]) -> tuple[int, int]:
    """Count windows and doors hosted by a zone's surfaces."""
    collection = doc["FenestrationSurface:Detailed"]
    windows = doors = 0
    for surface in surfaces:
        for obj in doc.get_referencing(surface.name):
            if obj.obj_type != "FenestrationSurface:Detailed":
                continue
            fen = collection.get(obj.name)
            if fen is None:
                continue
            # A fenestration surface with no surface type counts as a window, as before.
            if fen.get("surface_type") is not None and fen.surface_type == "Door":
                doors += 1
            else:
                windows += 1
    return windows, doors


def _zone_constructions(surfaces: list[AnyBuildingSurfaceDetailed]) -> list[str]:
    """Unique construction names used by a zone's surfaces."""
    return sorted({surface.construction_name for surface in surfaces if surface.construction_name})


def _zone_schedules(refs: set[IDFObject]) -> list[str]:
    """Schedule names referenced by objects that themselves reference this zone."""
    schedules: set[str] = set()
    for obj in refs:
        for field, value in obj.data.items():
            if "schedule" in field and isinstance(value, str) and value:
                schedules.add(value)
    return sorted(schedules)


def _zone_hvac_connections(refs: set[IDFObject], zone_name: str) -> list[str]:
    """ZoneHVAC:EquipmentConnections names for this zone.

    Falls back to the zone_name field when the connection object itself is unnamed
    (which is valid in EnergyPlus — ZoneHVAC:EquipmentConnections may use the zone
    name as its implicit identifier).
    """
    results: list[str] = []
    for conn in refs:
        if conn.obj_type != "ZoneHVAC:EquipmentConnections":
            continue
        results.append(conn.name or zone_name)
    return results


def _zone_thermostats(refs: set[IDFObject]) -> list[str]:
    """Thermostat control names from ZoneControl:Thermostat for this zone."""
    return [obj.name for obj in refs if obj.obj_type == "ZoneControl:Thermostat" and obj.name]


def _build_zone_properties(doc: AnyIDFDocument, zone_name: str) -> ZoneProperties:
    """Build a ZoneProperties summary for one zone."""
    refs = doc.get_referencing(zone_name)
    surfaces = _zone_surfaces(doc, refs)
    counts = _surface_counts(surfaces)
    has_surfaces = len(surfaces) > 0
    windows, doors = _fenestration_counts(doc, surfaces)
    counts.windows = windows
    counts.doors = doors

    area, vol, height = _zone_geometry(doc, zone_name, has_surfaces)

    return ZoneProperties(
        name=zone_name,
        floor_area_m2=area,
        volume_m3=vol,
        height_m=height,
        surface_counts=counts,
        constructions=_zone_constructions(surfaces),
        schedules=_zone_schedules(refs),
        hvac_connections=_zone_hvac_connections(refs, zone_name),
        thermostats=_zone_thermostats(refs),
    )


@tool(annotations=_READ_ONLY)
def get_zone_properties(
    zone_name: Annotated[str | None, Field(description="Zone name. Omit for all zones.")] = None,
) -> GetZonePropertiesResult:
    """Typed summary of zone geometry, surfaces, constructions, schedules, and HVAC.

    Returns floor area, volume, ceiling height, surface counts by type (walls/floors/roofs/
    windows/doors), unique construction names, schedule names referenced by zone loads,
    HVAC equipment connection names, and thermostat control object names.

    Geometry values (area, volume, height) are calculated from BuildingSurface:Detailed
    vertices and returned as None when no surfaces exist for the zone.

    Preconditions: model loaded.
    Side effects: none — read-only.
    """
    state = get_state()
    doc = state.require_model()

    if zone_name is not None:
        if "Zone" not in doc or doc["Zone"].get(zone_name) is None:
            from fastmcp.exceptions import ToolError

            raise ToolError(f"Zone '{zone_name}' not found in the model.")
        zones = [_build_zone_properties(doc, zone_name)]
    else:
        if "Zone" not in doc:
            return GetZonePropertiesResult(zone_count=0, zones=[])
        zones = [_build_zone_properties(doc, z.name) for z in doc["Zone"]]

    logger.debug("get_zone_properties: returned %d zone(s)", len(zones))
    return GetZonePropertiesResult(zone_count=len(zones), zones=zones)
