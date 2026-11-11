"""Authoring task: replace an air loop's constant-volume supply fan with a variable-volume fan.

**Applies to** models tagged ``cv_fan``: a ``Fan:ConstantVolume`` on the branches of an air loop.

**Prompt.** ``goal.cv_to_vav_fan`` with ``air_loop``: the first air loop (by name) whose branches hold a
``Fan:ConstantVolume`` or a fan named ``new_fan`` (so the verifier finds the same loop after the change), and
``new_fan``: the name the new fan must get.

**Success** (``support.authoring_succeeded``): that loop's branches hold a fan named ``new_fan`` that is a
``Fan:VariableVolume`` or a ``Fan:SystemModel`` with continuous speed control, no ``Fan:ConstantVolume``, and the
branch holding the new fan is a connected chain; the connection check reports no error (or is unavailable) and the
model simulates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import TaskSpec
from eval.support import (
    air_loop_entries,
    authoring_succeeded,
    branch_chain_ok,
    find,
    prompts_template,
    same,
    sorted_objects,
    text,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

NEW_FAN = "Added VAV Supply Fan"
CV_FAN = "Fan:ConstantVolume"


def target_loop(doc: IDFDocument) -> str:
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        for _, entry in air_loop_entries(doc, loop):
            if same(entry.object_type, CV_FAN) or (
                entry.object_type.casefold().startswith("fan:") and same(entry.name, NEW_FAN)
            ):
                return loop.name
    raise ValueError("no air loop with a constant-volume fan on its branches")


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"air_loop": target_loop(doc), "new_fan": NEW_FAN}


def goal_met(doc: IDFDocument) -> bool:
    loop = find(doc, "AirLoopHVAC", target_loop(doc))
    if loop is None:
        return False
    entries = air_loop_entries(doc, loop)
    if any(same(e.object_type, CV_FAN) for _, e in entries):
        return False
    for branch, entry in entries:
        if not same(entry.name, NEW_FAN):
            continue
        fan = find(doc, entry.object_type, entry.name)
        variable = fan is not None and (
            same(fan.obj_type, "Fan:VariableVolume")
            or (same(fan.obj_type, "Fan:SystemModel") and same(text(fan, "speed_control_method"), "Continuous"))
        )
        if variable and branch_chain_ok(doc, branch):
            return True
    return False


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    return authoring_succeeded(doc, result, goal_met=goal_met(doc))


TASK = TaskSpec(
    id="cv_to_vav_fan",
    kind="authoring",
    layer="topology",
    applies_to=["cv_fan"],
    prompt_template=prompts_template("goal.cv_to_vav_fan"),
    intended_tools=["get_hvac_topology", "trace_hvac", "check_model_integrity"],
    needs_energyplus=True,
    verify=verify,
    prompt_values=prompt_values,
)
