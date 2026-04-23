"""Tests for session isolation, LRU eviction, and concurrent reads."""

from __future__ import annotations

import asyncio
import types

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from idfkit import new_document

from idfkit_mcp.models import ListObjectsResult, SearchObjectsResult
from idfkit_mcp.state import (
    _MAX_SESSIONS,  # pyright: ignore[reportPrivateUsage]
    _current_session_id,  # pyright: ignore[reportPrivateUsage]
    _extract_session_id,  # pyright: ignore[reportPrivateUsage]
    _sessions,  # pyright: ignore[reportPrivateUsage]
    get_state,
    session_scope_from_context,
)
from tests.conftest import call_tool


class TestSessionIsolation:
    """Two sessions load different models without interference."""

    def test_different_sessions_get_different_state(self) -> None:
        token_a = _current_session_id.set("session-a")  # pyright: ignore[reportPrivateUsage]
        state_a = get_state()
        doc_a = new_document()
        doc_a.add("Zone", "ZoneA")
        state_a.document = doc_a
        state_a.schema = doc_a.schema
        _current_session_id.reset(token_a)  # pyright: ignore[reportPrivateUsage]

        token_b = _current_session_id.set("session-b")  # pyright: ignore[reportPrivateUsage]
        state_b = get_state()
        doc_b = new_document()
        doc_b.add("Zone", "ZoneB")
        state_b.document = doc_b
        state_b.schema = doc_b.schema
        _current_session_id.reset(token_b)  # pyright: ignore[reportPrivateUsage]

        # Verify isolation
        assert state_a is not state_b
        assert [o.name for o in state_a.document.get_collection("Zone")] == ["ZoneA"]
        assert [o.name for o in state_b.document.get_collection("Zone")] == ["ZoneB"]

    def test_session_scope_context_manager(self) -> None:
        with session_scope_from_context(None) as sid:
            assert sid == "local"
            state = get_state()
            state.document = new_document()

        # Outside the scope, default session ID is restored
        default_state = get_state()
        assert default_state is not state


class TestSessionEviction:
    """LRU eviction when the session registry is at capacity."""

    def test_oldest_session_evicted(self) -> None:
        # Create _MAX_SESSIONS sessions
        for i in range(_MAX_SESSIONS):  # pyright: ignore[reportPrivateUsage]
            token = _current_session_id.set(f"s-{i}")  # pyright: ignore[reportPrivateUsage]
            get_state()
            _current_session_id.reset(token)  # pyright: ignore[reportPrivateUsage]

        assert len(_sessions) == _MAX_SESSIONS  # pyright: ignore[reportPrivateUsage]
        assert "s-0" in _sessions  # pyright: ignore[reportPrivateUsage]

        # Creating one more evicts the oldest (s-0)
        token = _current_session_id.set("s-overflow")  # pyright: ignore[reportPrivateUsage]
        get_state()
        _current_session_id.reset(token)  # pyright: ignore[reportPrivateUsage]

        assert "s-0" not in _sessions  # pyright: ignore[reportPrivateUsage]
        assert "s-overflow" in _sessions  # pyright: ignore[reportPrivateUsage]
        assert len(_sessions) == _MAX_SESSIONS  # pyright: ignore[reportPrivateUsage]

    def test_accessed_session_not_evicted(self) -> None:
        # Create _MAX_SESSIONS sessions
        for i in range(_MAX_SESSIONS):  # pyright: ignore[reportPrivateUsage]
            token = _current_session_id.set(f"s-{i}")  # pyright: ignore[reportPrivateUsage]
            get_state()
            _current_session_id.reset(token)  # pyright: ignore[reportPrivateUsage]

        # Access s-0 to move it to the end of the LRU
        token = _current_session_id.set("s-0")  # pyright: ignore[reportPrivateUsage]
        get_state()
        _current_session_id.reset(token)  # pyright: ignore[reportPrivateUsage]

        # Add a new session — s-1 should be evicted (now oldest), not s-0
        token = _current_session_id.set("s-new")  # pyright: ignore[reportPrivateUsage]
        get_state()
        _current_session_id.reset(token)  # pyright: ignore[reportPrivateUsage]

        assert "s-0" in _sessions  # pyright: ignore[reportPrivateUsage]
        assert "s-1" not in _sessions  # pyright: ignore[reportPrivateUsage]


class TestSessionIdSanitization:
    """The ``mcp-session-id`` header is client-supplied and lands in filesystem paths.

    Malformed values must fall back to ``"stdio"`` so an attacker can't steer
    uploads, cache, or simulation output outside the per-session scope.
    """

    @staticmethod
    def _ctx_with_sid(sid: str) -> object:
        return types.SimpleNamespace(
            request_context=types.SimpleNamespace(request=types.SimpleNamespace(headers={"mcp-session-id": sid}))
        )

    def test_accepts_uuid_like_sid(self) -> None:
        sid = "7f8e9d6c-4b3a-2109-8765-fedcba987654"
        assert _extract_session_id(self._ctx_with_sid(sid)) == sid

    def test_rejects_path_traversal(self) -> None:
        for bad in ("../escape", "..", "../../etc", "a/b", "a\\b", "sess\x00id", "/absolute", ""):
            assert _extract_session_id(self._ctx_with_sid(bad)) == "stdio", f"should reject {bad!r}"

    def test_rejects_overlong_sid(self) -> None:
        assert _extract_session_id(self._ctx_with_sid("a" * 129)) == "stdio"


