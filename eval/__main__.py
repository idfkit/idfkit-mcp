"""Command line of the evaluation harness (contracts/eval-harness.md, "Command line").

```bash
uv run python -m eval run --treatment "uv run idfkit-mcp" --out eval/runs/<run_id>/ [...]
uv run python -m eval compare eval/runs/<a>/ [eval/runs/<b>/]
uv run python -m eval list-faults [--check-held-out]
```

Exit codes: 0 when the command completed (whatever the scores), 2 for bad configuration (including a prompt that
fails the lint, and for ``list-faults --check-held-out`` an invalid held-out fault), 3 when no tasks were runnable.

``run`` loads and validates the configuration, discovers and selects the faults and tasks, runs the held-out check
(an invalid held-out fault is reported and counted with the designed faults), lints every template, plans the
tasks over the reference models, then hands the plan to ``execute.execute_run``, which injects, renders and lints
every prompt before any agent runs, runs both conditions and writes the run directory (``run.json``,
``outcomes.jsonl``, ``tasks.jsonl``, ``transcripts/``, ``summary.md``). ``compare`` (re)writes ``summary.md`` of
each run it reads; with two runs, the second one's summary gains the slice delta.

Options beyond the contract, all optional: ``--baseline`` (named in the contract's Baseline section),
``--seed`` (the bootstrap seed recorded in run.json; random when omitted), ``--idfkit-repo`` / ``--idfkit-ref`` (the
idfkit checkout and ref the held-out check reads), ``--energyplus-dir``, ``--example-files`` and ``--weather`` (the
weather file of the harness's verification simulations; design days only when omitted).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

from eval.config import (
    BaselineConfig,
    ConfigError,
    load_baseline,
    load_prompt_templates,
    load_reference_models,
    load_runner,
)
from eval.execute import RunConfig, execute_pilot, execute_run, load_solved
from eval.held_out import GitError, HeldOutReport, check_held_out
from eval.lint import PromptLintError, check_prompt
from eval.model import MIN_REPEATS, BaselineKind, EvaluationRun, load_run
from eval.registry import (
    DEFAULT_MODELS_PER_TYPE,
    EVAL_DIR,
    MAX_MODELS_PER_TYPE,
    PlannedTask,
    Registry,
    discover,
    plan_tasks,
    select,
)
from eval.report import SUMMARY_FILE, render_summary
from eval.stats import DEFAULT_RESAMPLES

__all__ = ["RunConfig", "execute_run", "main"]

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NOTHING_RUNNABLE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m eval", description=__doc__.split("\n\n")[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the evaluation")
    _add_plan_args(run)
    run.add_argument("--repeat", type=int, default=MIN_REPEATS)
    run.add_argument("--seed", type=int, default=None, help="bootstrap seed (random when omitted; always recorded)")
    run.add_argument(
        "--skip-solved",
        type=Path,
        default=None,
        metavar="PILOT_DIR",
        help="drop the fault, question and authoring tasks a pilot's baseline fixed; controls are kept",
    )

    pilot = sub.add_parser("pilot", help="run the baseline once per task to find tasks it already solves")
    _add_plan_args(pilot)

    compare = sub.add_parser("compare", help="tables and gate verdict for a run; slice delta for two runs")
    compare.add_argument("runs", type=Path, nargs="+", metavar="RUN_DIR")

    list_faults = sub.add_parser("list-faults", help="list fault types and tasks")
    list_faults.add_argument("--check-held-out", action="store_true", help="exit 2 when a held-out fault is invalid")
    _add_held_out_args(list_faults)
    return parser


def _add_plan_args(run: argparse.ArgumentParser) -> None:
    run.add_argument("--models", type=Path, default=EVAL_DIR / "reference_models.toml")
    run.add_argument("--faults", default="all", help='"all", a layer ("topology", "results") or comma-separated ids')
    baseline = run.add_mutually_exclusive_group()
    baseline.add_argument("--baseline-config", type=Path, default=EVAL_DIR / "baseline.toml")
    baseline.add_argument("--baseline", help='baseline server command; the run is recorded as baseline_kind="other"')
    run.add_argument("--treatment", required=True, help='treatment server command, e.g. "uv run idfkit-mcp"')
    run.add_argument("--runner", type=Path, default=EVAL_DIR / "runners" / "claude_code.toml")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument(
        "--max-models",
        type=int,
        default=DEFAULT_MODELS_PER_TYPE,
        help=f"reference models per fault type or task, 1 to {MAX_MODELS_PER_TYPE} (default {DEFAULT_MODELS_PER_TYPE})",
    )
    _add_held_out_args(run)
    run.add_argument("--energyplus-dir", type=Path, default=None, help="EnergyPlus install (default: discovered)")
    run.add_argument("--example-files", type=Path, default=None, help="default: <EnergyPlus install>/ExampleFiles")
    run.add_argument(
        "--weather", type=Path, default=None, help="EPW for verification simulations (default: design days)"
    )


def _add_held_out_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--idfkit-repo", type=Path, default=None, help="idfkit checkout for the held-out check")
    parser.add_argument("--idfkit-ref", default="HEAD", help="ref of the idfkit level the treatment pins")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args)
        if args.command == "pilot":
            return cmd_pilot(args)
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
    plan = _plan(config, args.max_models)
    if args.skip_solved is not None:
        solved = load_solved(args.skip_solved)
        dropped = [t.task_id for t in plan if t.kind != "control" and t.task_id in solved]
        plan = [t for t in plan if t.task_id not in dropped]
        _err(f"--skip-solved: dropped {len(dropped)} tasks the pilot baseline fixed (controls kept)")
        config.out_dir.mkdir(parents=True, exist_ok=True)
        (config.out_dir / "skipped_solved.json").write_text(
            json.dumps({"pilot": str(args.skip_solved), "dropped": dropped}, indent=2) + "\n", encoding="utf-8"
        )
    runnable = [task for task in plan if task.runnable]
    _err(f"planned {len(plan)} tasks, {len(runnable)} runnable, {config.repeats} repeats per condition")
    if not runnable:
        _err("no runnable tasks")
        return EXIT_NOTHING_RUNNABLE
    return execute_run(config, plan)


def cmd_pilot(args: argparse.Namespace) -> int:
    config = prepare_run(args, pilot=True)
    lint_definitions(config)
    plan = _plan(config, args.max_models)
    runnable = [task for task in plan if task.runnable]
    _err(f"pilot: {len(runnable)} runnable tasks, baseline only, 1 session each")
    if not runnable:
        _err("no runnable tasks")
        return EXIT_NOTHING_RUNNABLE
    return execute_pilot(config, plan)


def _plan(config: RunConfig, max_models: int) -> list[PlannedTask]:
    if not 1 <= max_models <= MAX_MODELS_PER_TYPE:
        raise ConfigError(f"--max-models must be between 1 and {MAX_MODELS_PER_TYPE}, got {max_models}")
    return plan_tasks(
        config.selection,
        config.models,
        example_files=config.example_files,
        energyplus_available=config.energyplus_dir is not None,
        held_out_invalid=config.held_out_invalid,
        cap=max_models,
    )


def prepare_run(args: argparse.Namespace, *, pilot: bool = False) -> RunConfig:
    """Load and validate the configuration, select faults and tasks, and run the held-out check."""
    repeats: int = 1 if pilot else args.repeat
    if not pilot and repeats < MIN_REPEATS:
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
    weather: Path | None = args.weather
    if weather is not None and not weather.is_file():
        raise ConfigError(f"--weather {weather}: not a file")
    seed: int = args.seed if getattr(args, "seed", None) is not None else random.SystemRandom().randrange(2**32)
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
        weather=weather,
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


# --- compare -----------------------------------------------------------------------------------------------------


def cmd_compare(run_dirs: Sequence[Path]) -> int:
    """Print each run's summary and (re)write its ``summary.md``; with two runs, the second gains the slice delta
    (second minus first)."""
    if len(run_dirs) > 2:
        raise ConfigError("compare takes one or two run directories")
    registry = discover()
    runs: list[EvaluationRun] = []
    for run_dir in run_dirs:
        try:
            runs.append(load_run(run_dir))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ConfigError(f"{run_dir}: not a readable run directory ({exc!r})") from exc
    for index, (run_dir, run) in enumerate(zip(run_dirs, runs, strict=True)):
        previous = runs[0] if index == 1 else None
        text = render_summary(run, registry, previous=previous, previous_label=str(run_dirs[0]))
        (run_dir / SUMMARY_FILE).write_text(text, encoding="utf-8")
        print(text)
    return EXIT_OK


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
