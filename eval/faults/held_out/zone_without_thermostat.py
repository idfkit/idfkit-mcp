"""Held-out results fault: a conditioned zone left without a thermostat.

**Source.** idfkit-mcp issue 50, "get_zone_properties omits thermostat linkage even when ZoneControl:Thermostat is
present and referenced" (https://github.com/idfkit/idfkit-mcp/issues/50): whether a zone has a thermostat was the
thing an agent could not see through the server, so a zone that has none is a state an agent neither notices nor
repairs. That EnergyPlus runs such a zone without complaint, as an unconditioned zone, is the behaviour described
on Unmet Hours in "How can I create unconditioned thermal zone?" (2017,
https://unmethours.com/question/24969/how-can-i-create-unconditioned-thermal-zone/). No report of this exact
mistake made by an agent was found; the two sources give the blind spot and the consequence.

**Inject.** The first zone (by name) that has zone equipment, is not the controlling zone of a unitary system,
and is covered by a ``ZoneControl:Thermostat`` with an evaluable heating setpoint, loses that cover. A thermostat
naming the zone itself is removed. A thermostat naming a zone list is pointed at a new ``ZoneList`` holding the
other zones, so the rest of the building, and everything else that uses the original list, is untouched. The
setpoint objects and schedules stay. The simulation completes; the zone's terminal has nothing to control to, so
the zone floats and is sized for no load (on 5ZoneAirCooled the zone's winter design day minimum falls from 19.8
to 15.7 degC). Controlling zones are skipped because EnergyPlus stops on them ("Did not find air node (zone with
thermostat)"), which is a different symptom.

**Verify.** A ``ZoneControl:Thermostat`` covers the zone again, directly or through a zone list, and one of the
setpoint objects it names gives heating a setpoint whose yearly maximum is no more than 1 K below the original's.
The thermostat may have any name and may be a new object or an existing one widened to the zone. A result whose
simulation failed is never a fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import (
    check_result_if_given,
    expand_zones,
    find,
    key_of,
    prompts_template,
    same,
    schedule_stats,
    sorted_objects,
    text,
    unique_name,
    zone_equipment,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument, IDFObject
    from idfkit.simulation.result import SimulationResult

THERMOSTAT = "ZoneControl:Thermostat"
ZONE_FIELD = "zone_or_zonelist_name"
HEATING_FIELDS = {
    "thermostatsetpoint:singleheating": "setpoint_temperature_schedule_name",
    "thermostatsetpoint:singleheatingorcooling": "setpoint_temperature_schedule_name",
    "thermostatsetpoint:dualsetpoint": "heating_setpoint_temperature_schedule_name",
}
CONTROLLING_ZONE_FIELD = "controlling_zone_or_thermostat_location"
CONTROL_SLOTS = 4
MARGIN = 1.0


def _heating_maximum(doc: IDFDocument, thermostat: IDFObject) -> float | None:
    """The highest yearly maximum among the heating setpoint schedules a thermostat can use; ``None`` without one."""
    best: float | None = None
    for n in range(1, CONTROL_SLOTS + 1):
        obj_type = text(thermostat, f"control_{n}_object_type")
        field = HEATING_FIELDS.get(obj_type.casefold())
        setpoint = find(doc, obj_type, text(thermostat, f"control_{n}_name")) if field else None
        stats = schedule_stats(doc, text(setpoint, field)) if setpoint is not None and field else None
        if stats is not None and (best is None or stats.maximum > best):
            best = stats.maximum
    return best


def _cover(doc: IDFDocument, zone: str) -> IDFObject | None:
    """The thermostat covering ``zone``: one naming the zone itself first, then one naming a list that holds it."""
    thermostats = sorted_objects(doc, THERMOSTAT)
    for thermostat in thermostats:
        if same(text(thermostat, ZONE_FIELD), zone):
            return thermostat
    for thermostat in thermostats:
        if any(same(z, zone) for z in expand_zones(doc, text(thermostat, ZONE_FIELD))):
            return thermostat
    return None


def inject(doc: IDFDocument) -> InjectedFault:
    controlling = {text(obj, CONTROLLING_ZONE_FIELD).casefold() for obj in doc.all_objects}
    for zone in sorted_objects(doc, "Zone"):
        thermostat = _cover(doc, zone.name)
        if thermostat is None or zone.name.casefold() in controlling or not zone_equipment(doc, zone.name):
            continue
        maximum = _heating_maximum(doc, thermostat)
        if maximum is None:
            continue
        scope, names = [key_of(thermostat)], [thermostat.name, THERMOSTAT]
        covered = text(thermostat, ZONE_FIELD)
        others = [z for z in expand_zones(doc, covered) if not same(z, zone.name)]
        if others:
            rest = doc.add(
                "ZoneList",
                unique_name(doc, f"{covered} Controlled"),
                {"zones": [{"zone_name": z} for z in others]},
                validate=False,
            )
            thermostat[ZONE_FIELD] = rest.name
            scope.append(key_of(rest))
            names += [rest.name, covered]
        else:
            doc.removeidfobject(thermostat)
        return InjectedFault(
            scope=scope,
            object_names=names,
            field_names=[ZONE_FIELD],
            prompt_values={"zone": zone.name},
            details={"zone": zone.name, "heating_max": repr(maximum)},
        )
    raise ValueError("no equipped, non-controlling zone under a thermostat with an evaluable heating setpoint")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    if not check_result_if_given(result):
        return False
    zone, floor = injected.details["zone"], float(injected.details["heating_max"]) - MARGIN
    for thermostat in sorted_objects(doc, THERMOSTAT):
        if not any(same(z, zone) for z in expand_zones(doc, text(thermostat, ZONE_FIELD))):
            continue
        maximum = _heating_maximum(doc, thermostat)
        if maximum is not None and maximum >= floor:
            return True
    return False


FAULT = FaultType(
    id="zone_without_thermostat",
    layer="results",
    description="A conditioned zone is covered by no ZoneControl:Thermostat, so its equipment is not controlled.",
    held_out=True,
    applies_to=["vav_reheat"],
    intended_tools=[],
    prompt_template=prompts_template("symptom.zone_too_cold"),
    needs_energyplus=True,
    inject=inject,
    verify=verify,
)
