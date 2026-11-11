"""Open question: what total capacity does sizing give the boilers on a given plant loop?

**Applies to** models tagged ``hot_water``. ``plant_loop``: the first plant loop (by name) with a ``Boiler:HotWater``
on its supply side. **Key**: the sum, over the boilers on its supply branches, of the "Reference Capacity" in the
EquipmentSummary "Central Plant" table, in kW with one decimal. Like every sizing result it depends only on the
model's design days (``support.design_day_sizing``; a result passed by the harness is used when it carries the
table). **Verify** (``answers.first_number``): the first number in the answer, once the model's loop and boiler names
are blanked out, is within 5% of the key read as kW, or of the key in W (an answer given in watts).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.answers import first_number
from eval.model import TaskSpec
from eval.support import (
    SizingFacts,
    design_day_sizing,
    is_boiler,
    loops_with_supply,
    plant_loop_names,
    plant_side,
    prompts_template,
    side_component_types,
    sizing_facts,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

TOLERANCE = 0.05


def _loop(doc: IDFDocument) -> str:
    loops = loops_with_supply(doc, is_boiler)
    if not loops:
        raise ValueError("no plant loop with a hot-water boiler")
    return loops[0]


def _boilers(doc: IDFDocument) -> list[str]:
    side = plant_side(doc, _loop(doc), "supply")
    entries = side_component_types(doc, side) if side is not None else []
    return [e.name for e in entries if is_boiler(e.object_type)]


def _kilowatts(doc: IDFDocument, facts: SizingFacts) -> float:
    boilers = _boilers(doc)
    missing = [b for b in boilers if b.casefold() not in facts.plant_capacities]
    if not boilers or missing:
        raise ValueError(f"no sized capacity for boilers {missing or boilers}")
    return sum(facts.plant_capacities[b.casefold()] for b in boilers) / 1000.0


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"plant_loop": _loop(doc)}


def answer_key(doc: IDFDocument) -> str:
    return f"{_kilowatts(doc, design_day_sizing(doc)):.1f}"


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    if answer is None:
        return False
    key = _kilowatts(doc, sizing_facts(doc, result))
    value = first_number(answer, ignore=[*plant_loop_names(doc), *_boilers(doc)])
    if value is None or key <= 0:
        return False
    return any(abs(v - key) <= TOLERANCE * key for v in (value, value / 1000.0))


TASK = TaskSpec(
    id="boiler_design_capacity",
    kind="question",
    layer="results",
    applies_to=["hot_water"],
    prompt_template=prompts_template("question.boiler_design_capacity"),
    intended_tools=["get_object_results", "get_object_neighbourhood"],
    needs_energyplus=True,
    verify=verify,
    answer_key=answer_key,
    prompt_values=prompt_values,
)
