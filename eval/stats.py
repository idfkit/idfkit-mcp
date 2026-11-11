"""Evaluation statistics (FR-042a, SC-008, SC-009; research R-32). Standard library only: ``random``, ``statistics``.

- A task's score in a condition is the mean of its repeats. Skipped outcomes (FR-043) are left out, never counted
  as failures.
- Comparisons are paired by task: the per-task difference is treatment minus baseline, summarised by its mean,
  with a 95% percentile-bootstrap interval over tasks (10,000 resamples by default, seeded).
- A fault-type scope whose interval includes zero is ``descriptive_only``.
- The SC-008 spread is the range of the overall fix rate across the repeat passes of one condition.
- The SC-009 gate is decided per layer on pooled tasks (``gate_verdict``, ``layer_gate``).
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from eval.model import (
    LAYERS,
    BaselineKind,
    Comparison,
    Condition,
    Effect,
    GateVerdict,
    Layer,
    Metric,
    TaskKind,
    TaskOutcome,
)

DEFAULT_RESAMPLES = 10_000
CONFIDENCE = 0.95
FIX_RATE_GAIN = 0.20
"""SC-009: a fix rate at least 20 percentage points higher."""
TOOL_CALL_REDUCTION = 0.30
"""SC-009: at least 30% fewer tool calls at no lower fix rate."""


def metric_value(outcome: TaskOutcome, metric: Metric) -> float | None:
    """The value one outcome contributes to ``metric``, or ``None`` when it does not contribute.

    Skipped outcomes never contribute. ``wrong_top_candidate_rate`` counts outcomes where both
    ``top_candidate_edited`` and ``top_candidate_correct`` are set: 1 when the agent edited a top candidate that
    was not the injected object. A baseline outcome has neither (the baseline has no ``diagnose_symptom``), so it
    contributes its analogue instead (SC-009a, research R-37): 1 when its first model change targeted an object
    outside the fault's scope (``first_edit_correct`` is false), 0 when it targeted the scope.
    """
    if outcome.skipped:
        return None
    if metric == "fix_rate":
        return 1.0 if outcome.fixed else 0.0
    if metric == "tool_calls":
        return float(outcome.tool_calls)
    if metric == "response_tokens":
        return float(outcome.response_tokens)
    if metric == "unwanted_changes":
        return float(outcome.unwanted_changes)
    if metric == "false_fix_rate":
        return 1.0 if outcome.false_fix else 0.0
    if outcome.top_candidate_edited is None or outcome.top_candidate_correct is None:
        if outcome.condition == "baseline" and outcome.first_edit_correct is not None:
            return 0.0 if outcome.first_edit_correct else 1.0
        return None
    return 1.0 if outcome.top_candidate_edited and not outcome.top_candidate_correct else 0.0


def task_means(
    outcomes: Iterable[TaskOutcome],
    *,
    condition: Condition,
    metric: Metric,
    task_ids: Iterable[str] | None = None,
) -> dict[str, float]:
    """Per-task mean of ``metric`` over the repeats of ``condition``. Tasks with no contributing outcome are absent."""
    wanted = None if task_ids is None else set(task_ids)
    values: dict[str, list[float]] = {}
    for outcome in outcomes:
        if outcome.condition != condition or (wanted is not None and outcome.task_id not in wanted):
            continue
        value = metric_value(outcome, metric)
        if value is not None:
            values.setdefault(outcome.task_id, []).append(value)
    return {task_id: statistics.fmean(vals) for task_id, vals in sorted(values.items())}


def bootstrap_interval(
    differences: Sequence[float],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = CONFIDENCE,
) -> tuple[float, float]:
    """Percentile-bootstrap interval of the mean of ``differences``, resampling with replacement.

    Deterministic for a given ``seed``: a fresh ``random.Random(seed)`` drives the resamples.
    """
    if not differences:
        raise ValueError("no differences to resample")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    rng = random.Random(seed)  # noqa: S311 - statistical resampling, not cryptography
    n = len(differences)
    means = sorted(statistics.fmean(rng.choices(differences, k=n)) for _ in range(resamples))
    tail = (1.0 - confidence) / 2.0
    return _percentile(means, tail), _percentile(means, 1.0 - tail)


def compare(
    outcomes: Iterable[TaskOutcome],
    *,
    scope: str,
    metric: Metric,
    seed: int,
    task_ids: Iterable[str] | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    fault_type_scope: bool = False,
    baseline_condition: Condition = "baseline",
    treatment_condition: Condition = "treatment",
) -> Comparison | None:
    """Paired comparison of ``metric`` over the tasks in ``task_ids`` (all tasks when ``None``).

    Only tasks with a mean in both conditions are paired. Returns ``None`` when no task is paired. For an ablation
    run, pass ``baseline_condition="treatment"`` and ``treatment_condition="ablation"``.
    """
    items = list(outcomes)
    ids = None if task_ids is None else list(task_ids)
    base = task_means(items, condition=baseline_condition, metric=metric, task_ids=ids)
    treat = task_means(items, condition=treatment_condition, metric=metric, task_ids=ids)
    paired = sorted(base.keys() & treat.keys())
    if not paired:
        return None
    diffs = [treat[t] - base[t] for t in paired]
    ci_low, ci_high = bootstrap_interval(diffs, seed=seed, resamples=resamples)
    return Comparison(
        scope=scope,
        metric=metric,
        tasks=len(paired),
        baseline=statistics.fmean(base[t] for t in paired),
        treatment=statistics.fmean(treat[t] for t in paired),
        difference=statistics.fmean(diffs),
        ci_low=ci_low,
        ci_high=ci_high,
        descriptive_only=fault_type_scope and ci_low <= 0.0 <= ci_high,
    )


def repeat_spread(outcomes: Iterable[TaskOutcome], *, condition: Condition) -> float | None:
    """SC-008: the range (max minus min) of the overall fix rate across the repeat passes of ``condition``.

    ``None`` when no repeat pass has a contributing outcome.
    """
    by_repeat: dict[int, list[float]] = {}
    for outcome in outcomes:
        if outcome.condition != condition:
            continue
        value = metric_value(outcome, "fix_rate")
        if value is not None:
            by_repeat.setdefault(outcome.repeat, []).append(value)
    if not by_repeat:
        return None
    rates = [statistics.fmean(values) for values in by_repeat.values()]
    return max(rates) - min(rates)


def gate_verdict(
    *,
    fix_rate: Comparison | None,
    tool_calls: Comparison | None,
    held_out_fix_rate: Comparison | None,
    held_out_tool_calls: Comparison | None,
    unwanted_changes: Comparison | None,
    false_fix_rate: Comparison | None,
    wrong_top_candidate_rate: Comparison | None = None,
    baseline_kind: BaselineKind,
    ablation: bool,
) -> GateVerdict:
    """The SC-009 verdict for one layer, each clause decided separately.

    - ``effect``: ``"fix_rate"`` when the fix rate rises by at least 20 points; otherwise ``"tool_calls"`` when
      tool calls fall by at least 30% of the baseline mean and the fix rate difference is not negative. When both
      sizes are met, the one whose interval also excludes zero is chosen, fix rate first.
    - ``ci_excludes_zero``: the interval of the effect's metric lies wholly on the improving side of zero (fix
      rate: ``ci_low > 0``; tool calls: ``ci_high < 0``). With no effect, the fix rate's interval is read.
    - ``held_out_direction``: on held-out tasks, the effect's metric (fix rate when there is no effect) moves in
      the improving direction. False when no held-out task was paired.
    - ``no_more_unwanted_changes`` / ``no_more_false_fixes``: the mean difference is not positive. False when the
      comparison is missing, since the clause cannot be shown to hold.
    - ``wrong_top_candidate_ok`` (SC-009a): ``None`` when no diagnosis task ran, otherwise the difference is not
      positive.
    - ``valid``: false for a baseline other than ``pre_feature`` and for ablation runs.
    """
    fix_size = fix_rate is not None and fix_rate.difference >= FIX_RATE_GAIN
    call_size = (
        tool_calls is not None
        and fix_rate is not None
        and fix_rate.difference >= 0.0
        and tool_calls.baseline > 0.0
        and -tool_calls.difference / tool_calls.baseline >= TOOL_CALL_REDUCTION
    )
    fix_ci = fix_rate is not None and fix_rate.ci_low > 0.0
    call_ci = tool_calls is not None and tool_calls.ci_high < 0.0

    effect: Effect | None
    if fix_size and (fix_ci or not (call_size and call_ci)):
        effect, ci_ok = "fix_rate", fix_ci
    elif call_size:
        effect, ci_ok = "tool_calls", call_ci
    else:
        effect, ci_ok = None, fix_ci

    if effect == "tool_calls":
        held_out_direction = held_out_tool_calls is not None and held_out_tool_calls.difference < 0.0
    else:
        held_out_direction = held_out_fix_rate is not None and held_out_fix_rate.difference > 0.0

    no_more_unwanted = unwanted_changes is not None and unwanted_changes.difference <= 0.0
    no_more_false = false_fix_rate is not None and false_fix_rate.difference <= 0.0
    wrong_top_ok = None if wrong_top_candidate_rate is None else wrong_top_candidate_rate.difference <= 0.0
    valid = baseline_kind == "pre_feature" and not ablation
    passes = (
        effect is not None
        and ci_ok
        and held_out_direction
        and no_more_unwanted
        and no_more_false
        and wrong_top_ok is not False
        and valid
    )
    return GateVerdict(
        effect=effect,
        ci_excludes_zero=ci_ok,
        held_out_direction=held_out_direction,
        no_more_unwanted_changes=no_more_unwanted,
        no_more_false_fixes=no_more_false,
        wrong_top_candidate_ok=wrong_top_ok,
        valid=valid,
        passes=passes,
    )


def layer_gate(
    outcomes: Sequence[TaskOutcome],
    *,
    layer: str,
    layer_task_ids: Iterable[str],
    held_out_task_ids: Iterable[str],
    control_task_ids: Iterable[str],
    seed: int,
    baseline_kind: BaselineKind,
    ablation: bool,
    resamples: int = DEFAULT_RESAMPLES,
) -> GateVerdict:
    """``gate_verdict`` for one layer on pooled tasks: ``layer_task_ids`` are the layer's fault tasks (designed and
    held-out), ``held_out_task_ids`` its held-out fault tasks, ``control_task_ids`` the controls of the run."""

    def run(metric: Metric, ids: list[str], scope: str) -> Comparison | None:
        return compare(outcomes, scope=scope, metric=metric, seed=seed, task_ids=ids, resamples=resamples)

    pooled = list(layer_task_ids)
    held = list(held_out_task_ids)
    controls = list(control_task_ids)
    return gate_verdict(
        fix_rate=run("fix_rate", pooled, layer),
        tool_calls=run("tool_calls", pooled, layer),
        held_out_fix_rate=run("fix_rate", held, "held_out"),
        held_out_tool_calls=run("tool_calls", held, "held_out"),
        unwanted_changes=run("unwanted_changes", pooled, layer),
        false_fix_rate=run("false_fix_rate", controls, "control"),
        wrong_top_candidate_rate=run("wrong_top_candidate_rate", pooled, layer),
        baseline_kind=baseline_kind,
        ablation=ablation,
    )


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile ``q`` in [0, 1] of already sorted values."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


@dataclass(frozen=True)
class TaskInfo:
    """What the statistics need to know about a task id: its kind, layer, fault type and held-out status.

    ``held_out`` is true only for valid held-out faults; ``held_out_invalid`` ones count with the designed faults.
    """

    task_id: str
    kind: TaskKind
    layer: Layer
    fault_id: str | None
    held_out: bool


FAULT_METRICS: tuple[Metric, ...] = (
    "fix_rate",
    "tool_calls",
    "response_tokens",
    "unwanted_changes",
    "wrong_top_candidate_rate",
)
CONTROL_METRICS: tuple[Metric, ...] = ("false_fix_rate", "tool_calls", "response_tokens")


def scoped_comparisons(
    outcomes: Sequence[TaskOutcome],
    infos: Mapping[str, TaskInfo],
    *,
    seed: int,
    resamples: int = DEFAULT_RESAMPLES,
    baseline_condition: Condition = "baseline",
    treatment_condition: Condition = "treatment",
) -> list[Comparison]:
    """Comparisons over the standard scopes: ``overall`` and each layer (all fault tasks, held-out pooled in),
    each fault type (``descriptive_only`` when its interval includes zero), ``held_out`` (valid held-out fault
    tasks) and ``control``. Scopes or metrics with no paired task are left out."""
    fault_tasks = [i for i in infos.values() if i.kind == "fault"]
    scopes: list[tuple[str, list[str], tuple[Metric, ...], bool]] = [
        ("overall", [i.task_id for i in fault_tasks], FAULT_METRICS, False)
    ]
    for layer in LAYERS:
        scopes.append((layer, [i.task_id for i in fault_tasks if i.layer == layer], FAULT_METRICS, False))
    for fault_id in sorted({i.fault_id for i in fault_tasks if i.fault_id is not None}):
        scopes.append((fault_id, [i.task_id for i in fault_tasks if i.fault_id == fault_id], FAULT_METRICS, True))
    scopes.append(("held_out", [i.task_id for i in fault_tasks if i.held_out], FAULT_METRICS, False))
    scopes.append(("control", [i.task_id for i in infos.values() if i.kind == "control"], CONTROL_METRICS, False))

    comparisons: list[Comparison] = []
    for scope, ids, metrics, per_type in scopes:
        if not ids:
            continue
        for metric in metrics:
            comparison = compare(
                outcomes,
                scope=scope,
                metric=metric,
                seed=seed,
                task_ids=ids,
                resamples=resamples,
                fault_type_scope=per_type,
                baseline_condition=baseline_condition,
                treatment_condition=treatment_condition,
            )
            if comparison is not None:
                comparisons.append(comparison)
    return comparisons
