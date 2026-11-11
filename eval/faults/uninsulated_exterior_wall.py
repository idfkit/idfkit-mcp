"""Designed results fault: the insulation layers removed from an exterior wall construction.

**Inject.** The first ``Construction`` (by name) used by an exterior wall (a ``BuildingSurface:Detailed`` of type
Wall with outside boundary condition Outdoors) that has an insulation layer (a ``Material`` with conductivity at
most 0.06 W/m-K or a ``Material:NoMass`` with resistance at least 0.5 m2-K/W) loses those layers; at least one
layer always remains.

**Verify.** Every exterior wall that used the construction has, now, a construction whose R-value
(``idfkit.thermal.calculate_r_value``, films included) is at least 90% of the original: restoring the layers passes,
and so does assigning those walls another insulated construction. A result whose simulation failed is never a fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import (
    check_result_if_given,
    find,
    key_of,
    numeric,
    prompts_template,
    same,
    sorted_objects,
    text,
)

if TYPE_CHECKING:
    from idfkit import IDFDocument, IDFObject
    from idfkit.simulation.result import SimulationResult

LAYERS = ["outside_layer", *(f"layer_{n}" for n in range(2, 11))]
SURFACE = "BuildingSurface:Detailed"


def _r_value(construction: IDFObject) -> float:
    from idfkit.thermal import calculate_r_value

    return calculate_r_value(construction)


def _is_insulation(doc: IDFDocument, name: str) -> bool:
    material = find(doc, "Material", name)
    if material is not None:
        conductivity = numeric(material, "conductivity")
        return conductivity is not None and conductivity <= 0.06
    no_mass = find(doc, "Material:NoMass", name)
    if no_mass is not None:
        resistance = numeric(no_mass, "thermal_resistance")
        return resistance is not None and resistance >= 0.5
    return False


def _exterior_walls(doc: IDFDocument) -> list[IDFObject]:
    return [
        s
        for s in sorted_objects(doc, SURFACE)
        if same(text(s, "surface_type"), "Wall") and same(text(s, "outside_boundary_condition"), "Outdoors")
    ]


def inject(doc: IDFDocument) -> InjectedFault:
    walls = _exterior_walls(doc)
    used = {text(w, "construction_name").casefold() for w in walls}
    for construction in sorted_objects(doc, "Construction"):
        if construction.name.casefold() not in used:
            continue
        layers = [text(construction, f) for f in LAYERS if text(construction, f)]
        kept = [layer for layer in layers if not _is_insulation(doc, layer)]
        if len(kept) == len(layers) or not kept:
            continue
        original_r = _r_value(construction)
        for index, field in enumerate(LAYERS):
            construction[field] = kept[index] if index < len(kept) else None
        surfaces = [w for w in walls if same(text(w, "construction_name"), construction.name)]
        return InjectedFault(
            scope=[key_of(construction)] + [key_of(w) for w in surfaces],
            object_names=[construction.name, *(layer for layer in layers if layer not in kept)],
            field_names=LAYERS[1:],
            details={
                "construction": construction.name,
                "original_r": repr(original_r),
                "surfaces": "\n".join(w.name for w in surfaces),
            },
        )
    raise ValueError("no insulated construction on an exterior wall")


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    if not check_result_if_given(result):
        return False
    needed = 0.9 * float(injected.details["original_r"])
    for name in injected.details["surfaces"].split("\n"):
        surface = find(doc, SURFACE, name)
        construction = find(doc, "Construction", text(surface, "construction_name")) if surface else None
        if construction is None or _r_value(construction) < needed:
            return False
    return True


FAULT = FaultType(
    id="uninsulated_exterior_wall",
    layer="results",
    description="An exterior wall construction has lost its insulation layers.",
    held_out=False,
    applies_to=["air_loop"],
    intended_tools=["diagnose_symptom", "get_object_results"],
    prompt_template=prompts_template("symptom.heating_energy_high"),
    needs_energyplus=True,
    inject=inject,
    verify=verify,
)
