"""Transport-aware path validation for MCP tools.

The active transport is stored as module-level state set by ``server.main()``
via :func:`set_active_transport`. Tool code reads it through
:func:`active_transport` / :func:`restricted_transport_enabled`. When the
server is embedded (no ``main()`` call), the policy falls back to the public
``IDFKIT_MCP_TRANSPORT`` env var, and finally to ``stdio``.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp.exceptions import ToolError

# Module-level state set by server.main() once the CLI transport is known.
# None means "not configured yet"; readers fall back to IDFKIT_MCP_TRANSPORT.
_active_transport: str | None = None


def normalize_transport(transport: str | None) -> str:
    """Return the canonical transport name used by security policy checks."""
    if transport == "streamable-http":
        return "http"
    return transport or "stdio"


def set_active_transport(transport: str | None) -> None:
    """Record the CLI-selected transport for validators that run during tool calls.

    Pass ``None`` to reset (useful between tests).
    """
    global _active_transport
    _active_transport = normalize_transport(transport) if transport else None


def active_transport() -> str:
    """Return the currently configured transport, defaulting to local stdio."""
    if _active_transport is not None:
        return _active_transport
    return normalize_transport(os.environ.get("IDFKIT_MCP_TRANSPORT"))


def restricted_transport_enabled() -> bool:
    """Return True when the server is running in a network transport mode."""
    return active_transport() != "stdio"


def _env_roots(env_var: str) -> list[Path]:
    env = os.environ.get(env_var)
    if not env:
        return []
    sep = ";" if os.name == "nt" else ":"
    return [Path(p).resolve() for p in env.split(sep) if p.strip()]


def _allowed_output_roots() -> list[Path]:
    """Return the list of directories that output paths may resolve into.

    Reads ``IDFKIT_MCP_OUTPUT_DIRS`` (colon-separated on POSIX,
    semicolon-separated on Windows). Falls back to CWD for stdio only.
    """
    roots = _env_roots("IDFKIT_MCP_OUTPUT_DIRS")
    if roots:
        return roots
    if restricted_transport_enabled():
        raise ToolError(
            "IDFKIT_MCP_OUTPUT_DIRS is required for non-stdio transports. "
            "Set it to one or more directories where user-named output files may be written."
        )
    return [Path.cwd().resolve()]


def _validate_with_roots(path: Path, roots: list[Path], *, env_var: str, label: str) -> Path:
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
        f"{label} must be within an allowed directory ({dirs}). Got: '{path}'. Set {env_var} to add more directories."
    )


def validate_input_path(path: Path, *, label: str = "Input path") -> Path:
    """Validate a server-local input path.

    Local stdio clients keep direct filesystem access. Network transports must
    explicitly opt in via ``IDFKIT_MCP_INPUT_DIRS``; otherwise callers should
    use upload-backed workflows instead of server-local paths.
    """
    if not restricted_transport_enabled():
        return path

    roots = _env_roots("IDFKIT_MCP_INPUT_DIRS")
    if not roots:
        raise ToolError(
            f"{label} is disabled for non-stdio transports. "
            "Upload the model and call load_model(upload_name=...), or set IDFKIT_MCP_INPUT_DIRS "
            "to allow specific server-local input directories."
        )
    return _validate_with_roots(path, roots, env_var="IDFKIT_MCP_INPUT_DIRS", label=label)


def validate_output_path(path: Path, *, label: str = "Output path") -> Path:
    """Ensure *path* resolves within an allowed output directory.

    Allowed directories come from ``IDFKIT_MCP_OUTPUT_DIRS`` (colon-separated),
    falling back to the current working directory for stdio when the variable is unset.

    Both relative paths and absolute paths that fall inside an allowed
    directory are accepted.  Raises :class:`ToolError` for anything that
    escapes all allowed roots (including via ``..`` traversal or symlinks).
    """
    return _validate_with_roots(
        path,
        _allowed_output_roots(),
        env_var="IDFKIT_MCP_OUTPUT_DIRS",
        label=label,
    )


def validate_simulation_output_dir(path: Path, *, label: str = "Simulation output directory") -> Path:
    """Validate a caller-specified EnergyPlus run directory."""
    if not restricted_transport_enabled():
        return path

    roots = _env_roots("IDFKIT_MCP_SIMULATION_DIR")
    if not roots:
        raise ToolError("IDFKIT_MCP_SIMULATION_DIR is required for non-stdio transports.")
    return _validate_with_roots(path, roots, env_var="IDFKIT_MCP_SIMULATION_DIR", label=label)


def validate_restored_path(
    path: Path,
    *,
    label: str,
    env_var: str,
    extra_roots: list[Path] | None = None,
) -> Path:
    """Validate a path read from a persisted session file."""
    if not restricted_transport_enabled():
        return path

    roots = _env_roots(env_var)
    if extra_roots:
        roots.extend(root.resolve() for root in extra_roots)
    if not roots:
        raise ToolError(f"{env_var} is required to restore {label.lower()} for non-stdio transports.")
    return _validate_with_roots(path, roots, env_var=env_var, label=label)
