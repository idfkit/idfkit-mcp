"""Tests for simulation tools."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

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

        output_path = tmp_path / "district_cooling.csv"
        result = await call_tool(
            client,
            "export_timeseries",
            {
                "variable_name": "DistrictCooling:Facility",
                "key_value": "*",
                "frequency": "Hourly",
                "environment": "annual",
                "output_path": str(output_path),
            },
        )

        assert result["variable_name"] == "DistrictCooling:Facility"
        assert result["key_value"] is None
        assert result["rows"] == 1
        assert output_path.exists()
