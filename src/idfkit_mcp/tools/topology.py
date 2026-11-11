"""HVAC topology tools: how a model's HVAC objects connect through their nodes (idfkit.hvac)."""

from __future__ import annotations

import difflib
import logging
from collections import Counter
from collections.abc import Iterable
from typing import Annotated, Any, Literal, cast

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from idfkit import IDFDocument, IDFObject
from idfkit.hvac import (
    ComponentCategory,
    ConnectionType,
    Coverage,
    FlowEdge,
    Fluid,
    HVACTopology,
    LoopMembership,
    NodeUse,
    TopologyFinding,
)
from idfkit.hvac import ObjectKey as HvacKey
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp import models as m
from idfkit_mcp.compact_schema import compact_output_schema
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_MUTATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

_CATEGORIES: dict[str, ComponentCategory] = {c.value: c for c in ComponentCategory}
_FLUIDS: dict[str, Fluid] = {f.value.lower(): f for f in Fluid if f is not Fluid.UNKNOWN}
_ZONE_TYPES = ("Zone", "Space")
_CLOSEST = 5
_TIMES = "\u00d7"  # the multiplication sign of a collapsed count (spec FR-016)

FluidName = Literal["Air", "Water", "Steam", "Refrigerant"]


# ----------------------------------------------------------------------------------------------- #
# Mirrors: idfkit dataclasses to the response models
# ----------------------------------------------------------------------------------------------- #


def _key(key: HvacKey) -> m.ObjectKey:
    return m.ObjectKey(object_type=key.object_type, name=key.name)


def _use(use: NodeUse) -> m.NodeUse:
    return m.NodeUse(
        node=use.node,
        object=_key(use.object),
        category=use.category.value,
        field=use.field,
        connection=use.connection.value if use.connection is not None else None,
        stream=use.stream,
        fluid=use.fluid.value,
        is_parent=use.is_parent,
        via_nodelist=use.via_nodelist,
        rule=use.rule,
        provenance=use.provenance,
    )


def _membership(ms: LoopMembership) -> m.LoopMembership:
    return m.LoopMembership(
        loop=_key(ms.loop),
        kind=ms.kind,
        side=ms.side,
        branch=_key(ms.branch) if ms.branch is not None else None,
        position=ms.position,
        stream=ms.stream,
    )


def _memberships(topo: HVACTopology, objs: Iterable[IDFObject]) -> list[m.LoopMembership]:
    """Every membership of *objs*, each loop and side once per stream."""
    found = dict.fromkeys(ms for obj in objs for ms in topo.memberships(obj))
    return [_membership(ms) for ms in found]


def _edge(edge: FlowEdge) -> m.FlowEdge:
    return m.FlowEdge(
        source=_key(edge.source), target=_key(edge.target), node=edge.node, fluid=edge.fluid.value, kind=edge.kind
    )


def _finding(f: TopologyFinding) -> m.TopologyFinding:
    return m.TopologyFinding(
        code=f.code,
        severity=f.severity,
        objects=[_key(k) for k in f.objects],
        message=f.message,
        provenance=f.provenance,
        node=f.node,
        field=f.field,
        expected=f.expected,
        actual=f.actual,
        capped_from=f.capped_from,
        cap_reason=f.cap_reason,
    )


def coverage_model(coverage: Coverage) -> m.Coverage:
    """Mirror an idfkit ``Coverage``."""
    return m.Coverage.model_validate({
        "partial": coverage.partial,
        "uncovered": [
            {
                "kind": part.kind,
                "count": part.count,
                "examples": [_key(k) for k in part.examples],
                "reason": part.reason,
            }
            for part in coverage.uncovered
        ],
        "resolved": coverage.resolved,
        "unresolved": coverage.unresolved,
    })


# ----------------------------------------------------------------------------------------------- #
# Argument checks
# ----------------------------------------------------------------------------------------------- #


def _closest(name: str, candidates: Iterable[str]) -> str:
    pool = list(candidates)
    by_upper = {c.upper(): c for c in pool}
    near = difflib.get_close_matches(name.upper(), list(by_upper), n=_CLOSEST, cutoff=0.6)
    if not near:
        return ""
    return " Closest: " + ", ".join(repr(by_upper[n]) for n in near) + "."


