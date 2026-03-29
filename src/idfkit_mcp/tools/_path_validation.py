"""Output path validation for MCP tools."""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp.exceptions import ToolError


def _allowed_roots() -> list[Path]:
    """Return the list of directories that output paths may resolve into.

    Reads ``IDFKIT_MCP_OUTPUT_DIRS`` (colon-separated on POSIX,
    semicolon-separated on Windows).  Falls back to CWD when the variable
    is unset.
    """
    env = os.environ.get("IDFKIT_MCP_OUTPUT_DIRS")
    if env:
        sep = ";" if os.name == "nt" else ":"
        return [Path(p).resolve() for p in env.split(sep) if p.strip()]
    return [Path.cwd().resolve()]


def validate_output_path(path: Path, *, label: str = "Output path") -> Path:
    """Ensure *path* resolves within an allowed output directory.

    Allowed directories come from ``IDFKIT_MCP_OUTPUT_DIRS`` (colon-separated),
    falling back to the current working directory when the variable is unset.

    Both relative paths and absolute paths that fall inside an allowed
    directory are accepted.  Raises :class:`ToolError` for anything that
    escapes all allowed roots (including via ``..`` traversal or symlinks).
    """
    roots = _allowed_roots()
    cwd = Path.cwd().resolve()
    resolved = path.resolve() if path.is_absolute() else (cwd / path).resolve()
    for root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        else:
            return resolved
    dirs = ", ".join(str(r) for r in roots)
    raise ToolError(
        f"{label} must be within an allowed directory ({dirs}). "
        f"Got: '{path}'. Set IDFKIT_MCP_OUTPUT_DIRS to add more directories."
    )
