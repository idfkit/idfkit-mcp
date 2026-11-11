"""Model facts shared by the fault types and task specs under ``eval/faults/`` and ``eval/tasks/``.

Everything here reads or edits an ``IDFDocument`` through idfkit's public API only (the server is pinned to an
idfkit level without ``idfkit.hvac``, so connection facts are derived here from the raw objects: branches, branch
lists, connectors, supply paths, terminals and zone equipment). Selection helpers are deterministic: candidates are
visited in a stable order (object names case-folded and sorted, then list order inside an object), so a fault or a
task picks the same target on the same model every time.

Names are compared case-insensitively, as EnergyPlus does.
"""

from __future__ import annotations

import hashlib
import importlib
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from idfkit import IDFDocument, IDFObject, write_idf

from eval.model import ObjectKey

if TYPE_CHECKING:
    from idfkit.simulation.result import SimulationResult

PlantSideName = Literal["supply", "demand"]

TERMINAL_PREFIX = "AirTerminal:"
SINGLE_DUCT_NO_REHEAT = ("AirTerminal:SingleDuct:VAV:NoReheat", "AirTerminal:SingleDuct:ConstantVolume:NoReheat")
WATER_COOLING_COILS = ("Coil:Cooling:Water", "Coil:Cooling:Water:DetailedGeometry")
WATER_COILS = (*WATER_COOLING_COILS, "Coil:Heating:Water")
PACKAGED_ZONE_UNITS = (
    "ZoneHVAC:PackagedTerminalAirConditioner",
    "ZoneHVAC:PackagedTerminalHeatPump",
)
PACKAGED_AIR_LOOP_UNITS = (
    "AirLoopHVAC:UnitarySystem",
    "AirLoopHVAC:UnitaryHeatCool",
    "AirLoopHVAC:UnitaryHeatPump:AirToAir",
    "AirLoopHVAC:Unitary:Furnace:HeatCool",
    "AirLoopHVAC:Unitary:Furnace:HeatOnly",
    "AirLoopHVAC:UnitaryHeatOnly",
)
PORT_FIELD_PAIRS = (
    ("air_inlet_node_name", "air_outlet_node_name"),
    ("inlet_node_name", "outlet_node_name"),
    ("water_inlet_node_name", "water_outlet_node_name"),
    ("chilled_water_inlet_node_name", "chilled_water_outlet_node_name"),
    ("hot_water_inlet_node_name", "hot_water_outlet_node_name"),
)
"""(inlet, outlet) field pairs a branch component may carry, in the order they are tried."""


# --- fields ------------------------------------------------------------------------------------------------------


def same(a: str, b: str) -> bool:
    """EnergyPlus name equality: case-insensitive, surrounding spaces ignored."""
    return a.strip().casefold() == b.strip().casefold()


def text(obj: IDFObject, field_name: str) -> str:
    """A field's value as stripped text; ``""`` when the field is unset or unknown for the type."""
    value: object = obj.data.get(field_name)
    return "" if value is None else str(value).strip()


def has_field(obj: IDFObject, field_name: str) -> bool:
    return field_name in obj.data


def items(obj: IDFObject, wrapper: str) -> list[dict[str, Any]]:
    """A copy of an object's extensible items (``extensible_items`` returns live dicts)."""
    return [dict(item) for item in obj.extensible_items(wrapper)]


def item_values(obj: IDFObject, wrapper: str, key: str) -> list[str]:
    """One field of every extensible item, as stripped text, empty values left out."""
    values: list[str] = []
    for item in obj.extensible_items(wrapper):
        value: object = item.get(key)
        if value is not None and str(value).strip():
            values.append(str(value).strip())
    return values


def set_items(obj: IDFObject, wrapper: str, new_items: list[dict[str, Any]]) -> None:
    obj[wrapper] = new_items


def key_of(obj: IDFObject) -> ObjectKey:
    return ObjectKey(obj.obj_type, obj.name)


def sorted_objects(doc: IDFDocument, obj_type: str) -> list[IDFObject]:
    """The objects of one type, sorted by case-folded name."""
    if obj_type not in doc:
        return []
    return sorted(doc.get_collection(obj_type), key=lambda o: o.name.casefold())


