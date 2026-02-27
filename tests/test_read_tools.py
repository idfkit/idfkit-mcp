"""Tests for model read tools."""

from __future__ import annotations

import tempfile
from pathlib import Path

from idfkit import new_document, write_idf

from idfkit_mcp.state import ServerState, get_state


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return mcp._tool_manager._tools[name]


class TestLoadModel:
    def test_load_idf(self) -> None:
        doc = new_document()
        doc.add("Zone", "TestZone")
        with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as f:
            write_idf(doc, f.name)
            path = f.name

        result = _tool("load_model").fn(file_path=path)
        assert result["total_objects"] >= 1
        assert result["zone_count"] == 1

        state = get_state()
        assert state.document is not None
        assert state.file_path == Path(path)

    def test_load_nonexistent(self) -> None:
        result = _tool("load_model").fn(file_path="/nonexistent/file.idf")
        assert "error" in result


class TestGetModelSummary:
    def test_without_model(self) -> None:
        result = _tool("get_model_summary").fn()
        assert "error" in result

    def test_with_model(self, state_with_zones: ServerState) -> None:
        result = _tool("get_model_summary").fn()
        assert result["zone_count"] == 2
        assert result["total_objects"] >= 3  # 2 zones + 1 surface + defaults


class TestListObjects:
    def test_without_model(self) -> None:
        result = _tool("list_objects").fn(object_type="Zone")
        assert "error" in result

    def test_list_zones(self, state_with_zones: ServerState) -> None:
        result = _tool("list_objects").fn(object_type="Zone")
        assert result["total"] == 2
        names = [o["name"] for o in result["objects"]]
        assert "Office" in names
        assert "Corridor" in names

    def test_missing_type(self, state_with_zones: ServerState) -> None:
        result = _tool("list_objects").fn(object_type="Material")
        assert "error" in result


class TestGetObject:
    def test_get_zone(self, state_with_zones: ServerState) -> None:
        result = _tool("get_object").fn(object_type="Zone", name="Office")
        assert result["name"] == "Office"
        assert result["object_type"] == "Zone"

    def test_missing_object(self, state_with_zones: ServerState) -> None:
        result = _tool("get_object").fn(object_type="Zone", name="Nonexistent")
        assert "error" in result


class TestSearchObjects:
    def test_search_by_name(self, state_with_zones: ServerState) -> None:
        result = _tool("search_objects").fn(query="Office")
        assert result["count"] >= 1
        types = [m["object_type"] for m in result["matches"]]
        assert "Zone" in types

    def test_search_by_type(self, state_with_zones: ServerState) -> None:
        result = _tool("search_objects").fn(query="Office", object_type="Zone")
        assert result["count"] == 1

    def test_no_results(self, state_with_zones: ServerState) -> None:
        result = _tool("search_objects").fn(query="xyznonexistent")
        assert result["count"] == 0


class TestGetReferences:
    def test_referenced_zone(self, state_with_zones: ServerState) -> None:
        result = _tool("get_references").fn(name="Office")
        assert result["referenced_by_count"] >= 1
        ref_types = [r["object_type"] for r in result["referenced_by"]]
        assert "BuildingSurface:Detailed" in ref_types

    def test_unreferenced(self, state_with_zones: ServerState) -> None:
        result = _tool("get_references").fn(name="Corridor")
        assert result["referenced_by_count"] == 0
