"""Tests for simulation tools."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError
from idfkit.simulation.result import SimulationResult

from idfkit_mcp.models import ListOutputVariablesResult
from idfkit_mcp.state import ServerState
from tests.conftest import call_tool


class TestRunSimulation:
    async def test_no_model(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "run_simulation")

    async def test_no_weather(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "run_simulation")

    async def test_output_directory_accepted(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError, match=r"weather|No weather"):
            await call_tool(client, "run_simulation", {"output_directory": "/tmp/test_out"})  # noqa: S108

    async def test_defaults_to_latest_energyplus(self, client: object, state_with_model: ServerState) -> None:
        with patch("idfkit.simulation.config.find_energyplus") as mock_find:
            mock_find.side_effect = RuntimeError("test stop")
            with pytest.raises(ToolError):
                await call_tool(client, "run_simulation", {"design_day": True})
            mock_find.assert_called_once_with(path=None, version=None)


class TestListOutputVariables:
    async def test_no_simulation(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "list_output_variables")

    async def test_falls_back_to_sql_when_rdd_and_mdd_are_empty(
        self, client: object, state_with_sql_only_simulation: ServerState
    ) -> None:
        result = await call_tool(client, "list_output_variables", model=ListOutputVariablesResult)
        assert result.total_available == 3
        assert result.returned == 3
        assert {item.name for item in result.variables} == {
            "Zone Mean Air Temperature",
            "Site Outdoor Air Drybulb Temperature",
            "Electricity:Facility",
        }

    async def test_sql_fallback_respects_search(
        self, client: object, state_with_sql_only_simulation: ServerState
    ) -> None:
        result = await call_tool(client, "list_output_variables", {"search": "Drybulb"}, ListOutputVariablesResult)
        assert result.total_available == 3
        assert result.returned == 1
        assert result.variables[0].name == "Site Outdoor Air Drybulb Temperature"

    async def test_search_invalid_regex_raises(
        self, client: object, state_with_sql_only_simulation: ServerState
    ) -> None:
        """An invalid regex pattern is rejected with a clear error."""
        with pytest.raises(ToolError, match="Invalid regex"):
            await call_tool(client, "list_output_variables", {"search": "[invalid"})

    async def test_search_regex_works(self, client: object, state_with_sql_only_simulation: ServerState) -> None:
        """Valid regex patterns still work as expected."""
        result = await call_tool(
            client, "list_output_variables", {"search": "^Zone.*Temperature$"}, ListOutputVariablesResult
        )
        assert result.returned == 1
        assert result.variables[0].name == "Zone Mean Air Temperature"

    async def test_sql_fallback_ignores_thread_bound_cached_sql(
        self, client: object, state_with_sql_only_simulation: ServerState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise_thread_error(_self: SimulationResult) -> object:
            msg = "SQLite objects created in a thread can only be used in that same thread"
            raise RuntimeError(msg)

        monkeypatch.setattr(SimulationResult, "sql", property(_raise_thread_error))

        result = await call_tool(client, "list_output_variables", model=ListOutputVariablesResult)
        assert result.total_available == 3
        assert result.returned == 3


class TestQueryTimeseries:
    async def test_no_simulation(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "query_timeseries", {"variable_name": "Zone Mean Air Temperature"})

    async def test_meter_with_null_key_value(
        self, client: object, state_with_sql_only_simulation: ServerState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ts = SimpleNamespace(
            variable_name="DistrictCooling:Facility",
            key_value=None,
            units="J",
            frequency="Hourly",
            timestamps=[datetime(2013, 1, 1, 1, 0, 0)],
            values=[123.0],
        )
        monkeypatch.setattr("idfkit.simulation.parsers.sql.SQLResult.get_timeseries", lambda *_args, **_kwargs: fake_ts)

        result = await call_tool(
            client,
            "query_timeseries",
            {
                "variable_name": "DistrictCooling:Facility",
                "key_value": "*",
                "frequency": "Hourly",
                "environment": "annual",
            },
        )

        assert result["variable_name"] == "DistrictCooling:Facility"
        assert result["key_value"] is None
        assert result["returned"] == 1


class TestExportTimeseries:
    async def test_no_simulation(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "export_timeseries", {"variable_name": "Zone Mean Air Temperature"})

    async def test_meter_with_null_key_value(
        self,
        client: object,
        state_with_sql_only_simulation: ServerState,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        fake_ts = SimpleNamespace(
            variable_name="DistrictCooling:Facility",
            key_value=None,
            units="J",
            frequency="Hourly",
            timestamps=[datetime(2013, 1, 1, 1, 0, 0)],
            values=[456.0],
        )
        monkeypatch.setattr("idfkit.simulation.parsers.sql.SQLResult.get_timeseries", lambda *_args, **_kwargs: fake_ts)

        monkeypatch.chdir(tmp_path)
        result = await call_tool(
            client,
            "export_timeseries",
            {
                "variable_name": "DistrictCooling:Facility",
                "key_value": "*",
                "frequency": "Hourly",
                "environment": "annual",
                "output_path": "district_cooling.csv",
            },
        )

        assert result["variable_name"] == "DistrictCooling:Facility"
        assert result["key_value"] is None
        assert result["rows"] == 1
        assert (tmp_path / "district_cooling.csv").exists()

    async def test_export_rejects_path_outside_cwd(
        self,
        client: object,
        state_with_sql_only_simulation: ServerState,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ToolError, match="allowed directory"):
            await call_tool(
                client,
                "export_timeseries",
                {"variable_name": "Test", "output_path": "/tmp/evil.csv"},  # noqa: S108
            )
