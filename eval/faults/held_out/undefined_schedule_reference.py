"""Held-out topology fault: an internal gain that names a schedule the model does not define.

**Source.** Zhang, L., Chen, Z. and Ford, V. (2024), "Advancing building energy modeling with large language
models: Exploration and case studies", Energy and Buildings 323, 114788
(https://doi.org/10.1016/j.enbuild.2024.114788, preprint https://arxiv.org/abs/2402.09579). In its agentic
model-generation case study, objects are written one at a time by separate agents, and the debugging agent then
runs the assembled file in EnergyPlus, "identifying and correcting errors, primarily those arising from incorrect
references". A name invented for one object and never defined by another is the form this takes here. The
follow-up, Zhang, Ford, Chen and Chen (2025), "Automatic building energy model development and debugging using
large language models agentic workflow", Energy and Buildings 327, 115116 (https://www.osti.gov/biblio/2480816),
keeps a debugging agent for the same purpose; only its abstract was read, so no detail is taken from it.

**Inject.** The first ``Lights`` object (by name) whose schedule can be evaluated has its schedule name replaced
by a plausible name that no object in the model has. EnergyPlus 26.2 reports "GetInternalHeatGains: Lights = <name>
... Schedule Name = <new name>, item not found" and does not complete the run.

**Verify** (structural). The same ``Lights`` object exists and its schedule field names a schedule the model
defines, that can be evaluated over a year, and that behaves like a lighting schedule: never negative, not always
zero, and with a maximum no higher than the original's (or 1, whichever is larger). Restoring the original name
passes; so does defining a schedule under the new name, or choosing another fractional schedule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import find, key_of, prompts_template, schedule_stats, sorted_objects, text, unique_name

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

GAIN = "Lights"
FIELD = "schedule_name"
INVENTED = "Office Lighting Schedule"
TOLERANCE = 1e-6


def inject(doc: IDFDocument) -> InjectedFault:
    for gain in sorted_objects(doc, GAIN):
        original = text(gain, FIELD)
        stats = schedule_stats(doc, original)
        if stats is None or stats.maximum <= 0:
            continue
        invented = unique_name(doc, INVENTED)
        gain[FIELD] = invented
        return InjectedFault(
            scope=[key_of(gain)],
            object_names=[gain.name, invented, original],
            field_names=[FIELD],
            details={"object_name": gain.name, "original": original, "original_max": repr(stats.maximum)},
        )
    raise ValueError("no Lights object with an evaluable schedule")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    gain = find(doc, GAIN, injected.details["object_name"])
    if gain is None:
        return False
    stats = schedule_stats(doc, text(gain, FIELD))
    if stats is None:
        return False
    ceiling = max(1.0, float(injected.details["original_max"]))
    return stats.minimum >= -TOLERANCE and 0 < stats.maximum <= ceiling + TOLERANCE


FAULT = FaultType(
    id="undefined_schedule_reference",
    layer="topology",
    description="A Lights object names a schedule that no object in the model defines.",
    held_out=True,
    applies_to=["packaged_unit"],
    intended_tools=[],
    prompt_template=prompts_template("symptom.severe_error"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