def find(doc: IDFDocument, obj_type: str, name: str) -> IDFObject | None:
    """The object of ``obj_type`` named ``name`` (case-insensitive), or ``None``."""
    if not name or obj_type not in doc:
        return None
    return doc.get_collection(obj_type).get(name)


def find_by_name(doc: IDFDocument, obj_types: Iterable[str], name: str) -> IDFObject | None:
    for obj_type in obj_types:
        obj = find(doc, obj_type, name)
        if obj is not None:
            return obj
    return None


def objects_of_types(doc: IDFDocument, predicate: Callable[[str], bool]) -> list[IDFObject]:
    """Objects whose type satisfies ``predicate``, sorted by (type, name)."""
    found: list[IDFObject] = []
    for obj_type in sorted(doc.keys(), key=str.casefold):
        if predicate(obj_type):
            found.extend(sorted_objects(doc, obj_type))
    return found


def mentions(doc: IDFDocument, value: str, *, exclude: Iterable[ObjectKey] = ()) -> list[IDFObject]:
    """Objects holding ``value`` (case-insensitive) in any field, extensible items included."""
    wanted = value.strip().casefold()
    skip = set(exclude)
    found: list[IDFObject] = []
    for obj in doc.all_objects:
        if key_of(obj) in skip:
            continue
        if any(_holds(v, wanted) for v in obj.data.values()):
            found.append(obj)
    return found


def _holds(value: object, wanted: str) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() == wanted
    if isinstance(value, list):
        for entry in cast(list[object], value):
            if isinstance(entry, dict) and any(_holds(v, wanted) for v in cast(dict[str, object], entry).values()):
                return True
    return False


def all_names(doc: IDFDocument) -> set[str]:
    """Every object name and every string field value, case-folded: what a new name must not collide with."""
    seen: set[str] = set()
    for obj in doc.all_objects:
        if obj.name:
            seen.add(obj.name.casefold())
        for value in obj.data.values():
            _collect(value, seen)
    return seen


def _collect(value: object, seen: set[str]) -> None:
    if isinstance(value, str):
        seen.add(value.strip().casefold())
    elif isinstance(value, list):
        for entry in cast(list[object], value):
            if isinstance(entry, dict):
                for inner in cast(dict[str, object], entry).values():
                    _collect(inner, seen)


def unique_name(doc: IDFDocument, base: str) -> str:
    """``base``, or ``base`` with the smallest numeric suffix that nothing in the model uses yet."""
    taken = all_names(doc)
    if base.casefold() not in taken:
        return base
    n = 2
    while f"{base} {n}".casefold() in taken:
        n += 1
    return f"{base} {n}"


def misspell(name: str, taken: set[str]) -> str:
    """A deterministic typo of ``name``: two adjacent letters swapped in its last word of three letters or more.

    Falls back to doubling a letter when the swap changes nothing or collides with an existing name.
    """
    words = list(re.finditer(r"[A-Za-z]{3,}", name))
    candidates: list[str] = []
    for match in reversed(words):
        start = match.start()
        word = match.group(0)
        swapped = word[0] + word[2] + word[1] + word[3:]
        candidates.append(name[:start] + swapped + name[match.end() :])
        candidates.append(name[: start + 1] + word[1] + word[1:] + name[match.end() :])
    candidates.append(name + "x")
    for candidate in candidates:
        if not same(candidate, name) and candidate.casefold() not in taken:
            return candidate
    raise ValueError(f"cannot misspell {name!r}")


def numeric(obj: IDFObject, field_name: str) -> float | None:
    """A numeric field's value; ``None`` when it is empty, autosized or not a number."""
    value: object = obj.data.get(field_name)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def is_autosized(obj: IDFObject, field_name: str) -> bool:
    return text(obj, field_name).casefold() in ("autosize", "autocalculate")


# --- nodes, branches and loops -----------------------------------------------------------------------------------


def expand_nodes(doc: IDFDocument, name: str) -> list[str]:
    """A node name, or the members of the ``NodeList`` it names."""
    if not name:
        return []
    node_list = find(doc, "NodeList", name)
    if node_list is None:
        return [name]
    return item_values(node_list, "nodes", "node_name")


