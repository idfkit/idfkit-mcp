"""Tests for the check_model_integrity tool."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError
from idfkit import new_document

from idfkit_mcp.models import ModelIntegrityResult
from idfkit_mcp.state import ServerState, get_state
from tests.conftest import call_tool


class TestCheckModelIntegrity:
    async def test_no_model_raises(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "check_model_integrity")

    async def test_empty_model_runs_all_checks(self, client: object, state_with_model: ServerState) -> None:
        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        # All 6 checks should run regardless of model state
        assert len(result.checks_run) == 6
        # No geometry or HVAC issues in an empty model — only missing controls
        geo_issues = [i for i in result.issues if i.category == "geometry"]
        assert len(geo_issues) == 0

    async def test_zone_with_no_surfaces(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add("Zone", "EmptyZone")

        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        assert result.passed is False
        assert result.error_count >= 1
        zone_issues = [i for i in result.issues if i.category == "geometry" and i.object_type == "Zone"]
        assert any("EmptyZone" in i.message for i in zone_issues)

    async def test_zone_with_surface_passes(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        # Corridor has no surface — expected error; Office does have one
        office_geo_errors = [i for i in result.issues if i.category == "geometry" and i.object_name == "Office"]
        assert len(office_geo_errors) == 0

    async def test_orphan_schedule_warning(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add("Schedule:Constant", "UnusedSched", schedule_type_limits_name="", hourly_value=1.0, validate=False)

        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        sched_warnings = [i for i in result.issues if i.category == "schedules"]
        assert any("UnusedSched" in i.message for i in sched_warnings)
        assert all(i.severity == "warning" for i in sched_warnings)

    async def test_surface_boundary_mismatch(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add("Zone", "ZoneA")
        doc.add(
            "BuildingSurface:Detailed",
            "WallA",
            surface_type="Wall",
            construction_name="",
            zone_name="ZoneA",
            outside_boundary_condition="Surface",
            outside_boundary_condition_object="NonExistentWall",
            sun_exposure="NoSun",
            wind_exposure="NoWind",
            validate=False,
        )

        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        boundary_errors = [
            i for i in result.issues if i.category == "geometry" and i.object_type == "BuildingSurface:Detailed"
        ]
        assert len(boundary_errors) >= 1

    async def test_fenestration_missing_host(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add(
            "FenestrationSurface:Detailed",
            "Window1",
            surface_type="Window",
            construction_name="",
            building_surface_name="NonExistentWall",
            validate=False,
        )

        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        fen_errors = [i for i in result.issues if i.object_type == "FenestrationSurface:Detailed"]
        assert len(fen_errors) >= 1
        assert any("Window1" in i.message for i in fen_errors)

    async def test_hvac_missing_zone(self, client: object) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add(
            "ZoneHVAC:EquipmentConnections",
            "Conn1",
            zone_name="NonExistentZone",
            zone_conditioning_equipment_list_name="",
            zone_air_inlet_node_or_nodelist_name="",
            zone_air_exhaust_node_or_nodelist_name="",
            zone_air_node_name="",
            zone_return_air_node_or_nodelist_name="",
            validate=False,
        )

        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        hvac_errors = [i for i in result.issues if i.category == "hvac"]
        assert len(hvac_errors) >= 1

    async def test_checks_run_list(self, client: object, state_with_model: ServerState) -> None:
        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        expected = {
            "zones_with_no_surfaces",
            "required_simulation_controls",
            "orphan_schedules",
            "surface_boundary_mismatches",
            "fenestration_host_check",
            "hvac_zone_references",
        }
        assert set(result.checks_run) == expected
