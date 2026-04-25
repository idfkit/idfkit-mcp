"""Tests for model write tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.models import BatchAddResult, NewModelResult, RemoveObjectResult, RenameObjectResult, SaveModelResult
from idfkit_mcp.state import ServerState, get_state
from tests.conftest import call_tool


class TestNewModel:
    async def test_create_default(self, client: object) -> None:
        result = await call_tool(client, "new_model", model=NewModelResult)
        assert result.status == "created"
        assert result.version
        state = get_state()
        assert state.document is not None

    async def test_create_specific_version(self, client: object) -> None:
        result = await call_tool(client, "new_model", {"version": "24.1.0"}, NewModelResult)
        assert result.status == "created"
        assert "24.1.0" in result.version


class TestAddObject:
    async def test_add_zone(self, client: object, state_with_model: ServerState) -> None:
        result = await call_tool(client, "add_object", {"object_type": "Zone", "name": "TestZone"})
        assert result["name"] == "TestZone"
        assert result["object_type"] == "Zone"

    async def test_add_with_fields(self, client: object, state_with_model: ServerState) -> None:
        result = await call_tool(
            client,
            "add_object",
            {"object_type": "Zone", "name": "TestZone", "fields": {"x_origin": 10.0, "y_origin": 20.0}},
        )
        assert result["name"] == "TestZone"

    async def test_add_unknown_type(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "add_object", {"object_type": "NonExistent", "name": "Test"})

    async def test_add_without_model(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "add_object", {"object_type": "Zone", "name": "Test"})

    async def test_extensible_flat_fields_blocked(self, client: object, state_with_model: ServerState) -> None:
        """Passing flat vertex_* fields instead of a vertices array must raise."""
        with pytest.raises(ToolError, match="vertices"):
            await call_tool(
                client,
                "add_object",
                {
                    "object_type": "BuildingSurface:Detailed",
                    "name": "WallA",
                    "fields": {
                        "surface_type": "Wall",
                        "construction_name": "C1",
                        "zone_name": "Z1",
                        "outside_boundary_condition": "Outdoors",
                        "vertex_x_coordinate": 0,
                        "vertex_y_coordinate": 0,
                        "vertex_z_coordinate": 0,
                    },
                },
            )

    async def test_extensible_numbered_legacy_fields_blocked(
        self, client: object, state_with_model: ServerState
    ) -> None:
        """Legacy IDD-style numbered fields (vertex_1_x_coordinate) must also raise."""
        with pytest.raises(ToolError, match="vertices"):
            await call_tool(
                client,
                "add_object",
                {
                    "object_type": "BuildingSurface:Detailed",
                    "name": "WallA",
                    "fields": {
                        "surface_type": "Wall",
                        "construction_name": "C1",
                        "zone_name": "Z1",
                        "outside_boundary_condition": "Outdoors",
                        "vertex_1_x_coordinate": 0,
                        "vertex_1_y_coordinate": 0,
                        "vertex_1_z_coordinate": 0,
                    },
                },
            )

    async def test_extensible_array_form_succeeds(self, client: object, state_with_model: ServerState) -> None:
        """The vertices-array shape must be normalized to the flat numbered shape.

        idfkit's IDF writer serializes the canonical flat shape; passing the
        epJSON array straight through produces malformed IDF text. Our layer
        accepts the agent-friendly array form and expands it.
        """
        result = await call_tool(
            client,
            "add_object",
            {
                "object_type": "BuildingSurface:Detailed",
                "name": "WallB",
                "fields": {
                    "surface_type": "Wall",
                    "construction_name": "C1",
                    "zone_name": "Z1",
                    "outside_boundary_condition": "Outdoors",
                    "vertices": [
                        {"vertex_x_coordinate": 0, "vertex_y_coordinate": 0, "vertex_z_coordinate": 0},
                        {"vertex_x_coordinate": 1, "vertex_y_coordinate": 0, "vertex_z_coordinate": 0},
                        {"vertex_x_coordinate": 1, "vertex_y_coordinate": 0, "vertex_z_coordinate": 1},
                    ],
                },
            },
        )
        assert result["name"] == "WallB"
        # Normalized to flat numbered keys for idfkit's IDF writer.
        assert result["vertex_x_coordinate"] == 0
        assert result["vertex_x_coordinate_2"] == 1
        assert result["vertex_x_coordinate_3"] == 1
        assert result.get("vertices") is None


class TestBatchAddObjects:
    async def test_batch_add(self, client: object, state_with_model: ServerState) -> None:
        objects = [
            {"object_type": "Zone", "name": "Zone1"},
            {"object_type": "Zone", "name": "Zone2"},
            {"object_type": "Zone", "name": "Zone3"},
        ]
        result = await call_tool(client, "batch_add_objects", {"objects": objects}, BatchAddResult)
        assert result.total == 3
        assert result.success == 3
        assert result.errors == 0

    async def test_batch_partial_failure(self, client: object, state_with_model: ServerState) -> None:
        objects = [
            {"object_type": "Zone", "name": "Zone1"},
            {"object_type": "Zone", "name": "Zone1"},  # Duplicate
        ]
        result = await call_tool(client, "batch_add_objects", {"objects": objects}, BatchAddResult)
        assert result.total == 2
        assert result.success == 1
        assert result.errors == 1

    async def test_batch_missing_type(self, client: object, state_with_model: ServerState) -> None:
        objects = [{"name": "Test"}]
        result = await call_tool(client, "batch_add_objects", {"objects": objects}, BatchAddResult)
        assert result.errors == 1


class TestUpdateObject:
    async def test_update_fields(self, client: object, state_with_model: ServerState) -> None:
        await call_tool(client, "add_object", {"object_type": "Zone", "name": "TestZone"})
        result = await call_tool(
            client, "update_object", {"object_type": "Zone", "name": "TestZone", "fields": {"x_origin": 5.0}}
        )
        assert "x_origin" in result

    async def test_update_name_cascades_references(self, client: object, state_with_zones: ServerState) -> None:
        """Renaming via update_object cascades references (idfkit handles this)."""
        result = await call_tool(
            client, "update_object", {"object_type": "Zone", "name": "Office", "fields": {"name": "MainOffice"}}
        )
        assert result["name"] == "MainOffice"
        # Surface reference should have been updated automatically
        surface = await call_tool(client, "list_objects", {"object_type": "BuildingSurface:Detailed"})
        assert surface["objects"][0]["zone_name"] == "MainOffice"

    async def test_update_nonexistent(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            await call_tool(
                client, "update_object", {"object_type": "Zone", "name": "Missing", "fields": {"x_origin": 5.0}}
            )


class TestRemoveObject:
    async def test_remove_unreferenced(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(
            client, "remove_object", {"object_type": "Zone", "name": "Corridor"}, RemoveObjectResult
        )
        assert result.status == "removed"

    async def test_remove_referenced_blocked(self, client: object, state_with_zones: ServerState) -> None:
        with pytest.raises(ToolError, match="referenced"):
            await call_tool(client, "remove_object", {"object_type": "Zone", "name": "Office"})

    async def test_remove_referenced_forced(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(
            client, "remove_object", {"object_type": "Zone", "name": "Office", "force": True}, RemoveObjectResult
        )
        assert result.status == "removed"


class TestRenameObject:
    async def test_rename(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(
            client,
            "rename_object",
            {"object_type": "Zone", "old_name": "Office", "new_name": "MainOffice"},
            RenameObjectResult,
        )
        assert result.status == "renamed"
        assert result.references_updated >= 1


class TestDuplicateObject:
    async def test_duplicate(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(
            client, "duplicate_object", {"object_type": "Zone", "name": "Office", "new_name": "OfficeClone"}
        )
        assert result["name"] == "OfficeClone"


class TestUpdateObjectSingleton:
    """Singleton types should be updatable."""

    async def test_update_singleton(self, client: object, state_with_singletons: ServerState) -> None:
        result = await call_tool(
            client,
            "update_object",
            {"object_type": "SimulationControl", "name": "", "fields": {"do_zone_sizing_calculation": "No"}},
        )
        assert result["object_type"] == "SimulationControl"


class TestRemoveObjectSingleton:
    """Singleton types should be removable."""

    async def test_remove_singleton(self, client: object, state_with_singletons: ServerState) -> None:
        result = await call_tool(
            client,
            "remove_object",
            {"object_type": "GlobalGeometryRules", "name": "", "force": True},
            RemoveObjectResult,
        )
        assert result.status == "removed"


class TestSaveModel:
    async def test_save_idf(
        self, client: object, state_with_zones: ServerState, tmp_path: object, monkeypatch: object
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = await call_tool(client, "save_model", {"file_path": "output.idf"}, SaveModelResult)
        assert result.status == "saved"
        assert result.format == "idf"

    async def test_save_epjson(
        self, client: object, state_with_zones: ServerState, tmp_path: object, monkeypatch: object
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = await call_tool(
            client, "save_model", {"file_path": "output.epjson", "output_format": "epjson"}, SaveModelResult
        )
        assert result.status == "saved"
        assert result.format == "epjson"

    async def test_save_no_path(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "save_model")

    async def test_save_rejects_path_outside_allowed_dirs(
        self, client: object, state_with_zones: ServerState, tmp_path: object, monkeypatch: object
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ToolError, match="allowed directory"):
            await call_tool(client, "save_model", {"file_path": "/tmp/evil.idf"})  # noqa: S108

    async def test_save_allows_configured_output_dir(
        self, client: object, state_with_zones: ServerState, tmp_path: object, monkeypatch: object
    ) -> None:
        output_dir = tmp_path / "mounted_volume"
        output_dir.mkdir()
        monkeypatch.setenv("IDFKIT_MCP_OUTPUT_DIRS", str(output_dir))
        result = await call_tool(client, "save_model", {"file_path": str(output_dir / "model.idf")}, SaveModelResult)
        assert result.status == "saved"
        assert (output_dir / "model.idf").exists()

    async def test_save_blocks_overwrite_by_default(
        self, client: object, state_with_zones: ServerState, tmp_path: object, monkeypatch: object
    ) -> None:
        monkeypatch.chdir(tmp_path)
        await call_tool(client, "save_model", {"file_path": "model.idf"})
        with pytest.raises(ToolError, match="already exists"):
            await call_tool(client, "save_model", {"file_path": "model.idf"})

    async def test_save_overwrite_true(
        self, client: object, state_with_zones: ServerState, tmp_path: object, monkeypatch: object
    ) -> None:
        monkeypatch.chdir(tmp_path)
        await call_tool(client, "save_model", {"file_path": "model.idf"})
        result = await call_tool(client, "save_model", {"file_path": "model.idf", "overwrite": True}, SaveModelResult)
        assert result.status == "saved"
