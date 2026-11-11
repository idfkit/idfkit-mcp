"""Open question: how many coils take hot water from a given plant loop?

**Applies to** models tagged ``hot_water``. ``plant_loop``: the first plant loop (by name) with a ``Boiler:HotWater``
on its supply side. **Key**: the number of ``Coil:*`` components on the branches of its demand side, as an integer.
**Verify** (``answers.first_number``): the first number in the answer, once the names of the model's loops, zones
and coils are blanked out, equals the key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.answers import first_number
from eval.model import TaskSpec
from eval.support import (
    is_boiler,
    loops_with_supply,
    objects_of_types,
    plant_loop_names,
    plant_side,
    prompts_template,
    side_component_types,
    sorted_objects,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult


def _loop(doc: IDFDocument) -> str:
    loops = loops_with_supply(doc, is_boiler)
    if not loops:
        raise ValueError("no plant loop with a hot-water boiler")
    return loops[0]


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"plant_loop": _loop(doc)}


def answer_key(doc: IDFDocument) -> str:
    side = plant_side(doc, _loop(doc), "demand")
    entries = side_component_types(doc, side) if side is not None else []
    return str(sum(1 for e in entries if e.object_type.casefold().startswith("coil:")))


def _names(doc: IDFDocument) -> list[str]:
    names = [*plant_loop_names(doc)]
    names += [o.name for t in ("Zone", "AirLoopHVAC") for o in sorted_objects(doc, t)]
    names += [o.name for o in objects_of_types(doc, lambda t: t.casefold().startswith("coil:"))]
    return names


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    if answer is None:
        return False
    value = first_number(answer, ignore=_names(doc))
    return value is not None and value == float(answer_key(doc))


TASK = TaskSpec(
    id="hot_water_coil_count",
    kind="question",
    layer="topology",
    applies_to=["hot_water"],
    prompt_template=prompts_template("question.hot_water_coil_count"),
    intended_tools=["get_hvac_topology", "trace_hvac"],
    needs_energyplus=False,
    verify=verify,
    answer_key=answer_key,
    prompt_values=prompt_values,
)
