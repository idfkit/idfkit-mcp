"""The two conditions' servers (FR-042c, research R-13; task T066).

- **Baseline, pre-feature** (``eval/baseline.toml``): a ``git worktree`` of ``idfkit_mcp_sha`` in a temporary
  directory, run as ``uv run --project <worktree> --with <idfkit pin> idfkit-mcp``. The worktree is removed when
  the run ends (``Conditions.close``, or the ``build_conditions`` context manager).
- **Baseline, other** (``--baseline "<command>"``): that command; the run records ``baseline_kind = "other"``.
- **Treatment** (``--treatment "<command>"``): that command.

The agent runs in a per-task working directory, and so does the server it starts: MCP stdio configurations carry no
working directory. A ``uv run`` command that names no project (``uv run idfkit-mcp``) would then look for one in
that directory, so ``anchor_uv_command`` adds ``--project <idfkit-mcp checkout>`` to it. Other commands
(``uvx idfkit-mcp==X``, an absolute path) are used as given.
"""

from __future__ import annotations

import contextlib
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from eval.config import BaselineConfig, ConfigError
from eval.held_out import GitError
from eval.runner import ServerCommand

REPO_ROOT = Path(__file__).resolve().parent.parent
"""The idfkit-mcp checkout the harness runs from: the treatment's project."""

_PROJECT_OPTIONS = ("--project", "--directory")


@dataclass
class Conditions:
    """The servers of a run. ``baseline`` is ``None`` for an ablation run, which compares the treatment with
    itself under a disallowed-tools list."""

    treatment: ServerCommand
    baseline: ServerCommand | None
    baseline_sha: str
    baseline_idfkit: str
    treatment_revision: str
    cleanup: list[Path] = field(default_factory=list[Path], repr=False)
    """Worktrees to remove on ``close``."""
    repo: Path = REPO_ROOT

    def close(self) -> None:
        """Remove the baseline worktree, if one was made."""
        while self.cleanup:
            path = self.cleanup.pop()
            remove_worktree(self.repo, path)


def parse_command(command: str, *, project: Path = REPO_ROOT, env: Mapping[str, str] | None = None) -> ServerCommand:
    """A server command given on the command line, split like a POSIX shell would (no shell runs it)."""
    argv = shlex.split(command)
    if not argv:
        raise ConfigError("empty server command")
    return ServerCommand(argv=anchor_uv_command(argv, project), env=dict(env or {}))


def anchor_uv_command(argv: Sequence[str], project: Path) -> list[str]:
    """Add ``--project <project>`` after ``uv run`` when the command names no project or directory."""
    items = list(argv)
    if len(items) >= 2 and Path(items[0]).name in ("uv", "uv.exe") and items[1] == "run":
        named = any(
            item in _PROJECT_OPTIONS or item.startswith(tuple(f"{o}=" for o in _PROJECT_OPTIONS)) for item in items
        )
        if not named:
            return [items[0], "run", "--project", str(project), *items[2:]]
    return items


def baseline_server(worktree: Path, idfkit_pin: str, *, env: Mapping[str, str] | None = None) -> ServerCommand:
    """The pre-feature server: the worktree's own project with the pinned idfkit layered on top."""
    uv = shutil.which("uv") or "uv"
    argv = [uv, "run", "--project", str(worktree), "--with", idfkit_pin, "idfkit-mcp"]
    return ServerCommand(argv=argv, env=dict(env or {}))


def add_worktree(repo: Path, sha: str, parent: Path) -> Path:
    """Check out ``sha`` of ``repo`` as a detached worktree under ``parent``; ``GitError`` when it cannot."""
    _git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    path = parent / f"baseline-{sha}"
    _git(repo, "worktree", "add", "--detach", "--force", str(path), sha)
    return path


def remove_worktree(repo: Path, path: Path) -> None:
    """Remove a worktree made by ``add_worktree`` and its temporary parent; never raises."""
    try:
        _git(repo, "worktree", "remove", "--force", str(path))
    except GitError:
        shutil.rmtree(path, ignore_errors=True)
        with contextlib.suppress(GitError):
            _git(repo, "worktree", "prune")
    shutil.rmtree(path.parent, ignore_errors=True)


def revision(repo: Path = REPO_ROOT) -> str:
    """The checkout's short commit, with ``+dirty`` when the working tree has changes; ``"unknown"`` outside git."""
    try:
        sha = _git(repo, "rev-parse", "--short", "HEAD")
        dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
    except GitError:
        return "unknown"
    return f"{sha}+dirty" if dirty else sha


def prewarm(server: ServerCommand, *, timeout: float = 900.0) -> None:
    """Build the baseline's environment once, before any agent starts it: a cold ``uv run`` can outlast the agent
    CLI's server start-up timeout. Runs the same ``uv run`` with ``python -c "import idfkit_mcp"``."""
    argv = [*server.argv[:-1], "python", "-c", "import idfkit_mcp"]
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=timeout)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"the baseline server does not start: {' '.join(argv)}: {exc}") from exc


@contextmanager
def build_conditions(
    *,
    treatment_command: str,
    baseline: BaselineConfig | None,
    baseline_command: str | None,
    ablation: bool,
    env: Mapping[str, str] | None = None,
    repo: Path = REPO_ROOT,
    warm: bool = True,
) -> Iterator[Conditions]:
    """Build both conditions' servers for the length of the ``with`` block, then remove the baseline worktree."""
    treatment = parse_command(treatment_command, project=repo, env=env)
    conditions = Conditions(
        treatment=treatment,
        baseline=None,
        baseline_sha=baseline.idfkit_mcp_sha if baseline is not None else "",
        baseline_idfkit=baseline.idfkit if baseline is not None else "",
        treatment_revision=revision(repo),
        repo=repo,
    )
    try:
        if not ablation:
            if baseline_command is not None:
                conditions.baseline = parse_command(baseline_command, project=repo, env=env)
            elif baseline is not None:
                parent = Path(tempfile.mkdtemp(prefix="idfkit-eval-baseline-"))
                worktree = add_worktree(repo, baseline.idfkit_mcp_sha, parent)
                conditions.cleanup.append(worktree)
                conditions.baseline = baseline_server(worktree, baseline.idfkit, env=env)
                if warm:
                    prewarm(conditions.baseline)
            else:
                raise ConfigError("no baseline: pass --baseline-config or --baseline")
        yield conditions
    finally:
        conditions.close()


def _git(repo: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise GitError("git is not installed")
    try:
        done = subprocess.run([git, "-C", str(repo), *args], check=True, capture_output=True, text=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        raise GitError(f"git {' '.join(args)} failed in {repo}: {exc.stderr.strip()}") from exc
    return done.stdout.strip()
