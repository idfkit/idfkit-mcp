"""``summary.md`` (contract "Outputs"; task T074). Statistics come from ``eval.stats``.

Sections, in order: the run's facts; paired differences (treatment minus baseline) of fix rate, tool calls,
response tokens and unwanted changes, overall, per layer and per designed fault type, with 95% bootstrap
intervals and per-type rows whose interval includes zero marked descriptive; median tool calls and tokens per
condition; a separate table for held-out fault types; control false-fix rates, authoring success and question
accuracy per condition; skipped tasks; the SC-008 spread; SC-009a (wrong top-candidate edits against the
baseline's wrong first edits); SC-010a (share of tasks whose intended tool was used, per new tool); the SC-009
verdict per layer with each clause; and, from ``compare`` with two runs, the slice delta.

Paired differences are differences of task means (``stats.compare``), as the gate reads them. The "median" rows
are the median over tasks of each task's mean, per condition, given beside them as the contract asks.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from eval.model import Comparison, Condition, EvaluationRun, Metric, TaskOutcome, split_task_id
from eval.parsers import NEW_TOOLS
from eval.registry import Registry, task_infos
from eval.stats import TaskInfo, compare, layer_gate, repeat_spread, scoped_comparisons, task_means

SUMMARY_FILE = "summary.md"

_TABLE_METRICS: tuple[Metric, ...] = ("fix_rate", "tool_calls", "response_tokens", "unwanted_changes")
_CLAUSES = (
    ("effect", "effect size: fix rate +20 points, or 30% fewer tool calls at no lower fix rate"),
    ("ci_excludes_zero", "95% interval of the effect excludes zero"),
    ("held_out_direction", "same direction on held-out fault types"),
    ("no_more_unwanted_changes", "no increase in unwanted changes"),
    ("no_more_false_fixes", "no increase in false fixes on controls"),
    ("wrong_top_candidate_ok", "SC-009a: wrong top-candidate edits not above the baseline's wrong first edits"),
    ("valid", "valid: pre-feature baseline, not an ablation"),
    ("passes", "passes"),
)


def conditions_of(run: EvaluationRun) -> tuple[Condition, Condition]:
    """``(base, treat)``: baseline and treatment, or treatment and ablation for an ablation run."""
    return ("treatment", "ablation") if run.ablation else ("baseline", "treatment")


def comparisons_of(run: EvaluationRun, registry: Registry) -> tuple[dict[str, TaskInfo], list[Comparison]]:
    """The run's task infos and its comparisons over the standard scopes."""
    base, treat = conditions_of(run)
    infos = task_infos(registry, {o.task_id for o in run.outcomes}, held_out_invalid=run.held_out_invalid)
    comparisons = scoped_comparisons(
        run.outcomes,
        infos,
        seed=run.bootstrap_seed,
        resamples=run.bootstrap_resamples,
        baseline_condition=base,
        treatment_condition=treat,
    )
    return infos, comparisons


def slice_delta(first: Sequence[Comparison], second: Sequence[Comparison]) -> list[tuple[str, str, float]]:
    """Difference of differences (``second`` minus ``first``) for each scope and metric both runs have."""
    a = {(c.scope, c.metric): c.difference for c in first}
    b = {(c.scope, c.metric): c.difference for c in second}
    return [(scope, metric, b[(scope, metric)] - a[(scope, metric)]) for scope, metric in sorted(a.keys() & b.keys())]


