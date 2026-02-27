"""End-to-end integration tests for the idfkit MCP server."""

from __future__ import annotations


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return mcp._tool_manager._tools[name]


class TestCreateEditValidateSave:
    """Full workflow: create model → add objects → validate → save."""

    def test_full_workflow(self, tmp_path: object) -> None:
        import tempfile

        # 1. Create new model
        result = _tool("new_model").fn()
        assert result["status"] == "created"

        # 2. Describe Zone type before creating
        desc = _tool("describe_object_type").fn(object_type="Zone")
        assert desc["object_type"] == "Zone"

        # 3. Batch add objects
        objects = [
            {"object_type": "Zone", "name": "Office"},
            {"object_type": "Zone", "name": "Corridor"},
            {"object_type": "Zone", "name": "Storage"},
        ]
        batch_result = _tool("batch_add_objects").fn(objects=objects)
        assert batch_result["success"] == 3

        # 4. Get model summary
        summary = _tool("get_model_summary").fn()
        assert summary["zone_count"] == 3
        assert summary["total_objects"] >= 3

        # 5. List zones
        zones = _tool("list_objects").fn(object_type="Zone")
        assert zones["total"] == 3

        # 6. Update a zone
        updated = _tool("update_object").fn(object_type="Zone", name="Office", fields={"x_origin": 10.0})
        assert "x_origin" in updated

        # 7. Search for objects
        search = _tool("search_objects").fn(query="Office")
        assert search["count"] >= 1

        # 8. Validate
        validation = _tool("validate_model").fn()
        assert validation["is_valid"] is True

        # 9. Check references
        refs = _tool("check_references").fn()
        assert "dangling_count" in refs

        # 10. Save
        with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as f:
            save_result = _tool("save_model").fn(file_path=f.name)
        assert save_result["status"] == "saved"

        # 11. Load it back
        load_result = _tool("load_model").fn(file_path=f.name)
        assert load_result["zone_count"] == 3

    def test_rename_and_duplicate(self) -> None:
        # Create model with zones
        _tool("new_model").fn()
        _tool("add_object").fn(object_type="Zone", name="ZoneA")

        # Duplicate
        dup = _tool("duplicate_object").fn(object_type="Zone", name="ZoneA", new_name="ZoneB")
        assert dup["name"] == "ZoneB"

        # Rename
        renamed = _tool("rename_object").fn(object_type="Zone", old_name="ZoneA", new_name="ZoneC")
        assert renamed["status"] == "renamed"

        # Verify
        summary = _tool("get_model_summary").fn()
        assert summary["zone_count"] == 2

    def test_remove_workflow(self) -> None:
        _tool("new_model").fn()
        _tool("add_object").fn(object_type="Zone", name="TempZone")

        # Remove
        result = _tool("remove_object").fn(object_type="Zone", name="TempZone")
        assert result["status"] == "removed"

        # Verify empty
        summary = _tool("get_model_summary").fn()
        assert summary["zone_count"] == 0
