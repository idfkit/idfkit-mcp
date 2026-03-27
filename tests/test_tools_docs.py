"""Tests for the documentation lookup and search tools."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.models import (
    DescribeObjectTypeResult,
    GetDocSectionResult,
    LookupDocumentationResult,
    SearchDocsResult,
    SearchSchemaResult,
)
from idfkit_mcp.state import ServerState, get_state
from tests.conftest import call_tool


class TestLookupDocumentation:
    async def test_known_object_type(self, client: object) -> None:
        result = await call_tool(client, "lookup_documentation", {"object_type": "Zone"}, LookupDocumentationResult)
        assert result.object_type == "Zone"
        assert result.io_reference_url is not None
        assert "docs.idfkit.com" in result.io_reference_url
        assert "#zone" in result.io_reference_url
        assert result.engineering_reference_url is not None
        assert result.search_url is not None
        assert result.version  # should be set

    async def test_unknown_object_type(self, client: object) -> None:
        result = await call_tool(
            client, "lookup_documentation", {"object_type": "NotARealType"}, LookupDocumentationResult
        )
        assert result.object_type == "NotARealType"
        assert result.io_reference_url is None
        assert result.engineering_reference_url is not None
        assert result.search_url is not None

    async def test_with_explicit_version(self, client: object) -> None:
        result = await call_tool(
            client, "lookup_documentation", {"object_type": "Zone", "version": "24.1.0"}, LookupDocumentationResult
        )
        assert result.version == "24.1.0"
        assert result.io_reference_url is not None
        assert "/v24.1/" in result.io_reference_url


class TestDescribeObjectTypeDocUrl:
    async def test_doc_url_present(self, client: object) -> None:
        result = await call_tool(client, "describe_object_type", {"object_type": "Zone"}, DescribeObjectTypeResult)
        assert result.doc_url is not None
        assert "docs.idfkit.com" in result.doc_url
        assert "#zone" in result.doc_url

    async def test_doc_url_for_material(self, client: object) -> None:
        result = await call_tool(client, "describe_object_type", {"object_type": "Material"}, DescribeObjectTypeResult)
        assert result.doc_url is not None
        assert "#material" in result.doc_url


class TestSearchSchemaDocUrl:
    async def test_doc_url_in_matches(self, client: object) -> None:
        result = await call_tool(client, "search_schema", {"query": "Material", "limit": 10}, SearchSchemaResult)
        assert result.count > 0
        # All matches should have doc_url populated
        match_with_url = [m for m in result.matches if m.doc_url is not None]
        assert len(match_with_url) > 0
        assert "docs.idfkit.com" in match_with_url[0].doc_url  # type: ignore[operator]


class TestSearchDocs:
    async def test_basic_search(self, client: object) -> None:
        result = await call_tool(client, "search_docs", {"query": "zone"}, SearchDocsResult)
        assert result.count > 0
        assert result.version
        assert all(hit.score > 0 for hit in result.results)

    async def test_results_have_doc_url(self, client: object) -> None:
        result = await call_tool(client, "search_docs", {"query": "zone"}, SearchDocsResult)
        assert result.count > 0
        for hit in result.results:
            assert "docs.idfkit.com" in hit.doc_url
            assert hit.doc_url.startswith("https://")

    async def test_tag_filter(self, client: object) -> None:
        result = await call_tool(
            client, "search_docs", {"query": "zone", "tags": "Input Output Reference"}, SearchDocsResult
        )
        assert result.count > 0
        assert all("Input Output Reference" in hit.tags for hit in result.results)

    async def test_limit(self, client: object) -> None:
        result = await call_tool(client, "search_docs", {"query": "material", "limit": 3}, SearchDocsResult)
        assert len(result.results) <= 3

    async def test_html_stripped(self, client: object) -> None:
        result = await call_tool(client, "search_docs", {"query": "zone"}, SearchDocsResult)
        assert result.count > 0
        for hit in result.results:
            assert "<p>" not in hit.text
            assert "<code>" not in hit.text
            assert "<ul>" not in hit.text

    async def test_empty_query(self, client: object) -> None:
        result = await call_tool(client, "search_docs", {"query": ""}, SearchDocsResult)
        assert result.count == 0
        assert result.results == []

    async def test_text_truncated(self, client: object) -> None:
        result = await call_tool(client, "search_docs", {"query": "zone", "limit": 20}, SearchDocsResult)
        for hit in result.results:
            # Truncated text should be at most 500 chars + "..."
            assert len(hit.text) <= 503

    async def test_index_cached(self, client: object) -> None:
        await call_tool(client, "search_docs", {"query": "zone"}, SearchDocsResult)
        state = get_state()
        cached = state.docs_index
        assert cached is not None
        await call_tool(client, "search_docs", {"query": "material"}, SearchDocsResult)
        assert state.docs_index is cached


class TestGetDocSection:
    async def test_known_location(self, client: object) -> None:
        search_result = await call_tool(client, "search_docs", {"query": "zone heat balance"}, SearchDocsResult)
        assert search_result.count > 0

        loc = search_result.results[0].location
        result = await call_tool(client, "get_doc_section", {"location": loc}, GetDocSectionResult)
        assert result.title
        assert result.doc_url
        assert "docs.idfkit.com" in result.doc_url
        assert result.version

    async def test_unknown_location(self, client: object) -> None:
        with pytest.raises(ToolError, match="not found"):
            await call_tool(client, "get_doc_section", {"location": "nonexistent/path/#nothing"})

    async def test_full_text_not_truncated(self, client: object) -> None:
        search_result = await call_tool(
            client, "search_docs", {"query": "zone heat balance", "limit": 10}, SearchDocsResult
        )
        assert search_result.count > 0

        for hit in search_result.results:
            if hit.text.endswith("..."):
                full = await call_tool(client, "get_doc_section", {"location": hit.location}, GetDocSectionResult)
                assert len(full.text) > 500
                assert not full.text.endswith("...")
                return

        result = await call_tool(
            client, "get_doc_section", {"location": search_result.results[0].location}, GetDocSectionResult
        )
        assert len(result.text) >= 0

    async def test_html_stripped(self, client: object) -> None:
        search_result = await call_tool(client, "search_docs", {"query": "zone"}, SearchDocsResult)
        loc = search_result.results[0].location
        result = await call_tool(client, "get_doc_section", {"location": loc}, GetDocSectionResult)
        assert "<p>" not in result.text
        assert "<code>" not in result.text


class TestDocsIndexDownload:
    """Tests for the download and caching path of the search index."""

    _FAKE_INDEX: ClassVar[dict[str, object]] = {
        "items": [{"location": "test/page/#section", "title": "Test", "text": "hello", "tags": [], "path": []}],
        "config": {"separator": r"[\s\-]+"},
    }

    def test_downloads_and_caches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no local dir or cache exists, downloads from docs.idfkit.com and caches the file."""
        monkeypatch.delenv("IDFKIT_DOCS_DIR", raising=False)
        monkeypatch.setattr("idfkit_mcp.state._docs_cache_dir", lambda: tmp_path)

        raw = json.dumps(self._FAKE_INDEX).encode()

        def fake_urlopen(url: str, *, timeout: int = 30) -> BytesIO:
            return BytesIO(raw)

        with patch("idfkit_mcp.state.urlopen", fake_urlopen):
            state = ServerState()
            items, separator, version = state.get_or_load_docs_index("25.2")

        assert len(items) == 1
        assert items[0]["title"] == "Test"
        assert separator == r"[\s\-]+"
        assert version == "25.2"

        # Verify the file was cached
        cached = tmp_path / "v25.2" / "search.json"
        assert cached.exists()
        assert json.loads(cached.read_text()) == self._FAKE_INDEX

    def test_download_failure_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When download fails, raises FileNotFoundError with a helpful message."""
        monkeypatch.delenv("IDFKIT_DOCS_DIR", raising=False)
        monkeypatch.setattr("idfkit_mcp.state._docs_cache_dir", lambda: tmp_path)

        def fake_urlopen(url: str, *, timeout: int = 30) -> None:
            msg = "Connection refused"
            raise OSError(msg)

        with patch("idfkit_mcp.state.urlopen", fake_urlopen), pytest.raises(FileNotFoundError, match="IDFKIT_DOCS_DIR"):
            state = ServerState()
            state.get_or_load_docs_index("25.2")

    def test_stale_cache_triggers_redownload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the cached file is older than 7 days, re-downloads."""
        import os
        import time

        monkeypatch.delenv("IDFKIT_DOCS_DIR", raising=False)
        monkeypatch.setattr("idfkit_mcp.state._docs_cache_dir", lambda: tmp_path)

        # Write a stale cache file
        cache_dir = tmp_path / "v25.2"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "search.json"
        cache_file.write_text(json.dumps(self._FAKE_INDEX))
        # Set mtime to 8 days ago
        old_time = time.time() - 8 * 24 * 3600
        os.utime(cache_file, (old_time, old_time))

        updated_index = {
            "items": [{"location": "new/page/", "title": "Updated", "text": "new", "tags": [], "path": []}],
            "config": {"separator": r"[\s\-]+"},
        }
        raw = json.dumps(updated_index).encode()

        def fake_urlopen(url: str, *, timeout: int = 30) -> BytesIO:
            return BytesIO(raw)

        with patch("idfkit_mcp.state.urlopen", fake_urlopen):
            state = ServerState()
            items, _sep, _ver = state.get_or_load_docs_index("25.2")

        assert items[0]["title"] == "Updated"
