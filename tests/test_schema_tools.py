"""Tests for schema exploration tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.models import (
    AvailableReferencesResult,
    DescribeObjectTypeResult,
    ListObjectTypesResult,
    SearchSchemaResult,
)
from idfkit_mcp.tools.schema import _parse_version
from tests.conftest import call_tool


class TestParseVersion:
    def test_none(self) -> None:
        assert _parse_version(None) is None

    def test_valid(self) -> None:
        assert _parse_version("24.1.0") == (24, 1, 0)

    def test_invalid(self) -> None:
        with pytest.raises(ValueError, match=r"X\.Y\.Z"):
            _parse_version("24.1")


class TestListObjectTypes:
    async def test_returns_groups(self, client: object) -> None:
        result = await call_tool(client, "list_object_types", model=ListObjectTypesResult)
        assert result.total_types > 0
        assert result.groups

    async def test_filter_by_group(self, client: object) -> None:
        result = await call_tool(
            client, "list_object_types", {"group": "Thermal Zones and Surfaces"}, ListObjectTypesResult
        )
        assert result.total_types > 0
        assert "Thermal Zones and Surfaces" in result.groups

    async def test_returns_error_for_bad_version(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "list_object_types", {"version": "1.0.0"})

    async def test_truncated_when_over_limit(self, client: object) -> None:
        result = await call_tool(client, "list_object_types", model=ListObjectTypesResult)
        assert result.truncated is True
        for group_data in result.groups.values():
            assert group_data.count > 0
            assert group_data.types is None

    async def test_not_truncated_with_group_filter(self, client: object) -> None:
        result = await call_tool(
            client, "list_object_types", {"group": "Thermal Zones and Surfaces"}, ListObjectTypesResult
        )
        assert result.truncated is False
        for group_data in result.groups.values():
            assert group_data.types is not None

    async def test_high_limit_is_capped(self, client: object) -> None:
        result = await call_tool(client, "list_object_types", {"limit": 10000}, ListObjectTypesResult)
        assert result.total_types > 100
        assert result.truncated is True


class TestDescribeObjectType:
    async def test_zone(self, client: object) -> None:
        result = await call_tool(client, "describe_object_type", {"object_type": "Zone"}, DescribeObjectTypeResult)
        assert result.object_type == "Zone"
        assert result.has_name is True
        assert len(result.fields) > 0
        field_names = [f.name for f in result.fields]
        assert "x_origin" in field_names

    async def test_unknown_type(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "describe_object_type", {"object_type": "NonExistent"})

    async def test_extensible_group_for_building_surface(self, client: object) -> None:
        result = await call_tool(
            client,
            "describe_object_type",
            {"object_type": "BuildingSurface:Detailed"},
            DescribeObjectTypeResult,
        )
        assert result.is_extensible is True
        # Inner extensible fields should be lifted out of the flat fields list.
        flat_names = [f.name for f in result.fields]
        assert "vertex_x_coordinate" not in flat_names
        assert "surface_type" in flat_names
        assert result.extensible_group is not None
        assert result.extensible_group.key == "vertices"
        item_names = [f.name for f in result.extensible_group.item_fields]
        assert item_names == ["vertex_x_coordinate", "vertex_y_coordinate", "vertex_z_coordinate"]
        assert "vertices" in result.extensible_group.example
        assert len(result.extensible_group.example["vertices"]) >= 1

    async def test_extensible_group_absent_for_non_extensible(self, client: object) -> None:
        result = await call_tool(client, "describe_object_type", {"object_type": "Zone"}, DescribeObjectTypeResult)
        assert result.is_extensible is False
        assert result.extensible_group is None

    async def test_extensible_example_uses_enum_first_value(self, client: object) -> None:
        """Item fields with enum_values should seed the example with a real value."""
        result = await call_tool(
            client,
            "describe_object_type",
            {"object_type": "AirLoopHVAC:SupplyPath"},
            DescribeObjectTypeResult,
        )
        assert result.extensible_group is not None
        wrapper_key = result.extensible_group.key
        first_item = result.extensible_group.example[wrapper_key][0]
        enum_field = next(f for f in result.extensible_group.item_fields if f.name == "component_object_type")
        assert enum_field.enum_values
        assert first_item["component_object_type"] in enum_field.enum_values
        assert first_item["component_object_type"] != ""

    async def test_extensible_example_uses_placeholder_for_object_list(self, client: object) -> None:
        """Object-list (reference) item fields should get a clearly-placeholder string."""
        result = await call_tool(
            client,
            "describe_object_type",
            {"object_type": "Branch"},
            DescribeObjectTypeResult,
        )
        assert result.extensible_group is not None
        wrapper_key = result.extensible_group.key
        first_item = result.extensible_group.example[wrapper_key][0]
        # component_object_type is an object-list reference -> angle-bracketed placeholder
        value = first_item["component_object_type"]
        assert value.startswith("<") and value.endswith(">")
        assert value != ""


class TestSearchSchema:
    async def test_search_zone(self, client: object) -> None:
        result = await call_tool(client, "search_schema", {"query": "Zone", "limit": 30}, SearchSchemaResult)
        assert result.count > 0
        types = [m.object_type for m in result.matches]
        assert "Zone" in types

    async def test_search_no_results(self, client: object) -> None:
        result = await call_tool(client, "search_schema", {"query": "xyznonexistent123"}, SearchSchemaResult)
        assert result.count == 0

    async def test_limit_caps_results(self, client: object) -> None:
        result = await call_tool(client, "search_schema", {"query": "Zone", "limit": 5}, SearchSchemaResult)
        assert result.count <= 5
        assert len(result.matches) <= 5
        assert result.limit == 5

    async def test_default_limit_in_response(self, client: object) -> None:
        result = await call_tool(client, "search_schema", {"query": "Zone"}, SearchSchemaResult)
        assert result.limit == 10


class TestGetAvailableReferences:
    async def test_without_model(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(
                client,
                "get_available_references",
                {"object_type": "BuildingSurface:Detailed", "field_name": "zone_name"},
            )

    async def test_with_model(self, client: object, state_with_zones: object) -> None:
        result = await call_tool(
            client,
            "get_available_references",
            {"object_type": "BuildingSurface:Detailed", "field_name": "zone_name"},
            AvailableReferencesResult,
        )
        assert "Office" in result.available_names
        assert "Corridor" in result.available_names

    async def test_non_reference_field(self, client: object, state_with_model: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "get_available_references", {"object_type": "Zone", "field_name": "x_origin"})