def render_summary(
    run: EvaluationRun, registry: Registry, *, previous: EvaluationRun | None = None, previous_label: str = ""
) -> str:
    """The whole ``summary.md`` of ``run``; with ``previous``, a slice-delta section against it."""
    base, treat = conditions_of(run)
    infos, comparisons = comparisons_of(run, registry)
    lines: list[str] = []
    lines += _facts(run)
    held_types = {i.fault_id for i in infos.values() if i.kind == "fault" and i.held_out}
    main = [c for c in comparisons if c.scope not in held_types and c.scope != "held_out" and c.scope != "control"]
    lines += _section(f"Paired differences ({treat} minus {base})")
    lines += _comparison_table([c for c in main if c.metric in _TABLE_METRICS], base, treat)
    lines += _section("Median over tasks of task means")
    lines += _medians(run.outcomes, infos, (base, treat))
    lines += _section("Held-out fault types")
    held = [c for c in comparisons if (c.scope in held_types or c.scope == "held_out") and c.metric in _TABLE_METRICS]
    lines += _comparison_table(held, base, treat) if held else ["No valid held-out fault task was paired.", ""]
    lines += _section("Controls, authoring and questions")
    lines += _kind_rates(run.outcomes, infos, (base, treat))
    lines += _section("Skipped tasks")
    lines += _skips(run.outcomes)
    lines += _section("SC-008 repeatability")
    for condition in (base, treat):
        spread = repeat_spread(run.outcomes, condition=condition)
        shown = "no outcomes" if spread is None else f"{spread:.3f}"
        lines.append(f"- {condition}: range of the overall fix rate across repeat passes: {shown}")
    lines.append("")
    lines += _section("SC-009a diagnosis anchoring")
    lines += _anchoring(run, infos, (base, treat))
    lines += _section("SC-010a intended tool use")
    lines += _intended(run.outcomes, registry, treat)
    lines += _section("SC-009 verdict")
    lines += _verdicts(run, infos)
    if previous is not None:
        _, before = comparisons_of(previous, registry)
        lines += _section(f"Slice delta against {previous_label or previous.run_id}")
        lines.append("Difference of differences: this run's paired difference minus the earlier run's.")
        lines.append("")
        lines += ["| scope | metric | delta |", "|---|---|---:|"]
        lines += [f"| {scope} | {metric} | {delta:+.3f} |" for scope, metric, delta in slice_delta(before, comparisons)]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_summary(
    run: EvaluationRun,
    registry: Registry,
    out_dir: Path,
    *,
    previous: EvaluationRun | None = None,
    previous_label: str = "",
) -> Path:
    """Write ``summary.md`` into ``out_dir`` and return its path."""
    path = out_dir / SUMMARY_FILE
    path.write_text(render_summary(run, registry, previous=previous, previous_label=previous_label), encoding="utf-8")
    return path


# --- sections --------------------------------------------------------------------------------------------------------


def _section(title: str) -> list[str]:
    return [f"## {title}", ""]


def _facts(run: EvaluationRun) -> list[str]:
    lines = [f"# Evaluation run {run.run_id}", ""]
    facts: list[tuple[str, object]] = [
        ("started", run.started_at),
        ("finished", run.finished_at or "not finished"),
        ("runner", f"`{run.runner_command}`"),
        ("model", run.model_identifier),
        ("baseline kind", run.baseline_kind),
        ("baseline revision", f"{run.baseline_sha or '-'} with {run.baseline_idfkit or '-'}"),
        ("baseline command", f"`{run.baseline_command}`" if run.baseline_command else "-"),
        ("treatment revision", run.treatment_revision),
        ("treatment command", f"`{run.treatment_command}`" if run.treatment_command else "-"),
        ("ablation", f"yes, disallowed: {', '.join(run.disallowed_tools)}" if run.ablation else "no"),
        ("repeats", run.repeats),
        ("bootstrap", f"seed {run.bootstrap_seed}, {run.bootstrap_resamples} resamples, 95% percentile interval"),
        ("held-out invalid", ", ".join(run.held_out_invalid) or "none"),
    ]
    lines += [f"- {name}: {value}" for name, value in facts]
    if run.baseline_kind != "pre_feature" or run.ablation:
        lines += ["", "This run cannot decide SC-009: its verdict is reported but marked not valid."]
    lines.append("")
    return lines


