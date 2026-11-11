"""Tests of the evaluation harness skeleton (eval/), with no LLM and no agent runner (T033)."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from eval import __main__ as cli
from eval.conditions import build_conditions, parse_command
from eval.config import (
    BaselineConfig,
    ConfigError,
    ReferenceModel,
    load_baseline,
    load_prompt_templates,
    load_reference_models,
    load_runner,
)
from eval.diff import ModelDiff, diff, false_fix, first_edit_target, reported_fault, snapshot, unwanted_changes
from eval.execute import MODEL_NOTE
from eval.held_out import CHECKS_PATH, GitError, check_held_out, first_commit_adding
from eval.lint import PromptLintError, check_prompt, lint_prompt, lint_template
from eval.model import (
    BaselineKind,
    Comparison,
    EvaluationRun,
    EvaluationTask,
    FaultType,
    GateVerdict,
    InjectedFault,
    Metric,
    ObjectKey,
    TaskOutcome,
    TaskSpec,
    load_run,
    make_task_id,
    save_run,
    split_task_id,
)
from eval.parsers import ParsedTranscript, ToolCall, claude_stream_json, get_parser
from eval.registry import (
    EVAL_DIR,
    PlannedTask,
    Registry,
    applicable_models,
    discover,
    plan_tasks,
    select,
    task_infos,
)
from eval.runner import ServerCommand, build_argv, run_agent, write_mcp_config
from eval.stats import (
    TaskInfo,
    bootstrap_interval,
    compare,
    gate_verdict,
    layer_gate,
    metric_value,
    repeat_spread,
    scoped_comparisons,
)

SYMPTOM = "The simulation of this model fails. Make it run."
GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")


# --- helpers -----------------------------------------------------------------------------------------------------


def _outcome(task_id: str, condition: str, repeat: int = 0, **overrides: object) -> TaskOutcome:
    data: dict[str, object] = {
        "task_id": task_id,
        "condition": condition,
        "repeat": repeat,
        "fixed": False,
        "verified_by": "check",
        "skip_reason": None,
        "tool_calls": 10,
        "response_tokens": 1000,
        "unwanted_changes": 0,
        "false_fix": False,
        "tools_used": [],
        "intended_tool_used": None,
        "top_candidate_edited": None,
        "top_candidate_correct": None,
        "transcript_path": f"transcripts/{task_id}-{condition}-{repeat}.jsonl",
    }
    data.update(overrides)
    return TaskOutcome.from_dict(data)


def _cmp(metric: Metric, difference: float, ci: tuple[float, float], baseline: float = 0.5) -> Comparison:
    return Comparison(
        scope="topology",
        metric=metric,
        tasks=10,
        baseline=baseline,
        treatment=baseline + difference,
        difference=difference,
        ci_low=ci[0],
        ci_high=ci[1],
        descriptive_only=False,
    )


def _run(outcomes: Sequence[TaskOutcome] = (), **overrides: object) -> EvaluationRun:
    data: dict[str, object] = {
        "run_id": "r1",
        "started_at": "2026-11-11T00:00:00+00:00",
        "runner_command": "claude -p {prompt}",
        "model_identifier": "test-model",
        "baseline_kind": "pre_feature",
        "baseline_sha": "81d3cd6",
        "baseline_idfkit": "idfkit==1.2.0",
        "treatment_revision": "abc1234",
        "disallowed_tools": [],
        "repeats": 3,
        "bootstrap_seed": 7,
        "bootstrap_resamples": 500,
    }
    data.update(overrides)
    return EvaluationRun.from_dict(data, outcomes)


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    assert GIT is not None
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    if date is not None:
        env["GIT_COMMITTER_DATE"] = date
        env["GIT_AUTHOR_DATE"] = date
    subprocess.run([GIT, "-C", str(repo), *args], check=True, capture_output=True, env=env)  # noqa: S603


def _git_out(repo: Path, *args: str) -> str:
    assert GIT is not None
    done = subprocess.run([GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True)  # noqa: S603
    return done.stdout.strip()


def _commit_file(repo: Path, rel: str, content: str, date: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", f"add {rel}", date=date)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    return path


FAULT_MODULE = textwrap.dedent(
    """
    from __future__ import annotations

    from eval.model import FaultType, InjectedFault


    def _inject(doc: object) -> InjectedFault:
        return InjectedFault(scope=[])


    def _verify(doc: object, result: object, injected: InjectedFault) -> bool:
        return True


    FAULT = FaultType(
        id={fault_id!r},
        layer={layer!r},
        description="for tests",
        held_out={held_out!r},
        applies_to=["air_loop"],
        intended_tools=[],
        prompt_template={template!r},
        needs_energyplus={needs_ep!r},
        inject=_inject,
        verify=_verify,
    )
    """
)

AUTHORING_MODULE = textwrap.dedent(
    """
    from __future__ import annotations

    from eval.model import TaskSpec


    def _verify(doc: object, result: object, answer: str | None) -> bool:
        return True


    TASK = TaskSpec(
        id="add_reheat_coil",
        kind="authoring",
        layer="topology",
        applies_to=["vav_reheat"],
        prompt_template="Add a hot-water reheat coil to the terminal unit serving zone {zone}.",
        intended_tools=["trace_hvac"],
        needs_energyplus=True,
        verify=_verify,
    )
    """
)

CONTROLS = textwrap.dedent(
    """
    [[tasks]]
    id = "control_review"
    layer = "topology"
    applies_to = ["air_loop"]
    prompt_template = "Check that the HVAC system of this model is set up correctly."
    """
)


def _write_fault(
    eval_dir: Path,
    fault_id: str,
    *,
    held_out: bool = False,
    layer: str = "topology",
    template: str = SYMPTOM,
    needs_ep: bool = False,
) -> Path:
    directory = eval_dir / "faults" / ("held_out" if held_out else "")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{fault_id}.py"
    path.write_text(
        FAULT_MODULE.format(fault_id=fault_id, layer=layer, held_out=held_out, template=template, needs_ep=needs_ep),
        encoding="utf-8",
    )
    return path


def _make_eval_dir(root: Path) -> Path:
    eval_dir = root / "evaldefs"
    _write_fault(eval_dir, "typo_outlet")
    _write_fault(eval_dir, "undersized_coil", layer="results", needs_ep=True)
    (eval_dir / "tasks" / "authoring").mkdir(parents=True)
    (eval_dir / "tasks" / "authoring" / "add_reheat_coil.py").write_text(AUTHORING_MODULE, encoding="utf-8")
    (eval_dir / "tasks" / "controls.toml").write_text(CONTROLS, encoding="utf-8")
    return eval_dir


def _models() -> list[ReferenceModel]:
    return [
        ReferenceModel(id="a", file="a.idf", version="26.2", tags=["air_loop", "vav_reheat"]),
        ReferenceModel(id="b", file="b.idf", version="26.2", tags=["air_loop"]),
        ReferenceModel(id="c", file="c.idf", version="26.2", tags=["packaged_unit"]),
    ]


def _example_files(root: Path, names: Sequence[str] = ("a.idf", "b.idf", "c.idf")) -> Path:
    directory = root / "ExampleFiles"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("Version,26.2;\n", encoding="utf-8")
    return directory


# --- model ---------------------------------------------------------------------------------------------------------


def test_object_key_compares_case_insensitively() -> None:
    assert ObjectKey("Zone", "SPACE1-1") == ObjectKey("zone", "space1-1")
    assert len({ObjectKey("Zone", "A"), ObjectKey("ZONE", "a")}) == 1


def test_task_outcome_requires_skip_reason_when_skipped() -> None:
    with pytest.raises(ValueError, match="skip_reason"):
        _outcome("f@m", "treatment", verified_by="skipped")
    skipped = _outcome("f@m", "treatment", verified_by="skipped", skip_reason="EnergyPlus not found")
    assert skipped.skipped


def test_task_outcome_rejects_bad_literals_and_negative_repeat() -> None:
    with pytest.raises(ValueError, match="condition"):
        _outcome("f@m", "control")
    with pytest.raises(ValueError, match="0-based"):
        _outcome("f@m", "baseline", repeat=-1)


def test_evaluation_run_needs_three_repeats_and_derives_ablation() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        _run(repeats=2)
    assert not _run().ablation
    assert _run(disallowed_tools=["trace_hvac"]).ablation


def test_run_round_trips_through_run_dir(tmp_path: Path) -> None:
    outcomes = [_outcome("f@m", "baseline"), _outcome("f@m", "treatment", fixed=True, tools_used=["trace_hvac"])]
    run = _run(outcomes, held_out_invalid=["late_fault"])
    save_run(run, tmp_path / "run")
    loaded = load_run(tmp_path / "run")
    assert loaded == run
    assert '"ablation": false' in (tmp_path / "run" / "run.json").read_text(encoding="utf-8")


def test_task_ids_round_trip() -> None:
    assert split_task_id(make_task_id("outlet_node_typo", "5ZoneAirCooled")) == ("outlet_node_typo", "5ZoneAirCooled")
    with pytest.raises(ValueError):
        make_task_id("a@b", "m")


def test_evaluation_task_fault_id_only_for_fault_tasks() -> None:
    with pytest.raises(ValueError, match="fault_id"):
        EvaluationTask("t", "control", "f", "m.idf", SYMPTOM, None, "no change", [])


def test_task_spec_requires_verifier_for_authoring_and_key_for_questions() -> None:
    with pytest.raises(ValueError, match="verify"):
        TaskSpec("a", "authoring", "topology", ["air_loop"], SYMPTOM, [], True)
    with pytest.raises(ValueError, match="answer_key"):
        TaskSpec("q", "question", "topology", ["air_loop"], SYMPTOM, [], False, verify=lambda d, r, a: True)


def test_fault_effective_scope_unions_static_and_injected() -> None:
    fault = FaultType(
        id="x",
        layer="topology",
        description="",
        held_out=False,
        applies_to=["air_loop"],
        intended_tools=[],
        prompt_template=SYMPTOM,
        needs_energyplus=False,
        inject=lambda doc: InjectedFault(scope=[]),
        verify=lambda doc, result, injected: True,
        scope=[ObjectKey("BRANCH", "b1")],
    )
    injected = InjectedFault(scope=[ObjectKey("Branch", "B1"), ObjectKey("Node", "N1")])
    assert fault.effective_scope(injected) == [ObjectKey("branch", "b1"), ObjectKey("Node", "N1")]


def test_held_out_fault_has_no_intended_tools() -> None:
    with pytest.raises(ValueError, match="intended_tools"):
        FaultType(
            id="x",
            layer="results",
            description="",
            held_out=True,
            applies_to=[],
            intended_tools=["trace_hvac"],
            prompt_template=SYMPTOM,
            needs_energyplus=False,
            inject=lambda doc: InjectedFault(scope=[]),
            verify=lambda doc, result, injected: True,
        )


# --- committed configuration ---------------------------------------------------------------------------------------


def test_baseline_pins_the_pre_feature_revision() -> None:
    baseline = load_baseline(EVAL_DIR / "baseline.toml")
    assert (baseline.kind, baseline.idfkit_mcp_sha, baseline.idfkit) == ("pre_feature", "81d3cd6", "idfkit==1.2.0")


def test_runner_config_matches_contract() -> None:
    runner = load_runner(EVAL_DIR / "runners" / "claude_code.toml")
    assert runner.name == "claude-code-headless"
    assert runner.command == [
        "claude", "-p", "{prompt}", "--mcp-config", "{mcp_config}", "--strict-mcp-config",
        "--allowedTools", "mcp__idfkit", "--output-format", "stream-json", "--verbose",
    ]  # fmt: skip
    assert runner.max_turns == 40
    assert (runner.max_turns_flag, runner.model_flag, runner.timeout_seconds) == ("--max-turns", "--model", 1800)
    assert runner.parse == "claude_stream_json"
    assert runner.disallowed_tools == []
    assert runner.disallowed_flag == "--disallowedTools"
    assert not runner.ablation


def test_reference_models_cover_the_required_systems() -> None:
    models = load_reference_models(EVAL_DIR / "reference_models.toml")
    assert len(models) >= 20
    assert {m.version for m in models} == {"26.2"}
    tags = {tag for m in models for tag in m.tags}
    assert {"vav_reheat", "chilled_water", "hot_water", "packaged_unit", "zone_list", "hvac_template"} <= tags


def test_reference_model_files_exist_in_installed_example_files() -> None:
    install = cli.find_energyplus_dir(None)
    if install is None or not (install / "ExampleFiles").is_dir():
        pytest.skip("EnergyPlus ExampleFiles not found")
    missing = [m.file for m in load_reference_models(EVAL_DIR / "reference_models.toml")
               if not (install / "ExampleFiles" / m.file).is_file()]  # fmt: skip
    assert missing == []


def test_committed_prompt_templates_pass_the_lint() -> None:
    templates = load_prompt_templates(EVAL_DIR / "prompts.toml")
    assert "symptom.simulation_fails" in templates
    assert {name: lint_template(t) for name, t in templates.items() if lint_template(t)} == {}


def test_runner_config_must_have_placeholders(tmp_path: Path) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(
        'name = "x"\ncommand = ["agent", "{prompt}"]\nmodel = "m"\nmax_turns = 5\nparse = "p"\n'
        'disallowed_tools = []\ndisallowed_flag = "--no"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="mcp_config"):
        load_runner(path)


# --- prompt lint ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "This model has a fault. Fix it.",
        "There are FAULTS in the air loop.",
        "Find the injected change.",
        "Squash the bug in this model.",
        "Something buggy is going on.",
    ],
)
def test_lint_rejects_banned_words(prompt: str) -> None:
    assert [v.kind for v in lint_prompt(prompt)] == ["banned_word"]


def test_lint_rejects_object_field_and_fault_id() -> None:
    prompt = "Fix the outlet node name of VAV SYS 1 Branch: looks like an outlet node typo."
    kinds = {
        v.kind
        for v in lint_prompt(
            prompt, object_names=["vav sys 1 branch"], field_names=["outlet_node_name"], fault_id="outlet_node_typo"
        )
    }
    assert kinds == {"object_name", "field_name", "fault_id"}


@pytest.mark.parametrize(
    "prompt",
    [
        SYMPTOM,
        "Zone SPACE1-1 is too cold in winter. Find out why and fix it.",
        "Use the default schedule and debug the run if needed.",
    ],
)
def test_lint_accepts_symptom_prompts(prompt: str) -> None:
    assert (
        lint_prompt(prompt, object_names=["VAV SYS 1 Branch"], field_names=["Outlet Node Name"], fault_id="typo") == []
    )


def test_check_prompt_raises_with_every_violation() -> None:
    with pytest.raises(PromptLintError) as info:
        check_prompt("fault x", "The injected bug is here", fault_id="x_y")
    assert len(info.value.violations) == 2


# --- held-out check ------------------------------------------------------------------------------------------------


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """An evaluation repository and an idfkit repository, both with an initial commit."""
    harness = _init_repo(tmp_path / "harness")
    idfkit = _init_repo(tmp_path / "idfkit")
    _commit_file(harness, "README", "x", "2026-01-01T00:00:00+00:00")
    _commit_file(idfkit, "README", "x", "2026-01-01T00:00:00+00:00")
    return harness, idfkit


@needs_git
def test_held_out_valid_when_checks_not_added_yet(repos: tuple[Path, Path]) -> None:
    harness, idfkit = repos
    _commit_file(harness, "eval/faults/held_out/h1.py", "x", "2026-03-01T00:00:00+00:00")
    uncommitted = harness / "eval/faults/held_out/h2.py"
    uncommitted.write_text("x", encoding="utf-8")
    report = check_held_out({"h1": harness / "eval/faults/held_out/h1.py", "h2": uncommitted}, idfkit_repo=idfkit)
    assert report.checks_commit is None
    assert report.ok
    assert [s.defined_in is not None for s in report.statuses] == [True, False]


@needs_git
def test_held_out_invalid_when_added_after_checks(repos: tuple[Path, Path]) -> None:
    harness, idfkit = repos
    _commit_file(harness, "eval/faults/held_out/early.py", "x", "2026-02-01T00:00:00+00:00")
    _commit_file(idfkit, CHECKS_PATH, "x", "2026-02-15T12:00:00+02:00")
    _commit_file(harness, "eval/faults/held_out/late.py", "x", "2026-02-15T11:00:00+00:00")
    pending = harness / "eval/faults/held_out/pending.py"
    pending.write_text("x", encoding="utf-8")
    files = {
        "early": harness / "eval/faults/held_out/early.py",
        "late": harness / "eval/faults/held_out/late.py",
        "pending": pending,
    }
    report = check_held_out(files, idfkit_repo=idfkit)
    assert report.checks_commit is not None
    assert report.invalid == ["late", "pending"]
    assert not report.ok


@needs_git
def test_held_out_reads_checks_at_the_pinned_ref(repos: tuple[Path, Path]) -> None:
    harness, idfkit = repos
    _git(idfkit, "tag", "v1.0.0")
    _commit_file(idfkit, CHECKS_PATH, "x", "2026-02-01T00:00:00+00:00")
    _commit_file(harness, "eval/faults/held_out/h.py", "x", "2026-03-01T00:00:00+00:00")
    files = {"h": harness / "eval/faults/held_out/h.py"}
    assert check_held_out(files, idfkit_repo=idfkit, idfkit_ref="v1.0.0").ok
    assert not check_held_out(files, idfkit_repo=idfkit, idfkit_ref="HEAD").ok


@needs_git
def test_first_commit_adding_counts_the_first_addition(repos: tuple[Path, Path]) -> None:
    harness, _ = repos
    _commit_file(harness, "f.py", "x", "2026-02-01T00:00:00+00:00")
    _git(harness, "rm", "-q", "f.py")
    _git(harness, "commit", "-q", "-m", "rm", date="2026-02-02T00:00:00+00:00")
    _commit_file(harness, "f.py", "y", "2026-02-03T00:00:00+00:00")
    first = first_commit_adding(harness, "f.py")
    assert first is not None
    assert first.committed_at.isoformat() == "2026-02-01T00:00:00+00:00"


# --- statistics ----------------------------------------------------------------------------------------------------


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    diffs = [0.0, 1.0, 0.33, -0.33, 0.66, 1.0, 0.0, 0.33]
    first = bootstrap_interval(diffs, seed=42, resamples=2000)
    assert first == bootstrap_interval(diffs, seed=42, resamples=2000)
    assert first != bootstrap_interval(diffs, seed=43, resamples=2000)
    low, high = first
    assert low < sum(diffs) / len(diffs) < high


def test_bootstrap_of_constant_differences_is_a_point() -> None:
    assert bootstrap_interval([0.25] * 5, seed=1, resamples=100) == (0.25, 0.25)


def test_compare_pairs_task_means_and_ignores_skips() -> None:
    outcomes = [
        # task a: baseline fixes 1 of 3, treatment 3 of 3
        *[_outcome("f@a", "baseline", r, fixed=r == 0) for r in range(3)],
        *[_outcome("f@a", "treatment", r, fixed=True) for r in range(3)],
        # task b: both fix everything
        *[_outcome("f@b", "baseline", r, fixed=True) for r in range(3)],
        *[_outcome("f@b", "treatment", r, fixed=True) for r in range(3)],
        # task c: skipped in treatment, so it is not paired
        _outcome("f@c", "baseline", fixed=False),
        _outcome("f@c", "treatment", verified_by="skipped", skip_reason="EnergyPlus not found"),
    ]
    result = compare(outcomes, scope="overall", metric="fix_rate", seed=3, resamples=1000)
    assert result is not None
    assert result.tasks == 2
    assert math.isclose(result.baseline, (1 / 3 + 1) / 2)
    assert math.isclose(result.difference, 1 / 3)
    assert not result.descriptive_only
    per_type = compare(outcomes, scope="f", metric="fix_rate", seed=3, resamples=1000, fault_type_scope=True)
    assert per_type is not None
    assert per_type.ci_low == 0.0
    assert per_type.descriptive_only
    assert compare(outcomes, scope="x", metric="fix_rate", seed=3, task_ids=["f@c"]) is None


def test_repeat_spread_is_range_of_fix_rate_across_passes() -> None:
    outcomes = [
        _outcome("f@a", "treatment", 0, fixed=True),
        _outcome("f@b", "treatment", 0, fixed=True),
        _outcome("f@a", "treatment", 1, fixed=True),
        _outcome("f@b", "treatment", 1, fixed=False),
        _outcome("f@a", "treatment", 2, fixed=False),
        _outcome("f@b", "treatment", 2, verified_by="skipped", skip_reason="no EnergyPlus"),
    ]
    spread = repeat_spread(outcomes, condition="treatment")
    assert spread is not None
    assert math.isclose(spread, 1.0)
    assert repeat_spread(outcomes, condition="baseline") is None


PASS_FIX = _cmp("fix_rate", 0.25, (0.10, 0.40))
PASS_CALLS = _cmp("tool_calls", -1.0, (-2.0, 0.5), baseline=20.0)
PASS_HELD_FIX = _cmp("fix_rate", 0.05, (-0.1, 0.2))
PASS_HELD_CALLS = _cmp("tool_calls", 1.0, (-1.0, 3.0), baseline=20.0)
PASS_UNWANTED = _cmp("unwanted_changes", 0.0, (0.0, 0.0), baseline=0.0)
PASS_FALSE = _cmp("false_fix_rate", -0.1, (-0.3, 0.0), baseline=0.2)


def _verdict(
    *,
    fix_rate: Comparison | None = PASS_FIX,
    tool_calls: Comparison | None = PASS_CALLS,
    held_out_fix_rate: Comparison | None = PASS_HELD_FIX,
    held_out_tool_calls: Comparison | None = PASS_HELD_CALLS,
    unwanted_changes: Comparison | None = PASS_UNWANTED,
    false_fix_rate: Comparison | None = PASS_FALSE,
    wrong_top_candidate_rate: Comparison | None = None,
    baseline_kind: BaselineKind = "pre_feature",
    ablation: bool = False,
) -> GateVerdict:
    return gate_verdict(
        fix_rate=fix_rate,
        tool_calls=tool_calls,
        held_out_fix_rate=held_out_fix_rate,
        held_out_tool_calls=held_out_tool_calls,
        unwanted_changes=unwanted_changes,
        false_fix_rate=false_fix_rate,
        wrong_top_candidate_rate=wrong_top_candidate_rate,
        baseline_kind=baseline_kind,
        ablation=ablation,
    )


def test_gate_passes_on_fix_rate_gain() -> None:
    verdict = _verdict()
    assert verdict.effect == "fix_rate"
    assert verdict.ci_excludes_zero
    assert verdict.held_out_direction
    assert verdict.valid
    assert verdict.passes
    assert verdict.wrong_top_candidate_ok is None


def test_gate_passes_on_fewer_tool_calls_at_no_lower_fix_rate() -> None:
    verdict = _verdict(
        fix_rate=_cmp("fix_rate", 0.0, (-0.1, 0.1)),
        tool_calls=_cmp("tool_calls", -7.0, (-9.0, -5.0), baseline=20.0),
        held_out_tool_calls=_cmp("tool_calls", -2.0, (-5.0, 1.0), baseline=20.0),
    )
    assert verdict.effect == "tool_calls"
    assert verdict.passes
    lower_fix = _verdict(
        fix_rate=_cmp("fix_rate", -0.05, (-0.1, 0.0)),
        tool_calls=_cmp("tool_calls", -7.0, (-9.0, -5.0), baseline=20.0),
    )
    assert lower_fix.effect is None
    assert not lower_fix.passes


def test_gate_fails_when_the_effect_is_too_small_or_its_interval_includes_zero() -> None:
    small = _verdict(fix_rate=_cmp("fix_rate", 0.15, (0.05, 0.25)))
    assert small.effect is None
    assert small.ci_excludes_zero
    assert not small.passes
    wide = _verdict(fix_rate=_cmp("fix_rate", 0.25, (-0.05, 0.5)))
    assert wide.effect == "fix_rate"
    assert not wide.ci_excludes_zero
    assert not wide.passes


@pytest.mark.parametrize(
    ("make", "clause"),
    [
        (lambda: _verdict(held_out_fix_rate=_cmp("fix_rate", -0.05, (-0.2, 0.1))), "held_out_direction"),
        (lambda: _verdict(held_out_fix_rate=None), "held_out_direction"),
        (
            lambda: _verdict(unwanted_changes=_cmp("unwanted_changes", 0.3, (0.0, 0.6), baseline=0.0)),
            "no_more_unwanted_changes",
        ),
        (
            lambda: _verdict(false_fix_rate=_cmp("false_fix_rate", 0.1, (0.0, 0.2), baseline=0.0)),
            "no_more_false_fixes",
        ),
        (lambda: _verdict(false_fix_rate=None), "no_more_false_fixes"),
        (
            lambda: _verdict(wrong_top_candidate_rate=_cmp("wrong_top_candidate_rate", 0.2, (0.0, 0.4))),
            "wrong_top_candidate_ok",
        ),
        (lambda: _verdict(baseline_kind="other"), "valid"),
        (lambda: _verdict(ablation=True), "valid"),
    ],
)
def test_gate_fails_on_each_clause(make: Callable[[], GateVerdict], clause: str) -> None:
    base = _verdict().to_dict()
    verdict = make().to_dict()
    assert base["passes"] is True
    assert verdict[clause] is False
    assert verdict["passes"] is False
    assert {k for k in base if base[k] != verdict[k]} <= {clause, "passes"}


def test_wrong_top_candidate_clause_passes_when_not_higher() -> None:
    verdict = _verdict(wrong_top_candidate_rate=_cmp("wrong_top_candidate_rate", 0.0, (-0.1, 0.1)))
    assert verdict.wrong_top_candidate_ok is True
    assert verdict.passes


def test_layer_gate_and_scoped_comparisons_from_outcomes() -> None:
    outcomes: list[TaskOutcome] = []
    for model in ("a", "b", "c", "d"):
        for r in range(3):
            outcomes.append(_outcome(f"typo@{model}", "baseline", r, fixed=False))
            outcomes.append(_outcome(f"typo@{model}", "treatment", r, fixed=True, tool_calls=6))
            outcomes.append(_outcome(f"heldout@{model}", "baseline", r, fixed=False))
            outcomes.append(_outcome(f"heldout@{model}", "treatment", r, fixed=r < 2))
            outcomes.append(_outcome(f"ctrl@{model}", "baseline", r))
            outcomes.append(_outcome(f"ctrl@{model}", "treatment", r))
    infos = {
        **{f"typo@{m}": TaskInfo(f"typo@{m}", "fault", "topology", "typo", False) for m in "abcd"},
        **{f"heldout@{m}": TaskInfo(f"heldout@{m}", "fault", "topology", "heldout", True) for m in "abcd"},
        **{f"ctrl@{m}": TaskInfo(f"ctrl@{m}", "control", "topology", None, False) for m in "abcd"},
    }
    verdict = layer_gate(
        outcomes,
        layer="topology",
        layer_task_ids=[i for i in infos if not i.startswith("ctrl")],
        held_out_task_ids=[i for i in infos if i.startswith("heldout")],
        control_task_ids=[i for i in infos if i.startswith("ctrl")],
        seed=11,
        resamples=500,
        baseline_kind="pre_feature",
        ablation=False,
    )
    assert verdict.passes
    comparisons = scoped_comparisons(outcomes, infos, seed=11, resamples=500)
    scopes = {(c.scope, c.metric) for c in comparisons}
    assert {("overall", "fix_rate"), ("topology", "fix_rate"), ("typo", "fix_rate"), ("held_out", "fix_rate")} <= scopes
    assert ("control", "false_fix_rate") in scopes
    assert ("results", "fix_rate") not in scopes
    assert ("overall", "wrong_top_candidate_rate") not in scopes


# --- registry --------------------------------------------------------------------------------------------------------


def test_discover_loads_faults_and_tasks(tmp_path: Path) -> None:
    registry = discover(_make_eval_dir(tmp_path))
    assert [e.fault.id for e in registry.faults] == ["typo_outlet", "undersized_coil"]
    assert [(t.id, t.kind) for t in registry.tasks] == [("control_review", "control"), ("add_reheat_coil", "authoring")]
    assert registry.held_out_files() == {}


def test_discover_on_the_repository_succeeds() -> None:
    discover()


def test_discover_rejects_misplaced_held_out_fault(tmp_path: Path) -> None:
    eval_dir = tmp_path / "evaldefs"
    path = _write_fault(eval_dir, "misplaced", held_out=True)
    path.rename(eval_dir / "faults" / "misplaced.py")
    with pytest.raises(ConfigError, match="held_out"):
        discover(eval_dir)


def test_discover_rejects_duplicate_ids_and_missing_attribute(tmp_path: Path) -> None:
    eval_dir = _make_eval_dir(tmp_path)
    _write_fault(eval_dir, "control_review")
    with pytest.raises(ConfigError, match="duplicate"):
        discover(eval_dir)
    (eval_dir / "faults" / "control_review.py").write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="FAULT"):
        discover(eval_dir)


def test_select_by_all_layer_and_ids(tmp_path: Path) -> None:
    registry = discover(_make_eval_dir(tmp_path))
    assert len(select(registry, "all").faults) == 2
    results = select(registry, "results")
    assert [e.fault.id for e in results.faults] == ["undersized_coil"]
    assert results.tasks == []
    by_id = select(registry, "typo_outlet")
    assert [e.fault.id for e in by_id.faults] == ["typo_outlet"]
    assert [t.id for t in by_id.tasks] == ["control_review"]
    with pytest.raises(ConfigError, match="unknown"):
        select(registry, "nope")


def test_applicable_models_respects_tags_order_and_cap() -> None:
    models = _models()
    assert [m.id for m in applicable_models(["air_loop"], models)] == ["a", "b"]
    assert [m.id for m in applicable_models(["air_loop", "packaged_unit"], models, cap=2)] == ["a", "b"]
    assert applicable_models(["hvac_template"], models) == []


def test_plan_tasks_skips_energyplus_tasks_without_energyplus(tmp_path: Path) -> None:
    registry = discover(_make_eval_dir(tmp_path))
    example_files = _example_files(tmp_path, ["a.idf", "c.idf"])
    plan = plan_tasks(select(registry, "all"), _models(), example_files=example_files, energyplus_available=False)
    assert [(p.task_id, p.runnable) for p in plan] == [
        ("typo_outlet@a", True),
        ("undersized_coil@a", False),
        ("control_review@a", True),
        ("add_reheat_coil@a", False),
    ]
    assert plan[1].skip_reason == "EnergyPlus not found"
    assert plan_tasks(select(registry, "all"), _models(), example_files=None, energyplus_available=True) == []


def test_task_infos_from_task_ids(tmp_path: Path) -> None:
    registry = discover(_make_eval_dir(tmp_path))
    infos = task_infos(registry, ["typo_outlet@a", "control_review@b", "unknown@c"])
    assert infos["typo_outlet@a"].fault_id == "typo_outlet"
    assert infos["control_review@b"].kind == "control"
    assert "unknown@c" not in infos


# --- command line ----------------------------------------------------------------------------------------------------


def _models_toml(tmp_path: Path) -> Path:
    path = tmp_path / "models.toml"
    path.write_text(
        '[[models]]\nid = "a"\nfile = "a.idf"\nversion = "26.2"\ntags = ["air_loop", "vav_reheat"]\n',
        encoding="utf-8",
    )
    return path


def _run_args(tmp_path: Path, *extra: str) -> list[str]:
    return ["run", "--treatment", "uv run idfkit-mcp", "--out", str(tmp_path / "out"), "--seed", "1", *extra]


def test_cli_list_faults_exits_zero() -> None:
    assert cli.main(["list-faults"]) == 0
    assert cli.main(["list-faults", "--check-held-out"]) in (0, 2)


def test_cli_run_with_nothing_runnable_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "discover", lambda: Registry(faults=[], tasks=[]))
    assert cli.main(_run_args(tmp_path, "--example-files", str(_example_files(tmp_path)))) == 3


def test_cli_run_bad_configuration_exits_2(tmp_path: Path) -> None:
    assert cli.main(_run_args(tmp_path, "--repeat", "2")) == 2
    bad = tmp_path / "runner.toml"
    bad.write_text("name = 1\n", encoding="utf-8")
    assert cli.main(_run_args(tmp_path, "--runner", str(bad))) == 2
    assert cli.main(_run_args(tmp_path, "--faults", "no_such_fault")) == 2


def test_cli_run_prompt_lint_failure_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    eval_dir = tmp_path / "evaldefs"
    _write_fault(eval_dir, "leaky", template="There is an injected change. Fix it.")
    monkeypatch.setattr(cli, "discover", lambda: discover(eval_dir))
    assert cli.main(_run_args(tmp_path, "--example-files", str(_example_files(tmp_path)))) == 2
    assert "banned word 'injected'" in capsys.readouterr().err


def test_cli_run_hands_the_plan_to_the_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eval_dir = _make_eval_dir(tmp_path)
    models = _models_toml(tmp_path)
    seen: list[tuple[cli.RunConfig, list[PlannedTask]]] = []

    def fake_execute(config: cli.RunConfig, plan: Sequence[PlannedTask]) -> int:
        seen.append((config, list(plan)))
        return 0

    monkeypatch.setattr(cli, "discover", lambda: discover(eval_dir))
    monkeypatch.setattr(cli, "execute_run", fake_execute)
    example_files = str(_example_files(tmp_path))
    args = _run_args(
        tmp_path, "--models", str(models), "--example-files", example_files, "--baseline", "uvx idfkit-mcp"
    )
    assert cli.main(args) == 0
    config, plan = seen[0]
    assert config.baseline_kind == "other"
    assert config.bootstrap_seed == 1
    assert config.repeats == 3
    assert [p.task_id for p in plan] == ["typo_outlet@a", "undersized_coil@a", "control_review@a", "add_reheat_coil@a"]


def test_cli_run_with_a_missing_runner_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    eval_dir = _make_eval_dir(tmp_path)
    monkeypatch.setattr(cli, "discover", lambda: discover(eval_dir))
    runner = _runner_toml(tmp_path, command=["no-such-agent-binary", "{prompt}", "{mcp_config}"])
    models = str(_models_toml(tmp_path))
    args = _run_args(tmp_path, "--models", models, "--example-files", str(_example_files(tmp_path)))
    assert cli.main([*args, "--runner", str(runner)]) == 2
    assert "not found" in capsys.readouterr().err


@needs_git
def test_cli_list_faults_check_held_out_exits_2_on_invalid(
    repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    harness, idfkit = repos
    eval_dir = harness / "eval"
    _commit_file(idfkit, CHECKS_PATH, "x", "2026-02-01T00:00:00+00:00")
    path = _write_fault(eval_dir, "late_one", held_out=True)
    _git(harness, "add", str(path.relative_to(harness)))
    _git(harness, "commit", "-q", "-m", "late", date="2026-03-01T00:00:00+00:00")
    monkeypatch.setattr(cli, "discover", lambda: discover(eval_dir))
    assert cli.main(["list-faults"]) == 0
    assert cli.main(["list-faults", "--check-held-out"]) == 2  # no --idfkit-repo
    assert cli.main(["list-faults", "--check-held-out", "--idfkit-repo", str(idfkit)]) == 2
    assert cli.main(["list-faults", "--check-held-out", "--idfkit-repo", str(idfkit), "--idfkit-ref", "HEAD~1"]) == 0


def test_cli_compare_one_and_two_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    eval_dir = _make_eval_dir(tmp_path)
    monkeypatch.setattr(cli, "discover", lambda: discover(eval_dir))
    outcomes = [
        _outcome(f"typo_outlet@{m}", cond, r, fixed=cond == "treatment")
        for m in "ab"
        for cond in ("baseline", "treatment")
        for r in range(3)
    ]
    save_run(_run(outcomes), tmp_path / "r1")
    save_run(_run(outcomes, run_id="r2"), tmp_path / "r2")
    assert cli.main(["compare", str(tmp_path / "r1")]) == 0
    assert "SC-009 topology" in capsys.readouterr().out
    assert cli.main(["compare", str(tmp_path / "r1"), str(tmp_path / "r2")]) == 0
    assert "Slice delta" in capsys.readouterr().out
    assert cli.main(["compare", str(tmp_path / "missing")]) == 2


# --- agent runner, parser, conditions and diff (T063 to T067) ---------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "eval"
FAKE_AGENT = FIXTURES / "fake_agent.py"

ZONE_FAULT_MODULE = textwrap.dedent(
    """
    from __future__ import annotations

    from eval.model import FaultType, InjectedFault, ObjectKey


    def _inject(doc):
        doc["Zone"]["Office"].multiplier = 10
        return InjectedFault(
            scope=[ObjectKey("Zone", "Office")], object_names=["Office"], field_names=["multiplier"]
        )


    def _verify(doc, result, injected):
        return doc["Zone"]["Office"].data.get("multiplier") in (None, 1, 1.0)


    FAULT = FaultType(
        id="zone_multiplier",
        layer="topology",
        description="for tests",
        held_out=False,
        applies_to=["air_loop"],
        intended_tools=["trace_hvac"],
        prompt_template={template!r},
        needs_energyplus=False,
        inject=_inject,
        verify=_verify,
    )
    """
)

QUESTION_MODULE = textwrap.dedent(
    """
    from __future__ import annotations

    from eval.model import TaskSpec


    def _key(doc):
        return next(iter(doc["Zone"])).name


    def _verify(doc, result, answer):
        return answer is not None and _key(doc).casefold() in answer.casefold()


    TASK = TaskSpec(
        id="first_zone",
        kind="question",
        layer="topology",
        applies_to=["air_loop"],
        prompt_template="Which zone of this building is listed first?",
        intended_tools=["get_object_neighbourhood"],
        needs_energyplus=False,
        verify=_verify,
        answer_key=_key,
    )
    """
)

E2E_FAULT_PROMPT = "Zone loads look far too high. Find out why and correct the model."


def _runner_toml(tmp_path: Path, *, command: Sequence[str] | None = None, disallowed: Sequence[str] = ()) -> Path:
    argv = list(command) if command is not None else [sys.executable, str(FAKE_AGENT), "{prompt}", "{mcp_config}"]
    path = tmp_path / "runner.toml"
    path.write_text(
        f'name = "fake"\ncommand = {json.dumps(argv)}\nmodel = "fake-model"\nmax_turns = 7\n'
        'max_turns_flag = "--max-turns"\nmodel_flag = "--model"\ntimeout_seconds = 120\n'
        f'parse = "claude_stream_json"\ndisallowed_tools = {json.dumps(list(disallowed))}\n'
        'disallowed_flag = "--disallowedTools"\n',
        encoding="utf-8",
    )
    return path


def _reference_model(path: Path) -> Path:
    from idfkit import new_document, save_idf

    doc = new_document(version=(26, 2, 0))
    doc.add("Zone", "Office", {"multiplier": 1})
    doc.add("Zone", "Store", {"multiplier": 1})
    path.parent.mkdir(parents=True, exist_ok=True)
    save_idf(doc, path)
    return path


def _e2e_eval_dir(root: Path, *, template: str = E2E_FAULT_PROMPT) -> Path:
    eval_dir = root / "evaldefs"
    (eval_dir / "faults").mkdir(parents=True)
    (eval_dir / "faults" / "zone_multiplier.py").write_text(
        ZONE_FAULT_MODULE.format(template=template), encoding="utf-8"
    )
    _write_fault(eval_dir, "undersized_coil", layer="results", needs_ep=True)
    (eval_dir / "tasks" / "questions").mkdir(parents=True)
    (eval_dir / "tasks" / "questions" / "first_zone.py").write_text(QUESTION_MODULE, encoding="utf-8")
    (eval_dir / "tasks" / "controls.toml").write_text(CONTROLS, encoding="utf-8")
    return eval_dir


def _e2e_args(tmp_path: Path, out: Path, *extra: str) -> list[str]:
    _reference_model(tmp_path / "ExampleFiles" / "a.idf")
    models = tmp_path / "models.toml"
    models.write_text('[[models]]\nid = "a"\nfile = "a.idf"\nversion = "26.2"\ntags = ["air_loop"]\n', encoding="utf-8")
    return [
        "run",
        "--treatment", "fake-server treatment",
        "--baseline", "fake-server baseline",
        "--runner", str(_runner_toml(tmp_path)),
        "--models", str(models),
        "--example-files", str(tmp_path / "ExampleFiles"),
        "--out", str(out),
        "--seed", "3",
        *extra,
    ]  # fmt: skip


E2E = tuple[int, Path, list[dict[str, object]]]


def _e2e_run(root: Path, monkeypatch: pytest.MonkeyPatch, *, template: str = E2E_FAULT_PROMPT) -> E2E:
    """Run ``eval run`` end to end with the fake agent; return the exit code, the run directory and the agent log."""
    log = root / "agent-log.jsonl"
    eval_dir = _e2e_eval_dir(root, template=template)
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log))
    monkeypatch.setattr(cli, "find_energyplus_dir", lambda explicit: None)
    monkeypatch.setattr(cli, "discover", lambda: discover(eval_dir))
    out = root / "out"
    code = cli.main(_e2e_args(root, out))
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return code, out, entries


@pytest.fixture(scope="module")
def e2e(tmp_path_factory: pytest.TempPathFactory) -> E2E:
    """One end-to-end run shared by the tests that read it (18 fake-agent invocations)."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        return _e2e_run(tmp_path_factory.mktemp("e2e"), monkeypatch)


