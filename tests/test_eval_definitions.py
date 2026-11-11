"""The evaluation harness's fault types and task specs (tasks T068 to T072).

Reference models are loaded from the installed EnergyPlus ExampleFiles (26.1 here; the evaluation targets 26.2);
tests that need them skip when they are absent, and tests that simulate skip without EnergyPlus.
"""

from __future__ import annotations

import importlib
import math
import tempfile
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from idfkit import IDFDocument, load_idf

from eval import answers
from eval.answer_keys import compute_keys, load_committed, question_specs
from eval.config import ReferenceModel, load_prompt_templates, load_reference_models
from eval.lint import lint_prompt, lint_template
from eval.model import FaultType, InjectedFault, TaskSpec
from eval.registry import EVAL_DIR, MAX_MODELS_PER_TYPE, Registry, applicable_models, discover
from eval.support import (
    default_prompt_values,
    find,
    items,
    loop_branch_nodes,
    mentions,
    plant_side,
    render_prompt,
    same,
    set_items,
    text,
)

DESIGNED_TOPOLOGY = {
    "outlet_node_typo",
    "swapped_inlet_outlet",
    "branch_missing_from_list",
    "setpoint_on_unused_node",
    "terminal_outlet_not_zone_inlet",
    "water_coil_wrong_plant_side",
}
DESIGNED_RESULTS = {
    "undersized_reheat_coil",
    "wrong_heating_setpoint_schedule",
    "uninsulated_exterior_wall",
    "packaged_unit_availability_off",
}
AUTHORING = {"add_reheat_coil", "add_parallel_chiller", "add_vav_zone", "cv_to_vav_fan"}
QUESTIONS = {
    "plant_loop_of_reheat_coil",
    "zones_of_air_loop",
    "plant_loop_of_cooling_coil",
    "hot_water_coil_count",
    "largest_design_heating_load",
    "boiler_design_capacity",
}


def _example_files() -> Path | None:
    try:
        from idfkit.simulation.config import find_energyplus

        candidate = find_energyplus().install_dir / "ExampleFiles"
    except Exception:
        candidate = Path("/usr/local/EnergyPlus-26-1-0/ExampleFiles")
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


def _fresh(model: ReferenceModel) -> IDFDocument:
    return _original(model.file).copy()


def _designed() -> list[FaultType]:
    return [e.fault for e in _registry().faults if not e.fault.held_out]


def _fault_cases(ids: set[str]) -> list[tuple[str, str]]:
    if EXAMPLE_FILES is None:
        return []
    return [(f.id, m.id) for f in _designed() if f.id in ids for m in applicable_models(f.applies_to, _available())]


def _model(model_id: str) -> ReferenceModel:
    return next(m for m in _models() if m.id == model_id)


def _task_module(kind: str, task_id: str) -> ModuleType:
    folder = "authoring" if kind == "authoring" else "questions"
    return importlib.import_module(f"eval.tasks.{folder}.{task_id}")


# --- discovery and counts ------------------------------------------------------------------------------------------


def test_discovery_finds_the_designed_faults_and_tasks() -> None:
    registry = _registry()
    designed = {f.id: f for f in _designed()}
    assert set(designed) == DESIGNED_TOPOLOGY | DESIGNED_RESULTS
    assert {i for i, f in designed.items() if f.layer == "topology"} == DESIGNED_TOPOLOGY
    assert {i for i, f in designed.items() if f.layer == "results"} == DESIGNED_RESULTS
    assert all(f.needs_energyplus == (f.layer == "results") for f in designed.values())
    assert all(f.intended_tools and f.applies_to for f in designed.values())
    kinds: dict[str, set[str]] = {}
    for spec in registry.tasks:
        kinds.setdefault(spec.kind, set()).add(spec.id)
    assert kinds["authoring"] == AUTHORING
    assert kinds["question"] == QUESTIONS
    assert kinds["control"]
    for spec in registry.tasks:
        assert spec.prompt_values is not None, spec.id
        if spec.kind == "authoring":
            assert spec.needs_energyplus and spec.verify is not None
        if spec.kind == "question":
            assert spec.answer_key is not None and spec.verify is not None


