"""The held-out fault types of the evaluation harness (task T034, research R-33).

For every held-out fault and every reference model it applies to: discovery finds it, the rendered prompt passes
the lint, injection is deterministic, ``verify`` is False after injection and True after a reasonable repair.
Other repairs a modeller could make are accepted too, and half repairs are not.

Reference models are loaded from the installed EnergyPlus ExampleFiles; tests that need them skip when they are
absent. The last section runs EnergyPlus (design days only) to show that each injected model has the symptom its
prompt describes, and skips without EnergyPlus.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from idfkit import IDFDocument, load_idf
from idfkit.simulation.result import SimulationResult

from eval.config import ReferenceModel, load_reference_models
from eval.lint import lint_prompt, lint_template
from eval.model import FaultType, InjectedFault
from eval.registry import EVAL_DIR, Registry, applicable_models, discover
from eval.support import (
    default_prompt_values,
    find,
    items,
    render_prompt,
    simulated,
    sorted_objects,
    text,
)

HELD_OUT_TOPOLOGY = {"sizing_calculations_off", "undefined_schedule_reference"}
HELD_OUT_RESULTS = {"boiler_not_in_operation_scheme", "zone_without_thermostat", "interior_walls_exposed_outdoors"}
HELD_OUT = HELD_OUT_TOPOLOGY | HELD_OUT_RESULTS

THERMOSTAT = "ZoneControl:Thermostat"
SURFACE = "BuildingSurface:Detailed"


def _example_files() -> Path | None:
    try:
        from idfkit.simulation.config import find_energyplus

        candidate = find_energyplus().install_dir / "ExampleFiles"
    except Exception:
        candidate = Path("/usr/local/EnergyPlus-26-2-0/ExampleFiles")
    return candidate if candidate.is_dir() else None


def _energyplus_available() -> bool:
    try:
        from idfkit.simulation.config import find_energyplus

        find_energyplus()
    except Exception:
        return False
    return True


EXAMPLE_FILES = _example_files()
needs_models = pytest.mark.skipif(EXAMPLE_FILES is None, reason="EnergyPlus ExampleFiles not installed")
needs_energyplus = pytest.mark.skipif(
    EXAMPLE_FILES is None or not _energyplus_available(), reason="EnergyPlus not installed"
)


@cache
def _registry() -> Registry:
    return discover()


@cache
def _models() -> list[ReferenceModel]:
    return load_reference_models(EVAL_DIR / "reference_models.toml")


def _available() -> list[ReferenceModel]:
    assert EXAMPLE_FILES is not None
    return [m for m in _models() if (EXAMPLE_FILES / m.file).is_file()]


@cache
def _original(file: str) -> IDFDocument:
    assert EXAMPLE_FILES is not None
    return load_idf(str(EXAMPLE_FILES / file))


def _model(model_id: str) -> ReferenceModel:
    return next(m for m in _models() if m.id == model_id)


def _fresh(model_id: str) -> IDFDocument:
    return _original(_model(model_id).file).copy()


def _held_out() -> list[FaultType]:
    return [e.fault for e in _registry().faults if e.fault.held_out]


def _cases(ids: set[str] = HELD_OUT) -> list[tuple[str, str]]:
    if EXAMPLE_FILES is None:
        return []
    return [(f.id, m.id) for f in _held_out() if f.id in ids for m in applicable_models(f.applies_to, _available())]


# --- discovery -------------------------------------------------------------------------------------------------------


def test_discovery_finds_the_held_out_faults() -> None:
    held_out = {f.id: f for f in _held_out()}
    assert set(held_out) == HELD_OUT
    assert len(held_out) >= 5
    assert {i for i, f in held_out.items() if f.layer == "topology"} == HELD_OUT_TOPOLOGY
    assert {i for i, f in held_out.items() if f.layer == "results"} == HELD_OUT_RESULTS
    for fault in held_out.values():
        assert fault.held_out and fault.intended_tools == [], fault.id
        assert fault.needs_energyplus == (fault.layer == "results"), fault.id


def test_held_out_modules_sit_in_the_held_out_directory_and_cite_a_source() -> None:
    files = _registry().held_out_files()
    assert set(files) == HELD_OUT
    for fault_id, path in files.items():
        assert path.parent == EVAL_DIR / "faults" / "held_out", fault_id
        assert path.stem == fault_id
        source = path.read_text(encoding="utf-8")
        assert "**Source.**" in source and "http" in source, fault_id


def test_held_out_faults_do_not_repeat_a_designed_fault() -> None:
    designed = {e.fault.id for e in _registry().faults if not e.fault.held_out}
    assert designed and not designed & HELD_OUT


def test_tags_used_by_held_out_faults_exist_in_the_reference_models() -> None:
    tags = {t for m in _models() for t in m.tags}
    for fault in _held_out():
        assert fault.applies_to and set(fault.applies_to) <= tags, fault.id
        assert applicable_models(fault.applies_to, _models()), fault.id


def test_every_held_out_template_passes_the_template_lint() -> None:
    for fault in _held_out():
        assert lint_template(fault.prompt_template, fault_id=fault.id) == [], fault.id


@needs_models
def test_every_held_out_fault_has_applicable_installed_models() -> None:
    covered = {fault_id for fault_id, _ in _cases()}
    assert covered == HELD_OUT


# --- prompts and injection -----------------------------------------------------------------------------------------


@needs_models
@pytest.mark.parametrize(("fault_id", "model_id"), _cases())
def test_rendered_prompt_passes_the_lint(fault_id: str, model_id: str) -> None:
    fault = _registry().fault(fault_id)
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    values = {**default_prompt_values(doc), **injected.prompt_values}
    prompt = render_prompt(fault.prompt_template, values)
    assert injected.scope and injected.object_names and injected.field_names
    assert all(name.strip() for name in injected.object_names)
    violations = lint_prompt(
        prompt, object_names=injected.object_names, field_names=injected.field_names, fault_id=fault.id
    )
    assert violations == [], prompt


@needs_models
@pytest.mark.parametrize(("fault_id", "model_id"), _cases())
def test_injection_is_deterministic_and_changes_the_model(fault_id: str, model_id: str) -> None:
    from idfkit import write_idf

    fault = _registry().fault(fault_id)
    first_doc, second_doc = _fresh(model_id), _fresh(model_id)
    first, second = fault.inject(first_doc), fault.inject(second_doc)
    assert first == second
    assert write_idf(first_doc) == write_idf(second_doc)
    assert write_idf(first_doc) != write_idf(_original(_model(model_id).file))


# --- repairs ---------------------------------------------------------------------------------------------------------


def _restore_scope(doc: IDFDocument, original: IDFDocument, injected: InjectedFault) -> None:
    """Put every object in the fault's scope back as it was: removed objects are re-created, added ones removed."""
    for key in injected.scope:
        before = find(original, key.object_type, key.name)
        if before is None and key.name:
            after = find(doc, key.object_type, key.name)
            if after is not None:
                doc.removeidfobject(after)
            continue
        if before is None:
            before = sorted_objects(original, key.object_type)[0]
        after = find(doc, key.object_type, key.name) if key.name else sorted_objects(doc, key.object_type)[0]
        if after is None:
            doc.add(key.object_type, key.name, _fields(before), validate=False)
            continue
        for field_name in set(before.data) | set(after.data):
            after[field_name] = _fields(before).get(field_name)


