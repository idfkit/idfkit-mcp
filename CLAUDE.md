# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Install dependencies
uv sync

# Run all quality checks (lint, format, type check, deptry)
make check

# Run tests
make test

# Run a single test
uv run pytest tests/test_file.py::test_function -v

# Serve documentation locally
make docs

# Build and run Docker container
make docker-build && make docker-run
```

## Before Committing

Always run the full quality gate before proposing changes:

```bash
make check && make test
```

This runs: lock file validation, pre-commit hooks (ruff format/lint), pyright, deptry, and pytest.

## Automated idfkit bumps

When invoked by `.github/workflows/bump-idfkit.yml` on test failure after an idfkit version bump:

- Make the smallest possible compatibility change.
- Do not perform unrelated refactors.
- Do not change formatting broadly.
- Run `uv run pytest` before finishing.
- Preserve public APIs unless the idfkit upgrade requires otherwise.
- Summarize:
  - root cause
  - files changed
  - tests run
  - remaining risks