def expand_zones(doc: IDFDocument, name: str) -> list[str]:
    """A zone name, or the members of the ``ZoneList`` it names."""
    zone_list = find(doc, "ZoneList", name)
    if zone_list is None:
        return [name] if name else []
    return item_values(zone_list, "zones", "zone_name")


@dataclass(frozen=True)
class BranchEntry:
    """One component of a ``Branch``, as the branch lists it."""

    object_type: str
    name: str
    inlet: str
    outlet: str

    def is_(self, object_type: str, name: str) -> bool:
        return same(self.object_type, object_type) and same(self.name, name)


def branch_entries(branch: IDFObject) -> list[BranchEntry]:
    return [
        BranchEntry(
            object_type=str(item.get("component_object_type") or "").strip(),
            name=str(item.get("component_name") or "").strip(),
            inlet=str(item.get("component_inlet_node_name") or "").strip(),
            outlet=str(item.get("component_outlet_node_name") or "").strip(),
        )
        for item in branch.extensible_items("components")
    ]


def branches_of_list(doc: IDFDocument, branch_list_name: str) -> list[IDFObject]:
    """The ``Branch`` objects a ``BranchList`` names, in list order (missing branches left out)."""
    branch_list = find(doc, "BranchList", branch_list_name)
    if branch_list is None:
        return []
    found: list[IDFObject] = []
    for name in item_values(branch_list, "branches", "branch_name"):
        branch = find(doc, "Branch", name)
        if branch is not None:
            found.append(branch)
    return found


def air_loop_branches(doc: IDFDocument, loop: IDFObject) -> list[IDFObject]:
    return branches_of_list(doc, text(loop, "branch_list_name"))


def air_loop_entries(doc: IDFDocument, loop: IDFObject) -> list[tuple[IDFObject, BranchEntry]]:
    return [(branch, entry) for branch in air_loop_branches(doc, loop) for entry in branch_entries(branch)]


def air_loop_supply_outlets(doc: IDFDocument, loop: IDFObject) -> list[str]:
    return expand_nodes(doc, text(loop, "supply_side_outlet_node_names"))


def air_loop_of_branch(doc: IDFDocument, branch_name: str) -> IDFObject | None:
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        if any(same(b.name, branch_name) for b in air_loop_branches(doc, loop)):
            return loop
    return None


@dataclass(frozen=True)
class PlantSide:
    """One side of a ``PlantLoop`` or ``CondenserLoop``."""

    loop_type: str
    loop_name: str
    side: PlantSideName
    branch_list: str
    connector_list: str


_PLANT_SIDE_FIELDS: dict[str, dict[PlantSideName, tuple[str, str]]] = {
    "PlantLoop": {
        "supply": ("plant_side_branch_list_name", "plant_side_connector_list_name"),
        "demand": ("demand_side_branch_list_name", "demand_side_connector_list_name"),
    },
    "CondenserLoop": {
        "supply": ("condenser_side_branch_list_name", "condenser_side_connector_list_name"),
        "demand": ("condenser_demand_side_branch_list_name", "condenser_demand_side_connector_list_name"),
    },
}


def plant_sides(doc: IDFDocument) -> list[PlantSide]:
    """Every side of every plant and condenser loop: loops sorted by (type, name), supply before demand."""
    sides: list[PlantSide] = []
    for loop_type, fields in _PLANT_SIDE_FIELDS.items():
        for loop in sorted_objects(doc, loop_type):
            for side, (list_field, connector_field) in fields.items():
                sides.append(PlantSide(loop_type, loop.name, side, text(loop, list_field), text(loop, connector_field)))
    return sides


def plant_side(doc: IDFDocument, loop_name: str, side: PlantSideName) -> PlantSide | None:
    for candidate in plant_sides(doc):
        if same(candidate.loop_name, loop_name) and candidate.side == side:
            return candidate
    return None


def plant_loop_names(doc: IDFDocument) -> list[str]:
    return [loop.name for loop_type in _PLANT_SIDE_FIELDS for loop in sorted_objects(doc, loop_type)]


def side_branches(doc: IDFDocument, side: PlantSide) -> list[IDFObject]:
    return branches_of_list(doc, side.branch_list)


def side_branch_names(doc: IDFDocument, side: PlantSide) -> list[str]:
    branch_list = find(doc, "BranchList", side.branch_list)
    return [] if branch_list is None else item_values(branch_list, "branches", "branch_name")


