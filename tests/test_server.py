"""Tests for server creation and CLI argument parsing."""

from __future__ import annotations

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
