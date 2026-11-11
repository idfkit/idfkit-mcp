"""Authoring task: add a new zone served by a VAV terminal with reheat on an existing air loop.

**Applies to** models tagged ``vav_reheat``.

**Prompt.** ``goal.add_vav_zone`` with ``air_loop``: the first air loop (by name) serving a zone through an
``AirTerminal:SingleDuct:VAV:Reheat``, and ``new_zone``: the name the zone must get.

**Success** (``support.authoring_succeeded``): a ``Zone`` named ``new_zone`` exists, has heat-transfer surfaces, is
served by that air loop (``support.zones_served_by_air_loop``: supply path, splitter or plenum, terminal inlet) through
an ``AirTerminal:SingleDuct:VAV:Reheat`` whose outlet is one of the zone's inlet nodes; the connection check reports
no error (or is unavailable) and the model simulates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import TaskSpec
from eval.support import (
    authoring_succeeded,
    find,
    prompts_template,
    same,
    sorted_objects,
    surfaces_of_zone,
    text,
    zone_inlet_nodes,
    zone_terminals,
    zones_served_by_air_loop,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

NEW_ZONE = "Added Zone"
TERMINAL = "AirTerminal:SingleDuct:VAV:Reheat"


def target_loop(doc: IDFDocument) -> str:
    vav_zones = {zt.zone.casefold() for zt in zone_terminals(doc) if same(zt.terminal.obj_type, TERMINAL)}
    for loop in sorted_objects(doc, "AirLoopHVAC"):
        if any(z.casefold() in vav_zones for z in zones_served_by_air_loop(doc, loop)):
            return loop.name
    raise ValueError("no air loop serving a VAV reheat terminal")


def prompt_values(doc: IDFDocument) -> dict[str, str]:
    return {"air_loop": target_loop(doc), "new_zone": NEW_ZONE}


def goal_met(doc: IDFDocument) -> bool:
    zone = find(doc, "Zone", NEW_ZONE)
    loop = find(doc, "AirLoopHVAC", target_loop(doc))
    if zone is None or loop is None or not surfaces_of_zone(doc, zone.name):
        return False
    if not any(same(z, zone.name) for z in zones_served_by_air_loop(doc, loop)):
        return False
    inlets = {n.casefold() for n in zone_inlet_nodes(doc, zone.name)}
    return any(
        same(zt.zone, zone.name)
        and same(zt.terminal.obj_type, TERMINAL)
        and text(zt.terminal, "air_outlet_node_name").casefold() in inlets
        for zt in zone_terminals(doc)
    )


def verify(doc: IDFDocument, result: SimulationResult | None, answer: str | None) -> bool:
    return authoring_succeeded(doc, result, goal_met=goal_met(doc))


TASK = TaskSpec(
    id="add_vav_zone",
    kind="authoring",
    layer="topology",
    applies_to=["vav_reheat"],
    prompt_template=prompts_template("goal.add_vav_zone"),
    intended_tools=["get_hvac_topology", "trace_hvac", "check_model_integrity"],
    needs_energyplus=True,
    verify=verify,
    prompt_values=prompt_values,
)
