"""Executing a prepared run (task T073): the body of ``python -m eval run`` after configuration.

**How the agent's server gets the model.** idfkit-mcp has no option that preloads a model, so the agent loads it.
Each task's starting model (the reference model, with the fault injected for fault tasks) is written once to
``start.idf``. Every invocation (task, condition, repeat) gets a fresh working directory holding a copy named
``model.idf``; the agent CLI runs there, and so does the stdio server it starts, so ``load_model("model.idf")``
and ``save_model()`` work, and the server's session file (keyed by its working directory) never carries one
invocation's model or simulation into the next. The harness appends ``MODEL_NOTE`` to every prompt: it names the
file and asks the agent to save changes back to it. The note is the same for every task, condition and repeat, so
the rendered prompt is identical across conditions. Directory names are opaque counters: the agent sees its
working directory, which must not name the task.

**Order.** Every task is prepared (injected, rendered and linted) before any agent runs, so a prompt that fails the
lint stops the run with exit 2 and nothing executed. Then, for each repeat pass, each condition runs the same task
list in the same order.

**Verification.** After the agent exits the harness loads ``model.idf``:

- fault: ``FaultType.verify(final, result, injected)``; ``verified_by`` is ``"simulation"`` for faults that need
  EnergyPlus (the harness simulates the final model) and ``"check"`` otherwise;
- control: fixed when there is no false fix (``diff.false_fix``); ``"check"``;
- authoring: ``TaskSpec.verify(final, result, final_text)``; ``"simulation"`` or ``"check"`` as for faults;
- question: ``TaskSpec.verify(reference, reference_result, final_text)`` on the unmodified model; ``"answer_key"``.

A final model that does not load is not fixed, and is a false fix on a control. Planned skips (FR-043) and tasks
whose injection or answer key failed on a model are recorded as ``verified_by="skipped"`` with the reason, for
every condition and repeat. Simulations use ``--weather`` when given, otherwise a design-day run.

**Unwanted changes** (``diff``): changed objects outside the fault's effective scope for fault tasks; any change for
controls and questions (their scope is empty); none for authoring tasks, which declare no scope.
"""

from __future__ import annotations

import json
import shutil
import string
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

from eval.conditions import build_conditions
from eval.config import BaselineConfig, ConfigError, ReferenceModel, RunnerConfig
from eval.diff import Snapshot, diff, false_fix, first_edit_target, snapshot, unwanted_changes
from eval.held_out import HeldOutReport
from eval.lint import check_prompt
from eval.model import (
    OUTCOMES_FILE,
    RUN_FILE,
    TRANSCRIPTS_DIR,
    BaselineKind,
    Condition,
    EvaluationRun,
    EvaluationTask,
    FaultType,
    InjectedFault,
    ObjectKey,
    TaskOutcome,
    TaskSpec,
    VerifiedBy,
    save_run,
)
from eval.parsers import ParsedTranscript, Parser, get_parser
from eval.registry import PlannedTask, Registry, Selection
from eval.report import write_summary
from eval.runner import ServerCommand, build_argv, run_agent, write_mcp_config

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

EXIT_OK = 0

MODEL_FILE = "model.idf"
MODEL_NOTE = (
    "\n\nThe model is the EnergyPlus file model.idf in the current working directory. "
    "If you change the model, save it back to that file before you finish."
)
TASKS_FILE = "tasks.jsonl"
PILOT_FILE = "pilot.json"

_SUCCESS = {
    "fault": "the fault type's verifier accepts the final model",
    "control": "no model change and no reported fault",
    "authoring": "the task's verifier accepts the final model (connection check clean and it simulates)",
    "question": "the final answer matches the key computed from the unmodified model",
}


@dataclass(frozen=True)
class RunConfig:
    """Everything ``run`` resolved before executing: the input of ``execute_run``."""

    registry: Registry
    selection: Selection
    models: list[ReferenceModel]
    runner: RunnerConfig
    baseline_kind: BaselineKind
    baseline: BaselineConfig | None
    baseline_command: str | None
    treatment_command: str
    repeats: int
    out_dir: Path
    bootstrap_seed: int
    bootstrap_resamples: int
    prompts: dict[str, str]
    held_out: HeldOutReport | None
    energyplus_dir: Path | None
    example_files: Path | None
    weather: Path | None = None

    @property
    def held_out_invalid(self) -> list[str]:
        return [] if self.held_out is None else self.held_out.invalid


