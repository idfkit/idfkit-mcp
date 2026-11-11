"""The harness's TOML configuration: baseline, runner, reference models and prompt templates.

TOML parsing uses ``tomllib`` on Python 3.11+ and ``tomli`` on 3.10. ``tomli`` is not a direct dependency of
idfkit-mcp but is installed on 3.10 through fastmcp (``cyclopts`` requires ``tomli`` for ``python < 3.11``). The
module is imported by name at run time so that pyright, which checks against ``pythonVersion = "3.10"``, does not
need ``tomli`` to be installed in the 3.11+ development environment.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from eval.model import BaselineKind

REQUIRED_RUNNER_PLACEHOLDERS = ("{prompt}", "{mcp_config}")


class ConfigError(Exception):
    """A configuration file or a fault/task definition is invalid (exit code 2)."""


@dataclass(frozen=True)
class BaselineConfig:
    """``eval/baseline.toml`` (FR-042c)."""

    kind: BaselineKind
    idfkit_mcp_sha: str
    idfkit: str


@dataclass(frozen=True)
class RunnerConfig:
    """``eval/runners/*.toml`` (contract: "Runner configuration")."""

    name: str
    command: list[str]
    model: str
    max_turns: int
    parse: str
    disallowed_tools: list[str]
    disallowed_flag: str

    @property
    def ablation(self) -> bool:
        return bool(self.disallowed_tools)


@dataclass(frozen=True)
class ReferenceModel:
    """One entry of ``eval/reference_models.toml``; ``file`` resolves under ``$ENERGYPLUS_DIR/ExampleFiles``."""

    id: str
    file: str
    version: str
    tags: list[str]


def load_toml(path: Path) -> dict[str, object]:
    """Parse a TOML file, raising ``ConfigError`` when it is missing or malformed."""
    module = importlib.import_module("tomllib" if sys.version_info >= (3, 11) else "tomli")
    loads = cast(Callable[[str], dict[str, object]], module.loads)
    try:
        return loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read ({exc})") from exc
    except ValueError as exc:  # tomllib.TOMLDecodeError subclasses ValueError
        raise ConfigError(f"{path}: invalid TOML ({exc})") from exc


def load_baseline(path: Path) -> BaselineConfig:
    data = load_toml(path)
    kind = _str(data, "kind", path)
    if kind not in ("pre_feature", "other"):
        raise ConfigError(f"{path}: kind must be 'pre_feature' or 'other', got {kind!r}")
    idfkit = _str(data, "idfkit", path)
    if not idfkit.startswith("idfkit=="):
        raise ConfigError(f"{path}: idfkit must be an exact pin 'idfkit==X', got {idfkit!r}")
    return BaselineConfig(kind=kind, idfkit_mcp_sha=_str(data, "idfkit_mcp_sha", path), idfkit=idfkit)


def load_runner(path: Path) -> RunnerConfig:
    data = load_toml(path)
    command = _str_list(data, "command", path)
    for placeholder in REQUIRED_RUNNER_PLACEHOLDERS:
        if not any(placeholder in part for part in command):
            raise ConfigError(f"{path}: command must contain {placeholder}")
    max_turns = data.get("max_turns")
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise ConfigError(f"{path}: max_turns must be a positive integer")
    return RunnerConfig(
        name=_str(data, "name", path),
        command=command,
        model=_str(data, "model", path),
        max_turns=max_turns,
        parse=_str(data, "parse", path),
        disallowed_tools=_str_list(data, "disallowed_tools", path),
        disallowed_flag=_str(data, "disallowed_flag", path),
    )


def load_reference_models(path: Path) -> list[ReferenceModel]:
    """Read ``[[models]]`` entries, in file order, with unique ids."""
    data = load_toml(path)
    raw = data.get("models")
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{path}: expected a non-empty [[models]] array")
    models: list[ReferenceModel] = []
    seen: set[str] = set()
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise ConfigError(f"{path}: each [[models]] entry must be a table")
        entry = cast(dict[str, object], item)
        model = ReferenceModel(
            id=_str(entry, "id", path),
            file=_str(entry, "file", path),
            version=_str(entry, "version", path),
            tags=_str_list(entry, "tags", path),
        )
        if model.id in seen:
            raise ConfigError(f"{path}: duplicate model id {model.id!r}")
        if "@" in model.id:
            raise ConfigError(f"{path}: model id {model.id!r} must not contain '@'")
        seen.add(model.id)
        models.append(model)
    return models


def load_prompt_templates(path: Path) -> dict[str, str]:
    """Read ``eval/prompts.toml``: tables of named templates, flattened to ``"<table>.<name>"`` keys."""
    data = load_toml(path)
    templates: dict[str, str] = {}
    for table_name, table in data.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: top-level entries must be tables, got {table_name!r}")
        for name, template in cast(dict[str, object], table).items():
            if not isinstance(template, str) or not template.strip():
                raise ConfigError(f"{path}: {table_name}.{name} must be a non-empty string")
            templates[f"{table_name}.{name}"] = template
    if not templates:
        raise ConfigError(f"{path}: no templates")
    return templates


def _str(data: Mapping[str, object], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{path}: {key} must be a non-empty string")
    return value


def _str_list(data: Mapping[str, object], key: str, path: Path) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ConfigError(f"{path}: {key} must be a list of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise ConfigError(f"{path}: {key} must be a list of strings")
    return cast(list[str], items)
