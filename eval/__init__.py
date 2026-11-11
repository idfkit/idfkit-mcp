"""Evaluation harness for the model knowledge graph (User Story 2, FR-040 to FR-046).

A maintainer tool, never packaged: it lives at the repository root and is excluded from the wheel and the sdist.
Run it from the repository root with ``uv run python -m eval``. The command line is specified in
``specs/013-model-knowledge-graph/contracts/eval-harness.md`` in idfkit-unification; the data model in
``data-model.md`` there (Evaluation).

Modules:

- ``eval.model``: the data model (``FaultType``, ``TaskSpec``, ``EvaluationTask``, ``TaskOutcome``,
  ``EvaluationRun``, ``Comparison``, ``GateVerdict``) and run-directory I/O.
- ``eval.config``: the TOML configuration files (baseline, runner, reference models, prompt templates).
- ``eval.registry``: discovery of fault and task definitions, selection and model applicability.
- ``eval.lint``: the prompt lint (FR-042b).
- ``eval.held_out``: the git-based held-out check (FR-040a, research R-33).
- ``eval.stats``: the paired bootstrap, the SC-008 spread and the SC-009 gate verdict (research R-32).
"""

from __future__ import annotations
