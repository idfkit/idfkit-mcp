"""Held-out results fault: a hot-water loop whose operation scheme no longer dispatches its boiler.

**Source.** EnergyPlus user report on Unmet Hours, "Plant Loop Operation Scheme in Open Studio" (2015,
https://unmethours.com/question/5019/plant-loop-operation-scheme-in-open-studio/): a boiler loop that never turned
on and a model with no heating, because the loop's plant equipment operation scheme did not call the boiler. The
simulation completes; nothing in it says the plant is idle. The report's own cause was the scheme type; here the
same symptom comes from the scheme's equipment list, the place a boiler is forgotten when it is added by hand.

**Inject.** On the first plant loop (by name) with a ``Boiler:HotWater`` on its supply side, every boiler of that
supply side is removed from every equipment list the loop's operation schemes use. The loop circulates water that
is never heated. On 5ZoneAirCooled the winter design day drops from a 19.8 degC minimum zone temperature to 14.3
and the boiler heating rate from 14 kW to zero. The prompt names the first zone (by name) whose terminal has a
hot-water reheat coil, else the first zone with equipment.

**Verify.** The loop still has at least one boiler on its supply side, and every boiler there is named by an
operation scheme of the loop: in an equipment list of a load-range scheme whose range is not empty, or directly by
a scheme that lists equipment itself (component setpoint). Putting the boiler back in its list passes; so does a
new list or a new scheme that names it. A result whose simulation failed is never a fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import (
    check_result_if_given,
    default_prompt_values,
    find,
    is_boiler,
    items,
    key_of,
    loops_with_supply,
    numeric,
    plant_side,
    prompts_template,
    reheat_coil,
    same,
    set_items,
    side_component_types,
    text,
    zone_terminals,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument, IDFObject
    from idfkit.simulation.result import SimulationResult

LOOP = "PlantLoop"
SCHEMES = "PlantEquipmentOperationSchemes"
EQUIPMENT_LIST = "PlantEquipmentList"
MAX_SLOTS = 20
"""More control schemes, load ranges or directly listed equipment than any EnergyPlus object allows."""


def _loop_boilers(doc: IDFDocument, loop_name: str) -> list[str]:
    side = plant_side(doc, loop_name, "supply")
    if side is None:
        return []
    return [e.name for e in side_component_types(doc, side) if is_boiler(e.object_type)]


def _schemes(doc: IDFDocument, loop_name: str) -> list[IDFObject]:
    """The operation scheme objects (load range, component setpoint, ...) of a loop, in the order it lists them."""
    loop = find(doc, LOOP, loop_name)
    holder = find(doc, SCHEMES, text(loop, "plant_equipment_operation_scheme_name")) if loop is not None else None
    if holder is None:
        return []
    found: list[IDFObject] = []
    for n in range(1, MAX_SLOTS + 1):
        scheme = find(doc, text(holder, f"control_scheme_{n}_object_type"), text(holder, f"control_scheme_{n}_name"))
        if scheme is not None:
            found.append(scheme)
    return found


def _range_lists(doc: IDFDocument, scheme: IDFObject, *, live_only: bool) -> list[IDFObject]:
    """Equipment lists of a scheme's ranges; with ``live_only``, only ranges whose upper limit exceeds the lower."""
    found: list[IDFObject] = []
    for n in range(1, MAX_SLOTS + 1):
        equipment = find(doc, EQUIPMENT_LIST, text(scheme, f"range_{n}_equipment_list_name"))
        if equipment is None:
            continue
        lower, upper = numeric(scheme, f"load_range_{n}_lower_limit"), numeric(scheme, f"load_range_{n}_upper_limit")
        if live_only and lower is not None and upper is not None and upper <= lower:
            continue
        found.append(equipment)
    return found


def _dispatched(doc: IDFDocument, loop_name: str) -> set[str]:
    """Case-folded names of the equipment the loop's operation schemes can call."""
    names: set[str] = set()
    for scheme in _schemes(doc, loop_name):
        for equipment in _range_lists(doc, scheme, live_only=True):
            names.update(str(i.get("equipment_name") or "").strip().casefold() for i in items(equipment, "equipment"))
        for n in range(1, MAX_SLOTS + 1):
            names.add(text(scheme, f"equipment_{n}_name").casefold())
    names.discard("")
    return names


def _cold_zone(doc: IDFDocument) -> str:
    for zt in zone_terminals(doc):
        coil = reheat_coil(doc, zt.terminal)
        if coil is not None and same(coil.obj_type, "Coil:Heating:Water"):
            return zt.zone
    return default_prompt_values(doc)["zone"]


def inject(doc: IDFDocument) -> InjectedFault:
    for loop_name in loops_with_supply(doc, is_boiler):
        boilers = {name.casefold() for name in _loop_boilers(doc, loop_name)}
        changed: list[IDFObject] = []
        for scheme in _schemes(doc, loop_name):
            for equipment in _range_lists(doc, scheme, live_only=False):
                entries = items(equipment, "equipment")
                kept = [e for e in entries if str(e.get("equipment_name") or "").strip().casefold() not in boilers]
                if len(kept) != len(entries) and all(key_of(equipment) != key_of(c) for c in changed):
                    set_items(equipment, "equipment", kept)
                    changed.append(equipment)
        if not changed:
            continue
        return InjectedFault(
            scope=[key_of(c) for c in changed],
            object_names=[*(c.name for c in changed), *sorted(_loop_boilers(doc, loop_name)), loop_name],
            field_names=["equipment_name", "equipment_object_type"],
            prompt_values={"zone": _cold_zone(doc)},
            details={"loop": loop_name},
        )
    raise ValueError("no hot-water loop whose operation scheme lists its boiler")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    if not check_result_if_given(result):
        return False
    loop_name = injected.details["loop"]
    boilers = _loop_boilers(doc, loop_name)
    dispatched = _dispatched(doc, loop_name)
    return bool(boilers) and all(name.casefold() in dispatched for name in boilers)


FAULT = FaultType(
    id="boiler_not_in_operation_scheme",
    layer="results",
    description="A hot-water loop's boiler is missing from the equipment lists of the loop's operation schemes.",
    held_out=True,
    applies_to=["hot_water"],
    intended_tools=[],
    prompt_template=prompts_template("symptom.zone_too_cold"),
    needs_energyplus=True,
    inject=inject,
    verify=verify,
)
