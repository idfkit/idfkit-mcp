"""Tests for the analyze_peak_loads tool."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from idfkit.simulation.result import SimulationResult

from idfkit_mcp.models import PeakLoadAnalysisResult
from idfkit_mcp.state import ServerState, get_state
from tests.conftest import call_tool
from tests.linked_runs import install_run

_COOLING_TABLE = "Peak Cooling Sensible Heat Gain Components"
_HEATING_TABLE = "Peak Heating Sensible Heat Gain Components"

Row = tuple[str, str, str, str, str]
"""(ReportName, TableName, RowName, ColumnName, Value)."""


def _zone_summary_rows() -> list[Row]:
    report, table = "InputVerificationandResultsSummary", "Zone Summary"
    return [
        (report, table, "OFFICE", "Area", "100.00"),
        (report, table, "OFFICE", "Multipliers", "1.00"),
        (report, table, "OFFICE", "Part of Total Floor Area", "Yes"),
        (report, table, "Total", "Area", "100.00"),
    ]


def _sizing_rows() -> list[Row]:
    report, table = "HVACSizingSummary", "Zone Sensible Cooling"
    return [
        (report, table, "OFFICE", "Calculated Design Load", "2649.20"),
        (report, table, "OFFICE", "User Design Load", "2649.20"),
        (report, table, "OFFICE", "Design Day Name", "SUMMER DESIGN DAY"),
        (report, table, "OFFICE", "Date/Time Of Peak {TIMESTAMP}", "7/21 15:45:00"),
    ]


def _sensible_gain_rows(table: str, timestamp: str, value: str) -> list[Row]:
    report = "SensibleHeatGainSummary"
    column = (
        "People Sensible Heat Addition"
        if table == _COOLING_TABLE
        else "Opaque Surface Conduction and Other Heat Removal"
    )
    rows: list[Row] = []
    for row_name in ("OFFICE", "Total Facility"):
        rows.append((report, table, row_name, "Time of Peak {TIMESTAMP}", timestamp))
        rows.append((report, table, row_name, column, value))
    return rows


def _install_simulation(run_dir: Path, rows: list[Row]) -> ServerState:
    conn = sqlite3.connect(str(run_dir / "eplusout.sql"))
    conn.execute(
        "CREATE TABLE TabularDataWithStrings ("
        "  ReportName TEXT, ReportForString TEXT, TableName TEXT, RowName TEXT,"
        "  ColumnName TEXT, Units TEXT, Value TEXT)"
    )
    conn.executemany(
        "INSERT INTO TabularDataWithStrings VALUES (?, 'Entire Facility', ?, ?, ?, '', ?)",
        rows,
    )
    conn.commit()
    conn.close()

    state = get_state()
    state.simulation_result = SimulationResult(
        run_dir=run_dir, success=True, exit_code=0, stdout="", stderr="", runtime_seconds=0.1
    )
    return state


@pytest.fixture()
def design_day_only_simulation(tmp_path: Path) -> ServerState:
    """SQL output shaped like a design-day-only run: the sensible gain summary records no peak."""
    rows = _zone_summary_rows() + _sizing_rows()
    rows += _sensible_gain_rows(_COOLING_TABLE, "-", "0.00")
    rows += _sensible_gain_rows(_HEATING_TABLE, "-", "0.00")
    return _install_simulation(tmp_path, rows)


@pytest.fixture()
def weather_file_simulation(tmp_path: Path) -> ServerState:
    """SQL output shaped like a weather-file run with recorded peaks."""
    rows = _zone_summary_rows() + _sizing_rows()
    rows += _sensible_gain_rows(_COOLING_TABLE, "21-JUL-15:00", "4000.00")
    rows += _sensible_gain_rows(_HEATING_TABLE, "21-JAN-06:00", "-3000.00")
    return _install_simulation(tmp_path, rows)


class TestAnalyzePeakLoads:
    async def test_design_day_run_reports_peaks_unavailable(
        self, client: object, design_day_only_simulation: ServerState
    ) -> None:
        result = await call_tool(client, "analyze_peak_loads", model=PeakLoadAnalysisResult)

        for summary in (result.cooling, result.heating):
            assert summary.available is False
            assert summary.peak_w is None
            assert summary.peak_w_per_m2 is None
            assert summary.zones == []
            assert summary.unavailable_reason is not None
            assert "weather-file run periods" in summary.unavailable_reason

        assert result.sizing_cooling[0].user_load_w == pytest.approx(2649.2)
        assert not any("unusually low" in flag for flag in result.flags)
        assert any(flag.startswith("Cooling peak decomposition unavailable") for flag in result.flags)
        assert any(flag.startswith("Heating peak decomposition unavailable") for flag in result.flags)

    async def test_weather_file_run_reports_peaks(self, client: object, weather_file_simulation: ServerState) -> None:
        result = await call_tool(client, "analyze_peak_loads", model=PeakLoadAnalysisResult)

        assert result.cooling.available is True
        assert result.cooling.unavailable_reason is None
        assert result.cooling.peak_w == pytest.approx(4000.0)
        assert result.cooling.peak_w_per_m2 == pytest.approx(40.0)
        assert result.cooling.peak_timestamp == "21-JUL-15:00"
        assert [z.zone_name for z in result.cooling.zones] == ["OFFICE"]
        assert not any("unavailable" in flag for flag in result.flags)


class TestPeakLoadObjects:
    """Zone rows gain ``object`` and flags gain ``affected_objects`` (via ``flag_details``), changing no field (T090)."""

    async def test_zone_rows_carry_the_model_zone(self, client: object, tmp_path: Path) -> None:
        install_run("MultiStory", tmp_path)
        result = await call_tool(client, "analyze_peak_loads", model=PeakLoadAnalysisResult)

        rows = {z.zone_name: z for z in result.cooling.zones}
        center = rows["MID CENTER ZONE"]  # EnergyPlus upper-cases report rows
        assert center.object is not None
        assert center.object.model_dump() == {"object_type": "Zone", "name": "Mid Center Zone"}
        assert center.multiplier == 32
        assert all(z.object is not None and z.object.object_type == "Zone" for z in result.cooling.zones)

    async def test_flag_details_follow_flags(self, client: object, tmp_path: Path) -> None:
        install_run("MultiStory", tmp_path)
        result = await call_tool(client, "analyze_peak_loads", model=PeakLoadAnalysisResult)

        assert [d.flag for d in result.flag_details] == result.flags
        (outlier,) = [d for d in result.flag_details if d.flag.startswith("Zone 'MID CENTER ZONE'")]
        assert [k.model_dump() for k in outlier.affected_objects] == [
            {"object_type": "Zone", "name": "Mid Center Zone"}
        ]
        facility = [d for d in result.flag_details if not d.flag.startswith("Zone '")]
        assert all(d.affected_objects == [] for d in facility)

    async def test_existing_fields_unchanged(self, client: object, tmp_path: Path) -> None:
        """Without a model the zone objects are unknown; every other field is the same."""
        state = install_run("MultiStory", tmp_path)
        with_model = await call_tool(client, "analyze_peak_loads", model=PeakLoadAnalysisResult)
        state.document = None
        state._session_restored = True  # keep the session from reloading a model
        without = await call_tool(client, "analyze_peak_loads", model=PeakLoadAnalysisResult)

        assert all(z.object is None for z in without.cooling.zones + without.heating.zones)
        assert all(d.affected_objects == [] for d in without.flag_details)
        drop = {"cooling": {"zones": {"__all__": {"object"}}}, "heating": {"zones": {"__all__": {"object"}}}}
        assert with_model.model_dump(exclude={**drop, "flag_details": True}) == without.model_dump(
            exclude={**drop, "flag_details": True}
        )

    async def test_synthetic_run_without_model(self, client: object, weather_file_simulation: ServerState) -> None:
        result = await call_tool(client, "analyze_peak_loads", model=PeakLoadAnalysisResult)
        assert result.cooling.zones[0].object is None
        assert [d.flag for d in result.flag_details] == result.flags
