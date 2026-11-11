"""Protocol tests for get_object_neighbourhood (the cross-layer model graph), through FastMCP."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from idfkit.simulation.result import SimulationResult
from mcp.types import TextContent

from idfkit_mcp.models import ObjectNeighbourhood
from idfkit_mcp.state import get_state
from tests.conftest import call_tool
from tests.linked_runs import install_run

FIXTURES = Path(__file__).parent / "fixtures"
FIVE_ZONE_GZ = FIXTURES / "5ZoneAirCooled.idf.gz"
RESPONSE_BYTES = 8192
TERMINAL = {"object_type": "AirTerminal:SingleDuct:VAV:Reheat", "name": "SPACE1-1 VAV Reheat"}
TERMINAL_ID = "object:AIRTERMINAL:SINGLEDUCT:VAV:REHEAT:SPACE1-1 VAV REHEAT"
COIL_ID = "object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL"
ZONE_ID = "object:ZONE:SPACE1-1"
NO_RUN = "no simulation run in this session"


async def load_gz(client: Client[FastMCPTransport], gz: Path, tmp_path: Path) -> Client[FastMCPTransport]:
    target = tmp_path / gz.stem
    with gzip.open(gz, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    await client.call_tool("load_model", {"file_path": str(target)})
    return client


@pytest.fixture()
async def five_zone(client: Client[FastMCPTransport], tmp_path: Path) -> Client[FastMCPTransport]:
    return await load_gz(client, FIVE_ZONE_GZ, tmp_path)


async def neighbourhood(client: Client[FastMCPTransport], **arguments: object) -> ObjectNeighbourhood:
    result = await call_tool(client, "get_object_neighbourhood", dict(arguments), model=ObjectNeighbourhood)
    assert isinstance(result, ObjectNeighbourhood)
    return result


async def raw_size(client: Client[FastMCPTransport], **arguments: object) -> int:
    """Bytes of the serialized response as the client receives it (the text content)."""
    result = await client.call_tool("get_object_neighbourhood", dict(arguments))
    return sum(len(part.text.encode()) for part in result.content if isinstance(part, TextContent))


async def neighbourhood_error(client: Client[FastMCPTransport], **arguments: object) -> str:
    with pytest.raises(ToolError) as excinfo:
        await client.call_tool("get_object_neighbourhood", dict(arguments))
    return str(excinfo.value)


def ids(result: ObjectNeighbourhood) -> set[str]:
    return {n.id for n in result.nodes}


def assert_closed(result: ObjectNeighbourhood) -> None:
    """Every edge joins two returned nodes, and the start and frontier are returned nodes."""
    returned = ids(result)
    assert len(returned) == len(result.nodes)
    assert result.start in returned
    for edge in result.edges:
        assert edge.source in returned, edge
        assert edge.target in returned, edge
    assert set(result.frontier) <= returned


class TestUserStory7:
    async def test_terminal_coil_flow_through_nodes(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(five_zone, **TERMINAL, hops=2)
        assert result.start == TERMINAL_ID
        by_id = {n.id: n for n in result.nodes}
        coil = by_id[COIL_ID]
        assert coil.kind == "object"
        assert (coil.object_type, coil.name) == (
            "Coil:Heating:Water",
            "SPACE1-1 Zone Coil",
        )
        assert coil.attrs["category"] == "heating_coil"
        assert by_id[TERMINAL_ID].attrs["category"] == "terminal_unit"
        # The coil is joined to the terminal by flow edges through node nodes, never directly.
        flows = [e for e in result.edges if e.kind == "flow"]
        assert flows
        for edge in flows:
            ends = {by_id[edge.source].kind, by_id[edge.target].kind}
            assert ends == {"object", "node"}, edge
        coil_flow_nodes = {e.source for e in flows if e.target == COIL_ID} | {
            e.target for e in flows if e.source == COIL_ID
        }
        terminal_flow_nodes = {e.source for e in flows if e.target == TERMINAL_ID} | {
            e.target for e in flows if e.source == TERMINAL_ID
        }
        shared = coil_flow_nodes & terminal_flow_nodes
        assert shared and all(by_id[n].kind == "node" for n in shared)
        assert "node:SPACE1-1 ZONE COIL AIR IN NODE" in shared
        assert result.layers == ["model", "topology"]
        assert result.unavailable == {"results": NO_RUN}
        assert result.results_state is None
        assert_closed(result)

    async def test_zone_and_reheat_coil_are_object_nodes(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(
            five_zone,
            object_type="Zone",
            name="SPACE1-1",
            hops=3,
            edge_kinds=["flow", "reference"],
            categories=["terminal_unit", "heating_coil", "zone_equipment"],
        )
        by_id = {n.id: n for n in result.nodes}
        assert result.start == ZONE_ID
        for object_id in (ZONE_ID, TERMINAL_ID, COIL_ID):
            assert by_id[object_id].kind == "object"
        assert_closed(result)

    async def test_coil_membership_edge_to_its_loop(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(
            five_zone, object_type="Coil:Heating:Water", name="SPACE1-1 Zone Coil", edge_kinds=["membership"]
        )
        memberships = {(e.source, e.target) for e in result.edges if e.kind == "membership"}
        assert (COIL_ID, "object:PLANTLOOP:HOT WATER LOOP") in memberships
        assert (COIL_ID, "object:AIRLOOPHVAC:VAV SYS 1") in memberships
        assert {e.kind for e in result.edges} == {"membership"}
        assert_closed(result)

    async def test_category_filter_keeps_start_and_matching_objects(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(five_zone, **TERMINAL, hops=2, categories=["heating_coil"])
        objects = [n for n in result.nodes if n.kind == "object"]
        assert {n.id for n in objects} >= {TERMINAL_ID, COIL_ID}
        for node in objects:
            assert node.id == TERMINAL_ID or node.attrs["category"] == "heating_coil", node
        assert_closed(result)

    async def test_max_nodes_truncates_with_frontier(self, five_zone: Client[FastMCPTransport]) -> None:
        arguments: dict[str, object] = {**TERMINAL, "hops": 2, "max_nodes": 5}
        result = await neighbourhood(five_zone, **arguments)
        assert len(result.nodes) <= 5
        assert result.truncated is True
        assert result.omitted_nodes > 0
        assert result.frontier
        assert_closed(result)
        assert len(result.model_dump_json().encode()) < RESPONSE_BYTES
        assert await raw_size(five_zone, **arguments) < RESPONSE_BYTES

    @pytest.mark.parametrize(
        "start",
        [
            TERMINAL,
            {"object_type": "Schedule:Compact", "name": "ReheatCoilAvailSched"},
            {"object_type": "AirLoopHVAC", "name": "VAV Sys 1"},
        ],
    )
    async def test_large_walk_stays_under_8kb(self, five_zone: Client[FastMCPTransport], start: dict[str, str]) -> None:
        arguments: dict[str, object] = {**start, "hops": 3, "max_nodes": 100}
        result = await neighbourhood(five_zone, **arguments)
        assert result.truncated is True
        assert 1 <= len(result.nodes) < 100
        assert result.frontier
        assert_closed(result)
        assert len(result.model_dump_json().encode()) < RESPONSE_BYTES
        assert await raw_size(five_zone, **arguments) < RESPONSE_BYTES


class TestStarts:
    async def test_node_start(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(five_zone, object_type="Node", name="space1-1 zone coil air in node")
        assert result.start == "node:SPACE1-1 ZONE COIL AIR IN NODE"
        by_id = {n.id: n for n in result.nodes}
        start = by_id[result.start]
        assert start.kind == "node" and start.object_type is None
        assert start.name == "SPACE1-1 Zone Coil Air In Node"
        assert start.attrs["fluid"] == "Air"
        assert {TERMINAL_ID, COIL_ID} <= set(by_id)
        assert_closed(result)

    async def test_case_insensitive_object_start(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(five_zone, object_type="zone", name="space1-1")
        assert result.start == ZONE_ID
        assert_closed(result)

    async def test_object_nodes_carry_category(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(five_zone, **TERMINAL, hops=2)
        objects = [n for n in result.nodes if n.kind == "object"]
        assert objects
        for node in objects:
            assert node.object_type is not None
            assert isinstance(node.attrs.get("category"), str), node
        for node in result.nodes:
            if node.kind == "node":
                assert node.name and node.object_type is None

    async def test_node_kinds_filter(self, five_zone: Client[FastMCPTransport]) -> None:
        result = await neighbourhood(five_zone, **TERMINAL, hops=2, node_kinds=["Object"])
        assert {n.kind for n in result.nodes} == {"object"}
        assert_closed(result)

    async def test_results_unlinked_when_the_run_has_no_sqlite(
        self, five_zone: Client[FastMCPTransport], tmp_path: Path
    ) -> None:
        get_state().simulation_result = SimulationResult(
            run_dir=tmp_path, success=True, exit_code=0, stdout="", stderr="", runtime_seconds=0.1
        )
        result = await neighbourhood(five_zone, **TERMINAL)
        assert result.layers == ["model", "topology"]
        assert result.unavailable == {
            "results": "the session's run could not be linked to the model (no SQLite output)"
        }

    async def test_results_layer_after_a_linked_run(self, five_zone: Client[FastMCPTransport], tmp_path: Path) -> None:
        install_run("5ZoneAirCooled", tmp_path, load=False)
        result = await neighbourhood(
            five_zone, object_type="AirLoopHVAC", name="VAV Sys 1", node_kinds=["result_fact", "message"], max_nodes=10
        )
        assert result.layers == ["model", "topology", "results"]
        assert result.unavailable == {}
        assert result.results_state == "fresh"
        assert "result_fact" in {n.kind for n in result.nodes}
        messages = await neighbourhood(
            five_zone, object_type="AirLoopHVAC", name="VAV Sys 1", node_kinds=["message"], max_nodes=10
        )
        assert [n.attrs.get("message_kind") for n in messages.nodes if n.kind == "message"] == [
            "sizing.system_flow_ratio"
        ]
        links = [e for e in result.edges if e.kind == "result_link"]
        assert links
        assert all(e.target == "object:AIRLOOPHVAC:VAV SYS 1" for e in links)
        facts = [n for n in result.nodes if n.kind == "result_fact"]
        assert all(n.attrs.get("stale") is False for n in facts)
        assert_closed(result)

    async def test_results_layer_reads_stale_after_an_edit(
        self, five_zone: Client[FastMCPTransport], tmp_path: Path
    ) -> None:
        install_run("5ZoneAirCooled", tmp_path, load=False)
        next(iter(get_state().require_model()["Zone"])).multiplier = 2
        result = await neighbourhood(
            five_zone, object_type="AirLoopHVAC", name="VAV Sys 1", node_kinds=["result_fact", "message"], max_nodes=10
        )
        assert result.results_state == "stale"
        results = [n for n in result.nodes if n.kind in {"result_fact", "message"}]
        assert results
        assert all(n.attrs.get("stale") is True for n in results)


class TestErrors:
    async def test_no_model_loaded(self, client: Client[FastMCPTransport]) -> None:
        message = await neighbourhood_error(client, object_type="Zone", name="SPACE1-1")
        assert "No model loaded" in message

    @pytest.mark.parametrize("hops", [0, 4])
    async def test_hops_out_of_range(self, five_zone: Client[FastMCPTransport], hops: int) -> None:
        message = await neighbourhood_error(five_zone, **TERMINAL, hops=hops)
        assert "between 1 and 3" in message and str(hops) in message

    @pytest.mark.parametrize("max_nodes", [0, 101])
    async def test_max_nodes_out_of_range(self, five_zone: Client[FastMCPTransport], max_nodes: int) -> None:
        message = await neighbourhood_error(five_zone, **TERMINAL, max_nodes=max_nodes)
        assert "between 1 and 100" in message and str(max_nodes) in message

    async def test_unknown_node_kind(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await neighbourhood_error(five_zone, **TERMINAL, node_kinds=["object", "blob"])
        assert "'blob'" in message
        for kind in ("object", "node", "result_fact", "message"):
            assert kind in message

    async def test_unknown_edge_kind(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await neighbourhood_error(five_zone, **TERMINAL, edge_kinds=["flow", "pipe"])
        assert "'pipe'" in message
        for kind in ("reference", "flow", "control", "membership", "result_link"):
            assert kind in message

    async def test_unknown_category(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await neighbourhood_error(five_zone, **TERMINAL, categories=["heater"])
        assert "'heater'" in message
        for category in ("heating_coil", "cooling_coil", "fan", "pump", "terminal_unit", "other"):
            assert category in message

    async def test_object_not_found_lists_closest(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await neighbourhood_error(five_zone, object_type="Zone", name="SPACE1-2")
        assert "SPACE1-2" in message
        assert "Closest:" in message and "'SPACE1-1'" in message

    async def test_node_not_found_lists_closest(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await neighbourhood_error(five_zone, object_type="Node", name="SPACE1-1 Zone Coil Air In Nod")
        assert "Closest:" in message and "'SPACE1-1 Zone Coil Air In Node'" in message

    async def test_unknown_object_type(self, five_zone: Client[FastMCPTransport]) -> None:
        message = await neighbourhood_error(five_zone, object_type="Zne", name="SPACE1-1")
        assert "'Zone'" in message
