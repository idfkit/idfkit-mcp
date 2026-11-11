"""Prompt lint (FR-042b, contract "Rules").

A rendered prompt fails when it contains, case-insensitively:

- the injected object's name,
- the field name (as written, and with underscores and spaces swapped),
- the fault id (as written, and with underscores, hyphens and spaces swapped),
- a word starting with "fault", "injected" or "bug" ("faults", "faulty", "bugs" fail; "default" and "debug" do
  not, because they do not start with a banned word).

Templates are linted before rendering with ``lint_template``: banned words and the fault id only, since object and
field names are known only after injection.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

BANNED_WORDS = ("fault", "injected", "bug")

_BANNED = re.compile(r"\b(" + "|".join(BANNED_WORDS) + r")", re.IGNORECASE)

ViolationKind = Literal["object_name", "field_name", "fault_id", "banned_word"]


@dataclass(frozen=True)
class LintViolation:
    """One reason a prompt fails the lint."""

    kind: ViolationKind
    term: str

    def __str__(self) -> str:
        return f"prompt contains {self.kind.replace('_', ' ')} {self.term!r}"


class PromptLintError(Exception):
    """A prompt failed the lint (exit code 2)."""

    def __init__(self, label: str, prompt: str, violations: list[LintViolation]) -> None:
        self.label = label
        self.prompt = prompt
        self.violations = violations
        reasons = "; ".join(str(v) for v in violations)
        super().__init__(f"{label}: {reasons}: {prompt!r}")


def lint_prompt(
    prompt: str,
    *,
    object_names: Iterable[str] = (),
    field_names: Iterable[str] = (),
    fault_id: str | None = None,
) -> list[LintViolation]:
    """Every reason ``prompt`` fails the lint; empty when it passes."""
    violations = [LintViolation("banned_word", m.group(0)) for m in _BANNED.finditer(prompt)]
    folded = prompt.casefold()
    for name in object_names:
        if name.strip() and name.casefold() in folded:
            violations.append(LintViolation("object_name", name))
    for name in field_names:
        if any(variant in folded for variant in _variants(name, "_ ")):
            violations.append(LintViolation("field_name", name))
    if fault_id is not None and any(variant in folded for variant in _variants(fault_id, "_- ")):
        violations.append(LintViolation("fault_id", fault_id))
    return violations


def lint_template(template: str, *, fault_id: str | None = None) -> list[LintViolation]:
    """Lint an unrendered template: banned words and the fault id."""
    return lint_prompt(template, fault_id=fault_id)


def check_prompt(
    label: str,
    prompt: str,
    *,
    object_names: Iterable[str] = (),
    field_names: Iterable[str] = (),
    fault_id: str | None = None,
) -> None:
    """Raise ``PromptLintError`` when ``prompt`` fails the lint."""
    violations = lint_prompt(prompt, object_names=object_names, field_names=field_names, fault_id=fault_id)
    if violations:
        raise PromptLintError(label, prompt, violations)


def _variants(term: str, separators: str) -> set[str]:
    """``term`` case-folded, plus each spelling with its separators replaced by each other separator."""
    folded = term.strip().casefold()
    if not folded:
        return set()
    variants = {folded}
    for old in separators:
        for new in separators:
            if old != new:
                variants.add(folded.replace(old, new))
    return variants
