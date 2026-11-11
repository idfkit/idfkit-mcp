"""Command line of the evaluation harness (contracts/eval-harness.md, "Command line").

```bash
uv run python -m eval run --treatment "uv run idfkit-mcp" --out eval/runs/<run_id>/ [...]
uv run python -m eval compare eval/runs/<a>/ [eval/runs/<b>/]
uv run python -m eval list-faults [--check-held-out]
```

Exit codes: 0 when the command completed (whatever the scores), 2 for bad configuration (including a prompt that
fails the lint, and for ``list-faults --check-held-out`` an invalid held-out fault), 3 when no tasks were runnable.

``run`` prepares a run: it loads and validates the configuration, discovers and selects the faults and tasks, runs
the held-out check and the prompt lint, and plans the tasks over the reference models. Executing the plan (the
agent runner, conditions, diff and report: tasks T064 to T074) plugs in at ``execute_run``; until then ``run``
stops there with exit code 1 and says so.

Options beyond the contract, all optional: ``--baseline`` (named in the contract's Baseline section),
``--seed`` (the bootstrap seed recorded in run.json; random when omitted), ``--idfkit-repo`` / ``--idfkit-ref`` (the
idfkit checkout and ref the held-out check reads), ``--energyplus-dir`` and ``--example-files``.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.config import (
    BaselineConfig,
    ConfigError,
    ReferenceModel,
    RunnerConfig,
    load_baseline,
    load_prompt_templates,
    load_reference_models,
    load_runner,
)
from eval.held_out import GitError, HeldOutReport, check_held_out
from eval.lint import PromptLintError, check_prompt
from eval.model import MIN_REPEATS, BaselineKind, EvaluationRun, load_run
from eval.registry import EVAL_DIR, PlannedTask, Registry, Selection, discover, plan_tasks, select, task_infos
from eval.stats import DEFAULT_RESAMPLES, layer_gate, repeat_spread, scoped_comparisons

EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 1
EXIT_CONFIG = 2
EXIT_NOTHING_RUNNABLE = 3


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

    @property
    def held_out_invalid(self) -> list[str]:
        return [] if self.held_out is None else self.held_out.invalid


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__.split("\n\n")[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the evaluation")
    run.add_argument("--models", type=Path, default=EVAL_DIR / "reference_models.toml")
    run.add_argument("--faults", default="all", help='"all", a layer ("topology", "results") or comma-separated ids')
    baseline = run.add_mutually_exclusive_group()
    baseline.add_argument("--baseline-config", type=Path, default=EVAL_DIR / "baseline.toml")
    baseline.add_argument("--baseline", help='baseline server command; the run is recorded as baseline_kind="other"')
    run.add_argument("--treatment", required=True, help='treatment server command, e.g. "uv run idfkit-mcp"')
    run.add_argument("--runner", type=Path, default=EVAL_DIR / "runners" / "claude_code.toml")
    run.add_argument("--repeat", type=int, default=MIN_REPEATS)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--seed", type=int, default=None, help="bootstrap seed (random when omitted; always recorded)")
    _add_held_out_args(run)
    run.add_argument("--energyplus-dir", type=Path, default=None, help="EnergyPlus install (default: discovered)")
    run.add_argument("--example-files", type=Path, default=None, help="default: <EnergyPlus install>/ExampleFiles")

    compare = sub.add_parser("compare", help="tables and gate verdict for a run; slice delta for two runs")
    compare.add_argument("runs", type=Path, nargs="+", metavar="RUN_DIR")

    list_faults = sub.add_parser("list-faults", help="list fault types and tasks")
    list_faults.add_argument("--check-held-out", action="store_true", help="exit 2 when a held-out fault is invalid")
    _add_held_out_args(list_faults)
    return parser


def _add_held_out_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--idfkit-repo", type=Path, default=None, help="idfkit checkout for the held-out check")
    parser.add_argument("--idfkit-ref", default="HEAD", help="ref of the idfkit level the treatment pins")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args)
        if args.command == "compare":
            return cmd_compare(args.runs)
        return cmd_list_faults(args)
    except (ConfigError, GitError, PromptLintError) as exc:
        _err(f"error: {exc}")
        return EXIT_CONFIG


# --- run ---------------------------------------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    config = prepare_run(args)
    lint_definitions(config)
    plan = plan_tasks(
        config.selection,
        config.models,
        example_files=config.example_files,
        energyplus_available=config.energyplus_dir is not None,
        held_out_invalid=config.held_out_invalid,
    )
    runnable = [task for task in plan if task.runnable]
    _err(f"planned {len(plan)} tasks, {len(runnable)} runnable, {config.repeats} repeats per condition")
    if not runnable:
        _err("no runnable tasks")
        return EXIT_NOTHING_RUNNABLE
    try:
        return execute_run(config, plan)
    except NotImplementedError as exc:
        _err(f"error: {exc}")
        return EXIT_NOT_IMPLEMENTED


def prepare_run(args: argparse.Namespace) -> RunConfig:
    """Load and validate the configuration, select faults and tasks, and run the held-out check."""
    repeats: int = args.repeat
    if repeats < MIN_REPEATS:
        raise ConfigError(f"--repeat must be at least {MIN_REPEATS} (FR-042a), got {repeats}")
    runner = load_runner(args.runner)
    models = load_reference_models(args.models)
    prompts = load_prompt_templates(EVAL_DIR / "prompts.toml")
    baseline: BaselineConfig | None = None
    baseline_command: str | None = args.baseline
    if baseline_command is None:
        baseline = load_baseline(args.baseline_config)
        baseline_kind: BaselineKind = baseline.kind
    else:
        baseline_kind = "other"
    registry = discover()
    selection = select(registry, args.faults)
    report = held_out_check(registry, idfkit_repo=args.idfkit_repo, idfkit_ref=args.idfkit_ref)
    if report is not None:
        registry = registry.with_held_out_report(report)
        selection = select(registry, args.faults)
        for status in report.statuses:
            if not status.valid:
                _err(f"held_out_invalid: {status.fault_id}: {status.reason}; counted with the designed faults")
    energyplus_dir = find_energyplus_dir(args.energyplus_dir)
    example_files: Path | None = args.example_files
    if example_files is None and energyplus_dir is not None:
        example_files = energyplus_dir / "ExampleFiles"
    seed: int = args.seed if args.seed is not None else random.SystemRandom().randrange(2**32)
    return RunConfig(
        registry=registry,
        selection=selection,
        models=models,
        runner=runner,
        baseline_kind=baseline_kind,
        baseline=baseline,
        baseline_command=baseline_command,
        treatment_command=args.treatment,
        repeats=repeats,
        out_dir=args.out,
        bootstrap_seed=seed,
        bootstrap_resamples=DEFAULT_RESAMPLES,
        prompts=prompts,
        held_out=report,
        energyplus_dir=energyplus_dir,
        example_files=example_files,
    )


def held_out_check(registry: Registry, *, idfkit_repo: Path | None, idfkit_ref: str) -> HeldOutReport | None:
    """Run the held-out check; ``None`` when there are no held-out faults. Needs ``idfkit_repo`` otherwise."""
    files = registry.held_out_files()
    if not files:
        return None
    if idfkit_repo is None:
        raise ConfigError("held-out faults exist: pass --idfkit-repo (and --idfkit-ref) for the held-out check")
    return check_held_out(files, idfkit_repo=idfkit_repo, idfkit_ref=idfkit_ref)


def lint_definitions(config: RunConfig) -> None:
    """Lint every template before anything runs: prompts.toml, and each selected fault's and task's template
    (with its own id). Rendered prompts are linted again by the runner, with the injected names."""
    for name, template in config.prompts.items():
        check_prompt(f"prompts.toml {name}", template)
    for entry in config.selection.faults:
        check_prompt(f"fault {entry.fault.id}", entry.fault.prompt_template, fault_id=entry.fault.id)
    for spec in config.selection.tasks:
        check_prompt(f"{spec.kind} task {spec.id}", spec.prompt_template)


def find_energyplus_dir(explicit: Path | None) -> Path | None:
    """The EnergyPlus install directory, or ``None`` when EnergyPlus is not found (FR-043 skips apply)."""
    from idfkit.exceptions import EnergyPlusNotFoundError
    from idfkit.simulation.config import find_energyplus

    try:
        return find_energyplus(path=explicit).install_dir
    except EnergyPlusNotFoundError:
        if explicit is not None:
            raise ConfigError(f"--energyplus-dir {explicit}: no EnergyPlus installation found") from None
        return None


def execute_run(config: RunConfig, plan: Sequence[PlannedTask]) -> int:
    """Execute a prepared run and write ``run.json``, ``outcomes.jsonl``, ``transcripts/`` and ``summary.md``.

    The seam for tasks T064 to T074: build both conditions, inject each fault, render and lint each prompt, run
    every task ``config.repeats`` times per condition in the same order, record a ``TaskOutcome`` each, and write
    the run with ``model.save_run``. Returns ``EXIT_OK`` when the run completed.
    """
    raise NotImplementedError("the agent runner is not implemented yet (tasks T064 to T074)")


# --- compare -----------------------------------------------------------------------------------------------------


def cmd_compare(run_dirs: Sequence[Path]) -> int:
    if len(run_dirs) > 2:
        raise ConfigError("compare takes one or two run directories")
    registry = discover()
    tables: list[dict[tuple[str, str], float]] = []
    for run_dir in run_dirs:
        try:
            run = load_run(run_dir)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ConfigError(f"{run_dir}: not a readable run directory ({exc!r})") from exc
        tables.append(print_run(run, registry))
    if len(tables) == 2:
        first, second = tables
        print(f"\nSlice delta ({run_dirs[1]} minus {run_dirs[0]}), difference of differences")
        for key in sorted(first.keys() & second.keys()):
            print(f"  {key[0]:<28} {key[1]:<26} {second[key] - first[key]:+.3f}")
    return EXIT_OK


def print_run(run: EvaluationRun, registry: Registry) -> dict[tuple[str, str], float]:
    """Print a run's comparisons, SC-008 spread and per-layer SC-009 clauses; return ``(scope, metric) -> diff``."""
    base, treat = ("treatment", "ablation") if run.ablation else ("baseline", "treatment")
    infos = task_infos(registry, {o.task_id for o in run.outcomes}, held_out_invalid=run.held_out_invalid)
    comparisons = scoped_comparisons(
        run.outcomes,
        infos,
        seed=run.bootstrap_seed,
        resamples=run.bootstrap_resamples,
        baseline_condition=base,
        treatment_condition=treat,
    )
    print(f"Run {run.run_id} ({run.baseline_kind} baseline{', ablation' if run.ablation else ''})")
    print(f"  {'scope':<28} {'metric':<26} {'n':>4} {treat + ' - ' + base:>22}   95% interval")
    for c in comparisons:
        mark = "  descriptive" if c.descriptive_only else ""
        print(
            f"  {c.scope:<28} {c.metric:<26} {c.tasks:>4} {c.difference:>+22.3f}   [{c.ci_low:+.3f}, {c.ci_high:+.3f}]{mark}"
        )
    for condition in (base, treat):
        spread = repeat_spread(run.outcomes, condition=condition)
        if spread is not None:
            print(f"  SC-008 spread ({condition}): {spread:.3f}")
    controls = [i.task_id for i in infos.values() if i.kind == "control"]
    for layer in sorted({i.layer for i in infos.values() if i.kind == "fault"}):
        faults = [i for i in infos.values() if i.kind == "fault" and i.layer == layer]
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
        )
        clauses = ", ".join(f"{k}={v}" for k, v in verdict.to_dict().items())
        print(f"  SC-009 {layer}: {clauses}")
    return {(c.scope, c.metric): c.difference for c in comparisons}