def test_e2e_run_records_every_task_condition_and_repeat(
    e2e: E2E,
) -> None:
    code, out, log = e2e
    assert code == 0
    run = load_run(out)
    assert run.baseline_kind == "other" and not run.ablation
    assert run.model_identifier == "fake-model" and run.repeats == 3 and run.finished_at is not None
    assert run.baseline_command == "fake-server baseline" and run.treatment_command == "fake-server treatment"
    tasks = ["undersized_coil@a", "zone_multiplier@a", "control_review@a", "first_zone@a"]
    # Same task list and order for both conditions, repeat passes outermost.
    expected = [(t, c, r) for r in range(3) for c in ("baseline", "treatment") for t in tasks]
    assert [(o.task_id, o.condition, o.repeat) for o in run.outcomes] == expected
    # Three runnable tasks, six invocations each; the fake agent saw the same prompt in both conditions.
    assert len(log) == 18
    prompts: dict[str, set[str]] = {}
    for entry in log:
        prompts.setdefault(str(entry["condition"]), set()).add(str(entry["prompt"]))
    assert prompts["baseline"] == prompts["treatment"] and len(prompts["baseline"]) == 3
    for task_line in (out / "tasks.jsonl").read_text().splitlines():
        task = json.loads(task_line)
        assert task["skip_reason"] is not None or task["prompt"] in prompts["treatment"]


