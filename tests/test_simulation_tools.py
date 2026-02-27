"""Tests for simulation tools."""

from __future__ import annotations

from unittest.mock import patch

from idfkit_mcp.state import ServerState


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return mcp._tool_manager._tools[name]


class TestRunSimulation:
    def test_no_model(self) -> None:
        result = _tool("run_simulation").fn()
        assert "error" in result

    def test_no_weather(self, state_with_model: ServerState) -> None:
        result = _tool("run_simulation").fn()
        assert "error" in result

    def test_output_directory_accepted(self, state_with_model: ServerState) -> None:
        """output_directory param is accepted (fails for other reasons, not TypeError)."""
        result = _tool("run_simulation").fn(output_directory="/tmp/test_out")  # noqa: S108
        # Should fail because no weather file, not because of bad param
        assert "error" in result
        assert "weather" in result["error"].lower() or "No weather" in result["error"]

    def test_defaults_to_latest_energyplus(self, state_with_model: ServerState) -> None:
        """run_simulation lets find_energyplus pick the best version when not specified."""
        with patch("idfkit.simulation.config.find_energyplus") as mock_find:
            mock_find.side_effect = RuntimeError("test stop")
            result = _tool("run_simulation").fn(design_day=True)
            assert "error" in result
            mock_find.assert_called_once_with(path=None, version=None)


class TestGetResultsSummary:
    def test_no_simulation(self) -> None:
        result = _tool("get_results_summary").fn()
        assert "error" in result


class TestListOutputVariables:
    def test_no_simulation(self) -> None:
        result = _tool("list_output_variables").fn()
        assert "error" in result


class TestQueryTimeseries:
    def test_no_simulation(self) -> None:
        result = _tool("query_timeseries").fn(variable_name="Zone Mean Air Temperature")
        assert "error" in result


class TestExportTimeseries:
    def test_no_simulation(self) -> None:
        result = _tool("export_timeseries").fn(variable_name="Zone Mean Air Temperature")
        assert "error" in result
