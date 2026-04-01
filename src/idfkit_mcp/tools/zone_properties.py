"""Zone properties tool — typed summary of zone geometry, surfaces, constructions, and HVAC."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
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


def _zone_geometry(doc: Any, zone_name: str, has_surfaces: bool) -> tuple[float | None, float | None, float | None]:
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


def _surface_counts(doc: Any, zone_name: str) -> tuple[SurfaceTypeCounts, set[str]]:
    """Count surfaces by type for a zone; return counts and set of host surface names."""
    counts = SurfaceTypeCounts()
    host_surfaces: set[str] = set()

    if "BuildingSurface:Detailed" not in doc:
        return counts, host_surfaces

    for surface in doc.get_collection("BuildingSurface:Detailed"):
        if surface.data.get("zone_name", "").lower() != zone_name.lower():
            continue
        host_surfaces.add(surface.name.lower())
        surface_type = surface.data.get("surface_type", "").lower()
        bucket = _SURFACE_TYPE_MAP.get(surface_type, "other")
        setattr(counts, bucket, getattr(counts, bucket) + 1)

    return counts, host_surfaces


def _fenestration_counts(doc: Any, host_surfaces: set[str]) -> tuple[int, int]:
    """Count windows and doors for surfaces in this zone."""
    windows = doors = 0
    if "FenestrationSurface:Detailed" not in doc:
        return windows, doors
    for fen in doc.get_collection("FenestrationSurface:Detailed"):
        if fen.data.get("building_surface_name", "").lower() not in host_surfaces:
            continue
        if fen.data.get("surface_type", "").lower() == "door":
            doors += 1
        else:
            windows += 1
    return windows, doors


def _zone_constructions(doc: Any, zone_name: str) -> list[str]:
    """Unique construction names used by surfaces in this zone."""
    names: set[str] = set()
    if "BuildingSurface:Detailed" in doc:
        for surface in doc.get_collection("BuildingSurface:Detailed"):
            if surface.data.get("zone_name", "").lower() != zone_name.lower():
                continue
            cn = surface.data.get("construction_name", "")
            if cn:
                names.add(cn)
    return sorted(names)


def _zone_schedules(doc: Any, zone_name: str) -> list[str]:
    """Schedule names referenced by objects that themselves reference this zone."""
    schedules: set[str] = set()
    for obj in doc.get_referencing(zone_name):
        for field, value in obj.data.items():
            if "schedule" in field and isinstance(value, str) and value:
                schedules.add(value)
    return sorted(schedules)


def _zone_hvac_connections(doc: Any, zone_name: str) -> list[str]:
    """ZoneHVAC:EquipmentConnections names for this zone.

    Falls back to the zone_name field when the connection object itself is unnamed
    (which is valid in EnergyPlus — ZoneHVAC:EquipmentConnections may use the zone
    name as its implicit identifier).
    """
    if "ZoneHVAC:EquipmentConnections" not in doc:
        return []
    results: list[str] = []
    for conn in doc.get_collection("ZoneHVAC:EquipmentConnections"):
        if conn.data.get("zone_name", "").lower() != zone_name.lower():
            continue
        # Use explicit name if present; fall back to zone_name (the implicit key)
        results.append(conn.name or conn.data.get("zone_name", zone_name))
    return results


def _zone_thermostats(doc: Any, zone_name: str) -> list[str]:
    """Control object names from ZoneControl:Thermostat for this zone."""
    if "ZoneControl:Thermostat" not in doc:
        return []
    thermostats: list[str] = []
    for ctrl in doc.get_collection("ZoneControl:Thermostat"):
        zl = ctrl.data.get("zone_or_zonelist_or_space_or_spacelist_name", "")
        if not zl:
            zl = ctrl.data.get("zone_or_zonelist_name", "")
        if zl.lower() == zone_name.lower():
            control_name = ctrl.data.get("control_object_name", "")
            if control_name:
                thermostats.append(control_name)
    return thermostats


def _build_zone_properties(doc: Any, zone_name: str) -> ZoneProperties:
    """Build a ZoneProperties summary for one zone."""
    counts, host_surfaces = _surface_counts(doc, zone_name)
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
        constructions=_zone_constructions(doc, zone_name),
        schedules=_zone_schedules(doc, zone_name),
        hvac_connections=_zone_hvac_connections(doc, zone_name),
        thermostats=_zone_thermostats(doc, zone_name),
    )


@mcp.tool(annotations=_READ_ONLY)
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