@dataclass(frozen=True)
class Connectors:
    """The splitter and mixer of one plant loop side (``None`` when the side has none)."""

    splitter: IDFObject | None
    mixer: IDFObject | None

    def splitter_outlets(self) -> list[str]:
        return [] if self.splitter is None else item_values(self.splitter, "branches", "outlet_branch_name")

    def mixer_inlets(self) -> list[str]:
        return [] if self.mixer is None else item_values(self.mixer, "branches", "inlet_branch_name")


def side_connectors(doc: IDFDocument, side: PlantSide) -> Connectors:
    connector_list = find(doc, "ConnectorList", side.connector_list)
    splitter: IDFObject | None = None
    mixer: IDFObject | None = None
    if connector_list is not None:
        for n in (1, 2):
            obj_type = text(connector_list, f"connector_{n}_object_type")
            obj = find(doc, obj_type, text(connector_list, f"connector_{n}_name")) if obj_type else None
            if obj is not None and same(obj_type, "Connector:Splitter"):
                splitter = obj
            elif obj is not None and same(obj_type, "Connector:Mixer"):
                mixer = obj
    return Connectors(splitter, mixer)


def side_of_component(doc: IDFDocument, obj_type: str, name: str) -> tuple[PlantSide, IDFObject] | None:
    """The plant loop side and the branch holding a component, or ``None`` when no plant branch lists it."""
    for side in plant_sides(doc):
        for branch in side_branches(doc, side):
            if any(e.is_(obj_type, name) for e in branch_entries(branch)):
                return side, branch
    return None


def side_component_types(doc: IDFDocument, side: PlantSide) -> list[BranchEntry]:
    return [entry for branch in side_branches(doc, side) for entry in branch_entries(branch)]


def loops_with_supply(doc: IDFDocument, predicate: Callable[[str], bool]) -> list[str]:
    """Names of plant loops (sorted) with a supply-side component whose type satisfies ``predicate``."""
    return [
        side.loop_name
        for side in plant_sides(doc)
        if side.side == "supply" and side.loop_type == "PlantLoop"
        if any(predicate(e.object_type) for e in side_component_types(doc, side))
    ]


def is_chiller(obj_type: str) -> bool:
    return obj_type.casefold().startswith("chiller:")


def is_boiler(obj_type: str) -> bool:
    return same(obj_type, "Boiler:HotWater")


def component_ports(obj: IDFObject, entry: BranchEntry | None = None) -> tuple[str, str] | None:
    """The (inlet, outlet) node pair of a component: the first ``PORT_FIELD_PAIRS`` pair it carries, or, when
    ``entry`` is given, the first pair whose inlet or outlet matches the branch entry."""
    pairs = [(i, o) for i, o in PORT_FIELD_PAIRS if has_field(obj, i) and has_field(obj, o)]
    if entry is not None:
        for i, o in pairs:
            if same(text(obj, i), entry.inlet) or same(text(obj, o), entry.outlet):
                return text(obj, i), text(obj, o)
    if pairs:
        i, o = pairs[0]
        return text(obj, i), text(obj, o)
    return None


def branch_chain_ok(doc: IDFDocument, branch: IDFObject, *, loop_outlets: Iterable[str] = ()) -> bool:
    """Every component on ``branch`` carries the branch's nodes as its own ports, and consecutive components share
    a node. Components with no known port fields are skipped. ``loop_outlets``, when given, must contain the
    branch's last outlet node."""
    entries = branch_entries(branch)
    for index, entry in enumerate(entries):
        obj = find(doc, entry.object_type, entry.name)
        if obj is None:
            return False
        ports = component_ports(obj, entry)
        if ports is not None and not (same(ports[0], entry.inlet) and same(ports[1], entry.outlet)):
            return False
        if index + 1 < len(entries) and not same(entry.outlet, entries[index + 1].inlet):
            return False
    outlets = list(loop_outlets)
    return not (outlets and entries and not any(same(entries[-1].outlet, n) for n in outlets))


