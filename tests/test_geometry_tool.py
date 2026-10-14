"""Tests for the view_geometry tool."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastmcp.exceptions import ToolError
from idfkit import IDFDocument, new_document

from idfkit_mcp.state import get_state
from tests.conftest import call_tool

_FLOOR = [(0.0, 0.0, 0.0), (0.0, 5.0, 0.0), (5.0, 5.0, 0.0), (5.0, 0.0, 0.0)]


def _relative_model(*, zone_origin: tuple[float, float, float], north_axis: float = 0.0) -> IDFDocument:
    """A one-zone model authored in relative coordinates, with its zone moved off the origin."""
    doc = new_document()
    # new_document declares relative coordinates and an empty Building; only the north axis is set here.
    doc.get_collection("Building").first().north_axis = north_axis  # type: ignore[union-attr]
    x, y, z = zone_origin
    doc.add("Zone", "Room", x_origin=x, y_origin=y, z_origin=z, validate=False)
    doc.add(
        "BuildingSurface:Detailed",
        "Room_Floor",
        surface_type="Floor",
        construction_name="",
        zone_name="Room",
        outside_boundary_condition="Ground",
        sun_exposure="NoSun",
        wind_exposure="NoWind",
        number_of_vertices=4,
        vertices=[
            {"vertex_x_coordinate": vx, "vertex_y_coordinate": vy, "vertex_z_coordinate": vz} for vx, vy, vz in _FLOOR
        ],
        validate=False,
    )
    return doc


def _load(doc: IDFDocument) -> None:
    state = get_state()
    state.document = doc
    state.schema = doc.schema


def _flat(vertices: list[list[float]] | list[tuple[float, float, float]]) -> list[float]:
    return [c for v in vertices for c in v]


async def _view(client: object) -> tuple[dict[str, Any], str]:
    parts = await call_tool(client, "view_geometry")
    assert isinstance(parts, list)
    payload, summary = parts
    return json.loads(payload), summary


class TestViewGeometry:
    async def test_no_model_raises(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "view_geometry")

    async def test_relative_zone_origin_is_applied(self, client: object) -> None:
        _load(_relative_model(zone_origin=(40.0, 10.0, 3.0)))
        data, _ = await _view(client)

        (surface,) = data["surfaces"]
        assert surface["zone"] == "Room"
        assert _flat(surface["vertices"]) == pytest.approx(_flat([(x + 40.0, y + 10.0, z + 3.0) for x, y, z in _FLOOR]))

    async def test_building_north_axis_is_applied(self, client: object) -> None:
        # North axis 90 is a clockwise quarter turn seen from above: (x, y) -> (y, -x).
        _load(_relative_model(zone_origin=(0.0, 0.0, 0.0), north_axis=90.0))
        data, _ = await _view(client)

        (surface,) = data["surfaces"]
        assert _flat(surface["vertices"]) == pytest.approx(_flat([(y, -x, z) for x, y, z in _FLOOR]), abs=1e-9)
        assert data["northAxis"] == 90.0

    async def test_unresolved_surface_is_reported(self, client: object) -> None:
        doc = _relative_model(zone_origin=(0.0, 0.0, 0.0))
        doc.add(
            "BuildingSurface:Detailed",
            "Orphan_Wall",
            surface_type="Wall",
            construction_name="",
            zone_name="Missing Zone",
            outside_boundary_condition="Outdoors",
            number_of_vertices=4,
            vertices=[
                {"vertex_x_coordinate": vx, "vertex_y_coordinate": vy, "vertex_z_coordinate": vz}
                for vx, vy, vz in _FLOOR
            ],
            validate=False,
        )
        _load(doc)
        data, summary = await _view(client)

        assert [s["name"] for s in data["surfaces"]] == ["Room_Floor"]
        assert data["unresolved"] == [
            {
                "objectType": "BuildingSurface:Detailed",
                "name": "Orphan_Wall",
                "reason": "zone-not-found",
                "missingReference": "Missing Zone",
            }
        ]
        assert "Orphan_Wall" in summary
        assert "zone-not-found" in summary

    async def test_unattempted_types_are_reported(self, client: object) -> None:
        doc = new_document()
        doc.add("Zone", "Room", validate=False)
        doc.add("Wall:Exterior", "Simple_Wall", zone_name="Room", validate=False)
        _load(doc)
        data, summary = await _view(client)

        assert data["surfaces"] == []
        assert data["unattempted"] == [{"objectType": "Wall:Exterior", "count": 1}]
        assert "1 Wall:Exterior" in summary
