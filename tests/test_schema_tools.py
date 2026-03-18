"""Tests for schema exploration tools."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from idfkit_mcp.tools.schema import _parse_version, register


def _make_server() -> FastMCP:
    mcp = FastMCP("test")
    register(mcp)
    return mcp


class TestParseVersion:
    def test_none(self) -> None:
        assert _parse_version(None) is None

    def test_valid(self) -> None:
        assert _parse_version("24.1.0") == (24, 1, 0)

    def test_invalid(self) -> None:
        with pytest.raises(ValueError, match=r"X\.Y\.Z"):
            _parse_version("24.1")


class TestListObjectTypes:
    def test_returns_groups(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["list_object_types"]
        result = tool.fn()
        assert result.total_types > 0
        assert result.groups

    def test_filter_by_group(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["list_object_types"]
        result = tool.fn(group="Thermal Zones and Surfaces")
        assert result.total_types > 0
        # All returned items should be in the filtered group
        assert "Thermal Zones and Surfaces" in result.groups

    def test_returns_error_for_bad_version(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["list_object_types"]
        with pytest.raises(ToolError):
            tool.fn(version="1.0.0")

    def test_truncated_when_over_limit(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["list_object_types"]
        result = tool.fn()
        assert result.truncated is True
        # Truncated response should have counts but no type lists
        for group_data in result.groups.values():
            assert group_data.count > 0
            assert group_data.types is None

    def test_not_truncated_with_group_filter(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["list_object_types"]
        result = tool.fn(group="Thermal Zones and Surfaces")
        # A single group should fit within the default limit
        assert result.truncated is False
        for group_data in result.groups.values():
            assert group_data.types is not None

    def test_high_limit_includes_types(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["list_object_types"]
        result = tool.fn(limit=10000)
        assert result.truncated is False
        for group_data in result.groups.values():
            assert group_data.types is not None


class TestDescribeObjectType:
    def test_zone(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["describe_object_type"]
        result = tool.fn(object_type="Zone")
        assert result.object_type == "Zone"
        assert result.has_name is True
        assert len(result.fields) > 0
        field_names = [f.name for f in result.fields]
        assert "x_origin" in field_names

    def test_unknown_type(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["describe_object_type"]
        with pytest.raises(ToolError):
            tool.fn(object_type="NonExistent")


class TestSearchSchema:
    def test_search_zone(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["search_schema"]
        result = tool.fn(query="Zone")
        assert result.count > 0
        types = [m.object_type for m in result.matches]
        assert "Zone" in types

    def test_search_no_results(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["search_schema"]
        result = tool.fn(query="xyznonexistent123")
        assert result.count == 0

    def test_limit_caps_results(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["search_schema"]
        result = tool.fn(query="Zone", limit=5)
        assert result.count <= 5
        assert len(result.matches) <= 5
        assert result.limit == 5

    def test_default_limit_in_response(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["search_schema"]
        result = tool.fn(query="Zone")
        assert result.limit == 50


class TestGetAvailableReferences:
    def test_without_model(self) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["get_available_references"]
        with pytest.raises(ToolError):
            tool.fn(object_type="BuildingSurface:Detailed", field_name="zone_name")

    def test_with_model(self, state_with_zones: object) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["get_available_references"]
        result = tool.fn(object_type="BuildingSurface:Detailed", field_name="zone_name")
        assert "Office" in result.available_names
        assert "Corridor" in result.available_names

    def test_non_reference_field(self, state_with_model: object) -> None:
        from idfkit_mcp.server import mcp

        tool = mcp._tool_manager._tools["get_available_references"]
        with pytest.raises(ToolError):
            tool.fn(object_type="Zone", field_name="x_origin")