@dataclass
class PreparedTask:
    """One planned task after injection and rendering. ``skip_reason`` set means it will not run."""

    planned: PlannedTask
    skip_reason: str | None = None
    fault: FaultType | None = None
    spec: TaskSpec | None = None
    injected: InjectedFault | None = None
    task: EvaluationTask | None = None
    start_file: Path | None = None
    start: Snapshot | None = None
    scope: list[ObjectKey] = field(default_factory=list[ObjectKey])
    intended_tools: list[str] = field(default_factory=list[str])
    reference: tuple[IDFDocument, SimulationResult | None] | None = None


def execute_run(config: RunConfig, plan: Sequence[PlannedTask]) -> int:
    """Execute a prepared run and write ``run.json``, ``outcomes.jsonl``, ``tasks.jsonl``, ``transcripts/`` and
    ``summary.md`` into ``config.out_dir``. Configuration errors (``ConfigError``, ``PromptLintError``,
    ``GitError``) are raised before any agent runs."""
    parser = get_parser(config.runner.parse)
    _check_executable(config.runner.command[0])
    workroot = Path(tempfile.mkdtemp(prefix="idfkit-eval-"))
    try:
        tasks = prepare_tasks(config, plan, workroot)
        env = {"ENERGYPLUS_DIR": str(config.energyplus_dir)} if config.energyplus_dir is not None else {}
        with build_conditions(
            treatment_command=config.treatment_command,
            baseline=config.baseline,
            baseline_command=config.baseline_command,
            ablation=config.runner.ablation,
            env=env,
        ) as conditions:
            run = EvaluationRun(
                run_id=config.out_dir.resolve().name,
                started_at=_now(),
                runner_command=" ".join(config.runner.command),
                model_identifier=config.runner.model,
                baseline_kind=config.baseline_kind,
                baseline_sha=conditions.baseline_sha if config.baseline_command is None else "",
                baseline_idfkit=conditions.baseline_idfkit if config.baseline_command is None else "",
                treatment_revision=conditions.treatment_revision,
                disallowed_tools=list(config.runner.disallowed_tools),
                repeats=config.repeats,
                bootstrap_seed=config.bootstrap_seed,
                bootstrap_resamples=config.bootstrap_resamples,
                held_out_invalid=config.held_out_invalid,
                baseline_command=conditions.baseline.display() if conditions.baseline is not None else None,
                treatment_command=conditions.treatment.display(),
            )
            if conditions.baseline is not None:
                arms: list[tuple[Condition, ServerCommand, list[str]]] = [
                    ("baseline", conditions.baseline, []),
                    ("treatment", conditions.treatment, []),
                ]
            else:
                arms = [
                    ("treatment", conditions.treatment, []),
                    ("ablation", conditions.treatment, list(config.runner.disallowed_tools)),
                ]
            outcomes = _run_all(config, tasks, arms, run, parser, workroot)
        run = replace(run, outcomes=outcomes, finished_at=_now())
        save_run(run, config.out_dir)
        write_summary(run, config.registry, config.out_dir)
    finally:
        shutil.rmtree(workroot, ignore_errors=True)
    _err(f"run complete: {config.out_dir}")
    return EXIT_OK


