"""Tests for server creation and CLI argument parsing."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from idfkit_mcp.server import _parse_args, mcp
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
            "get_model_summary",
            "list_objects",
            "get_object",
            "search_objects",
            "get_references",
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
            "check_references",
            "run_simulation",
            "get_results_summary",
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


class TestParseArgs:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IDFKIT_MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("IDFKIT_MCP_HOST", raising=False)
        monkeypatch.delenv("IDFKIT_MCP_PORT", raising=False)
        monkeypatch.delenv("IDFKIT_MCP_MOUNT_PATH", raising=False)
        args = _parse_args([])
        assert args.transport == "stdio"
        assert args.host == "127.0.0.1"
        assert args.port == 8000
        assert args.mount_path is None

    def test_cli_overrides(self) -> None:
        args = _parse_args([
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--port",
            "9090",
            "--mount-path",
            "/mcp",
        ])
        assert args.transport == "http"
        assert args.host == "0.0.0.0"
        assert args.port == 9090
        assert args.mount_path == "/mcp"

    def test_env_var_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IDFKIT_MCP_TRANSPORT", "sse")
        monkeypatch.setenv("IDFKIT_MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("IDFKIT_MCP_PORT", "3000")
        monkeypatch.setenv("IDFKIT_MCP_MOUNT_PATH", "/api")
        args = _parse_args([])
        assert args.transport == "sse"
        assert args.host == "0.0.0.0"
        assert args.port == 3000
        assert args.mount_path == "/api"

    def test_cli_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IDFKIT_MCP_TRANSPORT", "sse")
        args = _parse_args(["--transport", "http"])
        assert args.transport == "http"

    def test_streamable_http_is_mapped_to_http(self) -> None:
        args = _parse_args(["--transport", "streamable-http"])
        assert args.transport == "http"

    def test_invalid_transport_rejected(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(["--transport", "invalid"])


class TestToolSchemas:
    """Verify that all tool schemas are well-formed for broad client compatibility."""

    @pytest.fixture()
    async def tools(self, client: Client) -> list[Any]:
        return await client.list_tools()

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
        # Tools that return dynamic dicts (no Pydantic model) — intentionally unstructured.
        unstructured_tools = {"add_object", "update_object", "duplicate_object", "get_object"}

        for tool in tools:
            if tool.name in unstructured_tools:
                assert tool.outputSchema is None, f"Tool '{tool.name}' should be unstructured but has an output schema"
            else:
                assert tool.outputSchema is not None, (
                    f"Tool '{tool.name}' is missing an output schema — add a Pydantic return type"
                )