def test_tags_used_by_definitions_exist_in_the_reference_models() -> None:
    tags = {t for m in _models() for t in m.tags}
    used = {t for f in _designed() for t in f.applies_to} | {t for s in _registry().tasks for t in s.applies_to}
    assert used <= tags


def test_at_least_one_control_per_five_fault_tasks_overall_and_per_layer() -> None:
    models = _models()
    faults: dict[str, int] = {"topology": 0, "results": 0}
    controls: dict[str, int] = {"topology": 0, "results": 0}
    for entry in _registry().faults:
        faults[entry.fault.layer] += len(applicable_models(entry.fault.applies_to, models, cap=MAX_MODELS_PER_TYPE))
    for spec in _registry().tasks:
        if spec.kind == "control":
            controls[spec.layer] += len(applicable_models(spec.applies_to, models, cap=MAX_MODELS_PER_TYPE))
    assert sum(controls.values()) * 5 >= sum(faults.values())
    for layer in faults:
        assert controls[layer] * 5 >= faults[layer], layer


def test_control_templates_are_prompt_templates_and_controls_have_no_tools() -> None:
    templates = set(load_prompt_templates(EVAL_DIR / "prompts.toml").values())
    for spec in _registry().tasks:
        if spec.kind == "control":
            assert spec.prompt_template in templates, spec.id
            assert spec.intended_tools == [] and spec.verify is None


def test_every_template_passes_the_template_lint() -> None:
    for fault in _designed():
        assert lint_template(fault.prompt_template, fault_id=fault.id) == [], fault.id
    for spec in _registry().tasks:
        assert lint_template(spec.prompt_template) == [], spec.id


# --- rendered prompts ------------------------------------------------------------------------------------------------


@needs_models
@pytest.mark.parametrize(("fault_id", "model_id"), _fault_cases(DESIGNED_TOPOLOGY | DESIGNED_RESULTS))
def test_fault_prompt_passes_the_lint_after_injection(fault_id: str, model_id: str) -> None:
    fault = _registry().fault(fault_id)
    doc = _fresh(_model(model_id))
    injected = fault.inject(doc)
    values = {**default_prompt_values(doc), **injected.prompt_values}
    prompt = render_prompt(fault.prompt_template, values)
    assert injected.object_names and injected.field_names and injected.scope
    violations = lint_prompt(
        prompt, object_names=injected.object_names, field_names=injected.field_names, fault_id=fault.id
    )
    assert violations == [], prompt


@needs_models
def test_every_task_prompt_renders_and_passes_the_lint() -> None:
    for spec in _registry().tasks:
        for model in applicable_models(spec.applies_to, _available()):
            doc = _original(model.file)
            values = spec.prompt_values(doc) if spec.prompt_values is not None else {}
            prompt = render_prompt(spec.prompt_template, values)
            assert lint_prompt(prompt) == [], (spec.id, model.id, prompt)


@needs_models
def test_injection_is_deterministic() -> None:
    model = _model("5ZoneAirCooled")
    for fault in _designed():
        if not applicable_models(fault.applies_to, [model]):
            continue
        first, second = fault.inject(_fresh(model)), fault.inject(_fresh(model))
        assert first == second, fault.id


# --- topology faults: inject, verify, repair -------------------------------------------------------------------------


def _restore_scope(doc: IDFDocument, original: IDFDocument, injected: InjectedFault) -> None:
    """The repair that puts every object in the fault's scope back as it was."""
    for key in injected.scope:
        before = find(original, key.object_type, key.name)
        after = find(doc, key.object_type, key.name)
        if before is None or after is None:
            continue
        for field_name in set(before.data) | set(after.data):
            value: Any = before.data.get(field_name)
            after[field_name] = [dict(i) for i in value] if isinstance(value, list) else value


def _rename_everywhere(doc: IDFDocument, old: str, new: str) -> None:
    """The repair a ``rename_node`` makes: every field holding ``old`` now holds ``new``."""
    for obj in mentions(doc, old):
        for field_name, value in list(obj.data.items()):
            if isinstance(value, str) and same(value, old):
                obj[field_name] = new
            elif isinstance(value, list):
                fixed = [
                    {k: (new if isinstance(v, str) and same(v, old) else v) for k, v in dict(i).items()}
                    for i in items(obj, field_name)
                ]
                set_items(obj, field_name, fixed)


