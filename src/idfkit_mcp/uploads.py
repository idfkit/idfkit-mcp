"""IdfUploadStore — FastMCP FileUpload provider tuned for IDF/epJSON uploads.

The base ``FileUpload`` provider exposes ``read_file`` to the LLM, which
returns full file content for any ``.json`` upload — for an epJSON model
that's hundreds of thousands of tokens of model data on the wire. We
suppress ``read_file`` and route bytes through ``load_model`` instead, so
file content stays server-side and the LLM only sees the compact
``ModelSummary``.

Scope key reuses the same ``_current_session_id`` contextvar that backs
``ServerState`` so uploads and per-session state share one identifier.
"""

from __future__ import annotations

import base64

from fastmcp.apps.file_upload import FileUpload
from fastmcp.server.context import Context


class IdfUploadStore(FileUpload):
    """FileUpload subclass that hides ``read_file`` and exposes raw bytes server-side."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._local.remove_tool("read_file")

    def _get_scope_key(self, ctx: Context) -> str:
        from idfkit_mcp.state import current_session_id

        return current_session_id()

    def get_bytes(self, name: str, session_id: str | None = None) -> bytes:
        """Return raw bytes for an uploaded file in the given (or current) session."""
        if session_id is None:
            from idfkit_mcp.state import current_session_id

            session_id = current_session_id()
        entry = self._store.get(session_id, {}).get(name)
        if entry is None:
            available = sorted(self._store.get(session_id, {}).keys())
            raise KeyError(f"No upload named {name!r} in this session. Available: {available}")
        return base64.b64decode(entry["data"])