class TestLayeredSessionResolution:
    """Identity sources resolve in priority order, regardless of ``mcp-session-id`` rotation.

    OpenAI's hosted MCP connector rotates ``mcp-session-id`` per tool call but
    sends a stable ``_meta["openai/session"]`` (openai-apps-sdk-examples#165).
    The gateway can forward an authenticated principal via ``x-idfkit-principal``
    that is even more stable. Both must produce session IDs that are (a) the
    same across calls from the same principal/conversation, and (b)
    filesystem-safe (hashed).
    """

    @staticmethod
    def _ctx(headers: dict[str, str] | None = None) -> object:
        return types.SimpleNamespace(
            request_context=types.SimpleNamespace(request=types.SimpleNamespace(headers=headers or {}))
        )

    @staticmethod
    def _message_with_openai_session(value: str | None) -> object:
        """Mimic a Pydantic ``CallToolRequestParams`` with ``_meta.openai/session``."""
        model_extra = {"openai/session": value} if value is not None else {}
        meta = types.SimpleNamespace(model_extra=model_extra)
        return types.SimpleNamespace(meta=meta, name="t", arguments={})

    def test_openai_session_survives_rotated_mcp_session_id(self) -> None:
        """ChatGPT's per-call transport rotation still produces a stable bucket."""
        stable_openai_sid = "v1/3hcF2IvUSD41ujMbfMGV5j4jJHQVKAEBSuy160vtVkteI6jPlxbLjBZTfzgEM7UusowFL1LJxmRu"
        msg = self._message_with_openai_session(stable_openai_sid)

        first = _extract_session_id(self._ctx({"mcp-session-id": "rotated-1"}), msg)
        second = _extract_session_id(self._ctx({"mcp-session-id": "rotated-2"}), msg)

        assert first == second
        assert first.startswith("openai_")
        # Different openai/session values must resolve to different buckets.
        other = _extract_session_id(self._ctx({}), self._message_with_openai_session("v1/different"))
        assert other != first

    def test_principal_header_takes_precedence_over_openai_session(self) -> None:
        """Gateway-injected auth identity wins over connector-supplied session."""
        ctx = self._ctx({
            "x-idfkit-principal": "t_abc123:oauth:oi_xyz",
            "mcp-session-id": "whatever",
        })
        msg = self._message_with_openai_session("v1/should-be-ignored")

        sid = _extract_session_id(ctx, msg)
        assert sid.startswith("principal_")

    def test_mcp_session_id_used_when_nothing_else_present(self) -> None:
        """Well-behaved clients (Claude Desktop, stdio) keep working unchanged."""
        ctx = self._ctx({"mcp-session-id": "stable-session-from-claude"})
        assert _extract_session_id(ctx, None) == "stable-session-from-claude"

    def test_falls_back_to_stdio_when_no_identity_available(self) -> None:
        assert _extract_session_id(self._ctx({}), None) == "stdio"

    def test_rejects_malformed_openai_session(self) -> None:
        """Control bytes and NULs must be rejected."""
        msg = self._message_with_openai_session("bad\x00session")
        assert _extract_session_id(self._ctx({}), msg) == "stdio"

    def test_session_id_is_filesystem_safe(self) -> None:
        """Hashed identity tokens contain only path-safe characters."""
        msg = self._message_with_openai_session("v1/has/slashes+and=equals")
        sid = _extract_session_id(self._ctx({}), msg)
        # No path-traversal, no separators
        assert "/" not in sid
        assert "\\" not in sid
        assert ".." not in sid


@pytest.mark.asyncio
class TestConcurrentReads:
    """Concurrent read-only tools on the same session don't interfere."""

    async def test_parallel_list_and_search(self, client: Client[FastMCPTransport]) -> None:
        state = get_state()
        doc = new_document()
        doc.add("Zone", "Office")
        doc.add("Zone", "Corridor")
        state.document = doc
        state.schema = doc.schema

        list_coro = call_tool(client, "list_objects", {"object_type": "Zone"}, ListObjectsResult)
        search_coro = call_tool(client, "search_objects", {"query": "Office"}, SearchObjectsResult)
        list_result, search_result = await asyncio.gather(list_coro, search_coro)

        assert isinstance(list_result, ListObjectsResult)
        assert isinstance(search_result, SearchObjectsResult)
        assert list_result.total >= 2
        assert any("Office" in m.name for m in search_result.matches)