def test_e2e_skips_energyplus_tasks_without_energyplus(
    e2e: E2E,
) -> None:
    _, out, log = e2e
    skipped = [o for o in load_run(out).outcomes if o.task_id == "undersized_coil@a"]
    assert len(skipped) == 6
    assert {(o.verified_by, o.skip_reason, o.fixed, o.transcript_path) for o in skipped} == {
        ("skipped", "EnergyPlus not found", False, "")
    }
    assert all("undersized" not in str(e["prompt"]) for e in log)
    assert "undersized_coil@a: EnergyPlus not found" in (out / "summary.md").read_text()


def test_e2e_fault_outcomes_diff_attribution_and_anchoring(
    e2e: E2E,
) -> None:
    _, out, _ = e2e
    by = {(o.task_id, o.condition, o.repeat): o for o in load_run(out).outcomes}
    treated = by[("zone_multiplier@a", "treatment", 1)]
    assert (treated.fixed, treated.verified_by, treated.unwanted_changes) == (True, "check", 0)
    assert (treated.tool_calls, treated.response_tokens) == (5, 60 + 900 + 240)
    assert treated.tools_used == ["diagnose_symptom", "trace_hvac"]
    assert treated.intended_tool_used is True
    # rank 1 is "OFFICE": the agent's first edit targeted it, and it is the injected object (case-insensitive).
    assert (treated.top_candidate_edited, treated.top_candidate_correct, treated.first_edit_correct) == (
        True,
        True,
        True,
    )
    base = by[("zone_multiplier@a", "baseline", 1)]
    assert (base.fixed, base.unwanted_changes, base.false_fix) == (False, 1, False)
    assert base.intended_tool_used is None  # SC-010a is read on treatment runs only
    assert (base.top_candidate_edited, base.first_edit_correct) == (None, False)
    assert base.transcript_path == "transcripts/zone_multiplier@a.baseline.1.jsonl"
    assert (out / base.transcript_path).read_text() == (FIXTURES / "baseline_wrong.jsonl").read_text()