def parse_categories(categories: list[str] | None) -> list[ComponentCategory] | None:
    """Resolve category names, or raise a ToolError listing the vocabulary."""
    if categories is None:
        return None
    unknown = [c for c in categories if c.lower() not in _CATEGORIES]
    if unknown:
        msg = f"Unknown component categories {unknown}. Valid categories: {', '.join(_CATEGORIES)}."
        raise ToolError(msg)
    return [_CATEGORIES[c.lower()] for c in categories]


def _parse_fluid(fluid: str | None) -> Fluid | None:
    if fluid is None:
        return None
    try:
        return _FLUIDS[fluid.lower()]
    except KeyError:
        msg = f"Unknown fluid {fluid!r}. Valid fluids: {', '.join(f.value for f in _FLUIDS.values())}."
        raise ToolError(msg) from None


def _canonical_type(doc: IDFDocument[Any], object_type: str) -> str:
    wanted = object_type.upper()
    for present in doc.collections:
        if present.upper() == wanted:
            return present
    schema_types = list(doc.schema.object_types) if doc.schema is not None else []
    for known in schema_types:
        if known.upper() == wanted:
            msg = f"The model has no {known} objects."
            raise ToolError(msg)
    msg = f"Unknown object type {object_type!r}.{_closest(object_type, schema_types)} Use search_schema to find it."
    raise ToolError(msg)


def find_object(doc: IDFDocument[Any], object_type: str, name: str) -> IDFObject:
    """Find an object case-insensitively, or raise a ToolError naming the closest names."""
    collection = doc.get_collection(_canonical_type(doc, object_type))
    obj = collection.get(name) if name else None
    if obj is None:
        names = [o.name for o in collection]
        msg = f"No {collection.obj_type} named {name!r}.{_closest(name, names)}"
        raise ToolError(msg)
    return obj


# ----------------------------------------------------------------------------------------------- #
# trace_hvac
# ----------------------------------------------------------------------------------------------- #


def _family(topo: HVACTopology, doc: IDFDocument[Any], obj: IDFObject) -> tuple[m.ObjectKey | None, list[m.ObjectKey]]:
    """Parent: the equipment that names this object and has parent uses. Children: the reverse."""
    parent: m.ObjectKey | None = None
    for referrer in doc.get_referencing(obj.name):
        uses = topo.ports(referrer)
        if uses and any(u.is_parent for u in uses) and uses[0].category is not ComponentCategory.OTHER:
            parent = m.ObjectKey(object_type=referrer.obj_type, name=referrer.name)
            break
    children: list[m.ObjectKey] = []
    if any(u.is_parent for u in topo.ports(obj)):
        for name in sorted(doc.get_references(obj)):
            for child in _named(doc, name):
                if child is not obj and topo.ports(child):
                    children.append(m.ObjectKey(object_type=child.obj_type, name=child.name))
    return parent, children


def _named(doc: IDFDocument[Any], name: str) -> list[IDFObject]:
    """Objects of any type with this name: the targets a reference name can resolve to."""
    return [obj for collection in doc.collections.values() if (obj := collection.get(name)) is not None]


def _nodelist_members(doc: IDFDocument[Any], topo: HVACTopology, name: str) -> list[str] | None:
    """The used nodes a NodeList names, in the model's spelling, or None when there is no such list."""
    if "NodeList" not in doc or (nodelist := doc.get_collection("NodeList").get(name)) is None:
        return None
    members: list[str] = []
    for entry in nodelist.data.get("nodes", []):
        node = cast("dict[str, Any]", entry).get("node_name") if isinstance(entry, dict) else None
        if isinstance(node, str) and node:
            try:
                members.append(topo.uses(node)[0].node)
            except (KeyError, IndexError):
                continue
    return members


