"""End-to-end integration tests for the idfkit MCP server."""

from __future__ import annotations

from fastmcp.client import Client
from fastmcp.client.transports import FastMCPTransport

from idfkit_mcp.models import (
    BatchAddResult,
    CheckReferencesResult,
    DescribeObjectTypeResult,
    ListObjectsResult,
    ModelSummary,
    NewModelResult,
    RemoveObjectResult,
    RenameObjectResult,
    SaveModelResult,
    SearchObjectsResult,
    ValidationResult,
)
from tests.conftest import call_tool


class TestCreateEditValidateSave:
    """Full workflow: create model → add objects → validate → save."""

    async def test_full_workflow(self, client: Client[FastMCPTransport], tmp_path: object) -> None:
        import tempfile

        result = await call_tool(client, "new_model", model=NewModelResult)
        assert result.status == "created"

        desc = await call_tool(client, "describe_object_type", {"object_type": "Zone"}, DescribeObjectTypeResult)
        assert desc.object_type == "Zone"

        objects = [
            {"object_type": "Zone", "name": "Office"},
            {"object_type": "Zone", "name": "Corridor"},
            {"object_type": "Zone", "name": "Storage"},
        ]
        batch_result = await call_tool(client, "batch_add_objects", {"objects": objects}, BatchAddResult)
        assert batch_result.success == 3

        summary = await call_tool(client, "get_model_summary", model=ModelSummary)
        assert summary.zone_count == 3
        assert summary.total_objects >= 3

        zones = await call_tool(client, "list_objects", {"object_type": "Zone"}, ListObjectsResult)
        assert zones.total == 3

        updated = await call_tool(
            client, "update_object", {"object_type": "Zone", "name": "Office", "fields": {"x_origin": 10.0}}
        )
        assert "x_origin" in updated

        search = await call_tool(client, "search_objects", {"query": "Office"}, SearchObjectsResult)
        assert search.count >= 1

        validation = await call_tool(client, "validate_model", model=ValidationResult)
        assert validation.is_valid is True

        refs = await call_tool(client, "check_references", model=CheckReferencesResult)
        assert refs.dangling_count is not None

        with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as f:
            save_result = await call_tool(client, "save_model", {"file_path": f.name}, SaveModelResult)
        assert save_result.status == "saved"

        load_result = await call_tool(client, "load_model", {"file_path": f.name}, ModelSummary)
        assert load_result.zone_count == 3

    async def test_rename_and_duplicate(self, client: object) -> None:
        await call_tool(client, "new_model", model=NewModelResult)
        await call_tool(client, "add_object", {"object_type": "Zone", "name": "ZoneA"})

        dup = await call_tool(client, "duplicate_object", {"object_type": "Zone", "name": "ZoneA", "new_name": "ZoneB"})
        assert dup["name"] == "ZoneB"

        renamed = await call_tool(
            client,
            "rename_object",
            {"object_type": "Zone", "old_name": "ZoneA", "new_name": "ZoneC"},
            RenameObjectResult,
        )
        assert renamed.status == "renamed"

        summary = await call_tool(client, "get_model_summary", model=ModelSummary)
        assert summary.zone_count == 2

    async def test_remove_workflow(self, client: object) -> None:
        await call_tool(client, "new_model", model=NewModelResult)
        await call_tool(client, "add_object", {"object_type": "Zone", "name": "TempZone"})

        result = await call_tool(
            client, "remove_object", {"object_type": "Zone", "name": "TempZone"}, RemoveObjectResult
        )
        assert result.status == "removed"

        summary = await call_tool(client, "get_model_summary", model=ModelSummary)
        assert summary.zone_count == 0
