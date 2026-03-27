"""3D geometry viewer tool — renders building surfaces in an interactive Three.js viewport."""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Annotated, Literal

from fastmcp.server.apps import AppConfig, ResourceCSP
from fastmcp.tools import ToolResult
from mcp.types import TextContent, ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
from idfkit_mcp.state import get_state
from idfkit_mcp.viewer import VIEWER_HTML

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Surface object types that carry 3D vertex geometry.
_SURFACE_TYPES = (
    "BuildingSurface:Detailed",
    "FenestrationSurface:Detailed",
    "Shading:Site:Detailed",
    "Shading:Building:Detailed",
    "Shading:Zone:Detailed",
)


def _extract_geometry(color_by: str) -> dict[str, object]:
    """Walk the loaded model and extract all surface vertices + metadata."""
    from idfkit.geometry import get_surface_coords

    state = get_state()
    doc = state.require_model()

    surfaces: list[dict[str, object]] = []
    zones: set[str] = set()

    for obj_type in _SURFACE_TYPES:
        collection = doc.get_collection(obj_type)
        if not collection:
            continue
        for obj in collection:
            polygon = get_surface_coords(obj)
            if polygon is None or polygon.num_vertices < 3:
                continue

            zone_name = getattr(obj, "zone_name", None) or ""
            surface_type = getattr(obj, "surface_type", None) or obj_type
            boundary = getattr(obj, "outside_boundary_condition", None) or ""
            construction = getattr(obj, "construction_name", None) or ""

            if zone_name:
                zones.add(zone_name)

            surfaces.append({
                "name": obj.name or "",
                "objectType": obj_type,
                "surfaceType": surface_type,
                "zone": zone_name,
                "boundary": boundary,
                "construction": construction,
                "area": round(polygon.area, 2),
                "tilt": round(polygon.tilt, 1),
                "azimuth": round(polygon.azimuth, 1),
                "vertices": [list(v.as_tuple()) for v in polygon.vertices],
            })

    # Building north axis for compass orientation.
    north_axis = 0.0
    building_collection = doc.get_collection("Building")
    if building_collection:
        building = building_collection.first()
        if building is not None:
            raw = getattr(building, "north_axis", None)
            if raw is not None:
                with contextlib.suppress(ValueError, TypeError):
                    north_axis = float(raw)

    return {
        "surfaces": surfaces,
        "zones": sorted(zones),
        "northAxis": north_axis,
        "colorBy": color_by,
    }


@mcp.tool(
    annotations=_READ_ONLY,
    app=AppConfig(
        resourceUri="ui://idfkit/geometry-viewer.html",
        prefersBorder=False,
    ),
)
def view_geometry(
    color_by: Annotated[
        Literal["type", "zone"],
        Field(description="Color surfaces by type (wall/floor/roof/window) or zone."),
    ] = "type",
) -> ToolResult:
    """Show interactive 3D building geometry from the loaded model.

    Renders all building surfaces, fenestration, and shading geometry in a
    Three.js viewport with orbit controls.  Click surfaces to inspect
    properties; toggle visibility by surface type or zone.
    """
    data = _extract_geometry(color_by)
    surfaces = data["surfaces"]
    zones = data["zones"]
    count = len(surfaces)  # type: ignore[arg-type]
    zone_count = len(zones)  # type: ignore[arg-type]
    logger.info("Extracted %d surfaces across %d zones for geometry viewer", count, zone_count)

    # Build a text summary for clients that don't support MCP Apps.
    type_counts: dict[str, int] = {}
    for s in surfaces:  # type: ignore[union-attr]
        st = s["surfaceType"]  # type: ignore[index]
        type_counts[st] = type_counts.get(st, 0) + 1  # type: ignore[arg-type]
    breakdown = ", ".join(f"{c} {t}" for t, c in sorted(type_counts.items()))
    summary = f"Model geometry: {count} surfaces across {zone_count} zones ({breakdown})."

    # The content array is delivered to the viewer via ontoolresult.
    # Non-Apps hosts display the text content to the LLM as a fallback.
    return ToolResult(
        content=[
            TextContent(type="text", text=json.dumps(data)),
            TextContent(type="text", text=summary),
        ]
    )


@mcp.resource(
    "ui://idfkit/geometry-viewer.html",
    name="geometry_viewer",
    title="3D Geometry Viewer",
    description="Interactive Three.js viewer for EnergyPlus building geometry.",
    app=AppConfig(
        csp=ResourceCSP(resourceDomains=["https://cdn.jsdelivr.net", "https://unpkg.com"]),
        prefersBorder=False,
    ),
)
def geometry_viewer_html() -> str:
    """Return the self-contained Three.js viewer HTML."""
    return VIEWER_HTML
