"""Held-out topology fault: the sizing calculations switched off in a model whose equipment is autosized.

**Source.** EnergyPlus user reports on Unmet Hours: "VRF system - Error" (2015,
https://unmethours.com/question/3101/vrf-system-error/) and "OpenStudio simulation fails when adding HVAC system"
(2018, https://unmethours.com/question/32654/openstudio-simulation-fails-when-adding-hvac-system/). Both runs stop
with "a zone sizing run must be done" for an autosized unit, and both answers point at the sizing options of the
simulation settings. The same condition is common enough for a downstream tool to refuse it up front
(canmet-energy/btap pull request 70, "Refuse a run dir whose sizing calculations are off, before EnergyPlus does").

**Inject.** Every ``do_*_sizing_calculation`` field of ``SimulationControl`` that is ``Yes`` is set to ``No``.
EnergyPlus 26.2 then stops before the first environment: "For autosizing of <unit>, a zone sizing run must be done.
The "SimulationControl" object did not have the field "Do Zone Sizing Calculation" set to Yes."

**Verify** (structural). ``SimulationControl`` exists and every calculation that was on before the injection is on
again. A calculation that was off in the reference model may be left either way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault, ObjectKey
from eval.support import ensure, prompts_template, same, sorted_objects, text

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

CONTROL = "SimulationControl"
FLAGS = ("do_zone_sizing_calculation", "do_system_sizing_calculation", "do_plant_sizing_calculation")


def inject(doc: IDFDocument) -> InjectedFault:
    controls = sorted_objects(doc, CONTROL)
    ensure(bool(controls), "no SimulationControl object")
    control = controls[0]
    switched = [flag for flag in FLAGS if same(text(control, flag), "Yes")]
    ensure(FLAGS[0] in switched, "the zone sizing calculation is not on, so switching it off changes nothing")
    for flag in switched:
        control[flag] = "No"
    return InjectedFault(
        scope=[ObjectKey(CONTROL, control.name)],
        object_names=[CONTROL],
        field_names=list(FLAGS),
        details={"switched_off": ",".join(switched)},
    )


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    controls = sorted_objects(doc, CONTROL)
    if not controls:
        return False
    return all(same(text(controls[0], flag), "Yes") for flag in injected.details["switched_off"].split(","))


FAULT = FaultType(
    id="sizing_calculations_off",
    layer="topology",
    description="The sizing calculations are switched off in SimulationControl while the equipment is autosized.",
    held_out=True,
    applies_to=["zone_list", "hvac_template"],
    intended_tools=[],
    prompt_template=prompts_template("symptom.simulation_fails"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
