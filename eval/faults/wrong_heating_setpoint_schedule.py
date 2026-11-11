"""Designed results fault: a thermostat's heating setpoint pointed at a 10 degC setback schedule.

**Inject.** The first ``ThermostatSetpoint:DualSetpoint`` (then ``ThermostatSetpoint:SingleHeating``), by name,
that a ``ZoneControl:Thermostat`` uses and whose heating schedule can be evaluated gets a new ``Schedule:Constant``
of 10 degC (same schedule type limits) as its heating setpoint schedule. Every zone using the thermostat runs cold;
the prompt names the first of them.

**Verify.** The same setpoint object exists and its heating schedule, evaluated hourly over a year with
``idfkit.schedules``, has a maximum no more than 0.5 K below the original schedule's maximum and a mean no more than
1 K below the original mean: restoring the original schedule passes, and so does any comparable heating schedule.
A result whose simulation failed is never a fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import (
    check_result_if_given,
    find,
    key_of,
    prompts_template,
    schedule_stats,
    schedule_type_limits,
    sorted_objects,
    text,
    thermostat_zones,
    unique_name,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

SETPOINTS = (
    ("ThermostatSetpoint:DualSetpoint", "heating_setpoint_temperature_schedule_name"),
    ("ThermostatSetpoint:SingleHeating", "setpoint_temperature_schedule_name"),
)
SETBACK = 10.0


def inject(doc: IDFDocument) -> InjectedFault:
    for obj_type, field in SETPOINTS:
        for setpoint in sorted_objects(doc, obj_type):
            zones = thermostat_zones(doc, obj_type, setpoint.name)
            original = text(setpoint, field)
            stats = schedule_stats(doc, original)
            if not zones or stats is None or stats.maximum <= SETBACK + 1:
                continue
            fields: dict[str, object] = {"hourly_value": SETBACK}
            limits = schedule_type_limits(doc, original)
            if limits:
                fields["schedule_type_limits_name"] = limits
            schedule = doc.add("Schedule:Constant", unique_name(doc, "Heating Setback Sch"), fields, validate=False)
            setpoint[field] = schedule.name
            return InjectedFault(
                scope=[key_of(setpoint), key_of(schedule)],
                object_names=[setpoint.name, schedule.name, original],
                field_names=[field],
                prompt_values={"zone": zones[0]},
                details={
                    "object_type": obj_type,
                    "object_name": setpoint.name,
                    "field": field,
                    "original": original,
                    "original_max": repr(stats.maximum),
                    "original_mean": repr(stats.mean),
                },
            )
    raise ValueError("no thermostat heating setpoint with an evaluable schedule")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    d = injected.details
    setpoint = find(doc, d["object_type"], d["object_name"])
    if setpoint is None or not check_result_if_given(result):
        return False
    stats = schedule_stats(doc, text(setpoint, d["field"]))
    if stats is None:
        return False
    return stats.maximum >= float(d["original_max"]) - 0.5 and stats.mean >= float(d["original_mean"]) - 1.0


FAULT = FaultType(
    id="wrong_heating_setpoint_schedule",
    layer="results",
    description="A thermostat's heating setpoint schedule is replaced by a constant 10 degC setback schedule.",
    held_out=False,
    applies_to=["air_loop"],
    intended_tools=["diagnose_symptom", "get_object_results"],
    prompt_template=prompts_template("symptom.zone_too_cold"),
    needs_energyplus=True,
    inject=inject,
    verify=verify,
)
