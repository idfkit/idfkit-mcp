"""Tests for model read tools."""

from __future__ import annotations

import base64
import builtins
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError
from idfkit import new_document, write_idf

from idfkit_mcp.models import ConvertOsmResult, ListObjectsResult, ModelSummary, SearchObjectsResult
from idfkit_mcp.state import ServerState, get_state, session_uploads_dir
from tests.conftest import call_tool, read_resource_json


class TestLoadModel:
    async def test_load_idf(self, client: object) -> None:
        doc = new_document()
        doc.add("Zone", "TestZone")
        with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as f:
            write_idf(doc, f.name)
            path = f.name

        result = await call_tool(client, "load_model", {"file_path": path}, ModelSummary)
        assert result.total_objects >= 1
        assert result.zone_count == 1

        state = get_state()
        assert state.document is not None
        assert state.file_path == Path(path)

    async def test_load_nonexistent(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "load_model", {"file_path": "/nonexistent/file.idf"})

    async def test_requires_exactly_one_source(self, client: object, tmp_path: Path) -> None:
        with pytest.raises(ToolError, match="exactly one"):
            await call_tool(client, "load_model", {})
        with pytest.raises(ToolError, match="exactly one"):
            await call_tool(
                client,
                "load_model",
                {"file_path": str(tmp_path / "x.idf"), "upload_name": "x.idf"},
            )

    async def test_load_from_upload(self, client: object) -> None:
        from idfkit_mcp.server import uploads

        doc = new_document()
        doc.add("Zone", "UploadedZone")
        with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as f:
            write_idf(doc, f.name)
            data = Path(f.name).read_bytes()

        state = get_state()
        uploads._store.setdefault(state.session_id, {})["upload.idf"] = {
            "name": "upload.idf",
            "size": len(data),
            "type": "text/plain",
            "data": base64.b64encode(data).decode(),
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            result = await call_tool(client, "load_model", {"upload_name": "upload.idf"}, ModelSummary)
            assert result.zone_count == 1
            assert state.document is not None
            materialized = session_uploads_dir(state.session_id) / "upload.idf"
            assert state.file_path == materialized
            assert materialized.read_bytes() == data
        finally:
            uploads._store.pop(state.session_id, None)
            state.clear_session()

    async def test_upload_missing_name(self, client: object) -> None:
        with pytest.raises(ToolError, match="No upload"):
            await call_tool(client, "load_model", {"upload_name": "does-not-exist.idf"})


class TestClearSessionPreservesUploads:
    async def test_clear_session_keeps_upload_dir(self, client: object) -> None:
        state = get_state()
        uploads_dir = session_uploads_dir(state.session_id)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / "model.idf").write_text("dummy")
        assert uploads_dir.exists()

        await call_tool(client, "clear_session", {})
        assert uploads_dir.exists(), "uploads should survive clear_session"
        assert (uploads_dir / "model.idf").exists()


class TestReadFileToolHidden:
    async def test_read_file_not_exposed(self, client: object) -> None:
        tools = await client.list_tools()  # type: ignore[attr-defined]
        names = {t.name for t in tools}
        assert not any(name.endswith("read_file") for name in names), (
            f"read_file should be hidden from the LLM to prevent token blow-up; saw {names}"
        )


