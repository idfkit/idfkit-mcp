"""Tests for simulation tools."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from idfkit_mcp.state import ServerState


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return mcp._tool_manager._tools[name]


class TestRunSimulation:
    def test_no_model(self) -> None:
        with pytest.raises(ToolError):
            _tool("run_simulation").fn()

    def test_no_weather(self, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            _tool("run_simulation").fn()

    def test_output_directory_accepted(self, state_with_model: ServerState) -> None:
        """output_directory param is accepted (fails for other reasons, not TypeError)."""
        with pytest.raises(ToolError, match=r"weather|No weather"):
            _tool("run_simulation").fn(output_directory="/tmp/test_out")  # noqa: S108

    def test_defaults_to_latest_energyplus(self, state_with_model: ServerState) -> None:
        """run_simulation lets find_energyplus pick the best version when not specified."""
        with patch("idfkit.simulation.config.find_energyplus") as mock_find:
            mock_find.side_effect = RuntimeError("test stop")
            with pytest.raises(ToolError):
                _tool("run_simulation").fn(design_day=True)
            mock_find.assert_called_once_with(path=None, version=None)


class TestGetResultsSummary:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("get_results_summary").fn()


class TestListOutputVariables:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("list_output_variables").fn()


class TestQueryTimeseries:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("query_timeseries").fn(variable_name="Zone Mean Air Temperature")


class TestExportTimeseries:
    def test_no_simulation(self) -> None:
        with pytest.raises(ToolError):
            _tool("export_timeseries").fn(variable_name="Zone Mean Air Temperature")
