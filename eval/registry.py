"""Discovery of fault types and task specs (contract "Inputs").

- ``eval/faults/*.py`` and ``eval/faults/held_out/*.py``: each module exposes ``FAULT: FaultType``.
- ``eval/tasks/controls.toml``: ``[[tasks]]`` entries, one control ``TaskSpec`` each.
- ``eval/tasks/authoring/*.py`` and ``eval/tasks/questions/*.py``: each module exposes ``TASK: TaskSpec``.

Modules are loaded by file path with ``importlib``, in file-name order; files starting with ``_`` are skipped so that
shared helpers can sit beside the definitions. Missing directories are empty, not errors. Every problem is a
``ConfigError`` (exit code 2).
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import TypeVar, cast

from eval.config import ConfigError, ReferenceModel, load_toml
from eval.held_out import HeldOutReport
from eval.model import LAYERS, FaultType, Layer, TaskKind, TaskSpec, make_task_id, split_task_id
from eval.stats import TaskInfo
from eval.support import default_prompt_values

EVAL_DIR = Path(__file__).resolve().parent
MAX_MODELS_PER_TYPE = 8
"""R-14: each fault type runs on every applicable model, capped at 8."""

_D = TypeVar("_D", FaultType, TaskSpec)

_CONTROL_KEYS = {"id", "layer", "applies_to", "prompt_template", "needs_energyplus"}


@dataclass(frozen=True)
class FaultEntry:
    """A discovered fault type and the file that defines it."""

    fault: FaultType
    path: Path


@dataclass(frozen=True)
class Registry:
    """Everything the harness can run, in a stable order (designed faults, held-out faults, then tasks)."""

    faults: list[FaultEntry]
    tasks: list[TaskSpec]

    def fault(self, fault_id: str) -> FaultType:
        for entry in self.faults:
            if entry.fault.id == fault_id:
                return entry.fault
        raise KeyError(fault_id)

    def task(self, task_id: str) -> TaskSpec:
        for spec in self.tasks:
            if spec.id == task_id:
                return spec
        raise KeyError(task_id)

    def held_out_files(self) -> dict[str, Path]:
        """``fault id -> file`` for the held-out faults, the input of ``held_out.check_held_out``."""
        return {e.fault.id: e.path for e in self.faults if e.fault.held_out}

    def with_held_out_report(self, report: HeldOutReport) -> Registry:
        """A copy whose held-out faults carry ``defined_in_commit`` from ``report``."""
        commits = {s.fault_id: s.defined_in.sha for s in report.statuses if s.defined_in is not None}
        faults = [
            FaultEntry(replace(e.fault, defined_in_commit=commits[e.fault.id]), e.path) if e.fault.id in commits else e
            for e in self.faults
        ]
        return Registry(faults=faults, tasks=self.tasks)


def discover(eval_dir: Path = EVAL_DIR) -> Registry:
    """Load every fault and task definition under ``eval_dir``. Ids must be unique across faults and tasks."""
    faults = [
        *load_faults(eval_dir / "faults", held_out=False),
        *load_faults(eval_dir / "faults" / "held_out", held_out=True),
    ]
    tasks = [
        *load_controls(eval_dir / "tasks" / "controls.toml"),
        *load_task_modules(eval_dir / "tasks" / "authoring", kind="authoring"),
        *load_task_modules(eval_dir / "tasks" / "questions", kind="question"),
    ]
    _check_unique([e.fault.id for e in faults] + [t.id for t in tasks])
    return Registry(faults=faults, tasks=tasks)


def load_faults(directory: Path, *, held_out: bool) -> list[FaultEntry]:
    """Load ``FAULT`` from each module in ``directory``; ``FAULT.held_out`` must equal ``held_out``."""
    entries: list[FaultEntry] = []
    for path in _modules_in(directory):
        fault = _attribute(path, "FAULT", FaultType)
        if fault.held_out != held_out:
            where = "eval/faults/held_out/" if fault.held_out else "eval/faults/"
            raise ConfigError(f"{path}: FAULT.held_out is {fault.held_out}, so the module belongs under {where}")
        _check_id(fault.id, path)
        entries.append(FaultEntry(fault=fault, path=path))
    return entries


def load_task_modules(directory: Path, *, kind: str) -> list[TaskSpec]:
    """Load ``TASK`` from each module in ``directory``; ``TASK.kind`` must equal ``kind``."""
    specs: list[TaskSpec] = []
    for path in _modules_in(directory):
        spec = _attribute(path, "TASK", TaskSpec)
        if spec.kind != kind:
            raise ConfigError(f"{path}: TASK.kind is {spec.kind!r}, expected {kind!r}")
        _check_id(spec.id, path)
        specs.append(spec)
    return specs


def load_controls(path: Path) -> list[TaskSpec]:
    """Read control tasks from ``[[tasks]]`` entries with keys id, layer, applies_to, prompt_template and
    needs_energyplus (default false). Controls have no intended tools and no verifier; their placeholders are filled
    by ``support.default_prompt_values``."""
    if not path.is_file():
        return []
    raw = load_toml(path).get("tasks")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: expected a [[tasks]] array")
    specs: list[TaskSpec] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise ConfigError(f"{path}: each [[tasks]] entry must be a table")
        specs.append(_control_spec(cast(dict[str, object], item), path))
    return specs


def _control_spec(entry: dict[str, object], path: Path) -> TaskSpec:
    unknown = set(entry) - _CONTROL_KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)} in a control task")
    task_id, layer, template = entry.get("id"), entry.get("layer"), entry.get("prompt_template")
    applies_to, needs_ep = entry.get("applies_to"), entry.get("needs_energyplus", False)
    if not isinstance(task_id, str) or not task_id:
        raise ConfigError(f"{path}: a control task has no id")
    if layer not in LAYERS:
        raise ConfigError(f"{path}: {task_id}: layer must be one of {LAYERS}")
    if not isinstance(template, str) or not template.strip():
        raise ConfigError(f"{path}: {task_id}: prompt_template must be a non-empty string")
    if not isinstance(applies_to, list) or not all(isinstance(t, str) for t in cast(list[object], applies_to)):
        raise ConfigError(f"{path}: {task_id}: applies_to must be a list of strings")
    if not isinstance(needs_ep, bool):
        raise ConfigError(f"{path}: {task_id}: needs_energyplus must be a boolean")
    _check_id(task_id, path)
    return TaskSpec(
        id=task_id,
        kind="control",
        layer=layer,
        applies_to=cast(list[str], applies_to),
        prompt_template=template,
        intended_tools=[],
        needs_energyplus=needs_ep,
        prompt_values=default_prompt_values,
    )


@dataclass(frozen=True)
class Selection:
    """The fault types and task specs a run covers."""

    faults: list[FaultEntry]
    tasks: list[TaskSpec]


def select(registry: Registry, selector: str) -> Selection:
    """Apply ``--faults``.

    - ``"all"``: every fault and every task.
    - a layer (``"topology"``, ``"results"``): that layer's faults and tasks.
    - a comma-separated list of ids: those faults and tasks, plus the controls of the selected faults' layers
      (a per-slice run covers its fault types and the controls, FR-046).
    """
    selector = selector.strip()
    if selector == "all":
        return Selection(faults=list(registry.faults), tasks=list(registry.tasks))
    if selector in LAYERS:
        return Selection(
            faults=[e for e in registry.faults if e.fault.layer == selector],
            tasks=[t for t in registry.tasks if t.layer == selector],
        )
    wanted = list(dict.fromkeys(part.strip() for part in selector.split(",") if part.strip()))
    if not wanted:
        raise ConfigError("--faults: empty selection")
    faults = {e.fault.id: e for e in registry.faults}
    tasks = {t.id: t for t in registry.tasks}
    unknown = [w for w in wanted if w not in faults and w not in tasks]
    if unknown:
        raise ConfigError(f"--faults: unknown fault or task ids {unknown}")
    chosen_faults = [faults[w] for w in wanted if w in faults]
    layers = {e.fault.layer for e in chosen_faults}
    chosen_tasks = [t for t in registry.tasks if t.id in wanted or (t.kind == "control" and t.layer in layers)]
    return Selection(faults=chosen_faults, tasks=chosen_tasks)


def applicable_models(
    applies_to: Iterable[str], models: Sequence[ReferenceModel], *, cap: int = MAX_MODELS_PER_TYPE
) -> list[ReferenceModel]:
    """Models sharing at least one tag with ``applies_to``, in reference-file order, at most ``cap``."""
    tags = set(applies_to)
    return [m for m in models if tags.intersection(m.tags)][:cap]


def load_module(path: Path) -> ModuleType:
    """Import a Python file by path under a private module name, registered in ``sys.modules``."""
    rel = path.resolve().relative_to(EVAL_DIR) if path.resolve().is_relative_to(EVAL_DIR) else Path(path.name)
    name = "_eval_defs." + ".".join(rel.with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"{path}: cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        del sys.modules[name]
        raise ConfigError(f"{path}: import failed: {exc!r}") from exc
    return module


def _modules_in(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.py") if not p.name.startswith("_"))


def _attribute(path: Path, name: str, kind: type[_D]) -> _D:
    module = load_module(path)
    value: object = getattr(module, name, None)
    if not isinstance(value, kind):
        raise ConfigError(f"{path}: expected a module attribute {name}: {kind.__name__}")
    return value


def _check_id(item_id: str, path: Path) -> None:
    if not item_id or "@" in item_id or item_id.strip() != item_id:
        raise ConfigError(f"{path}: invalid id {item_id!r} (non-empty, no '@', no surrounding spaces)")


def _check_unique(ids: list[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item_id in ids:
        (duplicates if item_id in seen else seen).add(item_id)
    if duplicates:
        raise ConfigError(f"duplicate fault or task ids: {sorted(duplicates)}")


@dataclass(frozen=True)
class PlannedTask:
    """One (fault type or task spec) x (reference model) pair of a run, before injection and prompt rendering.

    ``skip_reason`` is set when the task will be recorded as ``verified_by="skipped"`` (FR-043).
    """

    task_id: str
    spec_id: str
    kind: TaskKind
    layer: Layer
    model: ReferenceModel
    model_path: Path
    needs_energyplus: bool
    held_out: bool
    skip_reason: str | None

    @property
    def runnable(self) -> bool:
        return self.skip_reason is None


def plan_tasks(
    selection: Selection,
    models: Sequence[ReferenceModel],
    *,
    example_files: Path | None,
    energyplus_available: bool,
    held_out_invalid: Iterable[str] = (),
    cap: int = MAX_MODELS_PER_TYPE,
) -> list[PlannedTask]:
    """Expand a selection over the reference models, in a stable order (faults, then tasks; models in file order).

    Only models whose file exists under ``example_files`` are used (none when it is ``None``); the cap applies
    after that filter. ``needs_energyplus`` tasks get a skip reason when EnergyPlus is unavailable. Faults in
    ``held_out_invalid`` are planned with ``held_out=False``: they count with the designed faults.
    """
    if example_files is None:
        return []
    available = [m for m in models if (example_files / m.file).is_file()]
    invalid = set(held_out_invalid)
    skip = None if energyplus_available else "EnergyPlus not found"
    plan: list[PlannedTask] = []
    fault_kind: TaskKind = "fault"
    items: list[tuple[str, TaskKind, Layer, list[str], bool, bool]] = [
        (
            e.fault.id,
            fault_kind,
            e.fault.layer,
            e.fault.applies_to,
            e.fault.needs_energyplus,
            e.fault.held_out and e.fault.id not in invalid,
        )
        for e in selection.faults
    ]
    for t in selection.tasks:
        items.append((t.id, t.kind, t.layer, t.applies_to, t.needs_energyplus, False))
    for spec_id, kind, layer, applies_to, needs_ep, held_out in items:
        for model in applicable_models(applies_to, available, cap=cap):
            plan.append(
                PlannedTask(
                    task_id=make_task_id(spec_id, model.id),
                    spec_id=spec_id,
                    kind=kind,
                    layer=layer,
                    model=model,
                    model_path=example_files / model.file,
                    needs_energyplus=needs_ep,
                    held_out=held_out,
                    skip_reason=skip if needs_ep else None,
                )
            )
    return plan


def task_infos(
    registry: Registry, task_ids: Iterable[str], *, held_out_invalid: Iterable[str] = ()
) -> dict[str, TaskInfo]:
    """``TaskInfo`` for each task id whose spec is in the registry (see ``model.split_task_id``); others are left out."""
    invalid = set(held_out_invalid)
    faults = {e.fault.id: e.fault for e in registry.faults}
    tasks = {t.id: t for t in registry.tasks}
    infos: dict[str, TaskInfo] = {}
    for task_id in task_ids:
        spec_id, _ = split_task_id(task_id)
        if spec_id in faults:
            fault = faults[spec_id]
            infos[task_id] = TaskInfo(
                task_id, "fault", fault.layer, fault.id, fault.held_out and fault.id not in invalid
            )
        elif spec_id in tasks:
            spec = tasks[spec_id]
            infos[task_id] = TaskInfo(task_id, spec.kind, spec.layer, None, False)
    return infos
