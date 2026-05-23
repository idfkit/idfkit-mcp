"""Tests for the agent reference resources at idfkit://references/."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from mcp.shared.exceptions import McpError

from idfkit_mcp.tools.references import (
    ReferenceEntry,
    _parse_metadata,
    get_reference_markdown,
    list_references,
)
from tests.conftest import read_resource_json


class TestParseMetadata:
    def test_extracts_h1_and_first_paragraph(self) -> None:
        title, description = _parse_metadata(
            "# Topic title\n\nFirst paragraph of prose explaining what this is.\n\n## Next H2\n\nMore content."
        )
        assert title == "Topic title"
        assert description.startswith("First paragraph of prose")

    def test_joins_multi_line_paragraph(self) -> None:
        _, description = _parse_metadata("# Title\n\nLine one\nLine two\nLine three\n\n## Section\n")
        assert description == "Line one Line two Line three"

    def test_missing_h1_returns_empty(self) -> None:
        title, description = _parse_metadata("Just some content without a heading.")
        assert title == ""
        assert description == ""


class TestListReferences:
    def test_returns_entries_from_installed_idfkit(self) -> None:
        list_references.cache_clear()
        entries = list_references()
        if not entries:
            pytest.skip("Installed idfkit does not bundle agent references")
        assert all(isinstance(e, ReferenceEntry) for e in entries)
        slugs = [e.slug for e in entries]
        assert "hvac-templates" in slugs
        assert "simulation-execution" in slugs
        assert slugs == sorted(slugs)

    def test_entries_have_titles_and_descriptions(self) -> None:
        list_references.cache_clear()
        entries = list_references()
        if not entries:
            pytest.skip("Installed idfkit does not bundle agent references")
        for entry in entries:
            assert entry.title, f"missing title for {entry.slug}"
            assert entry.description, f"missing description for {entry.slug}"
            assert entry.slug

    def test_returns_empty_when_skill_root_missing(self) -> None:
        list_references.cache_clear()
        with patch("idfkit_mcp.tools.references._skill_root", return_value=None):
            assert list_references() == ()
        list_references.cache_clear()


class TestGetReferenceMarkdown:
    def test_returns_markdown_with_h1(self) -> None:
        list_references.cache_clear()
        if not list_references():
            pytest.skip("Installed idfkit does not bundle agent references")
        body = get_reference_markdown("hvac-templates")
        assert body.startswith("# HVAC templates")

    def test_unknown_topic_raises_value_error(self) -> None:
        list_references.cache_clear()
        if not list_references():
            pytest.skip("Installed idfkit does not bundle agent references")
        with pytest.raises(ValueError, match="Reference 'not-a-real-topic' not found"):
            get_reference_markdown("not-a-real-topic")

    def test_raises_when_skill_root_missing(self) -> None:
        list_references.cache_clear()
        with (
            patch("idfkit_mcp.tools.references._skill_root", return_value=None),
            pytest.raises(ValueError, match="does not bundle agent references"),
        ):
            get_reference_markdown("hvac-templates")
        list_references.cache_clear()

    @pytest.mark.parametrize(
        "topic",
        ["../etc/passwd", "..", "foo/bar", "FOO", "topic.md", "-leading-dash", ""],
    )
    def test_rejects_invalid_topic(self, topic: str) -> None:
        with pytest.raises(ValueError, match="Invalid reference topic"):
            get_reference_markdown(topic)


class TestReferenceIndexResource:
    async def test_index_includes_topics(self, client: object) -> None:
        list_references.cache_clear()
        if not list_references():
            pytest.skip("Installed idfkit does not bundle agent references")
        payload = await read_resource_json(client, "idfkit://references/")
        assert payload["count"] == len(payload["topics"])
        slugs = {topic["slug"] for topic in payload["topics"]}
        assert "hvac-templates" in slugs
        for topic in payload["topics"]:
            assert topic["uri"] == f"idfkit://references/{topic['slug']}"
            assert topic["title"]
            assert topic["description"]

    async def test_index_includes_skill_md(self, client: object) -> None:
        list_references.cache_clear()
        if not list_references():
            pytest.skip("Installed idfkit does not bundle agent references")
        payload = await read_resource_json(client, "idfkit://references/")
        assert payload["skill_md"]
        assert "Developing with idfkit" in payload["skill_md"]

    async def test_index_works_when_references_missing(self, client: object) -> None:
        list_references.cache_clear()
        with patch("idfkit_mcp.tools.references._skill_root", return_value=None):
            contents = await client.read_resource("idfkit://references/")  # type: ignore[attr-defined]
            payload = json.loads(contents[0].text)
        assert payload["count"] == 0
        assert payload["topics"] == []
        assert payload["skill_md"] is None
        list_references.cache_clear()


class TestReferenceDocumentResource:
    async def test_returns_markdown_body(self, client: object) -> None:
        list_references.cache_clear()
        if not list_references():
            pytest.skip("Installed idfkit does not bundle agent references")
        contents = await client.read_resource("idfkit://references/hvac-templates")  # type: ignore[attr-defined]
        assert contents
        body = contents[0].text
        assert body.startswith("# HVAC templates")
        assert "HVACTemplate:Zone:IdealLoadsAirSystem" in body

    async def test_unknown_topic_raises(self, client: object) -> None:
        list_references.cache_clear()
        if not list_references():
            pytest.skip("Installed idfkit does not bundle agent references")
        with pytest.raises(McpError, match="not found"):
            await client.read_resource("idfkit://references/not-a-real-topic")  # type: ignore[attr-defined]
