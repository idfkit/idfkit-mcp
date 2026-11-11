"""Open question: which plant loop supplies chilled water to the cooling coil of a given air loop?

**Applies to** models tagged ``chilled_water``. ``air_loop``: the first air loop (by name) with a water cooling coil
(``Coil:Cooling:Water`` or ``...:DetailedGeometry``) on its branches; outdoor-air system coils are not on the
branches and do not count. **Key**: the plant loop whose demand side lists the first such coil. **Verify**
(``answers.single_name_matches``): the answer names the key and no other plant or condenser loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.answers import single_name_matches
from eval.model import TaskSpec
from eval.support import (
    WATER_COOLING_COILS,
    air_loop_entries,
    plant_loop_names,
    prompts_template,
    side_of_component,
    sorted_objects,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult


def _target(doc: IDFDocument) -> tuple[str, str]:
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        for _, entry in air_loop_entries(doc, loop):
            if entry.object_type not in WATER_COOLING_COILS:
                continue
            located = side_of_component(doc, entry.object_type, entry.name)
            if located is not None and located[0].side == "demand":
                return loop.name, located[0].loop_name
    raise ValueError("no air loop with a water cooling coil on a plant loop")


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"air_loop": _target(doc)[0]}


def answer_key(doc: IDFDocument) -> str:
    return _target(doc)[1]


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    return answer is not None and single_name_matches(answer, answer_key(doc), plant_loop_names(doc))


TASK = TaskSpec(
    id="plant_loop_of_cooling_coil",
    kind="question",
    layer="topology",
    applies_to=["chilled_water"],
    prompt_template=prompts_template("question.plant_loop_of_cooling_coil"),
    intended_tools=["trace_hvac", "get_object_neighbourhood"],
    needs_energyplus=False,
    verify=verify,
    answer_key=answer_key,
    prompt_values=prompt_values,
)
