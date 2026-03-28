"""Output path validation for MCP tools."""

from __future__ import annotations

from pathlib import Path

from fastmcp.exceptions import ToolError


def validate_output_path(path: Path, *, label: str = "Output path") -> Path:
    """Ensure *path* resolves within the current working directory.

    Both relative paths and absolute paths that happen to fall inside CWD are
    accepted.  Raises :class:`ToolError` for anything that escapes CWD
    (including via ``..`` traversal or symlinks).
    """
    cwd = Path.cwd().resolve()
    resolved = path.resolve() if path.is_absolute() else (cwd / path).resolve()
    try:
        resolved.relative_to(cwd)
    except ValueError:
        raise ToolError(
            f"{label} must be within the working directory ({cwd}). "
            f"Got: '{path}'. Use a relative path instead."
        ) from None
    return resolved