def test_e2e_controls_and_questions(e2e: E2E) -> None:
    _, out, _ = e2e
    by = {(o.task_id, o.condition): o for o in load_run(out).outcomes if o.repeat == 2}
    clean, claims = by[("control_review@a", "treatment")], by[("control_review@a", "baseline")]
    assert (clean.false_fix, clean.fixed, clean.unwanted_changes) == (False, True, 0)
    assert (claims.false_fix, claims.fixed) == (True, False)  # no change, but a reported fault
    right, wrong = by[("first_zone@a", "treatment")], by[("first_zone@a", "baseline")]
    assert (right.fixed, right.verified_by, right.response_tokens) == (True, "answer_key", 2 * 160 + 95)
    assert right.tools_used == ["get_object_neighbourhood"] and right.intended_tool_used is True
    assert (wrong.fixed, wrong.verified_by) == (False, "answer_key")
    assert json.loads((out / "tasks.jsonl").read_text().splitlines()[3])["answer_key"] == "Office"


def test_e2e_invocations_are_isolated_and_bounded(
    e2e: E2E,
) -> None:
    _, _, log = e2e
    cwds = [str(e["cwd"]) for e in log]
    assert len(set(cwds)) == len(cwds)  # a fresh working directory per invocation
    for entry in log:
        argv = [str(a) for a in cast(list[object], entry["argv"])]
        assert argv[-4:] == ["--max-turns", "7", "--model", "fake-model"]
        assert "--disallowedTools" not in argv
        assert "zone_multiplier" not in str(entry["cwd"]) and "@" not in str(entry["cwd"])
        server = cast(dict[str, object], entry["server"])
        env = cast(dict[str, str], server["env"])
        assert Path(env["IDFKIT_MCP_OUTPUT_DIRS"]).resolve() == Path(str(entry["cwd"])).resolve()
        assert (server["command"], server["args"]) == ("fake-server", [entry["condition"]])
        assert str(entry["prompt"]).endswith(MODEL_NOTE)