def _readd_branch_first(doc: IDFDocument, injected: InjectedFault) -> None:
    side = plant_side(doc, injected.details["loop"], "demand")
    assert side is not None
    branch_list = find(doc, "BranchList", side.branch_list)
    assert branch_list is not None
    entries = items(branch_list, "branches")
    set_items(branch_list, "branches", [entries[0], {"branch_name": injected.details["branch"]}, *entries[1:]])


def _setpoint_on_other_branch_node(doc: IDFDocument, injected: InjectedFault) -> None:
    spm = find(doc, injected.details["object_type"], injected.details["object_name"])
    assert spm is not None
    nodes = sorted(loop_branch_nodes(doc)[injected.details["loop"].casefold()])
    spm["setpoint_node_or_nodelist_name"] = nodes[0]


def _zone_inlet_to_new_node(doc: IDFDocument, injected: InjectedFault) -> None:
    _rename_everywhere(doc, injected.details["original"], injected.details["moved_to"])


ALTERNATIVE_REPAIRS: dict[str, Callable[[IDFDocument, InjectedFault], None]] = {
    "outlet_node_typo": lambda doc, inj: _rename_everywhere(doc, inj.details["original"], inj.details["typo"]),
    "branch_missing_from_list": _readd_branch_first,
    "setpoint_on_unused_node": _setpoint_on_other_branch_node,
    "terminal_outlet_not_zone_inlet": _zone_inlet_to_new_node,
}


@needs_models
@pytest.mark.parametrize(("fault_id", "model_id"), _fault_cases(DESIGNED_TOPOLOGY))
def test_topology_fault_is_detected_and_a_repair_is_accepted(fault_id: str, model_id: str) -> None:
    fault = _registry().fault(fault_id)
    model = _model(model_id)
    doc = _fresh(model)
    injected = fault.inject(doc)
    assert fault.verify(doc, None, injected) is False

    _restore_scope(doc, _original(model.file), injected)
    assert fault.verify(doc, None, injected) is True

    alternative = ALTERNATIVE_REPAIRS.get(fault_id)
    if alternative is not None:
        other = _fresh(model)
        injected_again = fault.inject(other)
        alternative(other, injected_again)
        assert fault.verify(other, None, injected_again) is True


@needs_models
def test_outlet_typo_half_repair_is_rejected() -> None:
    fault = _registry().fault("outlet_node_typo")
    doc = _fresh(_model("5ZoneAirCooled"))
    injected = fault.inject(doc)
    branch = find(doc, "Branch", injected.details["branch"])
    assert branch is not None
    comps = items(branch, "components")
    for comp in comps:
        if same(str(comp["component_name"]), injected.details["object_name"]):
            comp["component_outlet_node_name"] = injected.details["typo"]
    set_items(branch, "components", comps)
    assert fault.verify(doc, None, injected) is False


# --- results faults ----------------------------------------------------------------------------------------------------


@needs_models
@pytest.mark.parametrize(("fault_id", "model_id"), _fault_cases(DESIGNED_RESULTS))
def test_results_fault_is_detected_and_restoring_it_is_accepted(fault_id: str, model_id: str) -> None:
    fault = _registry().fault(fault_id)
    model = _model(model_id)
    doc = _fresh(model)
    injected = fault.inject(doc)
    assert fault.verify(doc, None, injected) is False
    _restore_scope(doc, _original(model.file), injected)
    assert fault.verify(doc, None, injected) is True


