"""Open question: which zone on a given air loop has the largest design heating load after sizing?

**Applies to** models tagged ``air_loop``. ``air_loop``: the first air loop (by name) serving a zone. **Key**: among
the zones it serves, the one with the largest "User Design Load" in the HVACSizingSummary "Zone Sensible Heating"
table. Sizing uses only the model's own design days, so the key does not depend on the weather file an agent
chooses; it is computed from a design-day run (``support.design_day_sizing``) or read from the simulation result the
harness passes when that carries the table. **Verify**: the answer names exactly one zone of the model, and its
load is within 0.5% of the largest (ties are accepted).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.answers import mentioned
from eval.model import TaskSpec
from eval.support import (
    SizingFacts,
    design_day_sizing,
    prompts_template,
    sizing_facts,
    sorted_objects,
    zones_served_by_air_loop,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

TIE = 0.005


def _loop_and_zones(doc: IDFDocument) -> tuple[str, list[str]]:
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        zones = zones_served_by_air_loop(doc, loop)
        if zones:
            return loop.name, zones
    raise ValueError("no air loop serving a zone")


def _loads(doc: IDFDocument, facts: SizingFacts) -> dict[str, float]:
    zones = _loop_and_zones(doc)[1]
    loads = {z: facts.zone_heating_loads[z.casefold()] for z in zones if z.casefold() in facts.zone_heating_loads}
    if not loads:
        raise ValueError("no design heating load for the zones of the air loop")
    return loads


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"air_loop": _loop_and_zones(doc)[0]}


def answer_key(doc: IDFDocument) -> str:
    loads = _loads(doc, design_day_sizing(doc))
    return max(sorted(loads, key=str.casefold), key=lambda z: loads[z])


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    if answer is None:
        return False
    loads = _loads(doc, sizing_facts(doc, result))
    top = max(loads.values())
    accepted = {z.casefold() for z, load in loads.items() if load >= top * (1 - TIE)}
    hits = {m.casefold() for m in mentioned(answer, [z.name for z in sorted_objects(doc, "Zone")])}
    return len(hits) == 1 and hits <= accepted


TASK = TaskSpec(
    id="largest_design_heating_load",
    kind="question",
    layer="results",
    applies_to=["air_loop"],
    prompt_template=prompts_template("question.largest_design_heating_load"),
    intended_tools=["get_object_results", "get_object_neighbourhood"],
    needs_energyplus=True,
    verify=verify,
    answer_key=answer_key,
    prompt_values=prompt_values,
)
