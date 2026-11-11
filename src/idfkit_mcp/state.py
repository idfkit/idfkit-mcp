"""Server state management for the idfkit MCP server.

State is keyed per MCP session so that concurrent ``streamable-http``
connections each get their own model, simulation result, etc.  For
``stdio`` transport (single client) a fixed ``"stdio"`` session ID is
used, behaving identically to the previous singleton approach.
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import logging
import re
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.request import urlopen

from idfkit import LATEST_VERSION, IDFDocument, get_schema

if TYPE_CHECKING:
    from idfkit.migration import MigrationReport
    from idfkit.schema import EpJSONSchema
    from idfkit.simulation import ResultIndex
    from idfkit.simulation.result import SimulationResult
    from idfkit.weather.index import StationIndex

logger = logging.getLogger("idfkit_mcp")

DOCS_BASE_URL = "https://docs.idfkit.com"

NO_SIMULATION_RUN = "No simulation run in this session; run `run_simulation` first."
"""FR-019: results linked to objects exist only for runs this server started."""

ResultsState = Literal["fresh", "stale"]

# ---------------------------------------------------------------------------
# Per-session state registry
# ---------------------------------------------------------------------------

_current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_session_id", default="stdio")

_sessions: OrderedDict[str, ServerState] = OrderedDict()

_MAX_SESSIONS = 20
"""Maximum number of concurrent sessions before LRU eviction."""

MAX_CHANGE_LOG = 100
"""Maximum change-log entries retained per session."""

_SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
"""Allowed shape for MCP session IDs used as filesystem path components.

The ``mcp-session-id`` header is client-supplied. Without validation, a value
like ``../etc`` would escape the per-session scope on disk (cache dir, upload
scope, simulation run dir). Reject-and-fallback to ``"stdio"`` is safer than
sanitize-and-coerce: the attacker lands in a shared bucket they can see is
not theirs, instead of a quietly-redirected attacker-controlled path.
"""

_SAFE_IDENTITY_TOKEN = re.compile(r"[A-Za-z0-9_\-:/+=\.]{1,512}")
"""Permissive input validation for OAuth/ChatGPT identity tokens.

OpenAI's hosted MCP connector sends ``_meta["openai/session"]`` values that
look like ``v1/<base64>`` — they legitimately contain ``/`` and ``+``. Gateway
principal headers can likewise embed ``:`` as a separator. These values are
*always* hashed before use as filesystem path components (see
``_stable_session_id``), so this regex only screens out obvious garbage like
NULs or control bytes.
"""


def _cache_base_dir() -> Path:
    """Return the platform-appropriate idfkit cache base directory."""
    import os
    import sys

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "idfkit" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "idfkit"
    # Linux / other POSIX
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "idfkit"


def _session_cache_dir() -> Path:
    """Return the platform-appropriate directory for session state files."""
    return _cache_base_dir() / "sessions"


def session_uploads_dir(session_id: str) -> Path:
    """Return the per-session directory for uploaded files materialized to disk."""
    return _cache_base_dir() / "uploads" / session_id


def current_session_id() -> str:
    """Return the session ID bound to the current request scope."""
    return _current_session_id.get()


def _session_file_path(session_id: str | None = None) -> Path:
    """Return the session file path for a given session ID.

    For identity-bound sessions (``principal_…`` / ``openai_…``) the file is
    keyed by the identity itself, so the same user finds the same state across
    connector reconnects and transport-session rotations. For ``stdio`` (and
    any unrecognized session_id passed in), we fall back to hashing the current
    working directory — that preserves the original per-project isolation for
    the stdio single-client case.
    """
    import hashlib

    if session_id and (session_id.startswith("principal_") or session_id.startswith("openai_")):
        key = session_id
    else:
        key = str(Path.cwd().resolve())
    key_hash = hashlib.sha256(key.encode()).hexdigest()[:12]
    return _session_cache_dir() / f"{key_hash}.json"


def _docs_cache_dir() -> Path:
    """Return the platform-appropriate cache directory for documentation indexes."""
    return _cache_base_dir() / "docs"


def _download_search_index(version: str, cache_path: Path) -> dict[str, Any]:
    """Download the search index from docs.idfkit.com and cache it locally."""
    import json
    import logging

    logger = logging.getLogger(__name__)

    url = f"{DOCS_BASE_URL}/v{version}/search.json"
    logger.info("Downloading documentation index from %s", url)

    try:
        with urlopen(url, timeout=30) as resp:  # noqa: S310
            raw = resp.read()
    except Exception as e:
        msg = (
            f"Failed to download documentation index from {url}: {e}\n"
            "Set IDFKIT_DOCS_DIR to a local idfkit-docs dist/ directory for offline use."
        )
        raise FileNotFoundError(msg) from e

    data: dict[str, Any] = json.loads(raw)

    # Cache for next time
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(raw)
    logger.info("Cached documentation index to %s", cache_path)

    return data


SESSION_FILE_VERSION = 2
"""Version written by :meth:`ServerState.save_session`.