def execute_pilot(config: RunConfig, plan: Sequence[PlannedTask]) -> int:
    """Run the baseline condition once per runnable task and write ``pilot.json`` and ``transcripts/``.

    The pilot is a screen, not an evaluation: it writes no ``run.json`` and decides nothing. ``run --skip-solved``
    reads it to drop the fault, question and authoring tasks the baseline already solves, which cannot show a
    difference between the conditions. Controls are never dropped.
    """
    parser = get_parser(config.runner.parse)
    _check_executable(config.runner.command[0])
    if config.baseline is None and config.baseline_command is None:
        raise ConfigError("the pilot needs a baseline condition")
    started = _now()
    workroot = Path(tempfile.mkdtemp(prefix="idfkit-eval-pilot-"))
    try:
        tasks = prepare_tasks(config, plan, workroot)
        env = {"ENERGYPLUS_DIR": str(config.energyplus_dir)} if config.energyplus_dir is not None else {}
        with build_conditions(
            treatment_command=config.treatment_command,
            baseline=config.baseline,
            baseline_command=config.baseline_command,
            ablation=False,
            env=env,
        ) as conditions:
            assert conditions.baseline is not None  # noqa: S101
            (config.out_dir / TRANSCRIPTS_DIR).mkdir(parents=True, exist_ok=True)
            runnable = [t for t in tasks if t.skip_reason is None]
            results: dict[str, bool] = {}
            for counter, item in enumerate(runnable, start=1):
                outcome = _run_one(config, item, "baseline", 0, conditions.baseline, [], parser, workroot, counter)
                results[item.planned.task_id] = outcome.fixed
                state = "fixed" if outcome.fixed else "not fixed"
                _err(f"[pilot {counter}/{len(runnable)}] {item.planned.task_id} baseline: {state}")
        pilot = {
            "model_identifier": config.runner.model,
            "baseline_command": conditions.baseline.display(),
            "started_at": started,
            "finished_at": _now(),
            "fixed": results,
        }
        (config.out_dir / PILOT_FILE).write_text(json.dumps(pilot, indent=2) + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(workroot, ignore_errors=True)
    _err(f"pilot complete: {config.out_dir / PILOT_FILE}")
    return EXIT_OK


def load_solved(pilot_dir: Path) -> set[str]:
    """The task ids a pilot's baseline fixed, from ``<pilot_dir>/pilot.json``."""
    path = pilot_dir / PILOT_FILE
    if not path.is_file():
        raise ConfigError(f"--skip-solved {pilot_dir}: no {PILOT_FILE}")
    data = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    fixed = data.get("fixed")
    if not isinstance(fixed, dict):
        raise ConfigError(f"{path}: expected an object 'fixed'")
    return {str(task_id) for task_id, ok in cast("dict[str, object]", fixed).items() if ok is True}


# --- preparation -----------------------------------------------------------------------------------------------------


def prepare_tasks(config: RunConfig, plan: Sequence[PlannedTask], workroot: Path) -> list[PreparedTask]:
    """Inject, render and lint every planned task, in plan order. Raises ``PromptLintError`` on the first prompt
    that fails the lint and ``ConfigError`` for a template whose placeholder has no value."""
    from idfkit import load_idf, save_idf

    prepared: list[PreparedTask] = []
    for index, planned in enumerate(plan):
        item = PreparedTask(planned=planned, skip_reason=planned.skip_reason)
        prepared.append(item)
        if planned.kind == "fault":
            item.fault = config.registry.fault(planned.spec_id)
            item.intended_tools = list(item.fault.intended_tools)
        else:
            item.spec = config.registry.task(planned.spec_id)
            item.intended_tools = list(item.spec.intended_tools)
        if item.skip_reason is not None:
            continue
        try:
            doc = load_idf(str(planned.model_path))
        except Exception as exc:
            item.skip_reason = f"reference model does not load: {exc}"
            _err(f"skip {planned.task_id}: {item.skip_reason}")
            continue
        values = default_prompt_values(doc)
        answer_key: str | None = None
        object_names: list[str] = []
        field_names: list[str] = []
        try:
            if item.fault is not None:
                item.injected = item.fault.inject(doc)
                item.scope = item.fault.effective_scope(item.injected)
                values.update(item.injected.prompt_values)
                object_names, field_names = item.injected.object_names, item.injected.field_names
                template = item.fault.prompt_template
            else:
                assert item.spec is not None  # noqa: S101 - set above for every non-fault task
                if item.spec.prompt_values is not None:
                    values = item.spec.prompt_values(doc)
                if item.spec.answer_key is not None:
                    answer_key = item.spec.answer_key(doc)
                template = item.spec.prompt_template
        except Exception as exc:
            step = "inject" if item.fault is not None else "prompt_values or answer_key"
            item.skip_reason = f"{step} failed on {planned.model.id}: {exc!r}"
            _err(f"skip {planned.task_id}: {item.skip_reason}")
            continue
        body = render_prompt(template, values, label=planned.task_id)
        fault_id = item.fault.id if item.fault is not None else None
        check_prompt(
            f"{planned.task_id} prompt", body, object_names=object_names, field_names=field_names, fault_id=fault_id
        )
        prompt = body + MODEL_NOTE
        check_prompt(f"{planned.task_id} prompt", prompt, fault_id=fault_id)
        task_dir = workroot / "tasks" / f"t{index:04d}"
        task_dir.mkdir(parents=True)
        item.start_file = task_dir / "start.idf"
        save_idf(doc, item.start_file)
        item.start = snapshot(load_idf(str(item.start_file)))
        item.task = EvaluationTask(
            id=planned.task_id,
            kind=planned.kind,
            fault_id=fault_id,
            model_file=planned.model.file,
            prompt=prompt,
            answer_key=answer_key,
            success=_SUCCESS[planned.kind],
            intended_tools=item.intended_tools,
        )
    _write_tasks(config.out_dir, prepared)
    return prepared


def default_prompt_values(doc: IDFDocument) -> dict[str, str]:
    """Fallback values for the shared placeholders: ``{zone}``, ``{air_loop}`` and ``{plant_loop}`` are the first
    ``Zone``, ``AirLoopHVAC`` and ``PlantLoop`` in the model. A fault's ``InjectedFault.prompt_values`` override
    them; a task spec with ``prompt_values`` uses that instead."""
    wanted = {"zone": "zone", "airloophvac": "air_loop", "plantloop": "plant_loop"}
    values: dict[str, str] = {}
    for obj in doc.all_objects:
        key = wanted.get(obj.obj_type.casefold())
        if key is not None and key not in values and obj.name:
            values[key] = obj.name
    return values


def render_prompt(template: str, values: Mapping[str, str], *, label: str) -> str:
    """Fill ``{placeholder}`` fields; ``ConfigError`` when one has no value."""
    names = {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}
    missing = sorted(name for name in names if name not in values)
    if missing:
        raise ConfigError(f"{label}: no value for prompt placeholders {missing}")
    return template.format_map(dict(values))


# --- execution -------------------------------------------------------------------------------------------------------


def _run_all(
    config: RunConfig,
    tasks: Sequence[PreparedTask],
    arms: Sequence[tuple[Condition, ServerCommand, list[str]]],
    run: EvaluationRun,
    parser: Parser,
    workroot: Path,
) -> list[TaskOutcome]:
    out = config.out_dir
    (out / TRANSCRIPTS_DIR).mkdir(parents=True, exist_ok=True)
    (out / RUN_FILE).write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")
    outcomes: list[TaskOutcome] = []
    total = config.repeats * len(arms) * len(tasks)
    counter = 0
    with (out / OUTCOMES_FILE).open("w", encoding="utf-8") as stream:
        for repeat in range(config.repeats):
            for condition, server, disallowed in arms:
                for item in tasks:
                    counter += 1
                    if item.skip_reason is not None:
                        outcome = _skipped(item, condition, repeat, item.skip_reason)
                    else:
                        outcome = _run_one(
                            config, item, condition, repeat, server, disallowed, parser, workroot, counter
                        )
                    outcomes.append(outcome)
                    stream.write(json.dumps(outcome.to_dict()) + "\n")
                    stream.flush()
                    state = "skipped" if outcome.skipped else ("fixed" if outcome.fixed else "not fixed")
                    _err(f"[{counter}/{total}] {item.planned.task_id} {condition} repeat {repeat}: {state}")
    return outcomes


def _run_one(
    config: RunConfig,
    item: PreparedTask,
    condition: Condition,
    repeat: int,
    server: ServerCommand,
    disallowed: Sequence[str],
    parser: Parser,
    workroot: Path,
    counter: int,
) -> TaskOutcome:
    from idfkit import load_idf

    assert item.task is not None and item.start_file is not None and item.start is not None  # noqa: S101
    workdir = workroot / "work" / f"w{counter:05d}"
    workdir.mkdir(parents=True)
    model_path = workdir / MODEL_FILE
    shutil.copyfile(item.start_file, model_path)
    mcp_config = write_mcp_config(workroot / "work" / f"w{counter:05d}.mcp.json", server, workdir=workdir)
    argv = build_argv(config.runner, prompt=item.task.prompt, mcp_config=mcp_config, disallowed_tools=disallowed)
    rel = Path(TRANSCRIPTS_DIR) / f"{item.planned.task_id}.{condition}.{repeat}.jsonl"
    agent = run_agent(argv, cwd=workdir, transcript=config.out_dir / rel, timeout_seconds=config.runner.timeout_seconds)
    if agent.timed_out or agent.returncode != 0:
        why = "timed out" if agent.timed_out else f"exited {agent.returncode}"
        _err(f"warning: {item.planned.task_id} {condition} repeat {repeat}: the agent {why} (see {rel})")
    parsed = parser(agent.read_transcript())

    final: IDFDocument | None
    try:
        final = load_idf(str(model_path))
    except Exception as exc:
        _err(f"warning: {item.planned.task_id} {condition} repeat {repeat}: the final model does not load: {exc}")
        final = None
    changes = diff(item.start, snapshot(final)) if final is not None else None
    fixed, verified_by = _verify(config, item, final, parsed, workdir)
    kind = item.planned.kind
    is_false_fix = kind == "control" and false_fix(changes, parsed)
    if kind == "control":
        fixed = not is_false_fix
    unwanted = 0 if changes is None or kind == "authoring" else unwanted_changes(changes, item.scope)
    used = parsed.new_tools_used()
    called = {call.name for call in parsed.tool_calls if call.server is not None}
    intended_used = (
        None if condition == "baseline" or not item.intended_tools else bool(called & set(item.intended_tools))
    )
    top_edited, top_correct, first_correct = _anchoring(item, parsed)
    return TaskOutcome(
        task_id=item.planned.task_id,
        condition=condition,
        repeat=repeat,
        fixed=fixed,
        verified_by=verified_by,
        skip_reason=None,
        tool_calls=len(parsed.tool_calls),
        response_tokens=parsed.response_tokens,
        unwanted_changes=unwanted,
        false_fix=is_false_fix,
        tools_used=used,
        intended_tool_used=intended_used,
        top_candidate_edited=top_edited,
        top_candidate_correct=top_correct,
        transcript_path=rel.as_posix(),
        first_edit_correct=first_correct,
    )


def _verify(
    config: RunConfig, item: PreparedTask, final: IDFDocument | None, parsed: ParsedTranscript, workdir: Path
) -> tuple[bool, VerifiedBy]:
    """``(fixed, verified_by)``; a verifier that raises counts as not fixed, with a warning."""
    kind = item.planned.kind
    needs_ep = item.planned.needs_energyplus
    by: VerifiedBy = "simulation" if needs_ep else "check"
    if kind == "control":
        return False, "check"  # decided from the diff by the caller
    if kind == "question":
        by = "answer_key"
    label = f"{item.planned.task_id} verify"
    try:
        if kind == "question":
            assert item.spec is not None and item.spec.verify is not None  # noqa: S101
            reference, result = _reference(config, item, workdir)
            return bool(item.spec.verify(reference, result, parsed.final_text)), by
        if final is None:
            return False, by
        result = simulate_model(final, config=config, output_dir=workdir / "verify-sim") if needs_ep else None
        if item.fault is not None:
            assert item.injected is not None  # noqa: S101
            return bool(item.fault.verify(final, result, item.injected)), by
        assert item.spec is not None and item.spec.verify is not None  # noqa: S101
        return bool(item.spec.verify(final, result, parsed.final_text)), by
    except Exception as exc:
        _err(f"warning: {label} raised {exc!r}; counted as not fixed")
        return False, by


def _reference(config: RunConfig, item: PreparedTask, workdir: Path) -> tuple[IDFDocument, SimulationResult | None]:
    """The unmodified model of a question task (and its simulation when the task needs EnergyPlus), once."""
    from idfkit import load_idf

    if item.reference is None:
        assert item.start_file is not None  # noqa: S101
        doc = load_idf(str(item.start_file))
        result = (
            simulate_model(doc, config=config, output_dir=workdir / "reference-sim")
            if item.planned.needs_energyplus
            else None
        )
        item.reference = (doc, result)
    return item.reference


def simulate_model(doc: IDFDocument, *, config: RunConfig, output_dir: Path) -> SimulationResult | None:
    """Simulate for verification: with ``config.weather`` when set, otherwise design days only. ``None`` when
    EnergyPlus raised; a run that failed inside EnergyPlus is returned for the verifier to read."""
    from idfkit.simulation import simulate
    from idfkit.simulation.config import find_energyplus

    try:
        energyplus = find_energyplus(path=config.energyplus_dir)
        return simulate(
            doc, config.weather, output_dir=output_dir, energyplus=energyplus, design_day=config.weather is None
        )
    except Exception as exc:
        _err(f"warning: verification simulation failed: {exc!r}")
        return None


def _anchoring(item: PreparedTask, parsed: ParsedTranscript) -> tuple[bool | None, bool | None, bool | None]:
    """``(top_candidate_edited, top_candidate_correct, first_edit_correct)`` for a fault task (SC-009a, R-37).

    The top candidate is the rank-1 ``candidates`` entry of the first successful ``diagnose_symptom`` result; the
    first edit is ``diff.first_edit_target``. All three are ``None`` for other task kinds; the first two are
    ``None`` when no ``diagnose_symptom`` result names a candidate, the third when the agent changed nothing."""
    if item.planned.kind != "fault":
        return None, None, None
    first = first_edit_target(parsed)
    first_correct = None if first is None else in_scope(first, item.scope)
    top = top_candidate(parsed)
    if top is None:
        return None, None, first_correct
    return first == top, in_scope(top, item.scope), first_correct


def top_candidate(parsed: ParsedTranscript) -> ObjectKey | None:
    """The rank-1 candidate of the first successful ``diagnose_symptom`` call, if its result names one."""
    for call in parsed.tool_calls:
        if call.server is None or call.name != "diagnose_symptom" or call.is_error:
            continue
        data = call.result_json()
        if not isinstance(data, dict):
            continue
        candidates = cast(dict[str, object], data).get("candidates")
        if not isinstance(candidates, list) or not candidates:
            continue
        items = [cast(dict[str, object], c) for c in cast(list[object], candidates) if isinstance(c, dict)]
        ranked = sorted(items, key=_rank)
        obj = ranked[0].get("object") if ranked else None
        if isinstance(obj, dict):
            key = cast(dict[str, object], obj)
            object_type, name = key.get("object_type"), key.get("name")
            if isinstance(object_type, str) and isinstance(name, str):
                return ObjectKey(object_type, name)
    return None


def in_scope(key: ObjectKey, scope: Sequence[ObjectKey]) -> bool:
    """``key`` is in ``scope``, or ``scope`` covers its whole type with an empty name."""
    return key in scope or any(not s.name and s.object_type.casefold() == key.object_type.casefold() for s in scope)


def _rank(candidate: Mapping[str, object]) -> int:
    rank = candidate.get("rank")
    return rank if isinstance(rank, int) and not isinstance(rank, bool) else sys.maxsize


def _skipped(item: PreparedTask, condition: Condition, repeat: int, reason: str) -> TaskOutcome:
    return TaskOutcome(
        task_id=item.planned.task_id,
        condition=condition,
        repeat=repeat,
        fixed=False,
        verified_by="skipped",
        skip_reason=reason,
        tool_calls=0,
        response_tokens=0,
        unwanted_changes=0,
        false_fix=False,
        tools_used=[],
        intended_tool_used=None,
        top_candidate_edited=None,
        top_candidate_correct=None,
        transcript_path="",
    )


def _write_tasks(out_dir: Path, tasks: Sequence[PreparedTask]) -> None:
    """``tasks.jsonl``: one ``EvaluationTask`` per prepared task (the rendered prompt, the answer key)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for item in tasks:
        data: dict[str, object]
        if item.task is not None:
            data = {**asdict(item.task), "skip_reason": None}
        else:
            data = {"id": item.planned.task_id, "kind": item.planned.kind, "skip_reason": item.skip_reason}
        lines.append(json.dumps(data))
    (out_dir / TASKS_FILE).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _check_executable(command: str) -> None:
    if shutil.which(command) is None and not Path(command).is_file():
        raise ConfigError(f"the runner command {command!r} is not found")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _err(message: str) -> None:
    print(message, file=sys.stderr)
