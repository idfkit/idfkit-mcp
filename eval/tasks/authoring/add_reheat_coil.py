"""Authoring task: add a hot-water reheat coil to a zone's terminal unit and connect it to the hot-water loop.

**Applies to** models tagged ``hw_no_reheat``: a single-duct terminal without reheat and a hot-water boiler.

**Prompt.** ``goal.add_reheat_coil`` with ``zone``: the first zone (by name) served by an
``AirTerminal:SingleDuct:VAV:NoReheat`` or ``...:ConstantVolume:NoReheat`` terminal, and ``new_coil``: the name the
coil must get. The rule also accepts a zone whose terminal's reheat coil already has that name, so the verifier finds
the same zone in the final model.

**Success** (``support.authoring_succeeded``): a ``Coil:Heating:Water`` named ``new_coil`` is the reheat coil of a
terminal serving that zone, its air outlet is the terminal's outlet, it sits on a demand branch of a plant loop with
a ``Boiler:HotWater`` on its supply side and the demand splitter names that branch; the connection check reports no
error (or is unavailable) and the model simulates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import TaskSpec
from eval.support import (
    SINGLE_DUCT_NO_REHEAT,
    authoring_succeeded,
    is_boiler,
    loops_with_supply,
    prompts_template,
    reheat_coil,
    same,
    side_connectors,
    side_of_component,
    text,
    zone_terminals,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

NEW_COIL = "Added Reheat Coil"
COIL = "Coil:Heating:Water"


def target_zone(doc: IDFDocument) -> str:
    for zt in zone_terminals(doc):
        coil = reheat_coil(doc, zt.terminal)
        if zt.terminal.obj_type in SINGLE_DUCT_NO_REHEAT or (coil is not None and same(coil.name, NEW_COIL)):
            return zt.zone
    raise ValueError("no zone served by a single-duct terminal without reheat")


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"zone": target_zone(doc), "new_coil": NEW_COIL}


def goal_met(doc: IDFDocument) -> bool:
    zone = target_zone(doc)
    hot_loops = {name.casefold() for name in loops_with_supply(doc, is_boiler)}
    for zt in zone_terminals(doc):
        coil = reheat_coil(doc, zt.terminal)
        if not same(zt.zone, zone) or coil is None or not same(coil.obj_type, COIL) or not same(coil.name, NEW_COIL):
            continue
        if not same(text(coil, "air_outlet_node_name"), text(zt.terminal, "air_outlet_node_name")):
            continue
        located = side_of_component(doc, COIL, coil.name)
        if located is None:
            continue
        side, branch = located
        if side.side != "demand" or side.loop_name.casefold() not in hot_loops:
            continue
        if any(same(n, branch.name) for n in side_connectors(doc, side).splitter_outlets()):
            return True
    return False


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    return authoring_succeeded(doc, result, goal_met=goal_met(doc))


TASK = TaskSpec(
    id="add_reheat_coil",
    kind="authoring",
    layer="topology",
    applies_to=["hw_no_reheat"],
    prompt_template=prompts_template("goal.add_reheat_coil"),
    intended_tools=["get_hvac_topology", "trace_hvac", "check_model_integrity"],
    needs_energyplus=True,
    verify=verify,
    prompt_values=prompt_values,
)
