"""3D geometry viewer tool — renders building surfaces in an interactive Three.js viewport."""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Annotated, Literal

from fastmcp.apps import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources.function_resource import resource
from fastmcp.tools import ToolResult, tool
from idfkit import ResolvedSurface, Scene, get_scene
from mcp.types import TextContent, ToolAnnotations
from pydantic import Field

from idfkit_mcp.state import get_state
from idfkit_mcp.viewer import VIEWER_HTML

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Decimal places kept on each vertex coordinate in the viewer payload (one micrometre).
_VERTEX_DIGITS = 6


def _zone_names(scene: Scene) -> list[str]:
    """The zones that hold at least one resolved surface, sorted."""
    return sorted({s.zone for s in scene.surfaces if s.zone})


def _surface_type(resolved: ResolvedSurface) -> str:
    """The surface type, or the object type when the model leaves the field blank."""
    return resolved.surface_type or resolved.object_type


def _extract_geometry(scene: Scene, color_by: str) -> dict[str, object]:
    """Serialize a resolved scene for the viewer, in the frame EnergyPlus simulates.

    ``scene`` comes from ``idfkit.get_scene``, which applies zone origins, zone rotations and the
    building's north axis under the model's ``GlobalGeometryRules``. Objects it could not place and
    geometry types it does not read are returned alongside, so that nothing is dropped silently.
    Vertices are rounded to the micrometre, which removes floating-point residue from the rotations.
    """
    surfaces: list[dict[str, object]] = []
    for resolved in scene.surfaces:
        polygon = resolved.polygon
        surfaces.append({
            "name": resolved.name,
            "objectType": resolved.object_type,
            "surfaceType": _surface_type(resolved),
            "zone": resolved.zone,
            "boundary": resolved.boundary,
            "construction": resolved.construction,
            "area": round(polygon.area, 2),
            "tilt": round(polygon.tilt, 1),
            "azimuth": round(polygon.azimuth, 1),
            "vertices": [[round(c, _VERTEX_DIGITS) for c in v.as_tuple()] for v in polygon.vertices],
        })

    return {
        "surfaces": surfaces,
        "zones": _zone_names(scene),
        # Informational only: the vertices and azimuths above already carry the building rotation.
        "northAxis": scene.applied.north_axis,
        "coordinateSystem": scene.applied.coordinate_system,
        "unresolved": [
            {
                "objectType": u.object_type,
                "name": u.name,
                "reason": u.reason,
                "missingReference": u.missing_reference or None,
            }
            for u in scene.unresolved
        ],
        "unattempted": [{"objectType": u.object_type, "count": u.count} for u in scene.unattempted],
        "colorBy": color_by,
    }


def _skipped_summary(scene: Scene) -> str:
    """Name every geometry object the viewer does not draw, and why."""
    parts: list[str] = []
    if scene.unresolved:
        details = "; ".join(
            f"{u.object_type} '{u.name}' ({u.reason}{f': {u.missing_reference}' if u.missing_reference else ''})"
            for u in scene.unresolved
        )
        parts.append(f"Not drawn, could not be placed: {details}.")
    if scene.unattempted:
        details = ", ".join(f"{u.count} {u.object_type}" for u in scene.unattempted)
        parts.append(f"Not drawn, geometry type not read by the viewer: {details}.")
    return " ".join(parts)


@tool(
    annotations=_READ_ONLY,
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                resourceUri="ui://idfkit/geometry-viewer.html",
                prefersBorder=False,
            )
        )
    },
)
def view_geometry(
    color_by: Annotated[
        Literal["type", "zone"],
        Field(description="Color surfaces by type (wall/floor/roof/window) or zone."),
    ] = "type",
) -> ToolResult:
    """Show interactive 3D building geometry from the loaded model.

    Renders detailed building surfaces, fenestration, and shading geometry in a
    Three.js viewport with orbit controls, placed where EnergyPlus simulates
    them (zone origins, zone rotations and the building north axis applied).
    Click surfaces to inspect properties; toggle visibility by surface type or
    zone. Surfaces that cannot be placed and simplified geometry types (for
    example Wall:Exterior or Window) are not drawn; they are listed in the
    payload and in the text summary.
    """
    scene = get_scene(get_state().require_model())
    data = _extract_geometry(scene, color_by)
    count = len(scene.surfaces)
    zone_count = len(_zone_names(scene))
    logger.info("Extracted %d surfaces across %d zones for geometry viewer", count, zone_count)

    # Build a text summary for clients that don't support MCP Apps.
    type_counts = Counter(_surface_type(s) for s in scene.surfaces)
    breakdown = ", ".join(f"{c} {t}" for t, c in sorted(type_counts.items()))
    summary = f"Model geometry: {count} surfaces across {zone_count} zones ({breakdown})."
    skipped = _skipped_summary(scene)
    if skipped:
        summary = f"{summary} {skipped}"

    # The content array is delivered to the viewer via ontoolresult.
    # Non-Apps hosts display the text content to the LLM as a fallback.
    return ToolResult(
        content=[
            TextContent(type="text", text=json.dumps(data)),
            TextContent(type="text", text=summary),
        ]
    )


@resource(
    "ui://idfkit/geometry-viewer.html",
    name="geometry_viewer",
    title="3D Geometry Viewer",
    description="Interactive Three.js viewer for EnergyPlus building geometry.",
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                csp=ResourceCSP(resourceDomains=["https://cdn.jsdelivr.net", "https://unpkg.com"]),
                domain="geometry-viewer.idfkit.com",
                prefersBorder=False,
            )
        )
    },
)
def geometry_viewer_html() -> str:
    """Return the self-contained Three.js viewer HTML."""
    return VIEWER_HTML
