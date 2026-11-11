"""Designed topology fault: an air terminal whose outlet is not an inlet of the zone it serves.

**Inject.** The first ``AirTerminal:SingleDuct:VAV:Reheat`` (zones by name, then equipment-list order) whose
outlet node is shared by its reheat coil's air outlet and its air distribution unit's outlet, and is an inlet node
of its zone, is moved, together with that coil outlet and unit outlet, to a new node name. The unit is internally
consistent but delivers its air to a node the zone does not list.

**Verify** (structural): the terminal, its reheat coil and its air distribution unit share one outlet node again,
that node is among the zone's inlet nodes (a node list is expanded), and the unit is still in the zone's equipment
list. Pointing the zone's inlet at the new node passes as well as restoring the original node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault, ObjectKey
from eval.support import (
    find,
    key_of,
    prompts_template,
    reheat_coil,
    same,
    text,
    unique_name,
    zone_connections,
    zone_equipment,
    zone_inlet_nodes,
    zone_terminals,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

TERMINAL = "AirTerminal:SingleDuct:VAV:Reheat"
TERMINAL_OUT = "air_outlet_node_name"
COIL_OUT = "air_outlet_node_name"
ADU_OUT = "air_distribution_unit_outlet_node_name"


def inject(doc: IDFDocument) -> InjectedFault:
    for zt in zone_terminals(doc):
        if not same(zt.terminal.obj_type, TERMINAL):
            continue
        coil = reheat_coil(doc, zt.terminal)
        outlet = text(zt.terminal, TERMINAL_OUT)
        if coil is None or not same(text(coil, COIL_OUT), outlet) or not same(text(zt.adu, ADU_OUT), outlet):
            continue
        if not any(same(n, outlet) for n in zone_inlet_nodes(doc, zt.zone)):
            continue
        new_node = unique_name(doc, f"{zt.terminal.name} Outlet Node")
        zt.terminal[TERMINAL_OUT] = new_node
        coil[COIL_OUT] = new_node
        zt.adu[ADU_OUT] = new_node
        scope = [key_of(zt.terminal), key_of(coil), key_of(zt.adu)]
        conn = zone_connections(doc, zt.zone)
        if conn is not None:
            scope.append(key_of(conn))
            inlet_list = find(doc, "NodeList", text(conn, "zone_air_inlet_node_or_nodelist_name"))
            if inlet_list is not None:
                scope.append(ObjectKey("NodeList", inlet_list.name))
        return InjectedFault(
            scope=scope,
            object_names=[zt.terminal.name, coil.name, zt.adu.name, outlet, new_node],
            field_names=[TERMINAL_OUT, ADU_OUT],
            prompt_values={"zone": zt.zone},
            details={
                "zone": zt.zone,
                "terminal_type": zt.terminal.obj_type,
                "terminal": zt.terminal.name,
                "adu": zt.adu.name,
                "original": outlet,
                "moved_to": new_node,
            },
        )
    raise ValueError("no VAV reheat terminal whose outlet is its zone's inlet")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    d = injected.details
    terminal = find(doc, d["terminal_type"], d["terminal"])
    adu = find(doc, "ZoneHVAC:AirDistributionUnit", d["adu"])
    if terminal is None or adu is None or not same(text(adu, "air_terminal_name"), terminal.name):
        return False
    outlet = text(terminal, TERMINAL_OUT)
    coil = reheat_coil(doc, terminal)
    if coil is not None and not same(text(coil, COIL_OUT), outlet):
        return False
    if not same(text(adu, ADU_OUT), outlet):
        return False
    if not any(same(n, outlet) for n in zone_inlet_nodes(doc, d["zone"])):
        return False
    return any(same(e.obj_type, adu.obj_type) and same(e.name, adu.name) for e in zone_equipment(doc, d["zone"]))


FAULT = FaultType(
    id="terminal_outlet_not_zone_inlet",
    layer="topology",
    description="A VAV reheat terminal delivers air to a node that is not an inlet of the zone it serves.",
    held_out=False,
    applies_to=["vav_reheat"],
    intended_tools=["check_model_integrity", "trace_hvac", "get_object_neighbourhood"],
    prompt_template=prompts_template("symptom.simulation_fails"),
    needs_energyplus=False,
    inject=inject,
    verify=verify,
)
