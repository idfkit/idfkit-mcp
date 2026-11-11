"""Data model of the evaluation harness, mirroring data-model.md "Evaluation".

Field names and ``Literal`` values follow data-model.md exactly. Where the harness needs something the table does
not define, it is added here and named in the docstring of the class that carries it:

- ``ObjectKey`` and ``InjectedFault`` are local: idfkit 1.2.0 has no ``ObjectKey`` yet, and ``inject`` needs a
  return type.
- ``FaultType.verify`` also receives the ``InjectedFault`` its ``inject`` returned, because a verifier usually
  needs to know which object it changed. ``TaskSpec.verify`` also receives the agent's final answer text, because
  question tasks compare it with the key.
- ``TaskSpec.answer_key`` holds the function that computes a question's key from the unmodified model.
- ``TaskSpec.prompt_values`` computes the values of the template's placeholders from the unmodified model, the
  counterpart of ``InjectedFault.prompt_values`` for fault tasks. The registry sets it for control tasks
  (``support.default_prompt_values``); ``None`` means the template has no placeholders.
- ``EvaluationRun`` adds ``finished_at`` (the contract's run.json records "timestamps") and ``held_out_invalid``
  (the contract's rule: an invalid held-out fault "is recorded as ``held_out_invalid``"); ``ablation`` is derived
  from ``disallowed_tools``. It also records the server commands of both conditions (``baseline_command``,
  ``treatment_command``), since a ``baseline_kind="other"`` run has no baseline SHA.
- ``TaskOutcome.first_edit_correct`` is the baseline's side of SC-009a (research R-37): for fault tasks, whether
  the agent's first model-changing tool call targeted an object in the fault's scope. The baseline never calls
  ``diagnose_symptom``, so "changed a wrong object first" is what its "changed a wrong top candidate" is compared
  with (``stats.metric_value``).

Task ids follow one convention, set by ``make_task_id``: ``"<fault or task spec id>@<reference model id>"``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias, TypeVar, cast, get_args

if TYPE_CHECKING:
    from idfkit import IDFDocument
    from idfkit.simulation.result import SimulationResult

Layer = Literal["topology", "results"]
TaskKind = Literal["fault", "control", "authoring", "question"]
SpecKind = Literal["control", "authoring", "question"]
Condition = Literal["baseline", "treatment", "ablation"]
VerifiedBy = Literal["check", "simulation", "answer_key", "skipped"]
BaselineKind = Literal["pre_feature", "other"]
Metric = Literal[
    "fix_rate", "tool_calls", "response_tokens", "unwanted_changes", "false_fix_rate", "wrong_top_candidate_rate"
]
Effect = Literal["fix_rate", "tool_calls"]

LAYERS: tuple[Layer, ...] = get_args(Layer)
METRICS: tuple[Metric, ...] = get_args(Metric)

MIN_REPEATS = 3
"""FR-042a: every task runs at least three times per condition."""

TASK_ID_SEPARATOR = "@"

OUTCOMES_FILE = "outcomes.jsonl"
RUN_FILE = "run.json"
TRANSCRIPTS_DIR = "transcripts"


@dataclass(frozen=True, eq=False)
class ObjectKey:
    """An object's identity: type and name, compared case-insensitively (data-model.md, Shared)."""

    object_type: str
    name: str

    def _folded(self) -> tuple[str, str]:
        return (self.object_type.casefold(), self.name.casefold())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ObjectKey):
            return NotImplemented
        return self._folded() == other._folded()

    def __hash__(self) -> int:
        return hash(self._folded())


@dataclass(frozen=True)
class InjectedFault:
    """What ``FaultType.inject`` did to one model.

    Attributes:
        scope: Objects the fault touched. Changes outside it (and outside ``FaultType.scope``) are unwanted.
        object_names: Names the rendered prompt must not contain (the injected objects).
        field_names: Field names the rendered prompt must not contain.
        prompt_values: Values for the placeholders of the prompt template, for example ``{"zone": "SPACE1-1"}``.
        details: Free-form facts the verifier needs, for example the original field value.
    """

    scope: list[ObjectKey]
    object_names: list[str] = field(default_factory=list[str])
    field_names: list[str] = field(default_factory=list[str])
    prompt_values: dict[str, str] = field(default_factory=dict[str, str])
    details: dict[str, str] = field(default_factory=dict[str, str])