def _fields(obj: Any) -> dict[str, Any]:
    return {k: ([dict(i) for i in v] if isinstance(v, list) else v) for k, v in obj.data.items()}


def _restore(doc: IDFDocument, model_id: str, injected: InjectedFault) -> None:
    _restore_scope(doc, _original(_model(model_id).file), injected)


def _define_the_missing_schedule(doc: IDFDocument, model_id: str, injected: InjectedFault) -> None:
    """The other way to repair a dangling reference: define an object under the name that is referenced."""
    lights = find(doc, "Lights", injected.details["object_name"])
    assert lights is not None
    doc.add("Schedule:Constant", text(lights, "schedule_name"), {"hourly_value": 0.9}, validate=False)


def _boiler_in_a_new_list(doc: IDFDocument, model_id: str, injected: InjectedFault) -> None:
    """Leave the emptied list alone: put the loop's boilers in a new list and point the scheme's range at it."""
    original = _original(_model(model_id).file)
    loop = find(doc, "PlantLoop", injected.details["loop"])
    assert loop is not None
    holder = find(doc, "PlantEquipmentOperationSchemes", text(loop, "plant_equipment_operation_scheme_name"))
    assert holder is not None
    emptied = {key.name.casefold() for key in injected.scope}
    for n in range(1, 9):
        scheme = find(doc, text(holder, f"control_scheme_{n}_object_type"), text(holder, f"control_scheme_{n}_name"))
        if scheme is None:
            continue
        for r in range(1, 11):
            field = f"range_{r}_equipment_list_name"
            if text(scheme, field).casefold() not in emptied:
                continue
            before = find(original, "PlantEquipmentList", text(scheme, field))
            assert before is not None
            new_name = f"{before.name} repaired"
            if find(doc, "PlantEquipmentList", new_name) is None:
                doc.add("PlantEquipmentList", new_name, {"equipment": items(before, "equipment")}, validate=False)
            scheme[field] = new_name