def loop_branch_nodes(doc: IDFDocument) -> dict[str, set[str]]:
    """``loop name (case-folded) -> case-folded node names`` on the loop's branches, air and plant loops."""
    nodes: dict[str, set[str]] = {}
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        bucket = nodes.setdefault(loop.name.casefold(), set())
        for _, entry in air_loop_entries(doc, loop):
            bucket.update({entry.inlet.casefold(), entry.outlet.casefold()})
    for side in plant_sides(doc):
        bucket = nodes.setdefault(side.loop_name.casefold(), set())
        for entry in side_component_types(doc, side):
            bucket.update({entry.inlet.casefold(), entry.outlet.casefold()})
    for bucket in nodes.values():
        bucket.discard("")
    return nodes


# --- zones, terminals and air loops ------------------------------------------------------------------------------


def zone_connections(doc: IDFDocument, zone_name: str) -> IDFObject | None:
    for conn in sorted_objects(doc, "ZoneHVAC:EquipmentConnections"):
        if same(text(conn, "zone_name"), zone_name):
            return conn
    return None


def zone_inlet_nodes(doc: IDFDocument, zone_name: str) -> list[str]:
    conn = zone_connections(doc, zone_name)
    return [] if conn is None else expand_nodes(doc, text(conn, "zone_air_inlet_node_or_nodelist_name"))


def zone_equipment(doc: IDFDocument, zone_name: str) -> list[IDFObject]:
    """The objects in a zone's equipment list, in list order."""
    conn = zone_connections(doc, zone_name)
    if conn is None:
        return []
    eq_list = find(doc, "ZoneHVAC:EquipmentList", text(conn, "zone_conditioning_equipment_list_name"))
    if eq_list is None:
        return []
    found: list[IDFObject] = []
    for item in eq_list.extensible_items("equipment"):
        obj = find(doc, str(item.get("zone_equipment_object_type") or ""), str(item.get("zone_equipment_name") or ""))
        if obj is not None:
            found.append(obj)
    return found


def zone_of_equipment(doc: IDFDocument, obj: IDFObject) -> str | None:
    """The zone whose equipment list holds ``obj``; zones visited in sorted order."""
    for zone in sorted_objects(doc, "Zone"):
        if any(key_of(e) == key_of(obj) for e in zone_equipment(doc, zone.name)):
            return zone.name
    return None


@dataclass(frozen=True)
class ZoneTerminal:
    """A zone, the air distribution unit serving it and the unit's air terminal."""

    zone: str
    adu: IDFObject
    terminal: IDFObject


def zone_terminals(doc: IDFDocument) -> list[ZoneTerminal]:
    """Every (zone, ADU, terminal), zones sorted by name, then equipment-list order."""
    found: list[ZoneTerminal] = []
    for zone in sorted_objects(doc, "Zone"):
        for obj in zone_equipment(doc, zone.name):
            if not same(obj.obj_type, "ZoneHVAC:AirDistributionUnit"):
                continue
            terminal = find(doc, text(obj, "air_terminal_object_type"), text(obj, "air_terminal_name"))
            if terminal is not None:
                found.append(ZoneTerminal(zone.name, obj, terminal))
    return found


def reheat_coil(doc: IDFDocument, terminal: IDFObject) -> IDFObject | None:
    return find(doc, text(terminal, "reheat_coil_object_type"), text(terminal, "reheat_coil_name"))


def terminal_inlet_nodes(terminal: IDFObject) -> list[str]:
    """Air inlet nodes of a terminal: every field ending in ``inlet_node_name`` except water/steam inlets."""
    return [
        str(value).strip()
        for name, value in terminal.data.items()
        if name.endswith("inlet_node_name") and "water" not in name and "steam" not in name and value
    ]


def zones_served_by_air_loop(doc: IDFDocument, loop: IDFObject) -> list[str]:
    """Zones (sorted) supplied by an air loop: its supply paths are followed through zone splitters and supply
    plenums to the terminals they feed, and to zone inlet nodes fed directly."""
    reached = {n.casefold() for n in expand_nodes(doc, text(loop, "demand_side_inlet_node_names"))}
    path_parts = [o for t in ("AirLoopHVAC:ZoneSplitter", "AirLoopHVAC:SupplyPlenum") for o in sorted_objects(doc, t)]
    grown = True
    while grown:
        grown = False
        for part in path_parts:
            if text(part, "inlet_node_name").casefold() in reached:
                for node in item_values(part, "nodes", "outlet_node_name"):
                    if node.casefold() not in reached:
                        reached.add(node.casefold())
                        grown = True
    served: set[str] = set()
    for zt in zone_terminals(doc):
        if any(n.casefold() in reached for n in terminal_inlet_nodes(zt.terminal)):
            served.add(zt.zone)
    for zone in sorted_objects(doc, "Zone"):
        if any(n.casefold() in reached for n in zone_inlet_nodes(doc, zone.name)):
            served.add(zone.name)
    return sorted(served, key=str.casefold)


