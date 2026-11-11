"""Protocol tests for the HVAC topology tools (trace_hvac), through FastMCP."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from idfkit import new_document

from idfkit_mcp.models import HVACTrace
from idfkit_mcp.state import get_state
from tests.conftest import call_tool

FIVE_ZONE_GZ = Path(__file__).parent / "fixtures" / "5ZoneAirCooled.idf.gz"
COIL = {"object_type": "Coil:Cooling:Water", "name": "Main Cooling Coil 1"}


@pytest.fixture()
async def five_zone(client: Client[FastMCPTransport], tmp_path: Path) -> Client[FastMCPTransport]:
    target = tmp_path / "5ZoneAirCooled.idf"
    with gzip.open(FIVE_ZONE_GZ, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    await client.call_tool("load_model", {"file_path": str(target)})
    return client


async def trace(client: Client[FastMCPTransport], **arguments: object) -> HVACTrace:
    result = await call_tool(client, "trace_hvac", dict(arguments), model=HVACTrace)
    assert isinstance(result, HVACTrace)
    return result


async def trace_error(client: Client[FastMCPTransport], **arguments: object) -> str:
    with pytest.raises(ToolError) as excinfo:
        await client.call_tool("trace_hvac", dict(arguments))
    return str(excinfo.value)


class TestComponentStart:
    async def test_ports_flow_and_category(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, object_type="coil:cooling:water", name="main cooling coil 1", hops=1)
        assert (result.start.object_type, result.start.name, result.start.category) == (
            "Coil:Cooling:Water",
            "Main Cooling Coil 1",
            "cooling_coil",
        )
        assert {u.fluid for u in result.ports} == {"Air", "Water"}
        assert [u.stream for u in result.ports] == sorted(u.stream for u in result.ports)
        assert {e.target.name for e in result.downstream} == {"Main Heating Coil 1", "CW Demand Mixer"}
        assert result.findings == []
        assert result.memberships == []
        assert result.producers == result.consumers == []

    async def test_a_reheat_coil_names_its_terminal_as_parent(self, five_zone: Client[FastMCPTransport]) -> None:
        coil = await trace(five_zone, object_type="Coil:Heating:Water", name="SPACE1-1 Zone Coil", hops=1)
        assert coil.parent is not None and coil.parent.name == "SPACE1-1 VAV Reheat"
        terminal = await trace(five_zone, object_type="AirTerminal:SingleDuct:VAV:Reheat", name="SPACE1-1 VAV Reheat")
        assert terminal.parent is not None and terminal.parent.object_type == "ZoneHVAC:AirDistributionUnit"
        assert [c.name for c in terminal.children] == ["SPACE1-1 Zone Coil"]

    async def test_a_branch_is_not_a_parent(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, **COIL, hops=1)
        assert result.parent is None

    async def test_the_typo_shows_in_the_coil_findings(self, five_zone: Client[FastMCPTransport]) -> None:
        await five_zone.call_tool("update_object", {**COIL, "fields": {"air_outlet_node_name": "TYPO NODE"}})
        result = await trace(five_zone, **COIL)
        t010 = [f for f in result.findings if f.code == "T010"]
        assert t010 and t010[0].severity == "error"
        assert any("TYPO NODE" in (f.actual or "") + (f.expected or "") for f in t010)
        assert "Main Heating Coil 1" not in {e.target.name for e in result.downstream}

    async def test_a_fluid_keeps_the_walk_on_one_stream(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, **COIL, hops=4, fluid="Water")
        assert result.upstream and all(e.fluid == "Water" for e in result.upstream + result.downstream)

    async def test_a_category_filter_keeps_matching_edges(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, **COIL, hops=10, categories=["chiller"], fluid="Water")
        assert {e.source.name for e in result.upstream} == {"Central Chiller"}


class TestOtherStarts:
    async def test_a_node_start(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, object_type="Node", name="main cooling coil 1 outlet node", hops=1)
        assert (result.start.object_type, result.start.name) == ("Node", "Main Cooling Coil 1 Outlet Node")
        assert result.fluid == "Air"
        assert [p.name for p in result.producers] == ["Main Cooling Coil 1"]
        assert [c.name for c in result.consumers] == ["Main Heating Coil 1"]
        assert {c.object.object_type for c in result.controls} >= {"Controller:WaterCoil"}
        assert result.ports == []

    async def test_a_zone_start(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, object_type="Zone", name="space1-1", hops=1)
        assert result.start.name == "SPACE1-1"
        assert result.start.category is None
        assert result.upstream and result.downstream

    async def test_a_nodelist_start(self, client: Client[FastMCPTransport]) -> None:
        state = get_state()
        doc = new_document()
        state.document = doc
        state.schema = doc.schema
        doc.add("NodeList", "Inlets", nodes=[{"node_name": "A"}, {"node_name": "B"}], validate=False)
        doc.add("Coil:Heating:Electric", "Heater A", air_inlet_node_name="X", air_outlet_node_name="A", validate=False)
        doc.add("Coil:Heating:Electric", "Heater B", air_inlet_node_name="Y", air_outlet_node_name="B", validate=False)
        result = await trace(client, object_type="Node", name="inlets", hops=1)
        assert (result.start.object_type, result.start.name) == ("NodeList", "Inlets")
        assert {p.name for p in result.producers} == {"Heater A", "Heater B"}

    async def test_ems_programs_make_coverage_partial(self, five_zone: Client[FastMCPTransport]) -> None:
        doc = get_state().require_model()
        doc.add("EnergyManagementSystem:Program", "Override", lines=[{"program_line": "SET x = 1"}], validate=False)
        result = await trace(five_zone, **COIL, hops=1)
        assert result.coverage.partial is True
        assert "ems_program" in {p.kind for p in result.coverage.uncovered}


class TestErrors:
    async def test_no_model(self, client: Client[FastMCPTransport]) -> None:
        get_state().document = None
        with pytest.raises(ToolError, match="No model loaded"):
            await client.call_tool("trace_hvac", COIL)

    async def test_an_unknown_name_lists_the_closest_and_picks_none(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await trace_error(five_zone, object_type="Coil:Cooling:Water", name="Main Coolin Coil 1")
        assert "Closest: 'Main Cooling Coil 1'" in message

    async def test_an_unknown_node_lists_the_closest(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await trace_error(five_zone, object_type="Node", name="Main Cooling Coil Outlet Node")
        assert "'Main Cooling Coil 1 Outlet Node'" in message

    async def test_an_unknown_type_lists_the_closest(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await trace_error(five_zone, object_type="Coil:Cooling:Watr", name="x")
        assert "'Coil:Cooling:Water'" in message

    async def test_an_object_without_node_fields(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await trace_error(five_zone, object_type="Material", name="WD10")
        assert "no node fields" in message
        assert "idfkit://model/references/WD10" in message

    async def test_an_unknown_category_lists_the_vocabulary(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await trace_error(five_zone, **COIL, categories=["boilr"])
        assert "boiler" in message and "heating_coil" in message

    async def test_hops_out_of_range(self, five_zone: Client[FastMCPTransport]) -> None:
        with pytest.raises(ToolError):
            await five_zone.call_tool("trace_hvac", {**COIL, "hops": 11})