def test_e2e_every_rendered_prompt_passes_the_lint(
    e2e: E2E,
) -> None:
    _, _, log = e2e
    for entry in log:
        prompt = str(entry["prompt"])
        assert (
            lint_prompt(prompt, object_names=["Office"], field_names=["multiplier"], fault_id="zone_multiplier") == []
        )


def test_e2e_rendered_prompt_lint_failure_exits_2_before_any_agent_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The template passes the template lint, but {zone} renders to "Office", the injected object.
    template = "Zone {zone} is far too warm. Find out why and correct the model."
    code, out, log = _e2e_run(tmp_path, monkeypatch, template=template)
    assert code == 2
    assert log == []
    assert not (out / "outcomes.jsonl").exists()
    assert "object name 'Office'" in capsys.readouterr().err


def test_e2e_summary_and_compare_two_runs(
    e2e: E2E, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = e2e
    summary = (out / "summary.md").read_text()
    for heading in (
        "Paired differences (treatment minus baseline)",
        "Held-out fault types",
        "Controls, authoring and questions",
        "SC-008 repeatability",
        "SC-009a diagnosis anchoring",
        "SC-010a intended tool use",
        "### SC-009 topology",
        "This run cannot decide SC-009",
    ):
        assert heading in summary
    assert "| control | false-fix rate | baseline | 1 | 3 | 1.000 | 0 |" in summary
    assert "| trace_hvac | 1 | 1 | 1.000 |" in summary
    monkeypatch.setattr(cli, "discover", lambda: discover(out.parent / "evaldefs"))
    second = out.parent / "second"
    shutil.copytree(out, second)
    capsys.readouterr()
    assert cli.main(["compare", str(out), str(second)]) == 0
    printed = capsys.readouterr().out
    assert "Slice delta against" in printed
    assert "| zone_multiplier | fix_rate | +0.000 |" in (second / "summary.md").read_text()
    assert "Slice delta" not in (out / "summary.md").read_text()


def test_parser_reads_tool_calls_tokens_and_final_text() -> None:
    parsed = claude_stream_json.parse((FIXTURES / "treatment_fix.jsonl").read_text())
    assert parsed.tool_names == ["load_model", "diagnose_symptom", "trace_hvac", "update_object", "save_model"]
    assert {c.server for c in parsed.tool_calls} == {"idfkit"}
    assert parsed.tool_calls[3].input == {"object_type": "Zone", "name": "Office", "fields": {"multiplier": 1}}
    assert parsed.tool_calls[0].result == '{"version": "26.2.0", "zones": 2}'
    assert parsed.response_tokens == 60 + 900 + 240  # the result event's totals, cache reads left out
    assert parsed.final_text is not None and parsed.final_text.startswith("The Office zone multiplier")
    assert parsed.new_tools_used() == ["diagnose_symptom", "trace_hvac"]
    assert [c.name for c in parsed.mutating_calls()] == ["update_object"]
    assert (parsed.num_turns, parsed.is_error, parsed.unknown_events) == (6, False, 1)


def test_parser_is_robust_to_unknown_events_and_truncated_sessions() -> None:
    wrong = claude_stream_json.parse((FIXTURES / "baseline_wrong.jsonl").read_text())
    assert (wrong.unknown_events, wrong.malformed_lines) == (2, 1)
    truncated = claude_stream_json.parse((FIXTURES / "question_right.jsonl").read_text())
    assert truncated.final_text == "The first zone is Office."  # no result event: the last assistant text
    assert truncated.response_tokens == 2 * 160 + 95  # summed once per message id
    failed = claude_stream_json.parse((FIXTURES / "question_wrong.jsonl").read_text())
    assert failed.is_error and failed.tool_calls[0].is_error and failed.mutating_calls() == []
    assert claude_stream_json.parse("").tool_calls == []
    assert claude_stream_json.split_tool_name("mcp__plugin_x__trace_hvac") == ("plugin_x", "trace_hvac")
    assert claude_stream_json.split_tool_name("Bash") == (None, "Bash")
    with pytest.raises(ConfigError, match="unknown transcript parser"):
        get_parser("nope")


def test_build_argv_substitutes_and_appends(tmp_path: Path) -> None:
    runner = load_runner(_runner_toml(tmp_path, command=["agent", "-p", "{prompt}", "--cfg={mcp_config}"]))
    argv = build_argv(runner, prompt="Zone {x} {mcp_config}?", mcp_config=Path("/c.json"))
    assert argv == [
        "agent",
        "-p",
        "Zone {x} {mcp_config}?",
        "--cfg=/c.json",
        "--max-turns",
        "7",
        "--model",
        "fake-model",
    ]
    ablation = build_argv(runner, prompt="p", mcp_config=Path("/c.json"), disallowed_tools=["trace_hvac", "Bash"])
    assert ablation[-3:] == ["--disallowedTools", "mcp__idfkit__trace_hvac", "Bash"]
    unset = replace(runner, model="unset", max_turns_flag="")
    assert build_argv(unset, prompt="p", mcp_config=Path("/c.json")) == ["agent", "-p", "p", "--cfg=/c.json"]


def test_mcp_config_points_at_the_condition_server(tmp_path: Path) -> None:
    server = ServerCommand(argv=["uv", "run", "idfkit-mcp"], env={"ENERGYPLUS_DIR": "/ep"})
    path = write_mcp_config(tmp_path / "mcp.json", server, workdir=tmp_path)
    entry = json.loads(path.read_text())["mcpServers"]["idfkit"]
    assert (entry["command"], entry["args"]) == ("uv", ["run", "idfkit-mcp"])
    assert entry["env"] == {"IDFKIT_MCP_OUTPUT_DIRS": str(tmp_path), "ENERGYPLUS_DIR": "/ep"}


def test_run_agent_captures_output_and_enforces_the_timeout(tmp_path: Path) -> None:
    ok = run_agent(
        [sys.executable, "-c", "print('{}')"], cwd=tmp_path, transcript=tmp_path / "t" / "a.jsonl", timeout_seconds=60
    )
    assert (ok.returncode, ok.timed_out, ok.read_transcript()) == (0, False, "{}\n")
    assert json.loads((tmp_path / "t" / "a.meta.json").read_text())["returncode"] == 0
    slow = run_agent(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        transcript=tmp_path / "t" / "b.jsonl",
        timeout_seconds=0.5,
    )
    assert slow.timed_out and slow.duration_seconds < 20


def test_server_commands_are_anchored_to_the_checkout(tmp_path: Path) -> None:
    assert parse_command("uv run idfkit-mcp", project=tmp_path).argv == [
        "uv",
        "run",
        "--project",
        str(tmp_path),
        "idfkit-mcp",
    ]
    assert parse_command("uv run --project /x idfkit-mcp", project=tmp_path).argv == [
        "uv",
        "run",
        "--project",
        "/x",
        "idfkit-mcp",
    ]
    assert parse_command("uvx 'idfkit-mcp==0.9'", project=tmp_path).argv == ["uvx", "idfkit-mcp==0.9"]
    with pytest.raises(ConfigError):
        parse_command("  ")


@needs_git
def test_pre_feature_baseline_runs_from_a_worktree_that_is_removed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "pyproject.toml", "[project]\nname = 'x'\n", "2026-01-01T00:00:00+00:00")
    sha = _git_out(repo, "rev-parse", "HEAD")
    baseline = BaselineConfig(kind="pre_feature", idfkit_mcp_sha=sha[:7], idfkit="idfkit==1.2.0")
    with build_conditions(
        treatment_command="uv run idfkit-mcp",
        baseline=baseline,
        baseline_command=None,
        ablation=False,
        repo=repo,
        warm=False,
    ) as conditions:
        assert conditions.baseline is not None
        argv = conditions.baseline.argv
        worktree = Path(argv[argv.index("--project") + 1])
        assert (worktree / "pyproject.toml").is_file()
        assert argv[-3:] == ["--with", "idfkit==1.2.0", "idfkit-mcp"]
        assert conditions.treatment.argv[:4] == ["uv", "run", "--project", str(repo)]
        assert conditions.treatment_revision == sha[:7] or conditions.treatment_revision.startswith(sha[:7])
    assert not worktree.exists()
    assert len(_git_out(repo, "worktree", "list").splitlines()) == 1
    bad = BaselineConfig(kind="pre_feature", idfkit_mcp_sha="0000000", idfkit="idfkit==1.2.0")
    with (
        pytest.raises(GitError),
        build_conditions(
            treatment_command="x", baseline=bad, baseline_command=None, ablation=False, repo=repo, warm=False
        ),
    ):
        pass


