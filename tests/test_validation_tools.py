"""Tests for validation tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.state import ServerState
from tests.tool_helpers import get_tool_sync


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return get_tool_sync(mcp, name)


class TestValidateModel:
    def test_valid_model(self, state_with_model: ServerState) -> None:
        state_with_model.document.add("Zone", "TestZone")  # type: ignore[union-attr]
        result = _tool("validate_model").fn()
        assert result.is_valid is True

    def test_with_zones(self, state_with_zones: ServerState) -> None:
        result = _tool("validate_model").fn()
        assert result.is_valid is not None

    def test_filter_by_type(self, state_with_zones: ServerState) -> None:
        result = _tool("validate_model").fn(object_types=["Zone"])
        assert result.is_valid is not None

    def test_without_model(self) -> None:
        with pytest.raises(ToolError):
            _tool("validate_model").fn()


class TestCheckReferences:
    def test_no_dangling(self, state_with_zones: ServerState) -> None:
        result = _tool("check_references").fn()
        # The surface references "Office" zone which exists
        # construction_name is empty so it shouldn't count as dangling
        assert result.dangling_count is not None

    def test_without_model(self) -> None:
        with pytest.raises(ToolError):
            _tool("check_references").fn()
