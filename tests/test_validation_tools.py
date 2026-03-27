"""Tests for validation tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.models import ValidationResult
from idfkit_mcp.state import ServerState
from tests.conftest import call_tool


class TestValidateModel:
    async def test_valid_model(self, client: object, state_with_model: ServerState) -> None:
        state_with_model.document.add("Zone", "TestZone")  # type: ignore[union-attr]
        result = await call_tool(client, "validate_model", model=ValidationResult)
        assert result.is_valid is True

    async def test_with_zones(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "validate_model", model=ValidationResult)
        assert result.is_valid is not None

    async def test_filter_by_type(self, client: object, state_with_zones: ServerState) -> None:
        result = await call_tool(client, "validate_model", {"object_types": ["Zone"]}, ValidationResult)
        assert result.is_valid is not None

    async def test_without_model(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "validate_model")
