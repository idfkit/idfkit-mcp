"""Tests for session isolation, LRU eviction, and concurrent reads."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from idfkit import new_document

from idfkit_mcp.models import ListObjectsResult, SearchObjectsResult
from idfkit_mcp.state import (
    _MAX_SESSIONS,  # pyright: ignore[reportPrivateUsage]
    _current_session_id,  # pyright: ignore[reportPrivateUsage]
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
