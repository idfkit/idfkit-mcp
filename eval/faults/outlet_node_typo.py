"""Designed topology fault: a typo in a component's air outlet node name.

**Inject.** The first component, over air loops by name, branches in branch-list order and components in branch
order, whose ``air_inlet_node_name`` / ``air_outlet_node_name`` match its branch entry and which is followed by
another component on the branch, gets a misspelt ``air_outlet_node_name`` (two adjacent letters of a word swapped).
The branch still lists the correct node, so the component's outlet no longer reaches the next component.

**Verify** (structural): the component's air ports equal its branch entry again, the branch is a connected chain,
and the model is consistent about the name it settled on: either nothing mentions the misspelt name any more, or
nothing mentions the original name (an agent that renamed the node everywhere repaired the connection too).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault, ObjectKey
from eval.support import air_slot_connected, air_slots, all_names, ensure, key_of, mentions, misspell, prompts_template

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

FIELD = "air_outlet_node_name"


def inject(doc: IDFDocument) -> InjectedFault:
    slots = [s for s in air_slots(doc) if s.has_next]
    ensure(bool(slots), "no air loop component followed by another component on its branch")
    slot = slots[0]
    original = slot.entry.outlet
    typo = misspell(original, all_names(doc))
    slot.obj[FIELD] = typo
    return InjectedFault(
        scope=[key_of(slot.obj), ObjectKey("Branch", slot.branch.name)],
        object_names=[slot.obj.name, slot.branch.name, original, typo],
        field_names=[FIELD],
        details={
            "loop": slot.loop.name,
            "branch": slot.branch.name,
            "object_type": slot.obj.obj_type,
            "object_name": slot.obj.name,
            "original": original,
            "typo": typo,
        },
    )


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    d = injected.details
    if not air_slot_connected(doc, d["loop"], d["branch"], d["object_type"], d["object_name"]):
        return False
    return not mentions(doc, d["typo"]) or not mentions(doc, d["original"])


FAULT = FaultType(
    id="outlet_node_typo",
    layer="topology",
    description="A component's air outlet node name is misspelt, so it no longer connects to the next component.",
    held_out=False,
    applies_to=["air_loop"],
    intended_tools=["check_model_integrity", "trace_hvac", "rename_node"],
    prompt_template=prompts_template("symptom.simulation_fails"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
