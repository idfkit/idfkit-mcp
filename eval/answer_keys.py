"""Committed answer keys of the open questions (``eval/tasks/questions/<id>.json``).

Each question module computes its key from the unmodified model with ``answer_key(doc)``; this module computes the
key for every reference model the question applies to (capped at 8, as the run plans it) and commits it beside the
module, so a reviewer can read the expected answers and a test can detect a key that drifts.

```bash
uv run python -m eval.answer_keys [--example-files <dir>]   # rewrite the committed keys
```

The keys are computed from the EnergyPlus ExampleFiles of the installed EnergyPlus; each file says which version in
its ``header`` and ``energyplus`` fields. The evaluation targets the 26.2 files (contracts/eval-harness.md). Results-layer keys need EnergyPlus
(a design-day run each).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from eval.config import ReferenceModel, load_reference_models
from eval.model import TaskSpec
from eval.registry import EVAL_DIR, applicable_models, load_task_modules

QUESTIONS_DIR = EVAL_DIR / "tasks" / "questions"
HEADER = (
    "Answer keys computed by answer_key(doc) from the unmodified reference models of the EnergyPlus {version} "
    "ExampleFiles. Regenerate with: uv run python -m eval.answer_keys"
)


def keys_path(spec: TaskSpec) -> Path:
    return QUESTIONS_DIR / f"{spec.id}.json"


def question_specs() -> list[TaskSpec]:
    return load_task_modules(QUESTIONS_DIR, kind="question")


def models_for(spec: TaskSpec, models: Sequence[ReferenceModel], example_files: Path) -> list[ReferenceModel]:
    available = [m for m in models if (example_files / m.file).is_file()]
    return applicable_models(spec.applies_to, available)


def compute_keys(spec: TaskSpec, models: Sequence[ReferenceModel], example_files: Path) -> dict[str, str]:
    """``model id -> key`` for every applicable reference model under ``example_files``."""
    from idfkit import load_idf

    if spec.answer_key is None:
        raise ValueError(f"{spec.id}: not a question task")
    return {
        m.id: spec.answer_key(load_idf(str(example_files / m.file))) for m in models_for(spec, models, example_files)
    }


def load_committed(spec: TaskSpec) -> dict[str, str]:
    """The committed ``model id -> key`` of a question (empty when no file is committed)."""
    path = keys_path(spec)
    if not path.is_file():
        return {}
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    keys = cast(dict[str, object], raw).get("keys") if isinstance(raw, dict) else None
    if not isinstance(keys, dict):
        raise TypeError(f"{path}: expected an object with a 'keys' object")
    return {str(k): str(v) for k, v in cast(dict[object, object], keys).items()}


def write_keys(spec: TaskSpec, keys: dict[str, str], *, energyplus_version: str) -> Path:
    path = keys_path(spec)
    document = {
        "header": HEADER.format(version=energyplus_version),
        "question": spec.id,
        "energyplus": energyplus_version,
        "keys": keys,
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    from idfkit.simulation.config import find_energyplus

    parser = argparse.ArgumentParser(prog="python -m eval.answer_keys", description="rewrite the committed keys")
    parser.add_argument("--example-files", type=Path, default=None)
    args = parser.parse_args(argv)
    config = find_energyplus()
    example_files: Path = args.example_files or config.install_dir / "ExampleFiles"
    version = ".".join(str(part) for part in config.version)
    models = load_reference_models(EVAL_DIR / "reference_models.toml")
    for spec in question_specs():
        path = write_keys(spec, compute_keys(spec, models, example_files), energyplus_version=version)
        print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
