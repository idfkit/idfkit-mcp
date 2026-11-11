"""Protocol tests for get_object_results and idfkit://simulation/objects/{type}/{name} (US3, T091-T093).

Runs come from the committed result-linking fixtures (``tests/linked_runs.py``); no EnergyPlus is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from idfkit import load_idf

from idfkit_mcp.models import ObjectResults
from idfkit_mcp.state import NO_SIMULATION_RUN, ServerState, get_state
from tests.conftest import call_tool, read_resource_json
from tests.linked_runs import install_run, model_path

TERMINAL = {"object_type": "AirTerminal:SingleDuct:VAV:Reheat", "name": "SPACE1-1 VAV Reheat"}
AIR_LOOP = {"object_type": "AirLoopHVAC", "name": "VAV Sys 1"}


async def _results(client: Client[FastMCPTransport], **arguments: Any) -> ObjectResults:
    return await call_tool(client, "get_object_results", arguments, model=ObjectResults)  # type: ignore[return-value]


@pytest.fixture()
def five_zone(tmp_path: Path) -> ServerState:
    """5ZoneAirCooled, as if run_simulation had just run it."""
    return install_run("5ZoneAirCooled", tmp_path)


@pytest.fixture()
def multi_story(tmp_path: Path) -> ServerState:
    """MultiStory (zone multipliers 1 to 32), as if run_simulation had just run it."""
    return install_run("MultiStory", tmp_path)


class TestNoSimulation:
    async def test_no_run_is_an_actionable_error(self, client: Client[FastMCPTransport], tmp_path: Path) -> None:
        await call_tool(client, "load_model", {"file_path": str(model_path("5ZoneAirCooled", tmp_path))})
        with pytest.raises(ToolError, match="No simulation run in this session; run `run_simulation` first"):
            await call_tool(client, "get_object_results", TERMINAL)

    async def test_no_model_and_no_run(self, client: Client[FastMCPTransport]) -> None:
        with pytest.raises(ToolError, match="run `run_simulation` first"):
            await call_tool(client, "get_object_results", TERMINAL)

    async def test_loading_a_model_forgets_the_run(
        self, client: Client[FastMCPTransport], five_zone: ServerState, tmp_path: Path
    ) -> None:
        await call_tool(client, "load_model", {"file_path": str(model_path("MultiStory", tmp_path))})
        assert five_zone.simulation_run_dir is None
        assert five_zone.simulation_model_hash is None
        assert five_zone.simulation_run_revision is None
        with pytest.raises(ToolError, match="run `run_simulation` first"):
            await call_tool(client, "get_object_results", TERMINAL)

    async def test_resource_raises_the_same_error(self, client: Client[FastMCPTransport]) -> None:
        with pytest.raises(Exception, match="run_simulation"):
            await client.read_resource("idfkit://simulation/objects/Zone/SPACE1-1")

    def test_message_is_the_contract_text(self) -> None:
        assert NO_SIMULATION_RUN == "No simulation run in this session; run `run_simulation` first."


class TestObjectResults:
    async def test_terminal_sizing_facts(self, client: Client[FastMCPTransport], five_zone: ServerState) -> None:
        result = await _results(client, **TERMINAL)
        assert result.object.object_type == "AirTerminal:SingleDuct:VAV:Reheat"
        assert result.results_state == "fresh"
        assert result.facts.total > 0
        sizing = [f for f in result.facts.items if f.source == "sizing"]
        assert sizing
        assert all(f.where.startswith("ComponentSizes#") for f in sizing)
        assert all(f.multiplier is None for f in result.facts.items)
        assert result.coverage.resolved is not None
        assert result.coverage.resolved > 0
        assert result.coverage.unresolved == 0

    async def test_names_match_case_insensitively_and_return_model_spelling(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        result = await _results(client, object_type="airloophvac", name="vav sys 1")
        assert result.object.object_type == "AirLoopHVAC"
        assert result.object.name == "VAV Sys 1"

    async def test_linked_message_with_occurrences(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        result = await _results(client, **AIR_LOOP)
        assert result.messages.total == 1
        (message,) = result.messages.items
        assert message.kind == "sizing.system_flow_ratio"
        assert message.severity == "warning"
        assert message.occurrences == 1
        assert [link.key.name for link in message.objects if link.key is not None] == ["VAV Sys 1"]

    async def test_messages_first_seen(self, client: Client[FastMCPTransport], multi_story: ServerState) -> None:
        result = await _results(client, object_type="ZoneHVAC:WindowAirConditioner", name="Gnd West Window AC")
        (message,) = result.messages.items
        assert message.kind == "zonehvac.max_iterations"
        assert message.first_seen == "RUN PERIOD 1 02/11 15:50"

    async def test_node_is_allowed(self, client: Client[FastMCPTransport], five_zone: ServerState) -> None:
        result = await _results(client, object_type="Node", name="space1-1 node")
        assert result.object.object_type == "Node"
        assert result.object.name == "SPACE1-1 Node"
        assert result.available_variables.total >= 1
        assert result.neighbours.total >= 1

    async def test_neighbours_carry_their_top_fact(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        result = await _results(client, **TERMINAL)
        coil = [n for n in result.neighbours.items if n.object.object_type == "Coil:Heating:Water"]
        assert coil
        assert coil[0].top_fact is not None
        assert coil[0].top_fact.source == "sizing"

    async def test_every_list_is_bounded_by_limit(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        result = await _results(client, object_type="Zone", name="SPACE1-1", limit=3)
        for page in (result.facts, result.messages, result.available_variables, result.neighbours):
            assert len(page.items) <= 3
            assert page.omitted == page.total - len(page.items)
        assert result.facts.total > 3
        assert result.facts.omitted == result.facts.total - 3

    async def test_default_answer_fits_8_kb(self, client: Client[FastMCPTransport], five_zone: ServerState) -> None:
        for start in (AIR_LOOP, TERMINAL, {"object_type": "Zone", "name": "SPACE1-1"}):
            raw = await client.call_tool("get_object_results", {**start, "limit": 100})
            assert len(json.dumps(raw.structured_content, separators=(",", ":"))) <= 8 * 1024

    @pytest.mark.parametrize("limit", [0, 101])
    async def test_limit_out_of_range(
        self, client: Client[FastMCPTransport], five_zone: ServerState, limit: int
    ) -> None:
        with pytest.raises(ToolError, match="limit must be between 1 and 100"):
            await call_tool(client, "get_object_results", {**TERMINAL, "limit": limit})

    async def test_unknown_object_names_closest_and_search_objects(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        with pytest.raises(ToolError, match=r"No AirLoopHVAC named 'VAV Sys 2'.*VAV Sys 1.*search_objects"):
            await call_tool(client, "get_object_results", {"object_type": "AirLoopHVAC", "name": "VAV Sys 2"})

    async def test_unknown_node(self, client: Client[FastMCPTransport], five_zone: ServerState) -> None:
        with pytest.raises(ToolError, match=r"No node named 'SPACE9-1 Node'.*search_objects"):
            await call_tool(client, "get_object_results", {"object_type": "Node", "name": "SPACE9-1 Node"})

    async def test_object_with_no_results_is_not_an_error(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        result = await _results(client, object_type="Material", name="WD10")
        assert result.facts.total == 0
        assert result.messages.total == 0

    async def test_resource_has_the_same_content(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        tool = await call_tool(client, "get_object_results", AIR_LOOP)
        resource = await read_resource_json(client, "idfkit://simulation/objects/AirLoopHVAC/VAV Sys 1")
        assert resource == tool


class TestMultipliers:
    async def test_zone_facts_carry_the_zone_multiplier(
        self, client: Client[FastMCPTransport], multi_story: ServerState
    ) -> None:
        for zone, multiplier in (("Mid Center Zone", 32), ("Mid West Zone", 8), ("Gnd West Zone", 1)):
            result = await _results(client, object_type="Zone", name=zone)
            assert result.facts.items
            assert {f.multiplier for f in result.facts.items} == {multiplier}

    async def test_non_zone_facts_have_no_multiplier(
        self, client: Client[FastMCPTransport], multi_story: ServerState
    ) -> None:
        result = await _results(client, object_type="ZoneHVAC:WindowAirConditioner", name="Mid Center Window AC")
        assert result.facts.items
        assert all(f.multiplier is None for f in result.facts.items)


class TestSharedNames:
    async def test_types_sharing_a_name_stay_separate(self, client: Client[FastMCPTransport], tmp_path: Path) -> None:
        """A People object named like its zone (as in ShopWithSimplePVT) gets none of the zone's results."""
        state = get_state()
        doc = load_idf(str(model_path("5ZoneAirCooled", tmp_path)), strict=True)
        doc.add(
            "People",
            "SPACE1-1",
            zone_or_zonelist_or_space_or_spacelist_name="SPACE1-1",
            number_of_people_schedule_name="OCCUPY-1",
            activity_level_schedule_name="ActSchd",
            validate=False,
        )
        state.document = doc
        state.schema = doc.schema
        install_run("5ZoneAirCooled", tmp_path, load=False)

        zone = await _results(client, object_type="Zone", name="SPACE1-1")
        people = await _results(client, object_type="People", name="SPACE1-1")
        assert zone.object.object_type == "Zone"
        assert people.object.object_type == "People"
        assert zone.facts.total > 0
        assert all(f.multiplier == 1 for f in zone.facts.items)
        assert people.facts.total == 0
        assert people.available_variables.total == 0