def _new_thermostat_for_the_zone(doc: IDFDocument, model_id: str, injected: InjectedFault) -> None:
    """Give the zone a thermostat of its own, under a new name, with the controls of the one it had."""
    original = _original(_model(model_id).file)
    zone = injected.details["zone"]
    before = next(
        t
        for t in sorted_objects(original, THERMOSTAT)
        if zone.casefold() in {z.casefold() for z in _zones_of(original, t)}
    )
    doc.add(THERMOSTAT, f"{zone} repaired", {**_fields(before), "zone_or_zonelist_name": zone}, validate=False)


def _zones_of(doc: IDFDocument, thermostat: Any) -> list[str]:
    from eval.support import expand_zones

    return expand_zones(doc, text(thermostat, "zone_or_zonelist_name"))


def _walls_adiabatic(doc: IDFDocument, model_id: str, injected: InjectedFault) -> None:
    for key in injected.scope:
        surface = find(doc, SURFACE, key.name)
        assert surface is not None
        surface["outside_boundary_condition"] = "Adiabatic"
        surface["outside_boundary_condition_object"] = ""
        surface["sun_exposure"] = "NoSun"
        surface["wind_exposure"] = "NoWind"


Repair = Callable[[IDFDocument, str, InjectedFault], None]

REPAIRS: dict[str, list[Repair]] = {
    "sizing_calculations_off": [_restore],
    "undefined_schedule_reference": [_restore, _define_the_missing_schedule],
    "boiler_not_in_operation_scheme": [_restore, _boiler_in_a_new_list],
    "zone_without_thermostat": [_restore, _new_thermostat_for_the_zone],
    "interior_walls_exposed_outdoors": [_restore, _walls_adiabatic],
}


def test_every_held_out_fault_has_a_repair_in_these_tests() -> None:
    assert set(REPAIRS) == HELD_OUT


@needs_models
@pytest.mark.parametrize(("fault_id", "model_id"), _cases())
def test_fault_is_detected_and_every_reasonable_repair_is_accepted(fault_id: str, model_id: str) -> None:
    fault = _registry().fault(fault_id)
    assert fault.verify(_fresh(model_id), None, fault.inject(_fresh(model_id))) is True  # the unmodified model passes
    for repair in REPAIRS[fault_id]:
        doc = _fresh(model_id)
        injected = fault.inject(doc)
        assert fault.verify(doc, None, injected) is False
        repair(doc, model_id, injected)
        assert fault.verify(doc, None, injected) is True, repair.__name__


# --- half repairs and wrong repairs are rejected -------------------------------------------------------------------


@needs_models
@pytest.mark.parametrize("model_id", [m for f, m in _cases({"sizing_calculations_off"})])
def test_sizing_needs_every_calculation_that_was_on(model_id: str) -> None:
    fault = _registry().fault("sizing_calculations_off")
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    switched = injected.details["switched_off"].split(",")
    control = sorted_objects(doc, "SimulationControl")[0]
    control[switched[0]] = "Yes"
    assert fault.verify(doc, None, injected) is (len(switched) == 1)
    doc.removeidfobject(control)
    assert fault.verify(doc, None, injected) is False


@needs_models
@pytest.mark.parametrize("model_id", [m for f, m in _cases({"undefined_schedule_reference"})])
def test_schedule_reference_must_resolve_to_a_lighting_like_schedule(model_id: str) -> None:
    fault = _registry().fault("undefined_schedule_reference")
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    lights = find(doc, "Lights", injected.details["object_name"])
    assert lights is not None
    doc.add("Schedule:Constant", "Always Off Repair", {"hourly_value": 0.0}, validate=False)
    lights["schedule_name"] = "Always Off Repair"
    assert fault.verify(doc, None, injected) is False  # lights that never come on are not a repair
    doc.add("Schedule:Constant", "Setpoint Repair", {"hourly_value": 21.0}, validate=False)
    lights["schedule_name"] = "Setpoint Repair"
    assert fault.verify(doc, None, injected) is False  # a temperature schedule is not a lighting schedule
    doc.removeidfobject(lights)
    assert fault.verify(doc, None, injected) is False  # deleting the object is not a repair


