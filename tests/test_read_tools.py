"""Tests for model read tools."""

from __future__ import annotations

import builtins
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

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


class TestConvertOsmToIdf:
    def test_missing_openstudio(self, tmp_path: Path) -> None:
        osm_path = tmp_path / "input.osm"
        osm_path.write_text("OSM")
        output_path = tmp_path / "out.idf"

        original_import = builtins.__import__

        def _import(name: str, *args: object, **kwargs: object) -> object:
            if name == "openstudio":
                msg = "No module named openstudio"
                raise ImportError(msg)
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import):
            result = _tool("convert_osm_to_idf").fn(
                osm_path=str(osm_path),
                output_path=str(output_path),
            )

        assert "error" in result
        assert "OpenStudio" in result["error"]
        assert "suggestion" in result

    def test_missing_input_file(self, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        with patch.dict(sys.modules, {"openstudio": fake_openstudio}):
            result = _tool("convert_osm_to_idf").fn(
                osm_path=str(tmp_path / "missing.osm"),
                output_path=str(tmp_path / "out.idf"),
            )
        assert "error" in result
        assert "not found" in result["error"]

    def test_invalid_extensions(self, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        bad_input = tmp_path / "input.txt"
        bad_input.write_text("not osm")
        good_input = tmp_path / "input.osm"
        good_input.write_text("osm")
        with patch.dict(sys.modules, {"openstudio": fake_openstudio}):
            bad_in = _tool("convert_osm_to_idf").fn(
                osm_path=str(bad_input),
                output_path=str(tmp_path / "out.idf"),
            )
            bad_out = _tool("convert_osm_to_idf").fn(
                osm_path=str(good_input),
                output_path=str(tmp_path / "out.txt"),
            )
        assert "error" in bad_in
        assert ".osm" in bad_in["error"]
        assert "error" in bad_out
        assert ".idf" in bad_out["error"]

    def test_output_exists_requires_overwrite(self, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        osm_path = tmp_path / "input.osm"
        osm_path.write_text("OSM")
        output_path = tmp_path / "out.idf"
        output_path.write_text("existing")

        with patch.dict(sys.modules, {"openstudio": fake_openstudio}):
            result = _tool("convert_osm_to_idf").fn(
                osm_path=str(osm_path),
                output_path=str(output_path),
                overwrite=False,
            )
        assert "error" in result
        assert "overwrite=True" in result["error"]

    def test_successful_conversion_loads_state(self, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        osm_path = tmp_path / "input.osm"
        osm_path.write_text("OSM")
        output_path = tmp_path / "out.idf"

        doc = new_document()
        doc.add("Zone", "ConvertedZone")

        with patch.dict(sys.modules, {"openstudio": fake_openstudio}), patch("idfkit.load_idf", return_value=doc):
            result = _tool("convert_osm_to_idf").fn(
                osm_path=str(osm_path),
                output_path=str(output_path),
                allow_newer_versions=True,
                overwrite=False,
            )

        assert result["status"] == "converted"
        assert result["osm_path"] == str(osm_path)
        assert result["output_path"] == str(output_path)
        assert result["openstudio_version"] == "3.11.0"
        assert "zone_count" in result
        assert "total_objects" in result
        assert "translator_warnings_count" in result
        assert "translator_errors_count" in result

        state = get_state()
        assert state.document is doc
        assert state.file_path == output_path
        assert state.simulation_result is None


class _OptionalModel:
    def empty(self) -> bool:
        return False

    def get(self) -> object:
        return object()


class _VersionTranslator:
    def __init__(self) -> None:
        self._warnings = ["warn"]
        self._errors: list[str] = []

    def setAllowNewerVersions(self, _allow: bool) -> None:
        return None

    def loadModel(self, _path: str) -> _OptionalModel:
        return _OptionalModel()

    def warnings(self) -> list[str]:
        return self._warnings

    def errors(self) -> list[str]:
        return self._errors


class _Workspace:
    def save(self, path: str, _overwrite: bool) -> bool:
        Path(path).write_text("Version,24.1;")
        return True


class _ForwardTranslator:
    def __init__(self) -> None:
        self._warnings: list[str] = []
        self._errors: list[str] = []

    def translateModel(self, _model: object) -> _Workspace:
        return _Workspace()

    def warnings(self) -> list[str]:
        return self._warnings

    def errors(self) -> list[str]:
        return self._errors


def _fake_openstudio_module() -> object:
    return types.SimpleNamespace(
        openStudioVersion=lambda: "3.11.0",
        path=lambda value: value,
        osversion=types.SimpleNamespace(VersionTranslator=_VersionTranslator),
        energyplus=types.SimpleNamespace(ForwardTranslator=_ForwardTranslator),
    )
