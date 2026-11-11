"""Tests for the check_model_integrity tool."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
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
        # All 7 checks should run regardless of model state
        assert len(result.checks_run) == 7
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
        # The type has no Name field, so the issue names the zone the connections serve.
        assert hvac_errors[0].object_name == "NonExistentZone"
        assert "NonExistentZone" in hvac_errors[0].message

    async def test_checks_run_list(self, client: object, state_with_model: ServerState) -> None:
        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        expected = {
            "zones_with_no_surfaces",
            "required_simulation_controls",
            "orphan_schedules",
            "surface_boundary_mismatches",
            "fenestration_host_check",
            "hvac_zone_references",
            "hvac_topology",
        }
        assert set(result.checks_run) == expected


FIVE_ZONE_GZ = Path(__file__).parent / "fixtures" / "5ZoneAirCooled.idf.gz"


@pytest.fixture()
async def five_zone(client: Client[FastMCPTransport], tmp_path: Path) -> Client[FastMCPTransport]:
    target = tmp_path / "5ZoneAirCooled.idf"
    with gzip.open(FIVE_ZONE_GZ, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    await client.call_tool("load_model", {"file_path": str(target)})
    return client


class TestHVACTopologyGroup:
    async def test_unmodified_model_has_no_topology_errors(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await call_tool(five_zone, "check_model_integrity", model=ModelIntegrityResult)
        assert "hvac_topology" in result.checks_run
        assert not [i for i in result.issues if i.category == "hvac_topology" and i.severity == "error"]

    async def test_an_outlet_typo_is_a_t010_and_a_t030(self, five_zone: Client[FastMCPTransport]) -> None:
        await five_zone.call_tool(
            "update_object",
            {
                "object_type": "Coil:Cooling:Water",
                "name": "Main Cooling Coil 1",
                "fields": {"air_outlet_node_name": "TYPO NODE"},
            },
        )
        result = await call_tool(five_zone, "check_model_integrity", model=ModelIntegrityResult)
        topo = [i for i in result.issues if i.category == "hvac_topology"]
        t010 = [i for i in topo if i.message.startswith("[T010]")]
        assert t010 and t010[0].severity == "error"
        assert any("TYPO NODE" in i.message for i in t010)
        assert any(i.message.startswith("[T030]") and "TYPO NODE" in i.message for i in topo)
        assert result.passed is False

    async def test_findings_beyond_fifty_are_grouped_by_code(self, client: Client[FastMCPTransport]) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        for i in range(60):
            doc.add(
                "Coil:Heating:Electric",
                f"Coil {i}",
                air_inlet_node_name=f"In {i}",
                air_outlet_node_name=f"Out {i}",
                validate=False,
            )
        result = await call_tool(client, "check_model_integrity", model=ModelIntegrityResult)
        topo = [i for i in result.issues if i.category == "hvac_topology"]
        grouped = [i for i in topo if "more findings of this code" in i.message]
        assert len(topo) - len(grouped) == 50
        assert grouped and all(i.object_type is None for i in grouped)