def _node_trace(doc: IDFDocument[Any], topo: HVACTopology, name: str, walk: dict[str, Any]) -> m.HVACTrace:
    try:
        nodes = [topo.uses(name)[0].node]
        start = m.TraceStart(object_type="Node", name=nodes[0])
    except (KeyError, IndexError):
        members = _nodelist_members(doc, topo, name)
        if not members:
            msg = f"No node or NodeList named {name!r} is used by any object.{_closest(name, topo.nodes())}"
            raise ToolError(msg) from None
        nodes = members
        start = m.TraceStart(object_type="NodeList", name=doc.get_collection("NodeList")[name].name)
    uses = [u for n in nodes for u in topo.uses(n)]
    fluids = {u.fluid for u in uses if not u.is_parent and u.connection is not None}
    wanted = {n.upper() for n in nodes}
    return m.HVACTrace(
        start=start,
        fluid=fluids.pop().value if len(fluids) == 1 else None,
        producers=_unique(o for n in nodes for o in _keys(topo.producers(n))),
        consumers=_unique(o for n in nodes for o in _keys(topo.consumers(n))),
        controls=[_use(u) for n in nodes for u in topo.controls(n)],
        memberships=_memberships(topo, [o for n in nodes for o in (*topo.producers(n), *topo.consumers(n))]),
        upstream=[_edge(e) for e in topo.upstream(name, **walk)],
        downstream=[_edge(e) for e in topo.downstream(name, **walk)],
        findings=[_finding(f) for f in topo.check() if f.node is not None and f.node.upper() in wanted],
        coverage=coverage_model(topo.coverage),
    )


def _keys(objs: Iterable[IDFObject]) -> Iterable[m.ObjectKey]:
    return (m.ObjectKey(object_type=o.obj_type, name=o.name) for o in objs)


def _unique(keys: Iterable[m.ObjectKey]) -> list[m.ObjectKey]:
    seen: set[tuple[str, str]] = set()
    out: list[m.ObjectKey] = []
    for k in keys:
        ident = (k.object_type.upper(), k.name.upper())
        if ident not in seen:
            seen.add(ident)
            out.append(k)
    return out


def _object_trace(
    topo: HVACTopology,
    doc: IDFDocument[Any],
    obj: IDFObject,
    walk: dict[str, Any],
) -> m.HVACTrace:
    ports = sorted(topo.ports(obj), key=lambda u: u.stream)
    try:
        upstream = topo.upstream(obj, **walk)
        downstream = topo.downstream(obj, **walk)
    except KeyError:
        msg = (
            f"{obj.obj_type} {obj.name!r} has no node fields, so it has no HVAC connections. "
            f"Read idfkit://model/references/{obj.name} to see what it references and what references it."
        )
        raise ToolError(msg) from None
    is_zone = obj.obj_type in _ZONE_TYPES
    category = None if is_zone else (ports[0].category.value if ports else None)
    port_nodes = {u.node.upper() for u in ports}
    own = HvacKey(obj.obj_type, obj.name)
    parent, children = (None, []) if is_zone else _family(topo, doc, obj)
    findings = [
        f
        for f in topo.check()
        if own in f.objects
        or any(k.object_type in _ZONE_TYPES and k.name.upper() == obj.name.upper() for k in f.objects)
    ]
    return m.HVACTrace(
        start=m.TraceStart(object_type=obj.obj_type, name=obj.name, category=category),
        ports=[_use(u) for u in ports],
        controls=_unique_uses(u for n in port_nodes for u in topo.controls(n)),
        memberships=_memberships(topo, [obj]),
        parent=parent,
        children=children,
        upstream=[_edge(e) for e in upstream],
        downstream=[_edge(e) for e in downstream],
        findings=[_finding(f) for f in findings],
        coverage=coverage_model(topo.coverage),
    )


def _unique_uses(uses: Iterable[NodeUse]) -> list[m.NodeUse]:
    return [_use(u) for u in dict.fromkeys(uses)]