def air_loop_serving_zone(doc: IDFDocument, zone_name: str) -> IDFObject | None:
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        if any(same(z, zone_name) for z in zones_served_by_air_loop(doc, loop)):
            return loop
    return None


def thermostat_zones(doc: IDFDocument, setpoint_type: str, setpoint_name: str) -> list[str]:
    """Zones (sorted) whose ``ZoneControl:Thermostat`` uses the given setpoint object."""
    zones: set[str] = set()
    for tstat in sorted_objects(doc, "ZoneControl:Thermostat"):
        for n in range(1, 5):
            if same(text(tstat, f"control_{n}_object_type"), setpoint_type) and same(
                text(tstat, f"control_{n}_name"), setpoint_name
            ):
                zones.update(expand_zones(doc, text(tstat, "zone_or_zonelist_name")))
    return sorted(zones, key=str.casefold)


def surfaces_of_zone(doc: IDFDocument, zone_name: str) -> list[IDFObject]:
    """Heat-transfer surfaces of a zone: detailed and simple walls, roofs, floors (by ``zone_name`` or a space)."""
    spaces = {s.name.casefold() for s in sorted_objects(doc, "Space") if same(text(s, "zone_name"), zone_name)}
    found: list[IDFObject] = []
    for obj in objects_of_types(doc, _is_surface_type):
        owner = text(obj, "zone_name")
        if same(owner, zone_name) or owner.casefold() in spaces or text(obj, "space_name").casefold() in spaces:
            found.append(obj)
    return found


def _is_surface_type(obj_type: str) -> bool:
    folded = obj_type.casefold()
    return folded in ("buildingsurface:detailed", "floor:detailed", "wall:detailed", "roofceiling:detailed") or (
        folded.startswith(("wall:", "roof", "floor:", "ceiling:")) and "detailed" not in folded
    )


# --- schedules ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleStats:
    """Hourly statistics of a schedule over a year (2024, idfkit's default)."""

    minimum: float
    maximum: float
    mean: float


def schedule_stats(doc: IDFDocument, name: str) -> ScheduleStats | None:
    """Statistics of the schedule named ``name``; ``None`` when it is missing or cannot be evaluated."""
    from idfkit.schedules import values

    schedule = doc.get_schedule(name) if name else None
    if schedule is None:
        return None
    try:
        hourly = values(schedule, document=doc)
    except Exception:
        return None
    if not hourly:
        return None
    return ScheduleStats(min(hourly), max(hourly), sum(hourly) / len(hourly))


def schedule_type_limits(doc: IDFDocument, name: str) -> str:
    schedule = doc.get_schedule(name) if name else None
    return "" if schedule is None else text(schedule, "schedule_type_limits_name")


# --- prompts -----------------------------------------------------------------------------------------------------


def render_prompt(template: str, values: Mapping[str, str]) -> str:
    """Fill a prompt template's ``{placeholder}`` fields; a missing value raises ``KeyError``."""
    return template.format_map(dict(values))


def default_prompt_values(doc: IDFDocument) -> dict[str, str]:
    """Placeholder values for templates rendered on an unmodified model (control tasks).

    ``zone``: the first zone (by name) with zone equipment, else the first zone. ``air_loop`` and ``plant_loop``:
    the first ``AirLoopHVAC`` and ``PlantLoop`` by name. Keys are left out when the model has no such object.
    """
    values: dict[str, str] = {}
    zones = sorted_objects(doc, "Zone")
    equipped = [z for z in zones if zone_connections(doc, z.name) is not None]
    if equipped or zones:
        values["zone"] = (equipped or zones)[0].name
    for placeholder, obj_type in (("air_loop", "AirLoopHVAC"), ("plant_loop", "PlantLoop")):
        objs = sorted_objects(doc, obj_type)
        if objs:
            values[placeholder] = objs[0].name
    return values


