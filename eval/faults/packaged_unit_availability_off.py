"""Designed results fault: a packaged unit's availability schedule switched to always off.

**Inject.** The first packaged unit, over the zone units (``ZoneHVAC:PackagedTerminalAirConditioner`` and
``...HeatPump``) and then the air-loop unitary types (``AirLoopHVAC:UnitarySystem``, ``...UnitaryHeatCool``,
``...UnitaryHeatPump:AirToAir``, the furnaces and ``...UnitaryHeatOnly``), names sorted within each type, whose
zone can be found, gets a new ``Schedule:Constant`` of 0 as its availability schedule. The zone is the one whose
equipment list holds a zone unit, or a unitary system's controlling zone, else the first zone its air loop serves.

**Verify.** The unit still exists and its availability schedule is blank (always available) or, evaluated hourly
over a year, has a positive maximum and a mean at least 90% of the original schedule's mean (a blank original counts
as 1). A result whose simulation failed is never a fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import (
    PACKAGED_AIR_LOOP_UNITS,
    PACKAGED_ZONE_UNITS,
    air_loop_entries,
    check_result_if_given,
    find,
    key_of,
    prompts_template,
    schedule_stats,
    sorted_objects,
    text,
    unique_name,
    zone_of_equipment,
    zones_served_by_air_loop,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument, IDFObject
    from idfkit.simulation.result import SimulationResult

FIELD = "availability_schedule_name"


def _zone(doc: IDFDocument, unit: IDFObject) -> str | None:
    if unit.obj_type in PACKAGED_ZONE_UNITS:
        return zone_of_equipment(doc, unit)
    controlling = text(unit, "controlling_zone_or_thermostat_location")
    zone = find(doc, "Zone", controlling) if controlling else None
    if zone is not None:
        return zone.name
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        if any(e.is_(unit.obj_type, unit.name) for _, e in air_loop_entries(doc, loop)):
            served = zones_served_by_air_loop(doc, loop)
            return served[0] if served else None
    return None


def _mean(doc: IDFDocument, schedule: str) -> float | None:
    if not schedule:
        return 1.0
    stats = schedule_stats(doc, schedule)
    return None if stats is None else stats.mean


def inject(doc: IDFDocument) -> InjectedFault:
    for obj_type in (*PACKAGED_ZONE_UNITS, *PACKAGED_AIR_LOOP_UNITS):
        for unit in sorted_objects(doc, obj_type):
            zone = _zone(doc, unit)
            original = text(unit, FIELD)
            mean = _mean(doc, original)
            if zone is None or mean is None or mean <= 0:
                continue
            schedule = doc.add(
                "Schedule:Constant", unique_name(doc, "Unit Off Sch"), {"hourly_value": 0.0}, validate=False
            )
            unit[FIELD] = schedule.name
            return InjectedFault(
                scope=[key_of(unit), key_of(schedule)],
                object_names=[unit.name, schedule.name, *([original] if original else [])],
                field_names=[FIELD],
                prompt_values={"zone": zone},
                details={"object_type": unit.obj_type, "object_name": unit.name, "original_mean": repr(mean)},
            )
    raise ValueError("no packaged unit with a known zone and an available schedule")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    unit = find(doc, injected.details["object_type"], injected.details["object_name"])
    if unit is None or not check_result_if_given(result):
        return False
    schedule = text(unit, FIELD)
    if not schedule:
        return True
    stats = schedule_stats(doc, schedule)
    return stats is not None and stats.maximum > 0 and stats.mean >= 0.9 * float(injected.details["original_mean"])


FAULT = FaultType(
    id="packaged_unit_availability_off",
    layer="results",
    description="A packaged unit's availability schedule is replaced by an always-off schedule.",
    held_out=False,
    applies_to=["packaged_unit"],
    intended_tools=["diagnose_symptom", "get_object_results"],
    prompt_template=prompts_template("symptom.zone_too_warm"),
    needs_energyplus=True,
    inject=inject,
    verify=verify,
)