def test_ablation_conditions_have_no_baseline(tmp_path: Path) -> None:
    with build_conditions(
        treatment_command="srv", baseline=None, baseline_command=None, ablation=True, repo=tmp_path, warm=False
    ) as conditions:
        assert conditions.baseline is None and conditions.treatment.argv == ["srv"]


def test_diff_finds_changes_outside_scope_case_insensitively() -> None:
    from idfkit import new_document

    start = new_document(version=(26, 2, 0))
    start.add("Zone", "Office", {"multiplier": 1})
    start.add("Zone", "Store")
    start.add("Output:Variable", "", {"key_value": "*", "variable_name": "Zone Mean Air Temperature"})
    final = new_document(version=(26, 2, 0))
    final.add("Zone", "OFFICE", {"multiplier": "1"}, validate=False)  # same object: name case, number spelling
    final.add("Zone", "Store", {"multiplier": 2})
    final.add("Zone", "Lobby")
    final.add("Output:Variable", "", {"key_value": "*", "variable_name": "Zone Air Temperature"})
    changes = diff(snapshot(start), snapshot(final))
    assert changes.added == [ObjectKey("Zone", "lobby"), ObjectKey("Output:Variable", "")]
    assert changes.modified == [ObjectKey("zone", "store")]
    assert changes.removed == [ObjectKey("Output:Variable", "")]
    assert unwanted_changes(changes, [ObjectKey("Zone", "Store")]) == 3
    assert unwanted_changes(changes, [ObjectKey("Zone", "Store"), ObjectKey("output:variable", "")]) == 1
    assert diff(snapshot(start), snapshot(start)).changed == []