# --- list-faults -------------------------------------------------------------------------------------------------


def cmd_list_faults(args: argparse.Namespace) -> int:
    registry = discover()
    report = (
        held_out_check(registry, idfkit_repo=args.idfkit_repo, idfkit_ref=args.idfkit_ref)
        if args.check_held_out
        else None
    )
    invalid = set(report.invalid) if report is not None else set[str]()
    print(f"{'id':<36} {'layer':<9} {'kind':<10} {'held_out':<9} needs_energyplus")
    for entry in registry.faults:
        fault = entry.fault
        held = "invalid" if fault.id in invalid else ("yes" if fault.held_out else "no")
        print(f"{fault.id:<36} {fault.layer:<9} {'fault':<10} {held:<9} {_yes(fault.needs_energyplus)}")
    for spec in registry.tasks:
        print(f"{spec.id:<36} {spec.layer:<9} {spec.kind:<10} {'-':<9} {_yes(spec.needs_energyplus)}")
    if not registry.faults and not registry.tasks:
        _err("no faults or tasks defined yet")
    if report is not None:
        for status in report.statuses:
            _err(f"{status.fault_id}: {'valid' if status.valid else 'held_out_invalid'}: {status.reason}")
        if not report.ok:
            return EXIT_CONFIG
    return EXIT_OK


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _err(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
