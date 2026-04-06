"""Zone properties tool — typed summary of zone geometry, surfaces, constructions, and HVAC."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp.tools import tool
from idfkit import IDFDocument, IDFObject
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.models import GetZonePropertiesResult, SurfaceTypeCounts, ZoneProperties
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

_SURFACE_TYPE_MAP: dict[str, str] = {
    "wall": "walls",
    "floor": "floors",
    "ceiling": "ceilings",
    "roof": "roofs",
}


def _zone_geometry(
    doc: IDFDocument, zone_name: str, has_surfaces: bool
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


def _surface_counts(refs: set[IDFObject]) -> tuple[SurfaceTypeCounts, set[str]]:
    """Count surfaces by type for a zone; return counts and set of host surface names."""
    counts = SurfaceTypeCounts()
    host_surfaces: set[str] = set()

    for surface in refs:
        if surface.obj_type != "BuildingSurface:Detailed":
            continue
        host_surfaces.add(surface.name.lower())
        surface_type = surface.data.get("surface_type", "").lower()
        bucket = _SURFACE_TYPE_MAP.get(surface_type, "other")
        setattr(counts, bucket, getattr(counts, bucket) + 1)

    return counts, host_surfaces


def _fenestration_counts(doc: IDFDocument, host_surfaces: set[str]) -> tuple[int, int]:
    """Count windows and doors for surfaces in this zone."""
    windows = doors = 0
    for host_name in host_surfaces:
        for fen in doc.get_referencing(host_name):
            if fen.obj_type != "FenestrationSurface:Detailed":
                continue
            if fen.data.get("surface_type", "").lower() == "door":
                doors += 1
            else:
                windows += 1
    return windows, doors


def _zone_constructions(refs: set[IDFObject]) -> list[str]:
    """Unique construction names used by surfaces in this zone."""
    names: set[str] = set()
    for surface in refs:
        if surface.obj_type != "BuildingSurface:Detailed":
            continue
        cn = surface.data.get("construction_name", "")
        if cn:
            names.add(cn)
    return sorted(names)


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


def _build_zone_properties(doc: IDFDocument, zone_name: str) -> ZoneProperties:
    """Build a ZoneProperties summary for one zone."""
    refs = doc.get_referencing(zone_name)
    counts, host_surfaces = _surface_counts(refs)
    has_surfaces = len(host_surfaces) > 0
    windows, doors = _fenestration_counts(doc, host_surfaces)
    counts.windows = windows
    counts.doors = doors

    area, vol, height = _zone_geometry(doc, zone_name, has_surfaces)

    return ZoneProperties(
        name=zone_name,
        floor_area_m2=area,
        volume_m3=vol,
        height_m=height,
        surface_counts=counts,
        constructions=_zone_constructions(refs),
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
        if "Zone" not in doc or doc.get_collection("Zone").get(zone_name) is None:
            from fastmcp.exceptions import ToolError

            raise ToolError(f"Zone '{zone_name}' not found in the model.")
        zones = [_build_zone_properties(doc, zone_name)]
    else:
        if "Zone" not in doc:
            return GetZonePropertiesResult(zone_count=0, zones=[])
        zones = [_build_zone_properties(doc, z.name) for z in doc.get_collection("Zone")]

    logger.debug("get_zone_properties: returned %d zone(s)", len(zones))
    return GetZonePropertiesResult(zone_count=len(zones), zones=zones)