@pytest.mark.parametrize(
    ("text", "reported"),
    [
        ("I corrected the outlet node of the coil.", True),
        ("The supply fan was misconfigured.", True),
        ("No issues found. The HVAC system is set up correctly.", False),
        ("There is nothing to fix.", False),
        ("Validation reported 0 errors.", False),
        ("Everything is correct.", False),
        (None, False),
    ],
)
def test_reported_fault_reads_the_final_message(text: str | None, reported: bool) -> None:
    assert reported_fault(ParsedTranscript(tool_calls=[], response_tokens=0, final_text=text)) is reported


def test_control_false_fix_on_change_or_mutating_call() -> None:
    quiet = ParsedTranscript(tool_calls=[], response_tokens=0, final_text="All good.")
    no_change = ModelDiff(added=[], removed=[], modified=[])
    assert false_fix(no_change, quiet) is False
    assert false_fix(ModelDiff(added=[], removed=[], modified=[ObjectKey("Zone", "A")]), quiet) is True
    assert false_fix(None, quiet) is True  # the final model did not load
    edit = ToolCall(id="1", name="update_object", server="idfkit", input={"object_type": "Zone", "name": "A"})
    unsaved = ParsedTranscript(tool_calls=[edit], response_tokens=0, final_text="All good.")
    assert false_fix(no_change, unsaved) is True
    assert first_edit_target(unsaved) == ObjectKey("zone", "a")
    failed = replace(edit, is_error=True)
    assert first_edit_target(ParsedTranscript(tool_calls=[failed], response_tokens=0, final_text=None)) is None


def test_baseline_wrong_first_edit_pairs_with_wrong_top_candidate() -> None:
    outcomes = [
        _outcome("f@a", "baseline", r, first_edit_correct=False) for r in range(3)
    ] + [
        _outcome("f@a", "treatment", r, top_candidate_edited=True, top_candidate_correct=r == 0) for r in range(3)
    ]  # fmt: skip
    comparison = compare(outcomes, scope="t", metric="wrong_top_candidate_rate", seed=1, resamples=50)
    assert comparison is not None
    assert (comparison.baseline, comparison.treatment) == (1.0, pytest.approx(2 / 3))
    treated_first_edit = _outcome("f@a", "treatment", first_edit_correct=False)
    assert metric_value(treated_first_edit, "wrong_top_candidate_rate") is None
