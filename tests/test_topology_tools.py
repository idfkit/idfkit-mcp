"""Protocol tests for the HVAC topology tools (trace_hvac, get_hvac_topology, rename_node), through FastMCP."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from idfkit import new_document
from mcp.types import TextResourceContents

from idfkit_mcp.models import (
    GetChangeLogResult,
    HVACTopologySummary,
    HVACTrace,
    LoopSummary,
    ModelIntegrityResult,
    NodeRenameResult,
)
from idfkit_mcp.state import get_state
from tests.conftest import call_tool

FIXTURES = Path(__file__).parent / "fixtures"
FIVE_ZONE_GZ = FIXTURES / "5ZoneAirCooled.idf.gz"
DUAL_DUCT_GZ = FIXTURES / "DOASDualDuctSchool.idf.gz"
TIMES = "\u00d7"  # the multiplication sign of a collapsed count (FR-016)
COIL = {"object_type": "Coil:Cooling:Water", "name": "Main Cooling Coil 1"}


async def load_gz(client: Client[FastMCPTransport], gz: Path, tmp_path: Path) -> Client[FastMCPTransport]:
    target = tmp_path / gz.stem
    with gzip.open(gz, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    await client.call_tool("load_model", {"file_path": str(target)})
    return client


@pytest.fixture()
async def five_zone(client: Client[FastMCPTransport], tmp_path: Path) -> Client[FastMCPTransport]:
    return await load_gz(client, FIVE_ZONE_GZ, tmp_path)


@pytest.fixture()
async def dual_duct(client: Client[FastMCPTransport], tmp_path: Path) -> Client[FastMCPTransport]:
    return await load_gz(client, DUAL_DUCT_GZ, tmp_path)


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
        assert [(ms.loop.name, ms.kind, ms.side, ms.stream) for ms in result.memberships] == [
            ("VAV Sys 1", "air", "supply", 1),
            ("Chilled Water Loop", "plant", "demand", 2),
        ]
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
        assert "get_object_neighbourhood(" in message

    async def test_an_unknown_category_lists_the_vocabulary(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await trace_error(five_zone, **COIL, categories=["boilr"])
        assert "boiler" in message and "heating_coil" in message

    async def test_hops_out_of_range(self, five_zone: Client[FastMCPTransport]) -> None:
        with pytest.raises(ToolError):
            await five_zone.call_tool("trace_hvac", {**COIL, "hops": 11})


# ----------------------------------------------------------------------------------------------- #
# get_hvac_topology
# ----------------------------------------------------------------------------------------------- #


async def topology(client: Client[FastMCPTransport], **arguments: object) -> HVACTopologySummary:
    result = await call_tool(client, "get_hvac_topology", dict(arguments), model=HVACTopologySummary)
    assert isinstance(result, HVACTopologySummary)
    return result


def by_name(summary: HVACTopologySummary) -> dict[str, LoopSummary]:
    return {lp.loop.name: lp for lp in summary.loops}


class TestTopologyChain:
    async def test_one_compact_record_per_loop(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await topology(five_zone, detail="chain")
        assert [lp.loop.name for lp in result.loops] == ["VAV Sys 1", "Hot Water Loop", "Chilled Water Loop"]
        assert (result.total, result.omitted) == (3, 0)
        for lp in result.loops:
            # SC-003: a loop record is at most about 200 tokens. Proxy: four characters of the serialised
            # record per token, so len(json) / 4 <= 200.
            assert len(lp.model_dump_json()) / 4 <= 200, lp.loop.name

    async def test_the_air_demand_side_collapses_the_zone_paths(self, five_zone: Client[FastMCPTransport]) -> None:
        air = by_name(await topology(five_zone, detail="chain"))["VAV Sys 1"]
        assert air.kind == "air" and air.fluid == "Air"
        to_zones, returns = air.demand.split("; ")
        assert to_zones.startswith(f"5{TIMES} AirLoopHVAC:ZoneSplitter 'Zone Supply Air Splitter 1'")
        assert "AirTerminal:SingleDuct:VAV:Reheat" in to_zones and to_zones.endswith("Coil:Heating:Water")
        assert returns == "AirLoopHVAC:ReturnPlenum 'Return-Plenum-1'"
        assert air.zones_served == 5

    async def test_the_hot_water_demand_collapses_the_coils(self, five_zone: Client[FastMCPTransport]) -> None:
        hot = by_name(await topology(five_zone, detail="chain"))["Hot Water Loop"]
        assert (hot.kind, hot.zones_served) == ("plant", 0)
        assert f"7{TIMES} Coil:Heating:Water" in hot.demand

    async def test_chilled_water_setpoints_are_water_side_only(self, five_zone: Client[FastMCPTransport]) -> None:
        chilled = by_name(await topology(five_zone, detail="chain"))["Chilled Water Loop"]
        assert chilled.setpoint_nodes == ["CW Supply Outlet Node", "Central Chiller Outlet Node"]

    async def test_dual_duct_decks_stay_separate(self, dual_duct: Client[FastMCPTransport]) -> None:
        result = await topology(dual_duct, loop="DUALDUCT_OTHER", detail="chain")
        (loop,) = result.loops
        decks = [entry for entry in loop.demand.split("; ") if entry.startswith(f"6{TIMES} ")]
        assert len(decks) == 2
        splitters = {entry.split("'")[1] for entry in decks}
        assert splitters == {"DUALDUCT_OTHER RC Supply Air Splitter", "DUALDUCT_OTHER Supply Air Splitter"}


class TestTopologySummary:
    async def test_summary_is_the_default(self, five_zone: Client[FastMCPTransport]) -> None:
        default = await topology(five_zone)
        explicit = await topology(five_zone, detail="summary")
        assert default == explicit
        air = by_name(default)["VAV Sys 1"]
        assert air.supply == "1 branch, 4 components"
        assert "\u2192" not in air.demand and TIMES not in air.demand

    async def test_a_loop_is_selected_case_insensitively(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await topology(five_zone, loop="hot water loop")
        assert [lp.loop.name for lp in result.loops] == ["Hot Water Loop"]
        assert (result.total, result.omitted) == (1, 0)

    async def test_an_unknown_loop_lists_the_closest(self, five_zone: Client[FastMCPTransport]) -> None:
        with pytest.raises(ToolError) as excinfo:
            await five_zone.call_tool("get_hvac_topology", {"loop": "VAV Sys"})
        assert "Closest: 'VAV Sys 1'" in str(excinfo.value)

    async def test_limit_reports_the_omitted_loops(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await topology(five_zone, limit=1)
        assert (result.total, result.omitted, len(result.loops)) == (3, 2, 1)


class TestMemberships:
    async def test_a_reheat_coil_sits_on_both_loops(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, object_type="Coil:Heating:Water", name="SPACE1-1 Zone Coil", hops=1)
        assert [(ms.loop.name, ms.kind, ms.side) for ms in result.memberships] == [
            ("VAV Sys 1", "air", "demand"),
            ("Hot Water Loop", "plant", "demand"),
        ]
        plant = result.memberships[1]
        assert plant.branch is not None and plant.branch.name == "SPACE1-1 Reheat Branch"
        assert plant.position == 0

    async def test_a_node_start_has_memberships(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await trace(five_zone, object_type="Node", name="SPACE3-1 In Node", hops=1)
        assert [(ms.loop.name, ms.side) for ms in result.memberships] == [
            ("VAV Sys 1", "demand"),
            ("Hot Water Loop", "demand"),
        ]


# ----------------------------------------------------------------------------------------------- #
# rename_node
# ----------------------------------------------------------------------------------------------- #


async def topology_issues(client: Client[FastMCPTransport]) -> list[tuple[str | None, str | None, str]]:
    result = await call_tool(client, "check_model_integrity", {}, model=ModelIntegrityResult)
    assert isinstance(result, ModelIntegrityResult)
    return [(i.object_type, i.object_name, i.message) for i in result.issues if i.category == "hvac_topology"]


async def rename_error(client: Client[FastMCPTransport], old: str, new: str) -> str:
    with pytest.raises(ToolError) as excinfo:
        await client.call_tool("rename_node", {"old": old, "new": new})
    return str(excinfo.value)


class TestRenameNode:
    async def test_end_to_end(self, five_zone: Client[FastMCPTransport]) -> None:
        before = await topology_issues(five_zone)
        result = await call_tool(
            five_zone, "rename_node", {"old": "mixed air node 1", "new": "AHU-1 Mixed Air"}, model=NodeRenameResult
        )
        assert isinstance(result, NodeRenameResult)
        assert (result.old, result.new, result.fields_updated) == ("Mixed Air Node 1", "AHU-1 Mixed Air", 6)
        assert {(k.object_type, k.name) for k in result.objects} == {
            ("Branch", "VAV Sys 1 Main Branch"),
            ("Coil:Cooling:Water", "Main Cooling Coil 1"),
            ("Controller:OutdoorAir", "OA Controller 1"),
            ("OutdoorAir:Mixer", "OA Mixing Box 1"),
            ("NodeList", "Main Branch SetPoint Node List"),
        }

        after = await topology_issues(five_zone)
        assert [issue for issue in after if issue not in before] == []

        log = await call_tool(five_zone, "get_change_log", {}, model=GetChangeLogResult)
        assert isinstance(log, GetChangeLogResult)
        assert any(e.tool == "rename_node" for e in log.entries)

        traced = await trace(five_zone, object_type="Node", name="AHU-1 Mixed Air", hops=1)
        assert traced.start.name == "AHU-1 Mixed Air"
        assert [p.name for p in traced.producers] == ["OA Mixing Box 1"]

    async def test_an_unknown_old_name_lists_the_closest(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await rename_error(five_zone, "Mixed Air Nod 1", "x")
        assert "Closest:" in message and "'Mixed Air Node 1'" in message

    async def test_an_empty_new_name(self, five_zone: Client[FastMCPTransport]) -> None:
        assert "empty" in await rename_error(five_zone, "Mixed Air Node 1", "")

    async def test_the_same_name(self, five_zone: Client[FastMCPTransport]) -> None:
        assert "old one" in await rename_error(five_zone, "Mixed Air Node 1", "Mixed Air Node 1")

    async def test_a_new_name_that_is_already_a_node(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await rename_error(five_zone, "Mixed Air Node 1", "Main Cooling Coil 1 Outlet Node")
        assert "already a node" in message


class TestHvacResource:
    async def test_the_loop_resource_is_the_chain_record(self, five_zone: Client[FastMCPTransport]) -> None:
        contents = await five_zone.read_resource("idfkit://model/hvac/VAV Sys 1")
        assert isinstance(contents[0], TextResourceContents)
        resource = HVACTopologySummary.model_validate_json(contents[0].text)
        tool = await topology(five_zone, loop="VAV Sys 1", detail="chain")
        assert resource == tool
        assert [lp.loop.name for lp in resource.loops] == ["VAV Sys 1"]
        assert resource.loops[0].demand.startswith(f"5{TIMES} ")
