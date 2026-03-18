"""Tests for server creation and CLI argument parsing."""

from __future__ import annotations

from typing import Any

import pytest

from idfkit_mcp.server import _parse_args, create_server


class TestCreateServer:
    def test_returns_fastmcp_instance(self) -> None:
        server = create_server()
        assert server.name == "idfkit"

    def test_registers_all_tool_groups(self) -> None:
        server = create_server()
        tool_names = set(server._tool_manager._tools)
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

    def test_custom_host_and_port(self) -> None:
        server = create_server(host="0.0.0.0", port=9090)
        assert server.settings.host == "0.0.0.0"
        assert server.settings.port == 9090


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
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "9090",
            "--mount-path",
            "/mcp",
        ])
        assert args.transport == "streamable-http"
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
        args = _parse_args(["--transport", "streamable-http"])
        assert args.transport == "streamable-http"

    def test_invalid_transport_rejected(self) -> None:
        with pytest.raises(SystemExit):
            _parse_args(["--transport", "invalid"])


class TestToolSchemas:
    """Verify that all tool schemas are well-formed for broad client compatibility."""

    @pytest.fixture()
    def tools(self) -> dict[str, Any]:
        server = create_server()
        return server._tool_manager._tools

    def test_all_tools_have_properties_key(self, tools: dict[str, Any]) -> None:
        """Every tool's inputSchema must include a 'properties' key.

        OpenAI's Agents SDK and other strict consumers require this key to be
        present, even for tools with no parameters (where it should be ``{}``).
        """
        for name, tool in tools.items():
            schema = tool.parameters
            assert "properties" in schema, f"Tool '{name}' inputSchema missing 'properties' key: {schema}"

    def test_all_tools_have_annotations(self, tools: dict[str, Any]) -> None:
        """Every tool should have ToolAnnotations set (readOnlyHint, etc.)."""
        for name, tool in tools.items():
            assert tool.annotations is not None, f"Tool '{name}' is missing annotations"

    def test_schemas_support_additional_properties_false(self, tools: dict[str, Any]) -> None:
        """Verify schemas can accept additionalProperties: false without conflict.

        OpenAI's ``convert_schemas_to_strict`` applies this constraint. Tools
        using open-ended ``dict[str, Any]`` parameters (e.g. add_object.fields,
        batch_add_objects.objects) are exempt since EnergyPlus field names are
        inherently dynamic.
        """
        # Tools with intentionally dynamic dict parameters that cannot be
        # constrained to a static schema.
        dynamic_schema_tools = {"add_object", "batch_add_objects", "update_object"}

        for name, tool in tools.items():
            if name in dynamic_schema_tools:
                continue
            schema = tool.parameters
            properties = schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                # Nested object schemas should not conflict with additionalProperties: false
                if prop_schema.get("type") == "object" and "properties" not in prop_schema:
                    pytest.fail(
                        f"Tool '{name}' param '{prop_name}' is an unstructured object "
                        f"(no 'properties' key) — incompatible with strict mode."
                    )

    def test_structured_output_tools_have_output_schema(self, tools: dict[str, Any]) -> None:
        """Tools with Pydantic return types must have an output schema defined."""
        # Tools that return dynamic dicts (no Pydantic model) — intentionally unstructured.
        unstructured_tools = {"add_object", "update_object", "duplicate_object", "get_object"}

        for name, tool in tools.items():
            if name in unstructured_tools:
                assert tool.fn_metadata.output_schema is None, (
                    f"Tool '{name}' should be unstructured but has an output schema"
                )
            else:
                assert tool.fn_metadata.output_schema is not None, (
                    f"Tool '{name}' is missing an output schema — add a Pydantic return type"
                )