@tool(annotations=_READ_ONLY, output_schema=compact_output_schema(m.HVACTrace))
def trace_hvac(
    object_type: Annotated[
        str,
        Field(description='"Node" for a node or NodeList, "Zone"/"Space" for a zone, else the component type.'),
    ],
    name: Annotated[str, Field(description="Node or object name, matched case-insensitively.")],
    hops: Annotated[int, Field(ge=0, le=10, description="Flow edges to walk upstream and downstream.")] = 2,
    categories: Annotated[
        list[str] | None,
        Field(description="Keep only walk edges ending at these component categories, e.g. heating_coil, boiler."),
    ] = None,
    fluid: Annotated[
        FluidName | None,
        Field(description="Keep the walks on one fluid. Default: follow every stream, crossing at coils."),
    ] = None,
) -> m.HVACTrace:
    """Trace one HVAC node or component: its ports, producers and consumers, controls, flow up and
    downstream, and the connection findings touching it.

    Nearest neighbour: the idfkit://model/references/{name} resource, for what an object references
    and what references it. Node names are not references, so only trace_hvac sees node connections.

    Preconditions: model loaded.
    Side effects: none.
    """
    doc = get_state().require_model()
    walk: dict[str, Any] = {"hops": hops, "categories": parse_categories(categories), "fluid": _parse_fluid(fluid)}
    topo = HVACTopology.from_document(doc)
    if object_type.strip().lower() in {"node", "nodelist"}:
        return _node_trace(doc, topo, name, walk)
    obj = find_object(doc, object_type, name)
    return _object_trace(topo, doc, obj, walk)


# ----------------------------------------------------------------------------------------------- #
# get_hvac_topology: loop summaries
# ----------------------------------------------------------------------------------------------- #

_LOOP_KINDS: dict[str, Literal["air", "plant", "condenser"]] = {
    "AIRLOOPHVAC": "air",
    "PLANTLOOP": "plant",
    "CONDENSERLOOP": "condenser",
}


def _label(obj: IDFObject) -> str:
    return f"{obj.obj_type} '{obj.name}'"


def _render_paths(paths: list[list[IDFObject]]) -> list[str]:
    """Each distinct path once, in first-seen order, a path seen once with every name.

    Single-component paths (parallel plant branches) of one type collapse to a count. Longer paths
    collapse only when they also start at the same component, whose name is kept: a dual-duct
    system's two decks share their types but not their splitter, so they stay two entries.
    """
    groups: dict[tuple[int | None, tuple[str, ...]], list[list[IDFObject]]] = {}
    for path in paths:
        if path:
            head = id(path[0]) if len(path) > 1 else None
            groups.setdefault((head, tuple(o.obj_type for o in path)), []).append(path)
    out: list[str] = []
    for (head, types), members in groups.items():
        if len(members) > 1:
            shown = [_label(members[0][0]), *types[1:]] if head is not None else list(types)
            out.append(f"{len(members)}{_TIMES} " + " → ".join(shown))
        else:
            out.append(" → ".join(_label(o) for o in members[0]))
    return out


def _render_side(paths: list[list[IDFObject]], *, parallel_outlet: bool) -> str:
    """A side as one flow-order string.

    Branch lists run inlet branch → {parallel branches} → outlet branch on plant and condenser
    loops, and inlet branch → {decks} on an air loop's supply side. An air demand side lists its
    paths to the zones, then its return paths, separated by semicolons.
    """
    if not paths:
        return ""
    if parallel_outlet and len(paths) >= 3:
        middle = " | ".join(_render_paths(paths[1:-1]))
        return " → ".join([*_render_paths([paths[0]]), "{" + middle + "}", *_render_paths([paths[-1]])])
    if not parallel_outlet and len(paths) >= 2:
        return " → ".join([*_render_paths([paths[0]]), "{" + " | ".join(_render_paths(paths[1:])) + "}"])
    return " → ".join(_render_paths(paths))


def _count_side(paths: list[list[IDFObject]], unit: str) -> str:
    components = sum(len(p) for p in paths)
    return f"{len(paths)} {unit}{'' if len(paths) == 1 else 'es' if unit == 'branch' else 's'}, {components} components"