Injector: TypeAlias = "Callable[[IDFDocument], InjectedFault]"
FaultVerifier: TypeAlias = "Callable[[IDFDocument, SimulationResult | None, InjectedFault], bool]"
TaskVerifier: TypeAlias = "Callable[[IDFDocument, SimulationResult | None, str | None], bool]"
AnswerKey: TypeAlias = "Callable[[IDFDocument], str]"
PromptValues: TypeAlias = "Callable[[IDFDocument], dict[str, str]]"


@dataclass(frozen=True)
class FaultType:
    """A fault type, defined by a module under ``eval/faults/`` (designed) or ``eval/faults/held_out/``.

    ``scope`` is the static part of the scope; ``inject`` returns the per-model scope in ``InjectedFault.scope``,
    and the effective scope is their union (``effective_scope``). ``defined_in_commit`` is filled by the registry
    from git (R-33); a fault module leaves it empty. ``held_out`` must match the directory the module is in.
    """

    id: str
    layer: Layer
    description: str
    held_out: bool
    applies_to: list[str]
    intended_tools: list[str]
    prompt_template: str
    needs_energyplus: bool
    inject: Injector
    verify: FaultVerifier
    defined_in_commit: str = ""
    scope: list[ObjectKey] = field(default_factory=list[ObjectKey])

    def __post_init__(self) -> None:
        _check_literal(self.layer, Layer, "FaultType.layer")
        if self.held_out and self.intended_tools:
            raise ValueError(f"held-out fault {self.id!r} must have no intended_tools")

    def effective_scope(self, injected: InjectedFault) -> list[ObjectKey]:
        """The static scope and the injected scope, without duplicates, in order."""
        seen: dict[ObjectKey, None] = {}
        for key in [*self.scope, *injected.scope]:
            seen.setdefault(key, None)
        return list(seen)


@dataclass(frozen=True)
class TaskSpec:
    """A non-fault task: one module under ``eval/tasks/authoring|questions/`` or an entry of ``controls.toml``.

    ``verify`` is required for authoring and question tasks; control tasks are decided by the diff (any model change
    or any reported fault is a false fix), so theirs is ``None``. ``answer_key`` is required for question tasks.
    ``prompt_values`` fills the template's placeholders from the unmodified model (``None``: no placeholders).
    """

    id: str
    kind: SpecKind
    layer: Layer
    applies_to: list[str]
    prompt_template: str
    intended_tools: list[str]
    needs_energyplus: bool
    verify: TaskVerifier | None = None
    answer_key: AnswerKey | None = None
    prompt_values: PromptValues | None = None

    def __post_init__(self) -> None:
        _check_literal(self.kind, SpecKind, "TaskSpec.kind")
        _check_literal(self.layer, Layer, "TaskSpec.layer")
        if self.kind in ("authoring", "question") and self.verify is None:
            raise ValueError(f"{self.kind} task {self.id!r} needs a verify function")
        if self.kind == "question" and self.answer_key is None:
            raise ValueError(f"question task {self.id!r} needs an answer_key function")
        if self.kind == "control" and self.intended_tools:
            raise ValueError(f"control task {self.id!r} must have no intended_tools")


@dataclass(frozen=True)
class EvaluationTask:
    """One concrete task: a fault or spec applied to one reference model, with its rendered prompt."""

    id: str
    kind: TaskKind
    fault_id: str | None
    model_file: str
    prompt: str
    answer_key: str | None
    success: str
    intended_tools: list[str]

    def __post_init__(self) -> None:
        _check_literal(self.kind, TaskKind, "EvaluationTask.kind")
        if (self.kind == "fault") != (self.fault_id is not None):
            raise ValueError(f"task {self.id!r}: fault_id is set exactly for fault tasks")