@needs_models
@pytest.mark.parametrize("model_id", [m for f, m in _cases({"boiler_not_in_operation_scheme"})])
def test_boiler_must_be_in_a_live_range_of_the_loop(model_id: str) -> None:
    fault = _registry().fault("boiler_not_in_operation_scheme")
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    # A list that nothing uses does not dispatch the boiler.
    emptied = find(_original(_model(model_id).file), "PlantEquipmentList", injected.scope[0].name)
    assert emptied is not None
    doc.add("PlantEquipmentList", "Unused repair list", {"equipment": items(emptied, "equipment")}, validate=False)
    assert fault.verify(doc, None, injected) is False


@needs_models
@pytest.mark.parametrize("model_id", [m for f, m in _cases({"zone_without_thermostat"})])
def test_thermostat_must_cover_the_zone_and_heat(model_id: str) -> None:
    fault = _registry().fault("zone_without_thermostat")
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    zone = injected.details["zone"]
    cooling = sorted_objects(doc, "ThermostatSetpoint:SingleCooling")
    if cooling:
        doc.add(
            THERMOSTAT,
            "Cooling only repair",
            {
                "zone_or_zonelist_name": zone,
                "control_type_schedule_name": "Any",
                "control_1_object_type": "ThermostatSetpoint:SingleCooling",
                "control_1_name": cooling[0].name,
            },
            validate=False,
        )
        assert fault.verify(doc, None, injected) is False  # the zone is cold: a cooling-only thermostat is no repair


@needs_models
@pytest.mark.parametrize("model_id", [m for f, m in _cases({"interior_walls_exposed_outdoors"})])
def test_interior_walls_need_both_sides_repaired(model_id: str) -> None:
    fault = _registry().fault("interior_walls_exposed_outdoors")
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    pairs = [p.split("\t") for p in injected.details["pairs"].split(";")]
    assert len(pairs) >= 2 and len(injected.scope) == 2 * len(pairs)
    original = _original(_model(model_id).file)
    for wall_name, _partner_name in pairs:  # one side of each pair only
        before, after = find(original, SURFACE, wall_name), find(doc, SURFACE, wall_name)
        assert before is not None and after is not None
        for field_name in ("outside_boundary_condition", "outside_boundary_condition_object"):
            after[field_name] = before.data.get(field_name)
    assert fault.verify(doc, None, injected) is False


# --- the symptom, shown by EnergyPlus --------------------------------------------------------------------------------

ZONE_TEMPERATURE = "Zone Mean Air Temperature"
BOILER_RATE = "Boiler Heating Rate"


def _simulate(doc: IDFDocument, tmp: str) -> SimulationResult:
    from idfkit.simulation import simulate

    run = doc.copy()
    for variable in (ZONE_TEMPERATURE, BOILER_RATE):
        fields = {"key_value": "*", "variable_name": variable, "reporting_frequency": "Hourly"}
        run.add("Output:Variable", "", fields, validate=False)
    return simulate(run, design_day=True, output_dir=tmp)


def _zone_minimum(result: SimulationResult, zone: str) -> float:
    assert result.sql is not None
    return min(result.sql.get_timeseries(ZONE_TEMPERATURE, zone.upper()).values)


def _variable_total(result: SimulationResult, variable: str) -> float:
    assert result.sql is not None
    rows = result.sql.query(
        "SELECT SUM(d.Value) FROM ReportData d JOIN ReportDataDictionary k"
        " ON k.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex WHERE k.Name = ?",
        (variable,),
    )
    total = rows[0][0]
    return float(total) if isinstance(total, int | float) else 0.0


def _design_heating_load(result: SimulationResult, zone: str) -> float:
    assert result.sql is not None
    rows = result.sql.get_tabular_data(
        report_name="HVACSizingSummary", table_name="Zone Sensible Heating", column_name="User Design Load"
    )
    return next(float(r.value) for r in rows if r.row_name.strip().casefold() == zone.casefold())