Version 2 added ``simulation_model_hash`` and ``simulation_run_dir`` as
first-class session fields (research R-15). Version-1 files still load, with
both fields ``None``.
"""

_READABLE_SESSION_VERSIONS = frozenset({1, SESSION_FILE_VERSION})


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    """Return ``data[key]`` when it is a non-empty string, else ``None``."""
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _read_session_file(session_id: str | None = None) -> dict[str, Any] | None:
    """Read and validate the session file, returning None on any failure."""
    import json
    import logging

    session_path = _session_file_path(session_id)
    if not session_path.exists():
        return None

    try:
        data: dict[str, Any] = json.loads(session_path.read_text())
    except (json.JSONDecodeError, OSError):
        logging.getLogger(__name__).warning("Corrupt session file, ignoring: %s", session_path)
        return None

    version = data.get("version")
    if version not in _READABLE_SESSION_VERSIONS:
        logging.getLogger(__name__).warning(
            "Session file has unsupported version %r (expected one of %s), ignoring: %s",
            version,
            sorted(_READABLE_SESSION_VERSIONS),
            session_path,
        )
        return None
    return data


@dataclasses.dataclass
class ServerState:
    """Holds the active document, schema, and simulation result for one session.

    Instances are created and managed by :func:`get_state`, which keys them
    by MCP session ID.  For ``stdio`` transport a fixed ``"stdio"`` key is
    used (single-client, equivalent to the old singleton).  For
    ``streamable-http`` each connection gets an isolated instance keyed by
    the ``Mcp-Session-Id`` header.

    Session state (file_path, simulation run dir and model hash, weather file) is persisted
    to a JSON file on disk so that clients that restart the server between
    turns (e.g. Codex) can transparently resume where they left off.
    Persistence is disabled for HTTP sessions since they receive a new
    session ID on every connection.
    """

    document: IDFDocument[Literal[True]] | None = None
    schema: EpJSONSchema | None = None
    file_path: Path | None = None
    simulation_result: SimulationResult | None = None
    migration_report: MigrationReport | None = None
    weather_file: Path | None = None
    simulation_model_hash: str | None = None
    """SHA-256 of the IDF text written for the session's last run."""
    simulation_run_dir: str | None = None
    """Run directory of the session's last simulation, so linking can resume after a restart."""
    simulation_run_revision: int | None = None
    """``doc.revision`` of the document the session's last run simulated.

    Not persisted: a revision counts the edits of one in-memory document, so a document
    restored after a restart has its own count, and an equal number would mean nothing.
    A restored session has ``None`` here and earns freshness only through the model hash.
    """
    station_index: StationIndex | None = None
    docs_index: list[dict[str, object]] | None = None
    docs_version: str | None = None
    docs_separator: str | None = None

    # The document the last run simulated, the model hash per (document, revision) already
    # computed, and the session's result index with the run identity it was built for.
    _run_document: IDFDocument[Literal[True]] | None = dataclasses.field(default=None, repr=False)
    _hash_seen: tuple[int, int, str] | None = dataclasses.field(default=None, repr=False)
    _result_index: tuple[tuple[object, ...], ResultIndex] | None = dataclasses.field(default=None, repr=False)

    # Session persistence control (disabled for HTTP sessions)
    persistence_enabled: bool = True
    _session_restored: bool = dataclasses.field(default=False, repr=False)

    # Informational — set when the session is created via get_state()
    session_id: str = dataclasses.field(default="stdio", repr=False)

    # In-memory mutation log (not persisted; reset on clear_session)
    change_log: list[dict[str, str]] = dataclasses.field(default_factory=lambda: [])

    # Per-session locks to prevent concurrent long-running operations.
    # The EnergyPlus transition binaries share a working directory and cannot
    # run in parallel; concurrent simulations race on state.simulation_result.
    migration_lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock, repr=False)
    simulation_lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock, repr=False)

    def require_model(self) -> IDFDocument[Literal[True]]:
        """Return the active document, auto-restoring from session if needed."""
        if self.document is None:
            self._try_restore_session()
        if self.document is None:
            msg = "No model loaded. Use load_model or new_model first."
            raise RuntimeError(msg)
        return self.document

    def require_schema(self) -> EpJSONSchema:
        """Return the active schema, auto-restoring from session if needed."""
        if self.schema is None:
            self._try_restore_session()
        if self.schema is None:
            msg = "No schema loaded. Use load_model or new_model first."
            raise RuntimeError(msg)
        return self.schema

    def get_or_load_schema(self, version: tuple[int, int, int] | None = None) -> EpJSONSchema:
        """Return the active schema, or load one for the given version."""
        if version is not None:
            return get_schema(version)
        if self.schema is not None:
            return self.schema
        return get_schema(LATEST_VERSION)

    def get_or_load_station_index(self) -> StationIndex:
        """Return the cached station index, loading it on first use."""
        if self.station_index is None:
            from idfkit.weather import StationIndex

            self.station_index = StationIndex.load()
        return self.station_index

    def get_or_load_docs_index(self, version: str | None = None) -> tuple[list[dict[str, object]], str, str]:
        """Return cached docs index, loading on first use or version change.

        Resolution order:
        1. ``IDFKIT_DOCS_DIR`` env var (local dist/ directory)
        2. Local cache (``~/.cache/idfkit/docs/``)
        3. Download from ``docs.idfkit.com`` and cache locally

        Returns:
            Tuple of (items list, separator regex string, resolved version string).

        Raises:
            FileNotFoundError: If the index cannot be loaded from any source.
        """
        resolved_version = version or self._resolve_latest_docs_version()

        if self.docs_index is not None and self.docs_separator is not None and self.docs_version == resolved_version:
            return self.docs_index, self.docs_separator, resolved_version

        data = self._load_search_index(resolved_version)

        items: list[dict[str, object]] = data["items"]
        separator: str = data["config"]["separator"]
        self.docs_index = items
        self.docs_separator = separator
        self.docs_version = resolved_version
        return items, separator, resolved_version

    def _load_search_index(self, version: str) -> dict[str, Any]:
        """Load the search index from local dir, cache, or remote.

        Tries sources in order:
        1. ``IDFKIT_DOCS_DIR`` env var → ``{dir}/v{version}/search.json``
        2. Local cache → ``{cache_dir}/v{version}/search.json`` (max 7 days)
        3. Download from ``https://docs.idfkit.com/v{version}/search.json``
        """
        import json
        import os
        import time

        cache_max_age = 7 * 24 * 3600  # 7 days

        # 1. Explicit env var (development / Docker)
        env_dir = os.environ.get("IDFKIT_DOCS_DIR")
        if env_dir:
            local_path = Path(env_dir) / f"v{version}" / "search.json"
            if local_path.exists():
                with open(local_path) as f:
                    return json.load(f)  # type: ignore[no-any-return]

        # 2. Local cache (within TTL)
        cache_path = _docs_cache_dir() / f"v{version}" / "search.json"
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < cache_max_age:
                with open(cache_path) as f:
                    return json.load(f)  # type: ignore[no-any-return]

        # 3. Download from docs.idfkit.com (also refreshes stale cache)
        return _download_search_index(version, cache_path)

    def _resolve_latest_docs_version(self) -> str:
        """Determine the latest documented version.

        Uses the idfkit-bundled LATEST_VERSION constant as the default,
        which matches the latest version on docs.idfkit.com.
        """
        return f"{LATEST_VERSION[0]}.{LATEST_VERSION[1]}"

    def record_change(self, tool_name: str, summary: str | None = None) -> None:
        """Append a mutation entry to the in-memory change log, capped at MAX_CHANGE_LOG."""
        from datetime import datetime, timezone

        entry: dict[str, str] = {
            "tool": tool_name,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if summary is not None:
            entry["summary"] = summary
        self.change_log.append(entry)
        if len(self.change_log) > MAX_CHANGE_LOG:
            self.change_log = self.change_log[-MAX_CHANGE_LOG:]

    def require_simulation_result(self) -> SimulationResult:
        """Return the simulation result, auto-restoring from session if needed."""
        if self.simulation_result is None:
            self._try_restore_session()
        if self.simulation_result is None:
            msg = "No simulation results available. Use run_simulation first."
            raise RuntimeError(msg)
        return self.simulation_result

    # ------------------------------------------------------------------
    # Simulation run identity and the linked results (FR-019, FR-026)
    # ------------------------------------------------------------------

    def record_simulation(
        self, doc: IDFDocument[Literal[True]], result: SimulationResult, *, run_revision: int, model_hash: str
    ) -> None:
        """Record a run this server started: its result, the revision and model hash it simulated, its directory.

        Args:
            doc: The session document that was simulated.
            result: The run.
            run_revision: ``doc.revision`` when the model text was written for EnergyPlus.
            model_hash: SHA-256 of that model text (:func:`idfkit_mcp.tools.simulation.model_text_hash`).
        """
        self.simulation_result = result
        self.simulation_run_revision = run_revision
        self.simulation_model_hash = model_hash
        self.simulation_run_dir = str(result.run_dir.resolve())
        self._run_document = doc
        self._hash_seen = (id(doc), run_revision, model_hash)
        self._result_index = None

    def forget_simulation(self) -> None:
        """Drop the last run: a new model was loaded or created, so the run says nothing about it."""
        self.simulation_result = None
        self.simulation_run_revision = None
        self.simulation_model_hash = None
        self.simulation_run_dir = None
        self._run_document = None
        self._hash_seen = None
        self._result_index = None

    def _current_hash(self, doc: IDFDocument[Literal[True]]) -> str:
        """The model hash of *doc* as it is now, computed at most once per document revision."""
        seen = self._hash_seen
        if seen is not None and seen[0] == id(doc) and seen[1] == doc.revision:
            return seen[2]
        from idfkit_mcp.tools.simulation import model_text_hash

        digest = model_text_hash(doc)
        self._hash_seen = (id(doc), doc.revision, digest)
        return digest

    def _adopt_document(self, doc: IDFDocument[Literal[True]]) -> None:
        """Decide whether *doc*, which is not the document the run simulated, is still that model.

        This happens after a restart (the document was restored from its file) or after
        ``migrate_model`` replaced the document. Only the model hash can tell: when the run's
        hash is recorded and equals the hash of *doc* now, *doc* is the simulated model and its
        current revision becomes the run revision. Otherwise the run revision stays as it was,
        or ``None`` for a restored session, and the results are reported stale. Stale is the
        safe answer when nothing proves the model unchanged.
        """
        self._run_document = doc
        recorded = self.simulation_model_hash
        if recorded is not None and self._current_hash(doc) == recorded:
            self.simulation_run_revision = doc.revision
        elif self.simulation_run_revision is not None and self.simulation_run_revision == doc.revision:
            # Another document can carry the same revision number; it must not read as fresh.
            self.simulation_run_revision = None

    def require_results(self) -> tuple[ResultIndex, ResultsState]:
        """Return the session's :class:`~idfkit.simulation.ResultIndex` and whether it is fresh.

        The index is built lazily with :meth:`ResultIndex.build` on the first ask after a run
        and kept for that run. ``"stale"`` means the model changed since the run (FR-026).

        Raises:
            ToolError: When this session has no simulation run (FR-019), or the run has no SQLite output.
            RuntimeError: When no model is loaded.
        """
        from fastmcp.exceptions import ToolError

        if self.simulation_result is None:
            self._try_restore_session()
        result = self.simulation_result
        if result is None or self.simulation_run_dir is None:
            raise ToolError(NO_SIMULATION_RUN)
        doc = self.require_model()
        if self._run_document is not doc:
            self._adopt_document(doc)
        # A restored session with no recorded run revision builds with -1, which no document
        # revision equals, so its results always read stale (see _adopt_document).
        run_revision = self.simulation_run_revision if self.simulation_run_revision is not None else -1
        model_hash = self.simulation_model_hash or ""
        index = self._build_index(doc, result, run_revision, model_hash)
        # Hash only when the revision matches: a different revision is stale whatever the text.
        current_hash = self._current_hash(doc) if doc.revision == index.run_revision and model_hash else None
        fresh = index.is_fresh(doc, current_hash) and bool(model_hash)
        return index, "fresh" if fresh else "stale"

    def _build_index(
        self, doc: IDFDocument[Literal[True]], result: SimulationResult, run_revision: int, model_hash: str
    ) -> ResultIndex:
        from fastmcp.exceptions import ToolError
        from idfkit.simulation import ResultIndex
        from idfkit.simulation.result import SimulationResult as SimResult

        stamp: tuple[object, ...] = (id(doc), str(result.run_dir), run_revision, model_hash)
        held = self._result_index
        if held is not None and held[0] == stamp:
            return held[1]
        # Build from a private result handle: the session result's cached SQLite connection may
        # belong to another worker thread, and this one is closed once the index holds what it read.
        private = SimResult.from_directory(result.run_dir, output_prefix=result.output_prefix)
        sql = private.sql
        if sql is None:
            msg = (
                f"The last run in {result.run_dir} has no SQLite output, so its results cannot be linked to "
                "objects. Run run_simulation again; it adds Output:SQLite."
            )
            raise ToolError(msg)
        try:
            index = ResultIndex.build(doc, private, run_revision=run_revision, run_model_hash=model_hash)
        finally:
            sql.close()
        self._result_index = (stamp, index)
        return index

    def try_results(self) -> tuple[ResultIndex, ResultsState] | None:
        """Like :meth:`require_results`, but ``None`` when results cannot be linked, for additive fields."""
        try:
            return self.require_results()
        except Exception:
            logger.debug("Result linking unavailable", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def save_session(self) -> None:
        """Persist restorable state paths to the session file."""
        if not self.persistence_enabled:
            return

        import json
        from datetime import datetime, timezone

        self._sync_simulation_run_dir()
        data: dict[str, Any] = {
            "version": SESSION_FILE_VERSION,
            "cwd": str(Path.cwd().resolve()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "simulation_model_hash": self.simulation_model_hash,
            "simulation_run_dir": self.simulation_run_dir,
        }
        if self.file_path is not None and self.file_path.exists():
            data["file_path"] = str(self.file_path.resolve())
        if self.weather_file is not None and self.weather_file.exists():
            data["weather_file"] = str(self.weather_file.resolve())

        import logging

        session_path = _session_file_path(self.session_id)
        try:
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(json.dumps(data, indent=2))
        except OSError:
            logging.getLogger(__name__).warning("Failed to write session file: %s", session_path, exc_info=True)

    def _sync_simulation_run_dir(self) -> None:
        """Align ``simulation_run_dir`` with the in-memory simulation result.

        The result's directory wins when it exists. When it differs from the
        recorded directory, the recorded model hash belonged to another run and
        is dropped rather than attributed to this one.
        """
        result = self.simulation_result
        if result is None or not result.run_dir.is_dir():
            return
        run_dir = str(result.run_dir.resolve())
        recorded = self.simulation_run_dir
        if recorded is not None and str(Path(recorded).resolve()) == run_dir:
            self.simulation_run_dir = run_dir
            return
        self.simulation_run_dir = run_dir
        self.simulation_model_hash = None

    def _try_restore_session(self) -> None:
        """Attempt to restore state from the session file (called once lazily)."""
        if self._session_restored or not self.persistence_enabled:
            return
        self._session_restored = True

        data = _read_session_file(self.session_id)
        if data is None:
            return

        self._restore_model(data)
        self._restore_simulation(data)
        self._restore_weather(data)

    def _restore_model(self, data: dict[str, Any]) -> None:
        """Restore model from a session data dict."""
        import logging

        file_path_str = data.get("file_path")
        if file_path_str is None or self.document is not None:
            return
        fp = Path(file_path_str)
        if not fp.exists():
            return
        try:
            from idfkit import load_epjson, load_idf

            doc = (
                load_epjson(str(fp), strict=True)
                if fp.suffix.lower() in (".epjson", ".json")
                else load_idf(str(fp), strict=True)
            )
            self.document = doc
            self.schema = doc.schema
            self.file_path = fp
            logging.getLogger(__name__).info("Restored model from session: %s", fp)
        except Exception:
            logging.getLogger(__name__).warning("Failed to restore model from %s", fp, exc_info=True)

    def _restore_simulation(self, data: dict[str, Any]) -> None:
        """Restore simulation result from a session data dict."""
        import logging

        run_dir_str = _optional_str(data, "simulation_run_dir")
        if run_dir_str is None or self.simulation_result is not None:
            return
        rd = Path(run_dir_str)
        if not rd.is_dir():
            logging.getLogger(__name__).warning("Session simulation run directory no longer exists: %s", rd)
            return
        try:
            from idfkit.simulation.result import SimulationResult as SimResult

            self.simulation_result = SimResult.from_directory(rd)
            logging.getLogger(__name__).info("Restored simulation result from session: %s", rd)
        except Exception:
            logging.getLogger(__name__).warning("Failed to restore simulation result from %s", rd, exc_info=True)
            return
        # Version 1 recorded the run directory only as a restore hint: it says
        # nothing about which model text produced the run, so the run identity
        # stays unrecorded (both fields None) until the next run.
        if data.get("version") == SESSION_FILE_VERSION:
            self.simulation_run_dir = run_dir_str
            self.simulation_model_hash = _optional_str(data, "simulation_model_hash")

    def _restore_weather(self, data: dict[str, Any]) -> None:
        """Restore weather file path from a session data dict."""
        import logging

        weather_str = data.get("weather_file")
        if weather_str is None or self.weather_file is not None:
            return
        wp = Path(weather_str)
        if wp.exists():
            self.weather_file = wp
            logging.getLogger(__name__).info("Restored weather file from session: %s", wp)

    def clear_session(self) -> None:
        """Delete the session file and reset model/simulation state.

        Uploads are preserved so the user can re-load without re-uploading.
        """
        if self.persistence_enabled:
            session_path = _session_file_path(self.session_id)
            if session_path.exists():
                session_path.unlink()
        self.document = None
        self.schema = None
        self.file_path = None
        self.simulation_result = None
        self.migration_report = None
        self.weather_file = None
        self.forget_simulation()
        self.change_log.clear()
        self._session_restored = False


def _hash_identity(value: str) -> str:
    """Return a short, filesystem-safe hash of an identity token."""
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _request_header(ctx: Any, name: str) -> str | None:
    """Return an HTTP request header value from a FastMCP context, if any."""
    try:
        request = ctx.request_context.request
    except Exception:
        return None
    if request is None or not hasattr(request, "headers"):
        return None
    value = request.headers.get(name)
    return value if isinstance(value, str) else None


def _extract_openai_session(message: Any) -> str | None:
    """Return ``_meta["openai/session"]`` from a tool/resource request, if any.

    OpenAI's hosted MCP connector rotates the transport-level ``mcp-session-id``
    per tool call but sends a stable ``openai/session`` in the JSON-RPC params'
    ``_meta``. See openai/openai-apps-sdk-examples#165.
    """
    if message is None:
        return None
    meta = getattr(message, "meta", None)
    if meta is None:
        return None
    # Pydantic stores unknown ``_meta`` fields (which include ``/`` in the
    # key) in ``model_extra`` because ``extra="allow"`` is set on the type.
    extra_raw = getattr(meta, "model_extra", None)
    if not isinstance(extra_raw, dict):
        return None
    from typing import cast

    extra = cast("dict[str, Any]", extra_raw)
    value = extra.get("openai/session")
    return value if isinstance(value, str) and value else None


def _extract_session_id(ctx: Any, message: Any = None) -> str:
    """Resolve a stable session identifier from the current request.

    Priority (first match wins):

    1. ``X-Idfkit-Principal`` request header — a trusted, gateway-injected
       authenticated principal (e.g. ``tenant_id:actor_identity``). Stable
       across client reconnects and transport-session rotation.
    2. ``_meta["openai/session"]`` on the tool-call params — sent by ChatGPT's
       hosted MCP connector (see openai-apps-sdk-examples#165). Stable within
       a conversation even when ``mcp-session-id`` rotates per call.
    3. ``Mcp-Session-Id`` request header — the MCP transport-level session.
       Works for well-behaved clients (Claude Desktop, Cursor, stdio tests).
    4. ``"stdio"`` fallback.

    Identity tokens from (1) and (2) are hashed before being returned, so the
    session ID is always safe to use as a filesystem path component.
    """
    # 1. Gateway-injected authenticated principal (trusted)
    principal = _request_header(ctx, "x-idfkit-principal")
    if principal:
        if _SAFE_IDENTITY_TOKEN.fullmatch(principal):
            return f"principal_{_hash_identity(principal)}"
        logger.warning("Rejecting malformed x-idfkit-principal (%d chars)", len(principal))

    # 2. OpenAI connector's openai/session in the tool-call _meta
    openai_session = _extract_openai_session(message)
    if openai_session:
        if _SAFE_IDENTITY_TOKEN.fullmatch(openai_session):
            return f"openai_{_hash_identity(openai_session)}"
        logger.warning("Rejecting malformed openai/session (%d chars)", len(openai_session))

    # 3. Transport-level MCP session ID
    sid = _request_header(ctx, "mcp-session-id")
    if sid:
        if _SAFE_SESSION_ID.fullmatch(sid):
            return sid
        logger.warning("Rejecting malformed mcp-session-id (%d chars)", len(sid))

    return "stdio"


@contextmanager
def session_scope_from_context(ctx: Any, message: Any = None) -> Iterator[str]:
    """Temporarily bind the current session ID from a FastMCP context.

    ``message`` is the JSON-RPC params object (e.g. ``CallToolRequestParams``)
    and is used to pick up identity hints from ``_meta`` when the transport
    session is unreliable.
    """
    session_id = _extract_session_id(ctx, message) if ctx is not None else "local"
    token = _current_session_id.set(session_id)
    try:
        yield session_id
    finally:
        _current_session_id.reset(token)


def get_state() -> ServerState:
    """Return the ``ServerState`` for the current MCP session.

    Creates a new state on first access for a given session ID and evicts
    the least-recently-used session when the registry is full.
    """
    session_id = _current_session_id.get()

    if session_id in _sessions:
        _sessions.move_to_end(session_id)
        return _sessions[session_id]

    # Evict oldest sessions when at capacity
    while len(_sessions) >= _MAX_SESSIONS:
        evicted_id, _ = _sessions.popitem(last=False)
        logger.info("Evicted session %s (capacity %d)", evicted_id, _MAX_SESSIONS)

    state = ServerState(session_id=session_id)
    # Persistence requires an identifier that is stable across process restarts.
    # ``stdio`` (keyed by cwd) and identity-bound sessions (``principal_…`` /
    # ``openai_…``) qualify. Raw transport ``mcp-session-id`` does not — it
    # rotates on reconnect (and, for OpenAI's connector, per tool call).
    state.persistence_enabled = session_id == "stdio" or session_id.startswith(("principal_", "openai_"))
    _sessions[session_id] = state
    logger.debug("Created session %s", session_id)
    return state


def reset_sessions() -> None:
    """Clear all sessions and reset to the default ``"stdio"`` session.

    Intended for test fixtures only.
    """
    _sessions.clear()
    _current_session_id.set("stdio")