@dataclass(frozen=True)
class TaskOutcome:
    """One task, condition and repeat (one line of ``outcomes.jsonl``). ``repeat`` is 0-based."""

    task_id: str
    condition: Condition
    repeat: int
    fixed: bool
    verified_by: VerifiedBy
    skip_reason: str | None
    tool_calls: int
    response_tokens: int
    unwanted_changes: int
    false_fix: bool
    tools_used: list[str]
    intended_tool_used: bool | None
    top_candidate_edited: bool | None
    top_candidate_correct: bool | None
    transcript_path: str
    first_edit_correct: bool | None = None

    def __post_init__(self) -> None:
        _check_literal(self.condition, Condition, "TaskOutcome.condition")
        _check_literal(self.verified_by, VerifiedBy, "TaskOutcome.verified_by")
        if self.repeat < 0:
            raise ValueError(f"repeat must be 0-based, got {self.repeat}")
        if self.verified_by == "skipped" and not self.skip_reason:
            raise ValueError(f"outcome {self.task_id!r}: skip_reason is required when skipped")

    @property
    def skipped(self) -> bool:
        return self.verified_by == "skipped"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> TaskOutcome:
        return cls(
            task_id=_req(data, "task_id", str),
            condition=cast(Condition, _req(data, "condition", str)),
            repeat=_req(data, "repeat", int),
            fixed=_req(data, "fixed", bool),
            verified_by=cast(VerifiedBy, _req(data, "verified_by", str)),
            skip_reason=_opt(data, "skip_reason", str),
            tool_calls=_req(data, "tool_calls", int),
            response_tokens=_req(data, "response_tokens", int),
            unwanted_changes=_req(data, "unwanted_changes", int),
            false_fix=_req(data, "false_fix", bool),
            tools_used=_str_list(data, "tools_used"),
            intended_tool_used=_opt(data, "intended_tool_used", bool),
            top_candidate_edited=_opt(data, "top_candidate_edited", bool),
            top_candidate_correct=_opt(data, "top_candidate_correct", bool),
            transcript_path=_req(data, "transcript_path", str),
            first_edit_correct=_opt(data, "first_edit_correct", bool),
        )


@dataclass(frozen=True)
class EvaluationRun:
    """One evaluation run (``run.json``; the outcomes are written to ``outcomes.jsonl``)."""

    run_id: str
    started_at: str
    runner_command: str
    model_identifier: str
    baseline_kind: BaselineKind
    baseline_sha: str
    baseline_idfkit: str
    treatment_revision: str
    disallowed_tools: list[str]
    repeats: int
    bootstrap_seed: int
    bootstrap_resamples: int
    outcomes: list[TaskOutcome] = field(default_factory=list[TaskOutcome])
    finished_at: str | None = None
    held_out_invalid: list[str] = field(default_factory=list[str])
    baseline_command: str | None = None
    treatment_command: str | None = None

    def __post_init__(self) -> None:
        _check_literal(self.baseline_kind, BaselineKind, "EvaluationRun.baseline_kind")
        if self.repeats < MIN_REPEATS:
            raise ValueError(f"repeats must be at least {MIN_REPEATS} (FR-042a), got {self.repeats}")

    @property
    def ablation(self) -> bool:
        """Ablation runs disallow tools on the agent side (R-31) and never decide SC-009."""
        return bool(self.disallowed_tools)

    def to_dict(self, *, include_outcomes: bool = False) -> dict[str, object]:
        data = asdict(self)
        data["ablation"] = self.ablation
        if not include_outcomes:
            del data["outcomes"]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object], outcomes: Iterable[TaskOutcome] = ()) -> EvaluationRun:
        return cls(
            run_id=_req(data, "run_id", str),
            started_at=_req(data, "started_at", str),
            runner_command=_req(data, "runner_command", str),
            model_identifier=_req(data, "model_identifier", str),
            baseline_kind=cast(BaselineKind, _req(data, "baseline_kind", str)),
            baseline_sha=_req(data, "baseline_sha", str),
            baseline_idfkit=_req(data, "baseline_idfkit", str),
            treatment_revision=_req(data, "treatment_revision", str),
            disallowed_tools=_str_list(data, "disallowed_tools"),
            repeats=_req(data, "repeats", int),
            bootstrap_seed=_req(data, "bootstrap_seed", int),
            bootstrap_resamples=_req(data, "bootstrap_resamples", int),
            outcomes=list(outcomes),
            finished_at=_opt(data, "finished_at", str),
            held_out_invalid=_str_list(data, "held_out_invalid") if "held_out_invalid" in data else [],
            baseline_command=_opt(data, "baseline_command", str),
            treatment_command=_opt(data, "treatment_command", str),
        )


