"""Designed topology fault: a demand branch left out of its plant loop's branch list.

**Inject.** On the first plant loop (by name) with a ``Boiler:HotWater`` on its supply side, the first demand
branch in branch-list order, other than the first (inlet) and last (outlet) branch, that holds a
``Coil:Heating:Water`` is removed from the demand side's ``BranchList``. The splitter and mixer still name it.

**Verify** (structural): on the same loop's demand side, the coil sits on a branch of the branch list; every branch
the splitter and the mixer name is in the branch list; and the list still starts with the splitter's inlet branch
and ends with the mixer's outlet branch. Re-adding the branch anywhere in the middle passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault, ObjectKey
from eval.support import (
    branch_entries,
    find,
    is_boiler,
    items,
    loops_with_supply,
    plant_side,
    prompts_template,
    same,
    set_items,
    side_branch_names,
    side_branches,
    side_connectors,
    text,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

COIL = "Coil:Heating:Water"


def inject(doc: IDFDocument) -> InjectedFault:
    for loop_name in loops_with_supply(doc, is_boiler):
        side = plant_side(doc, loop_name, "demand")
        branch_list = find(doc, "BranchList", side.branch_list) if side is not None else None
        if side is None or branch_list is None:
            continue
        branches = side_branches(doc, side)
        for branch in branches[1:-1]:
            coils = [e for e in branch_entries(branch) if same(e.object_type, COIL)]
            if not coils:
                continue
            kept = [i for i in items(branch_list, "branches") if not same(str(i.get("branch_name") or ""), branch.name)]
            set_items(branch_list, "branches", kept)
            return InjectedFault(
                scope=[ObjectKey("BranchList", branch_list.name)],
                object_names=[branch.name, branch_list.name, coils[0].name],
                field_names=["branch_name"],
                prompt_values={"plant_loop": loop_name},
                details={"loop": loop_name, "branch": branch.name, "coil": coils[0].name},
            )
    raise ValueError("no hot-water demand branch holding a water heating coil")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    d = injected.details
    side = plant_side(doc, d["loop"], "demand")
    if side is None:
        return False
    listed = side_branch_names(doc, side)
    folded = [n.casefold() for n in listed]
    holds_coil = any(any(e.is_(COIL, d["coil"]) for e in branch_entries(b)) for b in side_branches(doc, side))
    connectors = side_connectors(doc, side)
    if not holds_coil or connectors.splitter is None or connectors.mixer is None or not listed:
        return False
    named = [*connectors.splitter_outlets(), *connectors.mixer_inlets()]
    if not all(n.casefold() in folded for n in named):
        return False
    return same(listed[0], text(connectors.splitter, "inlet_branch_name")) and same(
        listed[-1], text(connectors.mixer, "outlet_branch_name")
    )


FAULT = FaultType(
    id="branch_missing_from_list",
    layer="topology",
    description="A hot-water demand branch with a heating coil is missing from the demand side's branch list.",
    held_out=False,
    applies_to=["hot_water"],
    intended_tools=["check_model_integrity", "get_hvac_topology"],
    prompt_template=prompts_template("symptom.severe_error"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