@needs_energyplus
def test_undersized_reheat_coil_verify_reads_the_simulation() -> None:
    from idfkit.simulation import simulate

    fault = _registry().fault("undersized_reheat_coil")
    model = _model("5ZoneAirCooled")
    doc = _fresh(model)
    injected = fault.inject(doc)
    with tempfile.TemporaryDirectory() as tmp:
        result = simulate(doc, design_day=True, output_dir=tmp)
        assert fault.verify(doc, result, injected) is False
    terminal = find(doc, injected.details["terminal_type"], injected.details["terminal"])
    assert terminal is not None
    coil = find(doc, text(terminal, "reheat_coil_object_type"), text(terminal, "reheat_coil_name"))
    assert coil is not None
    coil["u_factor_times_area_value"] = 60.0
    coil["maximum_water_flow_rate"] = 1e-5  # still far below the terminal's design reheat flow
    with tempfile.TemporaryDirectory() as tmp:
        result = simulate(doc, design_day=True, output_dir=tmp)
        assert fault.verify(doc, result, injected) is False
    _restore_scope(doc, _original(model.file), injected)
    with tempfile.TemporaryDirectory() as tmp:
        result = simulate(doc, design_day=True, output_dir=tmp)
        assert fault.verify(doc, result, injected) is True


# --- authoring tasks ---------------------------------------------------------------------------------------------------


def _authoring_cases() -> list[tuple[str, str]]:
    if EXAMPLE_FILES is None:
        return []
    return [
        (s.id, m.id)
        for s in _registry().tasks
        if s.kind == "authoring"
        for m in applicable_models(s.applies_to, _available())
    ]


@needs_models
@pytest.mark.parametrize(("task_id", "model_id"), _authoring_cases())
def test_authoring_goal_is_not_met_by_the_unmodified_model(task_id: str, model_id: str) -> None:
    spec = _registry().task(task_id)
    module = _task_module("authoring", task_id)
    doc = _original(_model(model_id).file)
    assert module.goal_met(doc) is False
    assert spec.verify is not None and spec.verify(doc, None, None) is False


def _replace_cv_fan(doc: IDFDocument, new_fan: str, loop_name: str) -> None:
    from eval.support import air_loop_branches

    loop = find(doc, "AirLoopHVAC", loop_name)
    assert loop is not None
    for branch in air_loop_branches(doc, loop):
        comps = items(branch, "components")
        for comp in comps:
            if not same(str(comp["component_object_type"]), "Fan:ConstantVolume"):
                continue
            cv = find(doc, "Fan:ConstantVolume", str(comp["component_name"]))
            assert cv is not None
            doc.add(
                "Fan:VariableVolume",
                new_fan,
                {
                    "availability_schedule_name": text(cv, "availability_schedule_name"),
                    "fan_total_efficiency": cv.data.get("fan_total_efficiency", 0.7),
                    "pressure_rise": cv.data.get("pressure_rise", 600.0),
                    "maximum_flow_rate": cv.data.get("maximum_flow_rate", "autosize"),
                    "fan_power_minimum_flow_rate_input_method": "Fraction",
                    "fan_power_minimum_flow_fraction": 0.25,
                    "motor_efficiency": cv.data.get("motor_efficiency", 0.9),
                    "motor_in_airstream_fraction": 1.0,
                    "fan_power_coefficient_1": 0.0015302446,
                    "fan_power_coefficient_2": 0.0052080574,
                    "fan_power_coefficient_3": 1.1086242,
                    "fan_power_coefficient_4": -0.11635563,
                    "fan_power_coefficient_5": 0.0,
                    "air_inlet_node_name": text(cv, "air_inlet_node_name"),
                    "air_outlet_node_name": text(cv, "air_outlet_node_name"),
                },
                validate=False,
            )
            comp["component_object_type"] = "Fan:VariableVolume"
            comp["component_name"] = new_fan
            doc.removeidfobject(cv)
        set_items(branch, "components", comps)


@needs_energyplus
def test_cv_to_vav_fan_succeeds_when_the_fan_is_replaced_and_the_model_simulates() -> None:
    from idfkit.simulation import simulate

    spec = _registry().task("cv_to_vav_fan")
    module = _task_module("authoring", "cv_to_vav_fan")
    doc = _fresh(_model("CVRhMinHum"))
    values = module.prompt_values(doc)
    _replace_cv_fan(doc, values["new_fan"], values["air_loop"])
    assert module.goal_met(doc) is True
    assert spec.verify is not None
    assert spec.verify(doc, None, None) is False  # no simulation result: "simulates" is not established
    with tempfile.TemporaryDirectory() as tmp:
        result = simulate(doc, design_day=True, output_dir=tmp)
        assert spec.verify(doc, result, None) is True


