"""The cross-layer neighbourhood of one object or node (idfkit.graph)."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from idfkit import IDFDocument
from idfkit.graph import GraphEdge, GraphNode, ModelGraph, Subgraph
from idfkit.hvac import HVACTopology, ObjectKey
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp import models as m
from idfkit_mcp.compact_schema import compact_output_schema
from idfkit_mcp.state import get_state
from idfkit_mcp.tools.topology import RESPONSE_BYTES, closest, coverage_model, find_object, parse_categories

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

NODE_KINDS = ("object", "node", "result_fact", "message")
EDGE_KINDS = ("reference", "flow", "control", "membership", "result_link")
MAX_HOPS = 3
MAX_NODES = 100
_ENVELOPE_BYTES = 64
_NO_RUN = "no simulation run in this session"
_NOT_LINKED = "results are not linked to objects in this release"


def _kinds(given: list[str] | None, vocabulary: tuple[str, ...], what: str) -> list[str] | None:
    if given is None:
        return None
    unknown = [k for k in given if k.lower() not in vocabulary]
    if unknown:
        msg = f"Unknown {what} {unknown}. Valid {what}: {', '.join(vocabulary)}."
        raise ToolError(msg)
    return [k.lower() for k in given]


def _node(node: GraphNode) -> m.GraphNode:
    key = None if node.key is None else m.ObjectKey(object_type=node.key.object_type, name=node.key.name)
    return m.GraphNode(
        id=node.id, kind=node.kind, layer=node.layer, key=key, node=node.node, label=node.label, attrs=dict(node.attrs)
    )


def _edge(edge: GraphEdge) -> m.GraphEdge:
    return m.GraphEdge(
        source=edge.source, target=edge.target, kind=edge.kind, layer=edge.layer, key=edge.key, attrs=dict(edge.attrs)
    )


def _mirror(sub: Subgraph, *, simulated: bool) -> m.ObjectNeighbourhood:
    unavailable = {
        str(layer): (_NOT_LINKED if simulated else _NO_RUN) if layer == "results" else reason
        for layer, reason in sub.unavailable.items()
    }
    return m.ObjectNeighbourhood(
        start=sub.start,
        nodes=[_node(n) for n in sub.nodes],
        edges=[_edge(e) for e in sub.edges],
        layers=[str(layer) for layer in sub.layers],
        unavailable=unavailable,
        truncated=sub.truncated,
        omitted_nodes=sub.omitted_nodes,
        frontier=sub.frontier,
        results_state=sub.results_state,
        coverage=coverage_model(sub.coverage),
    )


def _start(doc: IDFDocument[Any], object_type: str, name: str) -> ObjectKey | str:
    if object_type.strip().lower() == "node":
        topo = HVACTopology.from_document(doc)
        try:
            topo.uses(name)
        except KeyError:
            msg = f"No node named {name!r} is used by any object.{closest(name, topo.nodes())}"
            raise ToolError(msg) from None
        return name
    obj = find_object(doc, object_type, name)
    return ObjectKey(obj.obj_type, obj.name)


@tool(annotations=_READ_ONLY, output_schema=compact_output_schema(m.ObjectNeighbourhood))
def get_object_neighbourhood(
    object_type: Annotated[str, Field(description='The start object\'s type, or "Node" to start from a node.')],
    name: Annotated[str, Field(description="Object or node name, matched case-insensitively.")],
    hops: Annotated[int, Field(description="Edges to walk from the start, 1-3.")] = 1,
    node_kinds: Annotated[
        list[str] | None, Field(description="Walk only these node kinds: object, node, result_fact, message.")
    ] = None,
    edge_kinds: Annotated[
        list[str] | None,
        Field(description="Walk only these edge kinds: reference, flow, control, membership, result_link."),
    ] = None,
    categories: Annotated[
        list[str] | None,
        Field(description="Keep only objects of these component categories (and the start), e.g. heating_coil."),
    ] = None,
    max_nodes: Annotated[int, Field(description="Most nodes returned, 1-100.")] = 40,
) -> m.ObjectNeighbourhood:
    """Walk the model graph around one object or node, across layers: objects joined by references,
    and fluid nodes joined to objects by flow, control and loop-membership edges.

    Nearest neighbours: trace_hvac, for one node or component's loop, side, branch, position and
    controls already interpreted; get_hvac_topology, for a whole loop in flow order. Use this one to
    cross layers, or for an object with no node fields. A cut walk sets truncated and lists the
    frontier; call again from a frontier node to continue.

    Preconditions: model loaded.
    Side effects: none.
    """
    state = get_state()
    doc = state.require_model()
    if not 1 <= hops <= MAX_HOPS:
        msg = f"hops must be between 1 and {MAX_HOPS}, got {hops}."
        raise ToolError(msg)
    if not 1 <= max_nodes <= MAX_NODES:
        msg = f"max_nodes must be between 1 and {MAX_NODES}, got {max_nodes}."
        raise ToolError(msg)
    walk: dict[str, Any] = {
        "hops": hops,
        "node_kinds": _kinds(node_kinds, NODE_KINDS, "node kinds"),
        "edge_kinds": _kinds(edge_kinds, EDGE_KINDS, "edge kinds"),
        "categories": parse_categories(categories),
    }
    start = _start(doc, object_type, name)
    graph = ModelGraph(doc)
    simulated = state.simulation_result is not None
    limit = max_nodes
    while True:
        result = _mirror(graph.neighbourhood(start, max_nodes=limit, **walk), simulated=simulated)
        size = len(result.model_dump_json()) + _ENVELOPE_BYTES
        if size <= RESPONSE_BYTES or limit == 1:
            return result
        # Shrink in proportion, at least by one node, until whole nodes and edges fit.
        limit = max(1, min(limit - 1, int(limit * RESPONSE_BYTES / size * 0.95)))
