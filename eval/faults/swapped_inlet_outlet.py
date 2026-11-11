"""Designed topology fault: a component's air inlet and outlet node names swapped.

**Inject.** The last component, over air loops by name, branches in branch-list order and components in branch
order, whose air ports match its branch entry and which sits between two other components, gets its
``air_inlet_node_name`` and ``air_outlet_node_name`` swapped. The branch keeps the correct order.

**Verify** (structural): the component's air ports equal its branch entry again and the branch is a connected chain
(each component's outlet is the next one's inlet, and every component's own ports equal its branch entry). Any
repair that restores a consistent flow direction passes, including renaming nodes along the branch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault, ObjectKey
from eval.support import air_slot_connected, air_slots, ensure, key_of, prompts_template

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

INLET = "air_inlet_node_name"
OUTLET = "air_outlet_node_name"


def inject(doc: IDFDocument) -> InjectedFault:
    slots = air_slots(doc)
    middle = [s for s in slots if s.has_previous and s.has_next]
    candidates = middle or [s for s in slots if s.has_previous]
    ensure(bool(candidates), "no air loop component downstream of another component")
    slot = candidates[-1]
    inlet, outlet = slot.entry.inlet, slot.entry.outlet
    slot.obj[INLET] = outlet
    slot.obj[OUTLET] = inlet
    return InjectedFault(
        scope=[key_of(slot.obj), ObjectKey("Branch", slot.branch.name)],
        object_names=[slot.obj.name, slot.branch.name],
        field_names=[INLET, OUTLET],
        details={
            "loop": slot.loop.name,
            "branch": slot.branch.name,
            "object_type": slot.obj.obj_type,
            "object_name": slot.obj.name,
            "inlet": inlet,
            "outlet": outlet,
        },
    )


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    d = injected.details
    return air_slot_connected(doc, d["loop"], d["branch"], d["object_type"], d["object_name"])


FAULT = FaultType(
    id="swapped_inlet_outlet",
    layer="topology",
    description="A component's air inlet and outlet node names are swapped, reversing it on its branch.",
    held_out=False,
    applies_to=["air_loop"],
    intended_tools=["check_model_integrity", "trace_hvac"],
    prompt_template=prompts_template("symptom.severe_error"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