class TestDiskBackedUploadStore:
    """Exercise IdfUploadStore configured with a root path (IDFKIT_MCP_UPLOAD_DIR)."""

    def test_on_store_writes_to_disk(self, tmp_path: Path) -> None:
        from idfkit_mcp.state import _current_session_id
        from idfkit_mcp.uploads import IdfUploadStore

        store = IdfUploadStore(root=tmp_path, name="Test")
        _current_session_id.set("sess-a")
        payload = [{"name": "a.idf", "size": 4, "type": "text/plain", "data": base64.b64encode(b"idf!").decode()}]
        store.on_store(payload, ctx=None)  # type: ignore[arg-type]

        assert (tmp_path / "sess-a" / "a.idf").read_bytes() == b"idf!"
        assert (tmp_path / "sess-a" / "a.idf.meta.json").exists()

    def test_get_bytes_reads_from_disk(self, tmp_path: Path) -> None:
        from idfkit_mcp.state import _current_session_id
        from idfkit_mcp.uploads import IdfUploadStore

        store = IdfUploadStore(root=tmp_path, name="Test")
        _current_session_id.set("sess-b")
        store.on_store(
            [{"name": "m.idf", "size": 5, "type": "text/plain", "data": base64.b64encode(b"bytes").decode()}],
            ctx=None,  # type: ignore[arg-type]
        )
        assert store.get_bytes("m.idf", session_id="sess-b") == b"bytes"

    def test_scope_isolation(self, tmp_path: Path) -> None:
        from idfkit_mcp.state import _current_session_id
        from idfkit_mcp.uploads import IdfUploadStore

        store = IdfUploadStore(root=tmp_path, name="Test")
        for sid, blob in [("one", b"first"), ("two", b"second")]:
            _current_session_id.set(sid)
            store.on_store(
                [{"name": "x.idf", "size": len(blob), "type": "text/plain", "data": base64.b64encode(blob).decode()}],
                ctx=None,  # type: ignore[arg-type]
            )
        assert store.get_bytes("x.idf", session_id="one") == b"first"
        assert store.get_bytes("x.idf", session_id="two") == b"second"

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        from idfkit_mcp.state import _current_session_id
        from idfkit_mcp.uploads import IdfUploadStore

        store = IdfUploadStore(root=tmp_path, name="Test")
        _current_session_id.set("sess-t")
        for bad in ("../escape.idf", "foo/bar.idf", ".hidden", ".."):
            with pytest.raises(ValueError):
                store.on_store(
                    [{"name": bad, "size": 1, "type": "text/plain", "data": base64.b64encode(b"x").decode()}],
                    ctx=None,  # type: ignore[arg-type]
                )

    def test_clear_scope_removes_disk_dir(self, tmp_path: Path) -> None:
        from idfkit_mcp.state import _current_session_id
        from idfkit_mcp.uploads import IdfUploadStore

        store = IdfUploadStore(root=tmp_path, name="Test")
        _current_session_id.set("sess-c")
        store.on_store(
            [{"name": "a.idf", "size": 1, "type": "text/plain", "data": base64.b64encode(b"a").decode()}],
            ctx=None,  # type: ignore[arg-type]
        )
        scope = tmp_path / "sess-c"
        assert scope.exists()
        store.clear_scope("sess-c")
        assert not scope.exists()


class TestModelSummaryResource:
    async def test_with_model(self, client: object, state_with_zones: ServerState) -> None:
        payload = await read_resource_json(client, "idfkit://model/summary")
        assert payload["zone_count"] == 2
        assert payload["total_objects"] >= 3


class TestObjectDataResource:
    async def test_get_zone(self, client: object, state_with_zones: ServerState) -> None:
        payload = await read_resource_json(client, "idfkit://model/objects/Zone/Office")
        assert payload["name"] == "Office"
        assert payload["object_type"] == "Zone"
        assert "x_origin" in payload

    async def test_get_singleton(self, client: object, state_with_singletons: ServerState) -> None:
        payload = await read_resource_json(client, "idfkit://schema/SimulationControl")
        assert payload["object_type"] == "SimulationControl"


class TestObjectReferencesResource:
    async def test_referenced_zone(self, client: object, state_with_zones: ServerState) -> None:
        payload = await read_resource_json(client, "idfkit://model/references/Office")
        assert payload["referenced_by_count"] >= 1

    async def test_unreferenced(self, client: object, state_with_zones: ServerState) -> None:
        payload = await read_resource_json(client, "idfkit://model/references/Corridor")
        assert payload["referenced_by_count"] == 0


class TestListObjects:
    async def test_without_model(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "list_objects", {"object_type": "Zone"})

    async def test_list_zones(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "list_objects", {"object_type": "Zone"}, ListObjectsResult)
        assert result.total == 2
        names = [o["name"] for o in result.objects]
        assert "Office" in names
        assert "Corridor" in names

    async def test_missing_type(self, client: object, state_with_zones: ServerState) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "list_objects", {"object_type": "Material"})

    async def test_include_all_fields(self, client: object, state_with_zones: ServerState) -> None:
        brief = await call_tool(client, "list_objects", {"object_type": "Zone"}, ListObjectsResult)
        full = await call_tool(
            client,
            "list_objects",
            {"object_type": "Zone", "include_all_fields": True},
            ListObjectsResult,
        )
        brief_keys = set(brief.objects[0].keys())
        full_keys = set(full.objects[0].keys())
        assert brief_keys.issubset(full_keys)
        assert len(full_keys) > len(brief_keys)


