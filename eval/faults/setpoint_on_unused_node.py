"""Designed topology fault: a setpoint manager placed on a node that no flow component uses.

**Inject.** The first setpoint manager, over ``SetpointManager:*`` types and names in sorted order, whose
``setpoint_node_or_nodelist_name`` is a single node on the branches of an air or plant loop, is moved to a new node
name that nothing else in the model uses. The loop keeps running without the setpoint it needs.

**Verify** (structural): the same setpoint manager still exists and every node it now sets (a node list is
expanded) is a node on the branches of the same loop. Restoring the original node passes; so does choosing another
branch node of that loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import (
    expand_nodes,
    find,
    find_by_name,
    key_of,
    loop_branch_nodes,
    objects_of_types,
    prompts_template,
    text,
    unique_name,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

FIELD = "setpoint_node_or_nodelist_name"


def _is_setpoint_manager(obj_type: str) -> bool:
    return obj_type.casefold().startswith("setpointmanager:")


def inject(doc: IDFDocument) -> InjectedFault:
    loops = loop_branch_nodes(doc)
    for spm in objects_of_types(doc, _is_setpoint_manager):
        node = text(spm, FIELD)
        if not node or find(doc, "NodeList", node) is not None:
            continue
        loop = next((name for name, nodes in loops.items() if node.casefold() in nodes), None)
        if loop is None:
            continue
        loop_obj = find_by_name(doc, ("AirLoopHVAC", "PlantLoop", "CondenserLoop"), loop)
        new_node = unique_name(doc, f"{node} SP")
        spm[FIELD] = new_node
        return InjectedFault(
            scope=[key_of(spm)],
            object_names=[spm.name, node, new_node],
            field_names=[FIELD],
            details={
                "object_type": spm.obj_type,
                "object_name": spm.name,
                "loop": loop_obj.name if loop_obj is not None else loop,
                "original": node,
                "moved_to": new_node,
            },
        )
    raise ValueError("no setpoint manager on a loop branch node")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    d = injected.details
    spm = find(doc, d["object_type"], d["object_name"])
    if spm is None:
        return False
    nodes = expand_nodes(doc, text(spm, FIELD))
    loop_nodes = loop_branch_nodes(doc).get(d["loop"].casefold(), set())
    return bool(nodes) and all(n.casefold() in loop_nodes for n in nodes)


FAULT = FaultType(
    id="setpoint_on_unused_node",
    layer="topology",
    description="A setpoint manager sets a node that no flow component uses, so its loop has no setpoint.",
    held_out=False,
    applies_to=["air_loop", "plant_loop"],
    intended_tools=["check_model_integrity", "trace_hvac"],
    prompt_template=prompts_template("symptom.severe_error"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
