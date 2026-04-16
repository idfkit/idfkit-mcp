"""IdfUploadStore — FastMCP FileUpload provider tuned for IDF/epJSON uploads.

The base ``FileUpload`` provider exposes ``read_file`` to the LLM, which
returns full file content for any ``.json`` upload — for an epJSON model
that's hundreds of thousands of tokens of model data on the wire. We
suppress ``read_file`` and route bytes through ``load_model`` instead, so
file content stays server-side and the LLM only sees the compact
``ModelSummary``.

Scope key reuses the same ``_current_session_id`` contextvar that backs
``ServerState`` so uploads and per-session state share one identifier.

Two storage backends:

- **In-memory** (default): bytes live on the instance; lost on process
  exit. Fine for stdio and single-container HTTP deployments.
- **Disk-backed** (``root`` set, typically via ``IDFKIT_MCP_UPLOAD_DIR``):
  bytes written to ``<root>/<session_id>/<name>`` with a sidecar
  ``<name>.meta.json``. Use this when the server is fronted by a
  shared volume (EFS, NFS) so replicas see the same uploads.
"""

from __future__ import annotations

import base64
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastmcp.apps.file_upload import FileUpload
from fastmcp.server.context import Context


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _make_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": entry["name"],
        "type": entry["type"],
        "size": entry["size"],
        "size_display": _format_size(entry["size"]),
        "uploaded_at": entry["uploaded_at"],
    }


def _safe_name(name: str) -> str:
    """Reject upload names that could escape the scope directory."""
    if not name or name in (".", ".."):
        raise ValueError(f"Invalid upload name: {name!r}")
    if "/" in name or "\\" in name or "\x00" in name:
        raise ValueError(f"Upload name must not contain path separators: {name!r}")
    if name.startswith("."):
        raise ValueError(f"Upload name must not start with '.': {name!r}")
    return name


class IdfUploadStore(FileUpload):
    """FileUpload subclass that hides ``read_file`` and exposes raw bytes server-side.

    Pass ``root`` (or set the ``IDFKIT_MCP_UPLOAD_DIR`` env var when constructed
    via ``server.py``) to persist uploads to disk under ``<root>/<session>/``.

    .. todo:: Uploads accumulate over time because ``clear_session`` no longer
       removes them (uploads are user data, not ephemeral state). For long-lived
       deployed servers this needs a cleanup strategy — e.g. TTL-based eviction,
       max total size per session, or a periodic sweep of stale scope directories.
    """

    def __init__(self, *, root: Path | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._local.remove_tool("read_file")
        self._root = root
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)

    def _get_scope_key(self, ctx: Context) -> str:
        from idfkit_mcp.state import current_session_id

        return current_session_id()

    # ------------------------------------------------------------------
    # Disk-backed storage overrides (no-ops when self._root is None)
    # ------------------------------------------------------------------

    def _scope_dir(self, scope: str) -> Path:
        if self._root is None:
            raise RuntimeError("_scope_dir called on in-memory store")
        d = self._root / scope
        d.mkdir(parents=True, exist_ok=True)
        return d

    def on_store(self, files: list[dict[str, Any]], ctx: Context) -> list[dict[str, Any]]:
        if self._root is None:
            return super().on_store(files, ctx)
        scope = self._get_scope_key(ctx)
        scope_dir = self._scope_dir(scope)
        for f in files:
            name = _safe_name(f["name"])
            (scope_dir / name).write_bytes(base64.b64decode(f["data"]))
            meta = {
                "name": name,
                "size": f["size"],
                "type": f["type"],
                "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            (scope_dir / f"{name}.meta.json").write_text(json.dumps(meta))
        return self.on_list(ctx)

    def on_list(self, ctx: Context) -> list[dict[str, Any]]:
        if self._root is None:
            return super().on_list(ctx)
        scope = self._get_scope_key(ctx)
        scope_dir = self._root / scope
        if not scope_dir.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for meta_path in sorted(scope_dir.glob("*.meta.json")):
            try:
                entries.append(_make_summary(json.loads(meta_path.read_text())))
            except (OSError, json.JSONDecodeError):
                continue
        return entries

    def on_read(self, name: str, ctx: Context) -> dict[str, Any]:
        # Kept so in-memory callers still work (read_file is not LLM-exposed).
        if self._root is None:
            return super().on_read(name, ctx)
        scope = self._get_scope_key(ctx)
        safe = _safe_name(name)
        scope_dir = self._root / scope
        meta_path = scope_dir / f"{safe}.meta.json"
        if not meta_path.exists():
            available = sorted(p.stem.removesuffix(".meta") for p in scope_dir.glob("*.meta.json"))
            raise ValueError(f"File {name!r} not found. Available: {available}")
        meta = json.loads(meta_path.read_text())
        return {
            "name": meta["name"],
            "size": meta["size"],
            "type": meta["type"],
            "uploaded_at": meta["uploaded_at"],
            "size_display": _format_size(meta["size"]),
        }

    def get_bytes(self, name: str, session_id: str | None = None) -> bytes:
        """Return raw bytes for an uploaded file in the given (or current) session."""
        if session_id is None:
            from idfkit_mcp.state import current_session_id

            session_id = current_session_id()
        safe = _safe_name(name)
        if self._root is not None:
            path = self._root / session_id / safe
            if not path.is_file():
                available = sorted(
                    p.name for p in (self._root / session_id).glob("*") if not p.name.endswith(".meta.json")
                )
                raise KeyError(f"No upload named {name!r} in this session. Available: {available}")
            return path.read_bytes()
        entry = self._store.get(session_id, {}).get(safe)
        if entry is None:
            available = sorted(self._store.get(session_id, {}).keys())
            raise KeyError(f"No upload named {name!r} in this session. Available: {available}")
        return base64.b64decode(entry["data"])

    def clear_scope(self, session_id: str) -> None:
        """Remove all uploads for a session from both backends."""
        self._store.pop(session_id, None)
        if self._root is not None:
            scope_dir = self._root / session_id
            if scope_dir.exists():
                shutil.rmtree(scope_dir, ignore_errors=True)