class TestUnresolved:
    async def test_unlinked_items_are_listed_in_coverage(
        self, client: Client[FastMCPTransport], tmp_path: Path
    ) -> None:
        """Results naming an object the model no longer has are counted and shown, never dropped."""
        state = get_state()
        doc = load_idf(str(model_path("5ZoneAirCooled", tmp_path)), strict=True)
        coil = doc.get_collection("Coil:Heating:Water").get("SPACE1-1 Zone Coil")
        assert coil is not None
        coil.name = "Renamed Reheat Coil"
        state.document = doc
        state.schema = doc.schema
        install_run("5ZoneAirCooled", tmp_path, load=False)

        result = await _results(client, **TERMINAL)
        assert result.coverage.partial is True
        assert result.coverage.unresolved is not None
        assert result.coverage.unresolved > 0
        (part,) = [p for p in result.coverage.uncovered if p.kind == "unlinked_result"]
        assert part.count == result.coverage.unresolved
        assert part.examples
        assert all(e.object_type == "Unresolved" for e in part.examples)
        assert any("SPACE1-1 ZONE COIL" in e.name.upper() for e in part.examples)


class TestFreshness:
    async def test_fresh_then_stale_after_update_object(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        assert (await _results(client, **TERMINAL)).results_state == "fresh"
        await call_tool(
            client,
            "update_object",
            {"object_type": "Zone", "name": "SPACE1-1", "fields": {"x_origin": 1.0}},
        )
        after = await _results(client, **TERMINAL)
        assert after.results_state == "stale"
        assert after.facts.total > 0  # stale results are still answered (FR-026)

    async def test_run_identity_is_recorded(self, five_zone: ServerState) -> None:
        doc = five_zone.require_model()
        assert five_zone.simulation_run_revision == doc.revision
        assert five_zone.simulation_model_hash is not None
        assert len(five_zone.simulation_model_hash) == 64
        assert five_zone.simulation_run_dir is not None

    async def test_replaced_document_with_the_same_text_is_fresh(
        self, client: Client[FastMCPTransport], five_zone: ServerState, tmp_path: Path
    ) -> None:
        """A restored or replaced document is the simulated model only if its model hash says so."""
        same = load_idf(str(model_path("5ZoneAirCooled", tmp_path)), strict=True)
        five_zone.document = same
        assert (await _results(client, **TERMINAL)).results_state == "fresh"

        changed = load_idf(str(model_path("5ZoneAirCooled", tmp_path)), strict=True)
        zone = changed.get_collection("Zone").get("SPACE1-1")
        assert zone is not None
        zone.x_origin = 5.0
        five_zone.document = changed
        assert (await _results(client, **TERMINAL)).results_state == "stale"

    async def test_restored_session_without_hash_is_stale(
        self, client: Client[FastMCPTransport], five_zone: ServerState
    ) -> None:
        """A run with no recorded model hash (a session file without one) never reads fresh."""
        five_zone.simulation_model_hash = None
        five_zone.simulation_run_revision = None
        assert (await _results(client, **TERMINAL)).results_state == "stale"