def prompts_template(name: str) -> str:
    """A template from ``eval/prompts.toml`` by its ``"<table>.<name>"`` key."""
    from eval.config import load_prompt_templates

    return load_prompt_templates(Path(__file__).resolve().parent / "prompts.toml")[name]


# --- connection check and simulation -----------------------------------------------------------------------------


def connection_check_errors(doc: IDFDocument) -> list[str] | None:
    """Messages of the connection check's error findings, or ``None`` when the check is unavailable.

    The check is ``idfkit.hvac.check_topology`` (contracts/idfkit-api.md). idfkit 1.2.0, the level the server pins,
    has no ``idfkit.hvac``; the module is imported by name so that the harness picks the check up as soon as the
    pinned level ships it, and callers fall back to the simulation alone until then.
    """
    try:
        module = importlib.import_module("idfkit.hvac")
    except ImportError:
        return None
    check: object = getattr(module, "check_topology", None)
    if not callable(check):
        return None
    findings = cast(Callable[[IDFDocument], Iterable[object]], check)(doc)
    errors: list[str] = []
    for finding in findings:
        if str(getattr(finding, "severity", "")) == "error":
            errors.append(str(getattr(finding, "message", finding)))
    return errors


def simulated(result: SimulationResult | None) -> bool:
    """The model simulated: EnergyPlus exited successfully with no fatal error."""
    return result is not None and result.success and not result.errors.has_fatal


@dataclass(frozen=True)
class SizingFacts:
    """Sizing results of one model, names case-folded.

    Attributes:
        zone_heating_loads: zone -> "User Design Load" [W] of the "Zone Sensible Heating" table.
        plant_capacities: equipment -> "Reference Capacity" [W] of the "Central Plant" table.
        component_sizes: (component type, component) -> {row label -> value} of ComponentSizingSummary.
    """

    zone_heating_loads: dict[str, float] = field(default_factory=dict[str, float])
    plant_capacities: dict[str, float] = field(default_factory=dict[str, float])
    component_sizes: dict[tuple[str, str], dict[str, float]] = field(
        default_factory=dict[tuple[str, str], dict[str, float]]
    )


def sizing_facts_from_result(result: SimulationResult | None) -> SizingFacts | None:
    """Sizing facts read from a simulation's SQL output; ``None`` without output or without sizing tables."""
    if result is None or result.sql is None:
        return None
    sql = result.sql
    facts = SizingFacts()
    for row in sql.get_tabular_data(report_name="HVACSizingSummary", table_name="Zone Sensible Heating"):
        if row.column_name == "User Design Load" and (value := _float(row.value)) is not None:
            facts.zone_heating_loads[row.row_name.strip().casefold()] = value
    for row in sql.get_tabular_data(report_name="EquipmentSummary", table_name="Central Plant"):
        if row.column_name == "Reference Capacity" and (value := _float(row.value)) is not None:
            facts.plant_capacities[row.row_name.strip().casefold()] = value
    for row in sql.get_tabular_data(report_name="ComponentSizingSummary"):
        if (value := _float(row.value)) is not None:
            bucket = facts.component_sizes.setdefault((row.table_name.casefold(), row.row_name.strip().casefold()), {})
            bucket[row.column_name] = value
    if not facts.zone_heating_loads and not facts.plant_capacities:
        return None
    return facts


def _float(value: str) -> float | None:
    try:
        return float(value.strip())
    except (AttributeError, ValueError):
        return None


_SIZING_CACHE: dict[str, SizingFacts] = {}


