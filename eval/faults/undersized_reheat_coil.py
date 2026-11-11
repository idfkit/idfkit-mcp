"""Designed results fault: a zone's hot-water reheat coil hard-sized far too small.

**Inject.** The first ``AirTerminal:SingleDuct:VAV:Reheat`` (zones by name) whose reheat coil is a
``Coil:Heating:Water`` gets that coil hard-sized: UA 5 W/K, maximum water flow 5e-6 m3/s and, for the
nominal-capacity input method, a rated capacity of 200 W. The zone cannot be heated.

**Verify.** The terminal's reheat coil (whatever its name now) is no longer undersized. Each sizing field is
autosized or left blank (the EnergyPlus default), or hard-sized to at least ten times the injected value. With a simulation result, two tighter rules from
ComponentSizingSummary apply: a hard-sized maximum water flow must be at least half the terminal's
``Design Size Maximum Reheat Water Flow Rate`` (EnergyPlus reports no design size for a hard-sized coil itself, but
does for its terminal), and any ``User-Specified X`` the coil reports must be at least half its ``Design Size X``.
A result whose simulation failed is never a fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import (
    check_result_if_given,
    find,
    is_autosized,
    key_of,
    numeric,
    prompts_template,
    reheat_coil,
    same,
    sizing_facts_from_result,
    text,
    zone_terminals,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

TERMINAL = "AirTerminal:SingleDuct:VAV:Reheat"
COIL = "Coil:Heating:Water"
DESIGN_REHEAT_FLOW = "Design Size Maximum Reheat Water Flow Rate"
SMALL = {"u_factor_times_area_value": 5.0, "maximum_water_flow_rate": 5e-6, "rated_capacity": 200.0}


def _sized_fields(method: str) -> list[str]:
    fields = ["u_factor_times_area_value", "maximum_water_flow_rate"]
    if same(method, "NominalCapacity"):
        fields = ["maximum_water_flow_rate", "rated_capacity"]
    return fields


def inject(doc: IDFDocument) -> InjectedFault:
    for zt in zone_terminals(doc):
        coil = reheat_coil(doc, zt.terminal)
        if not same(zt.terminal.obj_type, TERMINAL) or coil is None or not same(coil.obj_type, COIL):
            continue
        method = text(coil, "performance_input_method")
        fields = _sized_fields(method)
        for name in fields:
            coil[name] = SMALL[name]
        return InjectedFault(
            scope=[key_of(coil)],
            object_names=[coil.name, zt.terminal.name],
            field_names=fields,
            prompt_values={"zone": zt.zone},
            details={"zone": zt.zone, "terminal_type": zt.terminal.obj_type, "terminal": zt.terminal.name},
        )
    raise ValueError("no VAV reheat terminal with a hot-water reheat coil")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    if not check_result_if_given(result):
        return False
    terminal = find(doc, injected.details["terminal_type"], injected.details["terminal"])
    coil = reheat_coil(doc, terminal) if terminal is not None else None
    if terminal is None or coil is None:
        return False
    facts = sizing_facts_from_result(result)
    coil_sizes = facts.component_sizes.get((coil.obj_type.casefold(), coil.name.casefold()), {}) if facts else {}
    for label, value in coil_sizes.items():
        design = coil_sizes.get("Design Size " + label.removeprefix("User-Specified "))
        if label.startswith("User-Specified ") and design is not None and value < 0.5 * design:
            return False
    unit_sizes = (
        facts.component_sizes.get((terminal.obj_type.casefold(), terminal.name.casefold()), {}) if facts else {}
    )
    design_flow = unit_sizes.get(DESIGN_REHEAT_FLOW)
    for name in _sized_fields(text(coil, "performance_input_method")):
        if is_autosized(coil, name) or not text(coil, name):
            continue
        value = numeric(coil, name)
        floor = 0.5 * design_flow if name == "maximum_water_flow_rate" and design_flow else 10 * SMALL[name]
        if value is None or value < floor:
            return False
    return True


FAULT = FaultType(
    id="undersized_reheat_coil",
    layer="results",
    description="A zone's hot-water reheat coil is hard-sized far below its design load.",
    held_out=False,
    applies_to=["vav_reheat"],
    intended_tools=["diagnose_symptom", "get_object_results"],
    prompt_template=prompts_template("symptom.zone_too_cold"),
    needs_energyplus=True,
    inject=inject,
    verify=verify,
)
