"""Tests for server creation and CLI argument parsing."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from idfkit_mcp.server import mcp
from tests.conftest import read_resource_json


class TestCreateServer:
    def test_returns_fastmcp_instance(self) -> None:
        assert mcp.name == "idfkit"

    async def test_registers_all_tool_groups(self, client: Client) -> None:
        tool_names = {tool.name for tool in await client.list_tools()}
        expected = {
            "list_object_types",
            "describe_object_type",
            "search_schema",
            "load_model",
            "convert_osm_to_idf",
            "list_objects",
            "search_objects",
            "get_available_references",
            "new_model",
            "add_object",
            "batch_add_objects",
            "update_object",
            "remove_object",
            "rename_object",
            "duplicate_object",
            "save_model",
            "validate_model",
            "run_simulation",
            "list_output_variables",
            "query_timeseries",
            "export_timeseries",
            "search_weather_stations",
            "download_weather_file",
        }
        assert expected.issubset(tool_names)

    async def test_registers_resources(self, client: Client) -> None:
        resource_uris = {str(resource.uri) for resource in await client.list_resources()}
        template_uris = {str(template.uriTemplate) for template in await client.list_resource_templates()}

        assert "idfkit://model/summary" in resource_uris
        assert "idfkit://simulation/results" in resource_uris
        assert "idfkit://schema/{object_type}" in template_uris
        assert "idfkit://model/objects/{object_type}/{name}" in template_uris
        assert "idfkit://docs/{object_type}" in template_uris
        assert "idfkit://model/references/{name}" in template_uris

    async def test_reads_model_summary_resource(self, client: Client, state_with_zones: object) -> None:
        payload = await read_resource_json(client, "idfkit://model/summary")
        assert payload["zone_count"] == 2
        assert payload["total_objects"] >= 3

    async def test_reads_schema_resource_template(self, client: Client) -> None:
        payload = await read_resource_json(client, "idfkit://schema/Zone")
        assert payload["object_type"] == "Zone"
        assert "fields" in payload

    async def test_reads_object_resource_template(self, client: Client, state_with_zones: object) -> None:
        payload = await read_resource_json(client, "idfkit://model/objects/Zone/Office")
        assert payload["object_type"] == "Zone"
        assert payload["name"] == "Office"


def _is_third_party_app_tool(tool: Any) -> bool:
    """Skip tools registered by third-party FastMCP apps (e.g. FileUpload).

    Their schemas follow upstream conventions, not ours.
    """
    meta = getattr(tool, "meta", None) or {}
    return "app" in meta.get("fastmcp", {})


class TestToolSchemas:
    """Verify that all tool schemas are well-formed for broad client compatibility."""

    @pytest.fixture()
    async def tools(self, client: Client) -> list[Any]:
        all_tools = await client.list_tools()
        return [t for t in all_tools if not _is_third_party_app_tool(t)]

    async def test_all_tools_have_properties_key(self, tools: list[Any]) -> None:
        """Every tool's inputSchema must include a 'properties' key.

        OpenAI's Agents SDK and other strict consumers require this key to be
        present, even for tools with no parameters (where it should be ``{}``).
        """
        for tool in tools:
            schema = tool.inputSchema
            assert "properties" in schema, f"Tool '{tool.name}' inputSchema missing 'properties' key: {schema}"

    async def test_all_tools_have_annotations(self, tools: list[Any]) -> None:
        """Every tool should have ToolAnnotations set (readOnlyHint, etc.)."""
        for tool in tools:
            assert tool.annotations is not None, f"Tool '{tool.name}' is missing annotations"

    async def test_schemas_support_additional_properties_false(self, tools: list[Any]) -> None:
        """Verify schemas can accept additionalProperties: false without conflict.

        OpenAI's ``convert_schemas_to_strict`` applies this constraint. Tools
        using open-ended ``dict[str, Any]`` parameters (e.g. add_object.fields,
        batch_add_objects.objects) are exempt since EnergyPlus field names are
        inherently dynamic.
        """
        # Tools with intentionally dynamic dict parameters that cannot be
        # constrained to a static schema.
        dynamic_schema_tools = {"add_object", "batch_add_objects", "update_object"}

        for tool in tools:
            if tool.name in dynamic_schema_tools:
                continue
            schema = tool.inputSchema
            properties = schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                if prop_schema.get("type") == "object" and "properties" not in prop_schema:
                    pytest.fail(
                        f"Tool '{tool.name}' param '{prop_name}' is an unstructured object "
                        f"(no 'properties' key) — incompatible with strict mode."
                    )

    async def test_structured_output_tools_have_output_schema(self, tools: list[Any]) -> None:
        """Tools with Pydantic return types must have an output schema defined."""
        # Tools that return dynamic dicts or ToolResult (no Pydantic model) — intentionally unstructured.
        unstructured_tools = {"add_object", "update_object", "duplicate_object", "view_geometry", "view_schedules"}

        for tool in tools:
            if tool.name in unstructured_tools:
                assert tool.outputSchema is None, f"Tool '{tool.name}' should be unstructured but has an output schema"
            else:
                assert tool.outputSchema is not None, (
                    f"Tool '{tool.name}' is missing an output schema — add a Pydantic return type"
                )
