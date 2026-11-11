"""Open question: which plant loop serves the reheat coil of a given zone?

**Applies to** models tagged ``hot_water``. ``zone``: the first zone (by name) whose air terminal has a
``Coil:Heating:Water`` reheat coil on a plant loop's demand side. **Key**: that plant loop's name, found by following
the coil to the demand branch that lists it. **Verify** (``answers.single_name_matches``): the answer names the
key and no other plant or condenser loop of the model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.answers import single_name_matches
from eval.model import TaskSpec
from eval.support import plant_loop_names, prompts_template, reheat_coil, same, side_of_component, zone_terminals

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

COIL = "Coil:Heating:Water"


def _target(doc: IDFDocument) -> tuple[str, str]:
    for zt in zone_terminals(doc):
        coil = reheat_coil(doc, zt.terminal)
        if coil is None or not same(coil.obj_type, COIL):
            continue
        located = side_of_component(doc, COIL, coil.name)
        if located is not None and located[0].side == "demand":
            return zt.zone, located[0].loop_name
    raise ValueError("no zone with a hot-water reheat coil on a plant loop")


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"zone": _target(doc)[0]}


def answer_key(doc: IDFDocument) -> str:
    return _target(doc)[1]


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    return answer is not None and single_name_matches(answer, answer_key(doc), plant_loop_names(doc))


TASK = TaskSpec(
    id="plant_loop_of_reheat_coil",
    kind="question",
    layer="topology",
    applies_to=["hot_water"],
    prompt_template=prompts_template("question.plant_loop_of_reheat_coil"),
    intended_tools=["trace_hvac", "get_object_neighbourhood"],
    needs_energyplus=False,
    verify=verify,
    answer_key=answer_key,
    prompt_values=prompt_values,
)