def _loop_summary(topo: HVACTopology, loop: IDFObject, detail: str, findings: list[TopologyFinding]) -> m.LoopSummary:
    kind = _LOOP_KINDS[loop.obj_type.upper()]
    supply = topo.chain(loop, "supply")
    demand = topo.chain(loop, "demand")
    if detail == "chain":
        supply_text = _render_side(supply, parallel_outlet=kind != "air")
        demand_text = "; ".join(_render_paths(demand)) if kind == "air" else _render_side(demand, parallel_outlet=True)
    else:
        supply_text = _count_side(supply, "branch")
        demand_text = _count_side(demand, "path" if kind == "air" else "branch")
    members = {(o.obj_type.upper(), o.name.upper()) for path in (*supply, *demand) for o in path}
    members.add((loop.obj_type.upper(), loop.name.upper()))
    setpoints: dict[str, None] = {}
    air = kind == "air"
    for obj in [loop, *(o for path in (*supply, *demand) for o in path)]:
        for port in topo.ports(obj):
            if (port.fluid is Fluid.AIR) != air and port.fluid is not Fluid.UNKNOWN:
                continue  # a coil's other stream belongs to the other loop
            for use in topo.controls(port.node):
                if use.connection is ConnectionType.SETPOINT:
                    setpoints[use.node] = None
    counts = Counter(
        f.code for f in findings if any((k.object_type.upper(), k.name.upper()) in members for k in f.objects)
    )
    fluid = "Air" if kind == "air" else str(loop.data.get("fluid_type") or "Water")
    return m.LoopSummary(
        loop=m.ObjectKey(object_type=loop.obj_type, name=loop.name),
        kind=kind,
        fluid=fluid,
        supply=supply_text,
        demand=demand_text,
        zones_served=len(topo.zones_served(loop)) if kind == "air" else 0,
        setpoint_nodes=list(setpoints),
        finding_counts=dict(sorted(counts.items())),
    )


def build_topology_summary(loop: str | None, detail: str, limit: int) -> m.HVACTopologySummary:
    """The ``get_hvac_topology`` response; also serves the ``idfkit://model/hvac/{loop}`` resource."""
    doc = get_state().require_model()
    topo = HVACTopology.from_document(doc)
    loops = topo.loops()
    if loop is not None:
        chosen = [lp for lp in loops if lp.name.upper() == loop.strip().upper()]
        if not chosen:
            msg = (
                f"No AirLoopHVAC, PlantLoop or CondenserLoop named {loop!r}.{_closest(loop, (lp.name for lp in loops))}"
            )
            raise ToolError(msg)
        loops = chosen
    findings = topo.check()
    shown = loops[:limit]
    return m.HVACTopologySummary(
        loops=[_loop_summary(topo, lp, detail, findings) for lp in shown],
        total=len(loops),
        omitted=len(loops) - len(shown),
        coverage=coverage_model(topo.coverage),
    )


@tool(annotations=_READ_ONLY, output_schema=compact_output_schema(m.HVACTopologySummary))
def get_hvac_topology(
    loop: Annotated[str | None, Field(description="Loop name (air, plant or condenser). Default: every loop.")] = None,
    detail: Annotated[
        Literal["summary", "chain"],
        Field(
            description='"summary": counts per side. "chain": each side in flow order, repeated paths collapsed to a count.'
        ),
    ] = "summary",
    limit: Annotated[int, Field(ge=1, le=100, description="Loops per response.")] = 20,
) -> m.HVACTopologySummary:
    """Summarise HVAC loops: kind, fluid, supply and demand sides, zones served, setpoint nodes and
    connection findings per code.

    Nearest neighbour: trace_hvac, for one node or component (its loop, side, branch, position and
    controls) rather than whole loops.

    Preconditions: model loaded.
    Side effects: none.
    """
    return build_topology_summary(loop, detail, limit)


@tool(annotations=_MUTATE)
def rename_node(
    old: Annotated[str, Field(description="Current node name, matched case-insensitively.")],
    new: Annotated[str, Field(description="New node name; must not already be a node.")],
) -> m.NodeRenameResult:
    """Rename a node in every field and NodeList entry that uses it, in one step.

    Nearest neighbour: rename_object, for object names. Node names are not references, so
    rename_object never reaches them.

    Preconditions: model loaded.
    Side effects: rewrites the node fields; recorded in the change log.
    """
    doc = get_state().require_model()
    try:
        result = doc.rename_node(old, new)
    except KeyError:
        topo = HVACTopology.from_document(doc)
        msg = f"No field uses a node named {old!r}.{_closest(old, topo.nodes())}"
        raise ToolError(msg) from None
    except ValueError as e:
        raise ToolError(f"{e}. Choose another name.") from None
    logger.info("Renamed node %r -> %r (%d fields)", result.old, result.new, result.fields_updated)
    return m.NodeRenameResult(
        old=result.old,
        new=result.new,
        fields_updated=result.fields_updated,
        objects=[_key(k) for k in result.objects],
    )
