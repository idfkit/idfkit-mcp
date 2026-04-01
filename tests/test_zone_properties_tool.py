"""Tests for the get_zone_properties tool."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError
from idfkit import new_document

from idfkit_mcp.models import GetZonePropertiesResult
from idfkit_mcp.state import ServerState, get_state
from tests.conftest import call_tool


class TestGetZoneProperties:
    async def test_no_model_raises(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "get_zone_properties")

    async def test_empty_model_no_zones(self, client: object, state_with_model: ServerState) -> None:
        result = await call_tool(client, "get_zone_properties", model=GetZonePropertiesResult)
        assert result.zone_count == 0
        assert result.zones == []

    async def test_all_zones(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "get_zone_properties", model=GetZonePropertiesResult)
        assert result.zone_count == 2
        names = {z.name for z in result.zones}
        assert "Office" in names
        assert "Corridor" in names

    async def test_single_zone(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "get_zone_properties", {"zone_name": "Office"}, GetZonePropertiesResult)
        assert result.zone_count == 1
        assert result.zones[0].name == "Office"

    async def test_unknown_zone_raises(self, client: object, state_with_zones: ServerState) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "get_zone_properties", {"zone_name": "Nonexistent"})

    async def test_zone_with_surface_has_geometry(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema

        doc.add("Zone", "Room")
        # Add a simple floor surface with vertices so geometry can be computed
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
            vertex_1_x_coordinate=0.0,
            vertex_1_y_coordinate=0.0,
            vertex_1_z_coordinate=0.0,
            vertex_2_x_coordinate=5.0,
            vertex_2_y_coordinate=0.0,
            vertex_2_z_coordinate=0.0,
            vertex_3_x_coordinate=5.0,
            vertex_3_y_coordinate=5.0,
            vertex_3_z_coordinate=0.0,
            vertex_4_x_coordinate=0.0,
            vertex_4_y_coordinate=5.0,
            vertex_4_z_coordinate=0.0,
            validate=False,
        )

        result = await call_tool(client, "get_zone_properties", {"zone_name": "Room"}, GetZonePropertiesResult)
        zone = result.zones[0]
        assert zone.surface_counts.floors == 1
        assert zone.floor_area_m2 is not None
        assert zone.floor_area_m2 > 0

    async def test_zone_without_surfaces_has_no_geometry(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add("Zone", "EmptyRoom")

        result = await call_tool(client, "get_zone_properties", {"zone_name": "EmptyRoom"}, GetZonePropertiesResult)
        zone = result.zones[0]
        assert zone.floor_area_m2 is None
        assert zone.volume_m3 is None
        assert zone.height_m is None

    async def test_surface_type_counts(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "get_zone_properties", {"zone_name": "Office"}, GetZonePropertiesResult)
        zone = result.zones[0]
        assert zone.surface_counts.walls == 1

    async def test_constructions_collected(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add("Zone", "Room")
        doc.add(
            "BuildingSurface:Detailed",
            "Room_Wall",
            surface_type="Wall",
            construction_name="ExtWall",
            zone_name="Room",
            outside_boundary_condition="Outdoors",
            sun_exposure="SunExposed",
            wind_exposure="WindExposed",
            validate=False,
        )

        result = await call_tool(client, "get_zone_properties", {"zone_name": "Room"}, GetZonePropertiesResult)
        assert "ExtWall" in result.zones[0].constructions

    async def test_hvac_connections_named(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add("Zone", "Room")
        doc.add(
            "ZoneHVAC:EquipmentConnections",
            "Room_HVAC",
            zone_name="Room",
            zone_conditioning_equipment_list_name="",
            zone_air_inlet_node_or_nodelist_name="",
            zone_air_exhaust_node_or_nodelist_name="",
            zone_air_node_name="",
            zone_return_air_node_or_nodelist_name="",
            validate=False,
        )

        result = await call_tool(client, "get_zone_properties", {"zone_name": "Room"}, GetZonePropertiesResult)
        assert "Room_HVAC" in result.zones[0].hvac_connections
