"""Tests for simulation tools."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.state import ServerState
from tests.tool_helpers import get_tool_async, get_tool_sync


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return get_tool_sync(mcp, name)


async def _async_tool(name: str):
    from idfkit_mcp.server import mcp

    return await get_tool_async(mcp, name)


class TestRunSimulation:
    async def test_no_model(self) -> None:
        with pytest.raises(ToolError):
            await (await _async_tool("run_simulation")).fn()

    async def test_no_weather(self, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            await (await _async_tool("run_simulation")).fn()

    async def test_output_directory_accepted(self, state_with_model: ServerState) -> None:
        """output_directory param is accepted (fails for other reasons, not TypeError)."""
        with pytest.raises(ToolError, match=r"weather|No weather"):
            await (await _async_tool("run_simulation")).fn(output_directory="/tmp/test_out")  # noqa: S108

    async def test_defaults_to_latest_energyplus(self, state_with_model: ServerState) -> None:
        """run_simulation lets find_energyplus pick the best version when not specified."""
        with patch("idfkit.simulation.config.find_energyplus") as mock_find:
            mock_find.side_effect = RuntimeError("test stop")
            with pytest.raises(ToolError):
                await (await _async_tool("run_simulation")).fn(design_day=True)
            mock_find.assert_called_once_with(path=None, version=None)


class TestGetResultsSummary:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("get_results_summary").fn()


class TestListOutputVariables:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("list_output_variables").fn()

    def test_falls_back_to_sql_when_rdd_and_mdd_are_empty(self, state_with_sql_only_simulation: ServerState) -> None:
        result = _tool("list_output_variables").fn()
        assert result.total_available == 3
        assert result.returned == 3
        assert {item.name for item in result.variables} == {
            "Zone Mean Air Temperature",
            "Site Outdoor Air Drybulb Temperature",
            "Electricity:Facility",
        }

    def test_sql_fallback_respects_search(self, state_with_sql_only_simulation: ServerState) -> None:
        result = _tool("list_output_variables").fn(search="Drybulb")
        assert result.total_available == 3
        assert result.returned == 1
        assert result.variables[0].name == "Site Outdoor Air Drybulb Temperature"


class TestQueryTimeseries:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("query_timeseries").fn(variable_name="Zone Mean Air Temperature")


class TestExportTimeseries:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("export_timeseries").fn(variable_name="Zone Mean Air Temperature")