# --- open questions ----------------------------------------------------------------------------------------------------


@needs_models
def test_committed_answer_keys_match_recomputation() -> None:
    assert EXAMPLE_FILES is not None
    energyplus = _energyplus_available()
    for spec in question_specs():
        committed = load_committed(spec)
        assert committed, f"{spec.id}: no committed keys"
        if spec.needs_energyplus and not energyplus:
            continue
        assert compute_keys(spec, _models(), EXAMPLE_FILES) == committed, spec.id


def _question_cases() -> Iterator[tuple[TaskSpec, ReferenceModel]]:
    for spec in _registry().tasks:
        if spec.kind == "question":
            for model in applicable_models(spec.applies_to, _available()):
                yield spec, model


@needs_models
def test_question_verify_accepts_the_key_and_rejects_wrong_answers() -> None:
    energyplus = _energyplus_available()
    for spec, model in _question_cases():
        if spec.needs_energyplus and not energyplus:
            continue
        assert spec.verify is not None
        doc = _original(model.file)
        key = load_committed(spec)[model.id]
        assert spec.verify(doc, None, f"The answer is {key}.") is True, (spec.id, model.id)
        assert spec.verify(doc, None, "I could not find out.") is False, (spec.id, model.id)
        assert spec.verify(doc, None, None) is False


@needs_models
def test_name_questions_reject_an_answer_that_lists_every_candidate() -> None:
    for spec_id in ("plant_loop_of_reheat_coil", "plant_loop_of_cooling_coil"):
        spec = _registry().task(spec_id)
        doc = _original(_model("5ZoneAirCooled").file)
        loops = [o.name for t in ("PlantLoop", "CondenserLoop") for o in doc.get_collection(t)]
        assert spec.verify is not None
        assert spec.verify(doc, None, "It could be " + " or ".join(loops)) is False


@needs_models
def test_zone_set_question_needs_exactly_the_served_zones() -> None:
    spec = _registry().task("zones_of_air_loop")
    doc = _original(_model("5ZoneAirCooled").file)
    assert spec.verify is not None
    assert spec.verify(doc, None, "SPACE1-1, SPACE2-1, SPACE3-1, SPACE4-1 and SPACE5-1.") is True
    assert spec.verify(doc, None, "SPACE1-1, SPACE2-1, SPACE3-1 and SPACE4-1.") is False
    assert spec.verify(doc, None, "SPACE1-1 to SPACE5-1 and PLENUM-1.") is False


# --- answer normalisation ----------------------------------------------------------------------------------------------


def test_mentions_respect_name_boundaries_and_nesting() -> None:
    assert answers.mentioned("**SPACE1-10** is cold", ["SPACE1-1", "SPACE1-10"]) == {"SPACE1-10"}
    assert answers.mentioned("the `Hot Water Loop`", ["Water Loop", "Hot Water Loop"]) == {"Hot Water Loop"}
    assert answers.mentioned("zone   1 and Zone 2", ["Zone 1", "Zone 2", "Zone 10"]) == {"Zone 1", "Zone 2"}


def test_single_name_and_set_matching() -> None:
    loops = ["Hot Water Loop", "Chilled Water Loop"]
    assert answers.single_name_matches("It is the hot water loop.", "Hot Water Loop", loops)
    assert not answers.single_name_matches("Hot Water Loop or Chilled Water Loop", "Hot Water Loop", loops)
    assert answers.name_set_matches("None of them.", [], ["A1", "B1"])
    assert not answers.name_set_matches("A1", [], ["A1", "B1"])
    assert answers.split_key(answers.join_key(["b", "A"])) == ["A", "b"]


def test_first_number_skips_names_and_reads_words_and_separators() -> None:
    assert answers.first_number("Loop 2 has seven coils", ignore=["Loop 2"]) == 7.0
    assert answers.first_number("about 27,012 W") == 27012.0
    assert answers.first_number("SPACE1-1 needs 3.9 kW", ignore=["SPACE1-1"]) == 3.9
    assert answers.first_number("no number here") is None
    assert math.isclose(answers.first_number("-1.5") or 0.0, -1.5)