def design_day_sizing(doc: IDFDocument) -> SizingFacts:
    """Sizing facts from a design-day-only run of ``doc`` (``simulate(..., design_day=True)``).

    Sizing depends only on the model's own design days, never on a weather file, so the result does not depend on
    the weather an agent chooses. Runs in a temporary directory; cached by the model's IDF text.
    """
    from idfkit.simulation import simulate

    digest = hashlib.sha256(write_idf(doc).encode("utf-8")).hexdigest()
    cached = _SIZING_CACHE.get(digest)
    if cached is not None:
        return cached
    with tempfile.TemporaryDirectory(prefix="eval-sizing-") as tmp:
        result = simulate(doc, design_day=True, output_dir=tmp)
        try:
            facts = sizing_facts_from_result(result) if simulated(result) else None
        finally:
            result.close()
    if facts is None:
        raise RuntimeError("the design-day simulation produced no sizing tables")
    _SIZING_CACHE[digest] = facts
    return facts


def sizing_facts(doc: IDFDocument, result: SimulationResult | None) -> SizingFacts:
    """Sizing facts from ``result`` when it carries them, else from a design-day run of ``doc``."""
    return sizing_facts_from_result(result) or design_day_sizing(doc)


def check_result_if_given(result: SimulationResult | None) -> bool:
    """Results-layer verifiers accept a missing result (structural check only) but reject a failed simulation."""
    return result is None or simulated(result)


def ensure(condition: bool, message: str) -> None:
    """Raise ``ValueError`` (the fault cannot be injected into this model) unless ``condition`` holds."""
    if not condition:
        raise ValueError(message)


# --- air-side component slots (topology faults) ------------------------------------------------------------------


@dataclass(frozen=True)
class AirSlot:
    """A component on an air loop branch whose own air ports match the branch's nodes."""

    loop: IDFObject
    branch: IDFObject
    index: int
    entries: list[BranchEntry]
    obj: IDFObject

    @property
    def entry(self) -> BranchEntry:
        return self.entries[self.index]

    @property
    def has_previous(self) -> bool:
        return self.index > 0

    @property
    def has_next(self) -> bool:
        return self.index + 1 < len(self.entries)


def air_slots(doc: IDFDocument) -> list[AirSlot]:
    """Every air loop branch component with ``air_inlet_node_name`` and ``air_outlet_node_name`` matching the
    branch: air loops by name, branches in branch-list order, components in branch order."""
    slots: list[AirSlot] = []
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        for branch in air_loop_branches(doc, loop):
            entries = branch_entries(branch)
            for index, entry in enumerate(entries):
                obj = find(doc, entry.object_type, entry.name)
                if (
                    obj is not None
                    and same(text(obj, "air_inlet_node_name"), entry.inlet)
                    and same(text(obj, "air_outlet_node_name"), entry.outlet)
                ):
                    slots.append(AirSlot(loop, branch, index, entries, obj))
    return slots


def air_slot_connected(doc: IDFDocument, loop_name: str, branch_name: str, obj_type: str, obj_name: str) -> bool:
    """The component still sits on the branch, its air ports equal the branch's nodes, the whole branch is a
    connected chain (``branch_chain_ok``), and a last component's outlet is a supply outlet of the loop."""
    loop = find(doc, "AirLoopHVAC", loop_name)
    branch = find(doc, "Branch", branch_name)
    obj = find(doc, obj_type, obj_name)
    if loop is None or branch is None or obj is None:
        return False
    entries = branch_entries(branch)
    index = next((i for i, e in enumerate(entries) if e.is_(obj_type, obj_name)), None)
    if index is None:
        return False
    entry = entries[index]
    if not (
        same(text(obj, "air_inlet_node_name"), entry.inlet) and same(text(obj, "air_outlet_node_name"), entry.outlet)
    ):
        return False
    if not branch_chain_ok(doc, branch):
        return False
    if index + 1 < len(entries):
        return True
    return any(same(entry.outlet, n) for n in air_loop_supply_outlets(doc, loop))


# --- authoring tasks ---------------------------------------------------------------------------------------------


def authoring_succeeded(doc: IDFDocument, result: SimulationResult | None, *, goal_met: bool) -> bool:
    """The success rule of an authoring task (R-14): the goal is met, the connection check reports no error finding,
    and the model simulates.

    While ``idfkit.hvac`` is not importable (idfkit 1.2.0), ``connection_check_errors`` returns ``None`` and the
    rule falls back to the simulation alone: EnergyPlus's own node-connection checks then stand in for the
    connection check, since a model with a broken connection does not simulate.
    """
    if not goal_met:
        return False
    errors = connection_check_errors(doc)
    if errors:
        return False
    return simulated(result)
