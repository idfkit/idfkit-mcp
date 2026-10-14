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

## The consumer register

This repository is `idfkit-mcp` in the consumer register, `governance/consumers.toml` in
idfkit-conformance, read at the governance tag pinned in `.github/workflows/main.yml`. The register
records where the idfkit level is declared and never the level itself.

- **Where the level lives**: the exact `idfkit==X` pin in `project.dependencies` of `pyproject.toml`,
  and nowhere else. Bumping it needs no register change.
- **Self-check**: the `consumer-register` job in `main.yml` calls `check-consumer.yml` at that tag.
  It fails when the level moves to a file the register does not point at, or when a new dependency
  on either library appears that the register does not name. It does not care whether the level is
  current. Moving where the level is declared is a change to the register, in idfkit-conformance,
  reviewed by both languages.
- **Rehearsal**: `.github/workflows/rehearse-candidate.yml` builds a wheel from any idfkit ref and runs
  `uv run pyright`, then the tests, against it, without touching `pyproject.toml` or `uv.lock`. Run it
  before an idfkit release, not after one. pyright is the instrument that sees `write_idf(doc, path)`
  in `tools/write.py` stop meaning "save".
- **Version**: `idfkit-mcp --version` prints this server's version and the idfkit it runs against.
  The plugin and the hosted deployment both deliver this server to people, and each must be able to
  say which level it runs.

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

The bump also does three things that are not repairs, and none of them is for the repair step to undo:

- It lists every `idfkit:unavailable` statement marker resting on a capability the new level closed,
  opens the pull request as a draft, and fails while one is listed. Review one by removing the
  statement or by setting its `own_reason`.
- When the register holds a lag for this repository, it closes it through a paired pull request in
  idfkit-conformance.
- Dispatched with `decline_reason`, it bumps nothing and records a deliberate lag instead.