class TestSearchObjects:
    async def test_search_by_name(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "search_objects", {"query": "Office"}, SearchObjectsResult)
        assert result.count >= 1
        types = [m.object_type for m in result.matches]
        assert "Zone" in types

    async def test_search_by_type(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(
            client, "search_objects", {"query": "Office", "object_type": "Zone"}, SearchObjectsResult
        )
        assert result.count == 1

    async def test_no_results(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "search_objects", {"query": "xyznonexistent"}, SearchObjectsResult)
        assert result.count == 0


class TestConvertOsmToIdf:
    async def test_missing_openstudio(self, client: object, tmp_path: Path) -> None:
        osm_path = tmp_path / "input.osm"
        osm_path.write_text("OSM")
        output_path = tmp_path / "out.idf"

        original_import = builtins.__import__

        def _import(name: str, *args: object, **kwargs: object) -> object:
            if name == "openstudio":
                msg = "No module named openstudio"
                raise ImportError(msg)
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_import), pytest.raises(ToolError, match="OpenStudio"):
            await call_tool(client, "convert_osm_to_idf", {"osm_path": str(osm_path), "output_path": str(output_path)})

    async def test_missing_input_file(self, client: object, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        with patch.dict(sys.modules, {"openstudio": fake_openstudio}), pytest.raises(ToolError, match="not found"):
            await call_tool(
                client,
                "convert_osm_to_idf",
                {"osm_path": str(tmp_path / "missing.osm"), "output_path": str(tmp_path / "out.idf")},
            )

    async def test_invalid_extensions(self, client: object, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        bad_input = tmp_path / "input.txt"
        bad_input.write_text("not osm")
        good_input = tmp_path / "input.osm"
        good_input.write_text("osm")
        with patch.dict(sys.modules, {"openstudio": fake_openstudio}):
            with pytest.raises(ToolError, match=r"\.osm"):
                await call_tool(
                    client, "convert_osm_to_idf", {"osm_path": str(bad_input), "output_path": str(tmp_path / "out.idf")}
                )
            with pytest.raises(ToolError, match=r"\.idf"):
                await call_tool(
                    client,
                    "convert_osm_to_idf",
                    {"osm_path": str(good_input), "output_path": str(tmp_path / "out.txt")},
                )

    async def test_output_exists_requires_overwrite(self, client: object, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        osm_path = tmp_path / "input.osm"
        osm_path.write_text("OSM")
        output_path = tmp_path / "out.idf"
        output_path.write_text("existing")

        with patch.dict(sys.modules, {"openstudio": fake_openstudio}), pytest.raises(ToolError, match="overwrite=True"):
            await call_tool(
                client,
                "convert_osm_to_idf",
                {"osm_path": str(osm_path), "output_path": str(output_path), "overwrite": False},
            )

    async def test_successful_conversion_loads_state(self, client: object, tmp_path: Path) -> None:
        fake_openstudio = _fake_openstudio_module()
        osm_path = tmp_path / "input.osm"
        osm_path.write_text("OSM")
        output_path = tmp_path / "out.idf"

        doc = new_document()
        doc.add("Zone", "ConvertedZone")

        with patch.dict(sys.modules, {"openstudio": fake_openstudio}), patch("idfkit.load_idf", return_value=doc):
            result = await call_tool(
                client,
                "convert_osm_to_idf",
                {
                    "osm_path": str(osm_path),
                    "output_path": str(output_path),
                    "allow_newer_versions": True,
                    "overwrite": False,
                },
                ConvertOsmResult,
            )

        assert result.status == "converted"
        assert result.osm_path == str(osm_path)
        assert result.output_path == str(output_path)
        assert result.openstudio_version == "3.11.0"
        assert result.zone_count is not None
        assert result.total_objects is not None
        assert result.translator_warnings_count is not None
        assert result.translator_errors_count is not None

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
