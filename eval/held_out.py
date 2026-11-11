"""Held-out check (FR-040a, research R-33).

For each file under ``eval/faults/held_out/``, the commit that first added it must predate the first commit that
added ``src/idfkit/hvac/checks.py`` in the idfkit checkout, at the ref the treatment pins. Commits of the two
repositories are compared by committer date (``%cI``), the only order they share.

A held-out fault that fails is ``held_out_invalid``: it is reported and counted with the designed faults.

Edge cases:

- **No checks commit yet.** When ``checks.py`` has never been added at that ref, no check can have been written
  against any fault, so every committed held-out fault is valid, and so is an uncommitted one.
- **Uncommitted fault file.** When the checks commit exists and the fault file has no commit, the fault is invalid:
  it will be committed after the checks.
- A file deleted and re-added counts from its first addition (``git log --diff-filter=A --reverse``).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CHECKS_PATH = "src/idfkit/hvac/checks.py"


class GitError(Exception):
    """git is missing, or a path is not inside a git repository, or git failed."""


@dataclass(frozen=True)
class CommitRef:
    """A commit and its committer date."""

    sha: str
    committed_at: datetime


@dataclass(frozen=True)
class HeldOutStatus:
    """The check's result for one held-out fault file."""

    fault_id: str
    file: Path
    defined_in: CommitRef | None
    valid: bool
    reason: str


@dataclass(frozen=True)
class HeldOutReport:
    """The check's result for every held-out fault, and the checks commit it was compared with."""

    checks_commit: CommitRef | None
    statuses: list[HeldOutStatus]

    @property
    def invalid(self) -> list[str]:
        """Ids of ``held_out_invalid`` faults."""
        return [s.fault_id for s in self.statuses if not s.valid]

    @property
    def ok(self) -> bool:
        return not self.invalid


def first_commit_adding(repo: Path, path: str, *, ref: str = "HEAD") -> CommitRef | None:
    """The first commit reachable from ``ref`` that added ``path`` (relative to ``repo``), or ``None``."""
    out = _git(repo, "log", ref, "--diff-filter=A", "--reverse", "--format=%H%x09%cI", "--", path)
    for line in out.splitlines():
        if line.strip():
            sha, _, date = line.partition("\t")
            return CommitRef(sha=sha, committed_at=datetime.fromisoformat(date))
    return None


def check_held_out(
    fault_files: Mapping[str, Path],
    *,
    idfkit_repo: Path,
    idfkit_ref: str = "HEAD",
    checks_path: str = CHECKS_PATH,
) -> HeldOutReport:
    """Check every held-out fault file (``fault id -> file path``) against the idfkit checks commit.

    Args:
        fault_files: The held-out faults and the files that define them, in any git repository.
        idfkit_repo: A checkout of idfkit.
        idfkit_ref: The ref of that checkout at the level the treatment pins (a tag such as ``v1.3.0``).
        checks_path: The checks module, relative to the idfkit checkout.

    Raises:
        GitError: git is not available, or a path is not in a git repository, or ``idfkit_ref`` is unknown.
    """
    checks_commit = first_commit_adding(idfkit_repo, checks_path, ref=idfkit_ref)
    statuses: list[HeldOutStatus] = []
    for fault_id, file in fault_files.items():
        defined_in = first_commit_adding(file.parent, file.name)
        valid, reason = _judge(defined_in, checks_commit, checks_path)
        statuses.append(HeldOutStatus(fault_id=fault_id, file=file, defined_in=defined_in, valid=valid, reason=reason))
    return HeldOutReport(checks_commit=checks_commit, statuses=statuses)


def _judge(defined_in: CommitRef | None, checks: CommitRef | None, checks_path: str) -> tuple[bool, str]:
    if checks is None:
        return True, f"{checks_path} has not been added yet"
    if defined_in is None:
        return False, f"not committed, and {checks_path} was added in {checks.sha[:12]}"
    if defined_in.committed_at < checks.committed_at:
        return True, f"added in {defined_in.sha[:12]}, before {checks.sha[:12]}"
    return False, f"added in {defined_in.sha[:12]}, not before {checks_path} in {checks.sha[:12]}"


def _git(cwd: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise GitError("git is not on PATH")
    if not cwd.is_dir():
        raise GitError(f"{cwd} is not a directory")
    proc = subprocess.run([git, "-C", str(cwd), *args], capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} in {cwd} failed: {proc.stderr.strip()}")
    return proc.stdout
