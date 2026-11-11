"""HVAC topology tools: how a model's HVAC objects connect through their nodes (idfkit.hvac)."""

from __future__ import annotations

import difflib
import logging
from collections.abc import Iterable
from typing import Annotated, Any, Literal, cast

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from idfkit import IDFDocument, IDFObject
from idfkit.hvac import ComponentCategory, Coverage, FlowEdge, Fluid, HVACTopology, NodeUse, TopologyFinding
from idfkit.hvac import ObjectKey as HvacKey
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp import models as m
from idfkit_mcp.compact_schema import compact_output_schema
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

_CATEGORIES: dict[str, ComponentCategory] = {c.value: c for c in ComponentCategory}
_FLUIDS: dict[str, Fluid] = {f.value.lower(): f for f in Fluid if f is not Fluid.UNKNOWN}
_ZONE_TYPES = ("Zone", "Space")
_CLOSEST = 5

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
        memberships=[],
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
        memberships=[],
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
