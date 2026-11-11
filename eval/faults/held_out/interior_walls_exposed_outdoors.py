"""Held-out results fault: the walls a zone shares with its neighbours modelled as exterior walls.

**Source.** idfkit issue 165, "intersect_match leaves partial-overlap (T-junction) and stacked-storey shared walls
unmatched; interior walls leak as Outdoors" (https://github.com/idfkit/idfkit/issues/165): walls between zones
kept the ``Outdoors`` boundary condition, an interior zone surrounded by other zones had exterior walls, the
exterior wall area was more than twice the true figure, and the loads were overstated. The model simulates and
EnergyPlus reports nothing.

**Inject.** The zone (first by name among those tied) with the most interzone walls, counted as
``BuildingSurface:Detailed`` walls whose outside boundary condition is ``Surface`` and whose partner, in another
zone, points back. Every such wall of the zone and its partner become ``Outdoors``, sun and wind exposed, with no
boundary object. On ASHRAE901_OfficeSmall the core zone's design heating load rises several-fold.

**Verify.** Each of those pairs is interior again: both walls exist and either they name each other with boundary
condition ``Surface``, or both are ``Adiabatic`` (the usual simplification for a wall between zones at the same
conditions). A pair with one side repaired fails, as EnergyPlus would reject it. A result whose simulation failed
is never a fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eval.model import FaultType, InjectedFault
from eval.support import check_result_if_given, find, key_of, prompts_template, same, sorted_objects, text

if TYPE_CHECKING:
    from idfkit import IDFDocument, IDFObject
    from idfkit.simulation.result import SimulationResult

SURFACE = "BuildingSurface:Detailed"
CONDITION = "outside_boundary_condition"
PARTNER = "outside_boundary_condition_object"
EXPOSED = {CONDITION: "Outdoors", PARTNER: "", "sun_exposure": "SunExposed", "wind_exposure": "WindExposed"}
SEPARATOR = "\t"


def _interzone_walls(doc: IDFDocument) -> dict[str, list[tuple[IDFObject, IDFObject]]]:
    """``zone -> [(wall, partner)]`` for walls matched one-to-one with a wall of another zone; zones as written.

    A wall or partner that a third surface also names as its boundary object is left out: exposing such a pair
    would leave that third surface unmatched, which EnergyPlus rejects instead of simulating.
    """
    surfaces = sorted_objects(doc, SURFACE)
    named: dict[str, int] = {}
    for surface in surfaces:
        target = text(surface, PARTNER).casefold()
        if target:
            named[target] = named.get(target, 0) + 1
    by_zone: dict[str, list[tuple[IDFObject, IDFObject]]] = {}
    for wall in surfaces:
        zone = text(wall, "zone_name")
        if not zone or not same(text(wall, "surface_type"), "Wall") or not same(text(wall, CONDITION), "Surface"):
            continue
        partner = find(doc, SURFACE, text(wall, PARTNER))
        if partner is None or not same(text(partner, PARTNER), wall.name) or same(text(partner, "zone_name"), zone):
            continue
        if named.get(wall.name.casefold()) != 1 or named.get(partner.name.casefold()) != 1:
            continue
        by_zone.setdefault(zone, []).append((wall, partner))
    return by_zone


def inject(doc: IDFDocument) -> InjectedFault:
    by_zone = _interzone_walls(doc)
    if not by_zone:
        raise ValueError("no zone with interzone walls")
    zone = min(by_zone, key=lambda z: (-len(by_zone[z]), z.casefold()))
    pairs = by_zone[zone]
    for wall, partner in pairs:
        for surface in (wall, partner):
            for field, value in EXPOSED.items():
                surface[field] = value
    surfaces = [s for pair in pairs for s in pair]
    return InjectedFault(
        scope=[key_of(s) for s in surfaces],
        object_names=[*(s.name for s in surfaces), zone],
        field_names=list(EXPOSED),
        details={"zone": zone, "pairs": ";".join(f"{w.name}{SEPARATOR}{p.name}" for w, p in pairs)},
    )


def _interior(wall: IDFObject | None, partner: IDFObject | None) -> bool:
    if wall is None or partner is None:
        return False
    conditions = (text(wall, CONDITION), text(partner, CONDITION))
    if all(same(c, "Adiabatic") for c in conditions):
        return True
    return (
        all(same(c, "Surface") for c in conditions)
        and same(text(wall, PARTNER), partner.name)
        and same(text(partner, PARTNER), wall.name)
    )


def verify(doc: IDFDocument, result: SimulationResult | None, injected: InjectedFault) -> bool:
    if not check_result_if_given(result):
        return False
    for pair in injected.details["pairs"].split(";"):
        wall_name, _, partner_name = pair.partition(SEPARATOR)
        if not _interior(find(doc, SURFACE, wall_name), find(doc, SURFACE, partner_name)):
            return False
    return True


FAULT = FaultType(
    id="interior_walls_exposed_outdoors",
    layer="results",
    description="The walls a zone shares with neighbouring zones have the Outdoors boundary condition.",
    held_out=True,
    applies_to=["hw_no_reheat", "cv_fan", "hvac_template"],
    intended_tools=[],
    prompt_template=prompts_template("symptom.heating_energy_high"),
    needs_energyplus=True,
    inject=inject,
    verify=verify,
)
