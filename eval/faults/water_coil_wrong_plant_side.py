"""Designed topology fault: a water coil's branch connected to the supply side of its plant loop.

**Inject.** The first water coil (``Coil:Cooling:Water``, then ``Coil:Cooling:Water:DetailedGeometry``, then
``Coil:Heating:Water``; names sorted within each type) on a demand branch of a plant loop (not the inlet or outlet
branch) has its branch moved to the loop's supply side: removed from the demand ``BranchList``, splitter and mixer,
and added to the supply ``BranchList`` (before its outlet branch), splitter and mixer.

**Verify** (structural): the coil sits on a demand branch of the same plant loop, the demand splitter and mixer
both name that branch, and no supply side of any loop lists it, in its branch list, splitter or mixer.

**Symptom.** EnergyPlus still runs (with many warnings): the coil gets no chilled water, so cooling setpoints are
missed. The coil chosen on every applicable reference model is a cooling coil, hence the unmet-cooling prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eval.model import FaultType, InjectedFault
from eval.support import (
    WATER_COILS,
    find,
    items,
    key_of,
    plant_side,
    plant_sides,
    prompts_template,
    same,
    set_items,
    side_branch_names,
    side_connectors,
    side_of_component,
    sorted_objects,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument, IDFObject
    from idfkit.simulation.result import SimulationResult


def _without(obj: IDFObject, wrapper: str, key: str, name: str) -> list[dict[str, Any]]:
    return [i for i in items(obj, wrapper) if not same(str(i.get(key) or ""), name)]


def inject(doc: IDFDocument) -> InjectedFault:
    for coil_type in WATER_COILS:
        for coil in sorted_objects(doc, coil_type):
            located = side_of_component(doc, coil_type, coil.name)
            if located is None or located[0].side != "demand":
                continue
            demand, branch = located
            supply = plant_side(doc, demand.loop_name, "supply")
            if supply is None:
                continue
            d_conn, s_conn = side_connectors(doc, demand), side_connectors(doc, supply)
            d_list, s_list = find(doc, "BranchList", demand.branch_list), find(doc, "BranchList", supply.branch_list)
            d_split, d_mix, s_split, s_mix = d_conn.splitter, d_conn.mixer, s_conn.splitter, s_conn.mixer
            if d_list is None or s_list is None or d_split is None or d_mix is None or s_split is None or s_mix is None:
                continue
            inner = side_branch_names(doc, demand)[1:-1]
            if len(side_branch_names(doc, supply)) < 2 or not any(same(n, branch.name) for n in inner):
                continue
            set_items(d_list, "branches", _without(d_list, "branches", "branch_name", branch.name))
            set_items(d_split, "branches", _without(d_split, "branches", "outlet_branch_name", branch.name))
            set_items(d_mix, "branches", _without(d_mix, "branches", "inlet_branch_name", branch.name))
            s_items = items(s_list, "branches")
            set_items(s_list, "branches", [*s_items[:-1], {"branch_name": branch.name}, s_items[-1]])
            set_items(s_split, "branches", [*items(s_split, "branches"), {"outlet_branch_name": branch.name}])
            set_items(s_mix, "branches", [*items(s_mix, "branches"), {"inlet_branch_name": branch.name}])
            scope = [key_of(o) for o in (d_list, s_list, d_split, d_mix, s_split, s_mix)]
            return InjectedFault(
                scope=scope,
                object_names=[coil.name, branch.name, d_list.name, s_list.name],
                field_names=["branch_name", "outlet_branch_name", "inlet_branch_name"],
                prompt_values={"plant_loop": demand.loop_name},
                details={"loop": demand.loop_name, "coil_type": coil_type, "coil": coil.name, "branch": branch.name},
            )
    raise ValueError("no water coil on a demand branch of a plant loop with supply-side connectors")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    d = injected.details
    located = side_of_component(doc, d["coil_type"], d["coil"])
    if located is None:
        return False
    side, branch = located
    if side.side != "demand" or not same(side.loop_name, d["loop"]):
        return False
    conn = side_connectors(doc, side)
    if not any(same(n, branch.name) for n in conn.splitter_outlets()) or not any(
        same(n, branch.name) for n in conn.mixer_inlets()
    ):
        return False
    for other in plant_sides(doc):
        if other.side != "supply":
            continue
        other_conn = side_connectors(doc, other)
        listed = [*side_branch_names(doc, other), *other_conn.splitter_outlets(), *other_conn.mixer_inlets()]
        if any(same(n, branch.name) for n in listed):
            return False
    return True


FAULT = FaultType(
    id="water_coil_wrong_plant_side",
    layer="topology",
    description="A water coil's branch is on the supply side of its plant loop instead of the demand side.",
    held_out=False,
    applies_to=["water_coil"],
    intended_tools=["check_model_integrity", "get_hvac_topology", "trace_hvac"],
    prompt_template=prompts_template("symptom.unmet_cooling"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