@dataclass(frozen=True)
class Comparison:
    """One metric over one scope, from paired task means (R-32). ``difference`` is treatment minus baseline."""

    scope: str
    metric: Metric
    tasks: int
    baseline: float
    treatment: float
    difference: float
    ci_low: float
    ci_high: float
    descriptive_only: bool

    def __post_init__(self) -> None:
        _check_literal(self.metric, Metric, "Comparison.metric")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GateVerdict:
    """The SC-009 decision for one layer, with each clause."""

    effect: Effect | None
    ci_excludes_zero: bool
    held_out_direction: bool
    no_more_unwanted_changes: bool
    no_more_false_fixes: bool
    wrong_top_candidate_ok: bool | None
    valid: bool
    passes: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def make_task_id(spec_id: str, model_id: str) -> str:
    """The id of the task applying fault or task spec ``spec_id`` to reference model ``model_id``."""
    if TASK_ID_SEPARATOR in spec_id or TASK_ID_SEPARATOR in model_id:
        raise ValueError(f"ids must not contain {TASK_ID_SEPARATOR!r}: {spec_id!r}, {model_id!r}")
    return f"{spec_id}{TASK_ID_SEPARATOR}{model_id}"


def split_task_id(task_id: str) -> tuple[str, str]:
    """Inverse of ``make_task_id``: ``(spec_id, model_id)``."""
    spec_id, sep, model_id = task_id.partition(TASK_ID_SEPARATOR)
    if not sep:
        raise ValueError(f"not a task id: {task_id!r}")
    return spec_id, model_id


def save_run(run: EvaluationRun, out_dir: Path) -> None:
    """Write ``run.json`` and ``outcomes.jsonl`` into ``out_dir`` (created if missing)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / RUN_FILE).write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")
    lines = [json.dumps(outcome.to_dict()) for outcome in run.outcomes]
    (out_dir / OUTCOMES_FILE).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def load_run(run_dir: Path) -> EvaluationRun:
    """Read a run directory written by ``save_run``. ``outcomes.jsonl`` may be absent (it is not committed)."""
    raw: object = json.loads((run_dir / RUN_FILE).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"{run_dir / RUN_FILE}: expected a JSON object")
    outcomes: list[TaskOutcome] = []
    outcomes_path = run_dir / OUTCOMES_FILE
    if outcomes_path.is_file():
        for line in outcomes_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item: object = json.loads(line)
                if not isinstance(item, dict):
                    raise TypeError(f"{outcomes_path}: expected one JSON object per line")
                outcomes.append(TaskOutcome.from_dict(cast(dict[str, object], item)))
    return EvaluationRun.from_dict(cast(dict[str, object], raw), outcomes)


_T = TypeVar("_T", str, int, bool)


def _req(data: Mapping[str, object], key: str, kind: type[_T]) -> _T:
    if key not in data:
        raise KeyError(key)
    value = data[key]
    # bool is a subclass of int: an int field must not accept True/False.
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise TypeError(f"{key}: expected {kind.__name__}, got {type(value).__name__}")
    return value


def _opt(data: Mapping[str, object], key: str, kind: type[_T]) -> _T | None:
    if data.get(key) is None:
        return None
    return _req(data, key, kind)


def _str_list(data: Mapping[str, object], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise TypeError(f"{key}: expected a list of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise TypeError(f"{key}: expected a list of strings")
    return cast(list[str], items)


def _check_literal(value: str, literal: object, name: str) -> None:
    allowed = get_args(literal)
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
