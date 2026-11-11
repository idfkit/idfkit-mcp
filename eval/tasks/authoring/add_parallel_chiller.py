"""Authoring task: add a second chiller in parallel with the existing one on the chilled-water loop.

**Applies to** models tagged ``chilled_water``.

**Prompt.** ``goal.add_parallel_chiller`` with ``plant_loop``: the first plant loop (by name) with a ``Chiller:*``
on its supply side, and ``new_chiller``: the name the chiller must get.

**Success** (``support.authoring_succeeded``): a ``Chiller:*`` named ``new_chiller`` sits on a supply branch of that
loop, its evaporator ports equal its branch entry, the supply splitter and mixer both name its branch, and another
chiller sits on a different branch the splitter also names (so the two are in parallel); the connection check
reports no error (or is unavailable) and the model simulates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import TaskSpec
from eval.support import (
    authoring_succeeded,
    branch_entries,
    component_ports,
    find,
    is_chiller,
    loops_with_supply,
    plant_side,
    prompts_template,
    same,
    side_branches,
    side_connectors,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

NEW_CHILLER = "Added Parallel Chiller"


def target_loop(doc: IDFDocument) -> str:
    loops = loops_with_supply(doc, is_chiller)
    if not loops:
        raise ValueError("no plant loop with a chiller on its supply side")
    return loops[0]


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"plant_loop": target_loop(doc), "new_chiller": NEW_CHILLER}


def goal_met(doc: IDFDocument) -> bool:
    side = plant_side(doc, target_loop(doc), "supply")
    if side is None:
        return False
    connectors = side_connectors(doc, side)
    outlets = [n.casefold() for n in connectors.splitter_outlets()]
    inlets = [n.casefold() for n in connectors.mixer_inlets()]
    new_branch: str | None = None
    other_branches: set[str] = set()
    for branch in side_branches(doc, side):
        for entry in branch_entries(branch):
            if not is_chiller(entry.object_type):
                continue
            if same(entry.name, NEW_CHILLER):
                chiller = find(doc, entry.object_type, entry.name)
                ports = component_ports(chiller, entry) if chiller is not None else None
                if ports is not None and same(ports[0], entry.inlet) and same(ports[1], entry.outlet):
                    new_branch = branch.name.casefold()
            else:
                other_branches.add(branch.name.casefold())
    if new_branch is None or new_branch not in outlets or new_branch not in inlets:
        return False
    return any(b != new_branch and b in outlets for b in other_branches)


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    return authoring_succeeded(doc, result, goal_met=goal_met(doc))


TASK = TaskSpec(
    id="add_parallel_chiller",
    kind="authoring",
    layer="topology",
    applies_to=["chilled_water"],
    prompt_template=prompts_template("goal.add_parallel_chiller"),
    intended_tools=["get_hvac_topology", "trace_hvac", "check_model_integrity"],
    needs_energyplus=True,
    verify=verify,
    prompt_values=prompt_values,
)