def _comparison_table(rows: Sequence[Comparison], base: str, treat: str) -> list[str]:
    if not rows:
        return ["No paired fault tasks.", ""]
    lines = [
        f"| scope | metric | tasks | {base} | {treat} | difference | 95% interval | |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for c in rows:
        mark = "descriptive" if c.descriptive_only else ""
        lines.append(
            f"| {c.scope} | {c.metric} | {c.tasks} | {c.baseline:.3f} | {c.treatment:.3f} | {c.difference:+.3f} "
            f"| [{c.ci_low:+.3f}, {c.ci_high:+.3f}] | {mark} |"
        )
    lines.append("")
    return lines


def _medians(
    outcomes: Sequence[TaskOutcome], infos: Mapping[str, TaskInfo], conditions: Iterable[Condition]
) -> list[str]:
    lines = ["| tasks | condition | median tool calls | median response tokens |", "|---|---|---:|---:|"]
    groups = {
        "fault": [i.task_id for i in infos.values() if i.kind == "fault"],
        "control": [i.task_id for i in infos.values() if i.kind == "control"],
    }
    for group, ids in groups.items():
        if not ids:
            continue
        for condition in conditions:
            calls = task_means(outcomes, condition=condition, metric="tool_calls", task_ids=ids)
            tokens = task_means(outcomes, condition=condition, metric="response_tokens", task_ids=ids)
            lines.append(f"| {group} | {condition} | {_median(calls.values())} | {_median(tokens.values())} |")
    lines.append("")
    return lines


def _kind_rates(
    outcomes: Sequence[TaskOutcome], infos: Mapping[str, TaskInfo], conditions: Iterable[Condition]
) -> list[str]:
    measures = (("control", "false-fix rate"), ("authoring", "success rate"), ("question", "accuracy"))
    lines = ["| kind | measure | condition | tasks | runs | rate | skipped runs |", "|---|---|---|---:|---:|---:|---:|"]
    for kind, measure in measures:
        ids = {i.task_id for i in infos.values() if i.kind == kind}
        if not ids:
            continue
        for condition in conditions:
            runs = [o for o in outcomes if o.task_id in ids and o.condition == condition]
            done = [o for o in runs if not o.skipped]
            hits = [o.false_fix if kind == "control" else o.fixed for o in done]
            rate = f"{sum(hits) / len(hits):.3f}" if hits else "-"
            tasks = len({o.task_id for o in done})
            lines.append(
                f"| {kind} | {measure} | {condition} | {tasks} | {len(done)} | {rate} | {len(runs) - len(done)} |"
            )
    if len(lines) == 2:
        return ["No control, authoring or question tasks ran.", ""]
    lines.append("")
    return lines


def _skips(outcomes: Sequence[TaskOutcome]) -> list[str]:
    reasons: dict[str, str] = {}
    for o in outcomes:
        if o.skipped and o.skip_reason:
            reasons.setdefault(o.task_id, o.skip_reason)
    if not reasons:
        return ["None.", ""]
    return [*(f"- {task_id}: {reason}" for task_id, reason in sorted(reasons.items())), ""]


def _anchoring(run: EvaluationRun, infos: Mapping[str, TaskInfo], conditions: tuple[Condition, Condition]) -> list[str]:
    faults = [i.task_id for i in infos.values() if i.kind == "fault"]
    lines: list[str] = []
    for condition in conditions:
        outs = [o for o in run.outcomes if o.condition == condition and not o.skipped and o.task_id in faults]
        top = [o for o in outs if o.top_candidate_edited is not None and o.top_candidate_correct is not None]
        first = [o for o in outs if o.first_edit_correct is not None]
        wrong_top = sum(1 for o in top if o.top_candidate_edited and not o.top_candidate_correct)
        wrong_first = sum(1 for o in first if not o.first_edit_correct)
        lines.append(
            f"- {condition}: diagnose_symptom used in {len(top)} runs, {wrong_top} edited a wrong top candidate; "
            f"first edit outside the fault's scope in {wrong_first} of {len(first)} runs that changed the model"
        )
    base, treat = conditions
    comparison = compare(
        run.outcomes,
        scope="overall",
        metric="wrong_top_candidate_rate",
        seed=run.bootstrap_seed,
        task_ids=faults,
        resamples=run.bootstrap_resamples,
        baseline_condition=base,
        treatment_condition=treat,
    )
    lines.append("")
    if comparison is None:
        lines.append(
            f"No paired task: {treat} never called diagnose_symptom on a task where {base} changed the model, so "
            "the SC-009a clause is not decided."
        )
    else:
        lines.append(
            f"Paired over {comparison.tasks} tasks: {treat} wrong top-candidate rate {comparison.treatment:.3f}, "
            f"{base} wrong first-edit rate {comparison.baseline:.3f}, difference {comparison.difference:+.3f} "
            f"[{comparison.ci_low:+.3f}, {comparison.ci_high:+.3f}]."
        )
    lines.append("")
    return lines


def _intended(outcomes: Sequence[TaskOutcome], registry: Registry, condition: Condition) -> list[str]:
    intended = _intended_tools(registry, {o.task_id for o in outcomes})
    lines = ["| tool | tasks built for it | tasks where it was used | share |", "|---|---:|---:|---:|"]
    for tool in NEW_TOOLS:
        ids = sorted(t for t, tools in intended.items() if tool in tools)
        ran = {
            t: [tool in o.tools_used for o in outcomes if o.task_id == t and o.condition == condition and not o.skipped]
            for t in ids
        }
        ran = {t: uses for t, uses in ran.items() if uses}
        if not ran:
            continue
        shares = [sum(uses) / len(uses) for uses in ran.values()]
        used = sum(1 for uses in ran.values() if any(uses))
        lines.append(f"| {tool} | {len(ran)} | {used} | {statistics.fmean(shares):.3f} |")
    if len(lines) == 2:
        return [f"No {condition} task declares an intended new tool.", ""]
    lines += ["", "Share: the mean over tasks of the fraction of a task's repeats that called the tool.", ""]
    return lines


def _verdicts(run: EvaluationRun, infos: Mapping[str, TaskInfo]) -> list[str]:
    controls = [i.task_id for i in infos.values() if i.kind == "control"]
    layers = sorted({i.layer for i in infos.values() if i.kind == "fault"})
    if not layers:
        return ["No fault tasks: no verdict.", ""]
    lines: list[str] = []
    ran = {o.task_id for o in run.outcomes if not o.skipped}
    for layer in layers:
        faults = [i for i in infos.values() if i.kind == "fault" and i.layer == layer]
        if not any(i.task_id in ran for i in faults):
            lines += [f"### SC-009 {layer}", "", "Not decided: every fault task of this layer was skipped.", ""]
            continue
        verdict = layer_gate(
            run.outcomes,
            layer=layer,
            layer_task_ids=[i.task_id for i in faults],
            held_out_task_ids=[i.task_id for i in faults if i.held_out],
            control_task_ids=controls,
            seed=run.bootstrap_seed,
            resamples=run.bootstrap_resamples,
            baseline_kind=run.baseline_kind,
            ablation=run.ablation,
        ).to_dict()
        lines += [f"### SC-009 {layer}", "", "| clause | result |", "|---|---|"]
        lines += [
            f"| {text} | {'none' if verdict[key] is None and key == 'effect' else _shown(verdict[key])} |"
            for key, text in _CLAUSES
        ]
        lines.append("")
    return lines


def _intended_tools(registry: Registry, task_ids: Iterable[str]) -> dict[str, list[str]]:
    faults = {e.fault.id: e.fault.intended_tools for e in registry.faults}
    specs = {t.id: t.intended_tools for t in registry.tasks}
    found: dict[str, list[str]] = {}
    for task_id in task_ids:
        spec_id, _ = split_task_id(task_id)
        tools = faults.get(spec_id, specs.get(spec_id))
        if tools:
            found[task_id] = tools
    return found


def _median(values: Iterable[float]) -> str:
    items = list(values)
    return f"{statistics.median(items):.1f}" if items else "-"


def _shown(value: object) -> str:
    if value is None:
        return "not decided"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)
