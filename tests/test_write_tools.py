"""Tests for model write tools."""

from __future__ import annotations

import tempfile

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from idfkit_mcp.state import ServerState, get_state


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return mcp._tool_manager._tools[name]


class TestNewModel:
    def test_create_default(self) -> None:
        result = _tool("new_model").fn()
        assert result.status == "created"
        assert result.version
        state = get_state()
        assert state.document is not None

    def test_create_specific_version(self) -> None:
        result = _tool("new_model").fn(version="24.1.0")
        assert result.status == "created"
        assert "24.1.0" in result.version


class TestAddObject:
    def test_add_zone(self, state_with_model: ServerState) -> None:
        result = _tool("add_object").fn(object_type="Zone", name="TestZone")
        assert result["name"] == "TestZone"
        assert result["object_type"] == "Zone"

    def test_add_with_fields(self, state_with_model: ServerState) -> None:
        result = _tool("add_object").fn(
            object_type="Zone", name="TestZone", fields={"x_origin": 10.0, "y_origin": 20.0}
        )
        assert result["name"] == "TestZone"

    def test_add_unknown_type(self, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            _tool("add_object").fn(object_type="NonExistent", name="Test")

    def test_add_without_model(self) -> None:
        with pytest.raises(ToolError):
            _tool("add_object").fn(object_type="Zone", name="Test")


class TestBatchAddObjects:
    def test_batch_add(self, state_with_model: ServerState) -> None:
        objects = [
            {"object_type": "Zone", "name": "Zone1"},
            {"object_type": "Zone", "name": "Zone2"},
            {"object_type": "Zone", "name": "Zone3"},
        ]
        result = _tool("batch_add_objects").fn(objects=objects)
        assert result.total == 3
        assert result.success == 3
        assert result.errors == 0

    def test_batch_partial_failure(self, state_with_model: ServerState) -> None:
        objects = [
            {"object_type": "Zone", "name": "Zone1"},
            {"object_type": "Zone", "name": "Zone1"},  # Duplicate
        ]
        result = _tool("batch_add_objects").fn(objects=objects)
        assert result.total == 2
        assert result.success == 1
        assert result.errors == 1

    def test_batch_missing_type(self, state_with_model: ServerState) -> None:
        objects = [{"name": "Test"}]
        result = _tool("batch_add_objects").fn(objects=objects)
        assert result.errors == 1


class TestUpdateObject:
    def test_update_fields(self, state_with_model: ServerState) -> None:
        _tool("add_object").fn(object_type="Zone", name="TestZone")
        result = _tool("update_object").fn(object_type="Zone", name="TestZone", fields={"x_origin": 5.0})
        assert "x_origin" in result

    def test_update_nonexistent(self, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            _tool("update_object").fn(object_type="Zone", name="Missing", fields={"x_origin": 5.0})


class TestRemoveObject:
    def test_remove_unreferenced(self, state_with_zones: ServerState) -> None:
        result = _tool("remove_object").fn(object_type="Zone", name="Corridor")
        assert result.status == "removed"

    def test_remove_referenced_blocked(self, state_with_zones: ServerState) -> None:
        with pytest.raises(ToolError, match="referenced"):
            _tool("remove_object").fn(object_type="Zone", name="Office")

    def test_remove_referenced_forced(self, state_with_zones: ServerState) -> None:
        result = _tool("remove_object").fn(object_type="Zone", name="Office", force=True)
        assert result.status == "removed"


class TestRenameObject:
    def test_rename(self, state_with_zones: ServerState) -> None:
        result = _tool("rename_object").fn(object_type="Zone", old_name="Office", new_name="MainOffice")
        assert result.status == "renamed"
        assert result.references_updated >= 1


class TestDuplicateObject:
    def test_duplicate(self, state_with_zones: ServerState) -> None:
        result = _tool("duplicate_object").fn(object_type="Zone", name="Office", new_name="OfficeClone")
        assert result["name"] == "OfficeClone"


class TestUpdateObjectSingleton:
    """Singleton types should be updatable."""

    def test_update_singleton(self, state_with_singletons: ServerState) -> None:
        result = _tool("update_object").fn(
            object_type="SimulationControl", name="", fields={"do_zone_sizing_calculation": "No"}
        )
        assert result["object_type"] == "SimulationControl"


class TestRemoveObjectSingleton:
    """Singleton types should be removable."""

    def test_remove_singleton(self, state_with_singletons: ServerState) -> None:
        result = _tool("remove_object").fn(object_type="GlobalGeometryRules", name="", force=True)
        assert result.status == "removed"


class TestSaveModel:
    def test_save_idf(self, state_with_zones: ServerState) -> None:
        with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as f:
            result = _tool("save_model").fn(file_path=f.name)
        assert result.status == "saved"
        assert result.format == "idf"

    def test_save_epjson(self, state_with_zones: ServerState) -> None:
        with tempfile.NamedTemporaryFile(suffix=".epjson", delete=False) as f:
            result = _tool("save_model").fn(file_path=f.name, output_format="epjson")
        assert result.status == "saved"
        assert result.format == "epjson"

    def test_save_no_path(self, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            _tool("save_model").fn()