@needs_energyplus
@pytest.mark.parametrize(
    ("fault_id", "model_id"),
    [("sizing_calculations_off", "5ZoneAirCooledDemandLimiting"), ("undefined_schedule_reference", "DOAToPTAC")],
)
def test_topology_fault_stops_the_simulation_and_the_repair_runs(fault_id: str, model_id: str) -> None:
    fault = _registry().fault(fault_id)
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    with tempfile.TemporaryDirectory() as tmp:
        broken = _simulate(doc, tmp)
        assert not simulated(broken)
        broken.close()
    _restore(doc, model_id, injected)
    with tempfile.TemporaryDirectory() as tmp:
        repaired = _simulate(doc, tmp)
        assert simulated(repaired)
        repaired.close()


@needs_energyplus
def test_boiler_fault_leaves_the_boiler_idle_and_the_zone_cold() -> None:
    fault = _registry().fault("boiler_not_in_operation_scheme")
    model_id = "5ZoneAirCooled"
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    zone = injected.prompt_values["zone"]
    with tempfile.TemporaryDirectory() as tmp:
        broken = _simulate(doc, tmp)
        assert simulated(broken)  # nothing stops the run: the symptom is in the results
        assert _variable_total(broken, BOILER_RATE) == 0.0
        cold = _zone_minimum(broken, zone)
        assert fault.verify(doc, broken, injected) is False
        broken.close()
    _restore(doc, model_id, injected)
    with tempfile.TemporaryDirectory() as tmp:
        repaired = _simulate(doc, tmp)
        assert _variable_total(repaired, BOILER_RATE) > 0.0
        assert _zone_minimum(repaired, zone) - cold > 3.0
        assert fault.verify(doc, repaired, injected) is True
        repaired.close()


@needs_energyplus
def test_zone_without_thermostat_floats_cold() -> None:
    fault = _registry().fault("zone_without_thermostat")
    model_id = "5ZoneAirCooled"
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    zone = injected.prompt_values["zone"]
    with tempfile.TemporaryDirectory() as tmp:
        broken = _simulate(doc, tmp)
        assert simulated(broken)
        cold = _zone_minimum(broken, zone)
        assert fault.verify(doc, broken, injected) is False
        broken.close()
    _new_thermostat_for_the_zone(doc, model_id, injected)
    with tempfile.TemporaryDirectory() as tmp:
        repaired = _simulate(doc, tmp)
        assert _zone_minimum(repaired, zone) - cold > 3.0
        assert fault.verify(doc, repaired, injected) is True
        repaired.close()


@needs_energyplus
def test_exposed_interior_walls_multiply_the_design_heating_load() -> None:
    fault = _registry().fault("interior_walls_exposed_outdoors")
    model_id = "5ZoneCoolBeam"
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    zone = injected.details["zone"]
    with tempfile.TemporaryDirectory() as tmp:
        broken = _simulate(doc, tmp)
        assert simulated(broken)
        exposed_load = _design_heating_load(broken, zone)
        exposed_boiler = _variable_total(broken, BOILER_RATE)
        assert fault.verify(doc, broken, injected) is False
        broken.close()
    _restore(doc, model_id, injected)
    with tempfile.TemporaryDirectory() as tmp:
        repaired = _simulate(doc, tmp)
        assert exposed_load > 2.0 * _design_heating_load(repaired, zone)
        assert exposed_boiler > 1.5 * _variable_total(repaired, BOILER_RATE)
        assert fault.verify(doc, repaired, injected) is True
        repaired.close()


@needs_energyplus
def test_a_repair_that_does_not_simulate_is_not_a_fix() -> None:
    fault = _registry().fault("zone_without_thermostat")
    model_id = "5ZoneAirCooled"
    doc = _fresh(model_id)
    injected = fault.inject(doc)
    _new_thermostat_for_the_zone(doc, model_id, injected)
    assert fault.verify(doc, None, injected) is True
    control = sorted_objects(doc, "SimulationControl")[0]
    for flag in ("do_zone_sizing_calculation", "do_system_sizing_calculation", "do_plant_sizing_calculation"):
        control[flag] = "No"
    with tempfile.TemporaryDirectory() as tmp:
        failed = _simulate(doc, tmp)
        assert fault.verify(doc, failed, injected) is False
        failed.close()
