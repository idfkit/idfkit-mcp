"""Open question: which zones does a given air loop supply?

**Applies to** models tagged ``air_loop``. ``air_loop``: the first air loop (by name) that serves at least one zone.
**Key**: the zones it serves (``support.zones_served_by_air_loop``: supply path through zone splitters and supply
plenums to terminal inlets or zone inlet nodes; plenum zones themselves are not served), joined with ``"; "``.
**Verify** (``answers.name_set_matches``): the zones of the model the answer names are exactly the key's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.answers import join_key, name_set_matches, split_key
from eval.model import TaskSpec
from eval.support import prompts_template, sorted_objects, zones_served_by_air_loop

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult


def _target(doc: IDFDocument) -> tuple[str, list[str]]:
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        zones = zones_served_by_air_loop(doc, loop)
        if zones:
            return loop.name, zones
    raise ValueError("no air loop serving a zone")


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"air_loop": _target(doc)[0]}


def answer_key(doc: IDFDocument) -> str:
    return join_key(_target(doc)[1])


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    zones = [z.name for z in sorted_objects(doc, "Zone")]
    return answer is not None and name_set_matches(answer, split_key(answer_key(doc)), zones)


TASK = TaskSpec(
    id="zones_of_air_loop",
    kind="question",
    layer="topology",
    applies_to=["air_loop"],
    prompt_template=prompts_template("question.zones_of_air_loop"),
    intended_tools=["get_hvac_topology", "trace_hvac"],
    needs_energyplus=False,
    verify=verify,
    answer_key=answer_key,
    prompt_values=prompt_values,
)
