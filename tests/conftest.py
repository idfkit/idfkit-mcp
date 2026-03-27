"""Shared fixtures for idfkit-mcp tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from idfkit import new_document
from idfkit.simulation.result import SimulationResult

from idfkit_mcp.state import ServerState, get_state, reset_sessions


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset the session registry before each test."""
    reset_sessions()
    state = get_state()
    state.persistence_enabled = False


@pytest.fixture()
def state_with_model() -> ServerState:
    """Return server state with a new empty model loaded."""
    state = get_state()
    doc = new_document()
    state.document = doc
    state.schema = doc.schema
    return state


@pytest.fixture()
def state_with_zones() -> ServerState:
    """Return server state with a model containing zones and surfaces."""
    state = get_state()
    doc = new_document()
    state.document = doc
    state.schema = doc.schema

    doc.add("Zone", "Office")
    doc.add("Zone", "Corridor")
    doc.add(
        "BuildingSurface:Detailed",
        "Office_Wall",
        surface_type="Wall",
        construction_name="",
        zone_name="Office",
        outside_boundary_condition="Outdoors",
        sun_exposure="SunExposed",
        wind_exposure="WindExposed",
        validate=False,
    )
    return state


@pytest.fixture()
def state_with_singletons() -> ServerState:
    """Return server state with a model containing singleton objects.

    ``new_document()`` already creates default singletons (SimulationControl,
    GlobalGeometryRules, etc.), so we just use those.
    """
    state = get_state()
    doc = new_document()
    state.document = doc
    state.schema = doc.schema
    return state


@pytest.fixture()
def state_with_sql_only_simulation(tmp_path: Path) -> ServerState:
    """Return server state with simulation SQL populated and empty .rdd/.mdd files."""
    run_dir = tmp_path
    conn = sqlite3.connect(str(run_dir / "eplusout.sql"))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ReportDataDictionary ("
        "  ReportDataDictionaryIndex INTEGER PRIMARY KEY,"
        "  IsMeter INTEGER,"
        "  Type TEXT,"
        "  IndexGroup TEXT,"
        "  TimestepType TEXT,"
        "  KeyValue TEXT,"
        "  Name TEXT,"
        "  ReportingFrequency TEXT,"
        "  ScheduleName TEXT,"
        "  Units TEXT"
        ")"
    )
    cur.execute(
        "INSERT INTO ReportDataDictionary VALUES "
        "(1, 0, 'Zone', 'Facility', 'Zone', 'OFFICE', 'Zone Mean Air Temperature', 'Hourly', '', 'C'),"
        "(2, 0, 'Zone', 'Facility', 'Zone', '*', 'Site Outdoor Air Drybulb Temperature', 'Hourly', '', 'C'),"
        "(3, 1, 'Zone', 'Facility', 'Zone', '', 'Electricity:Facility', 'Hourly', '', 'J')"
    )
    conn.commit()
    conn.close()

    (run_dir / "eplusout.rdd").write_text("", encoding="latin-1")
    (run_dir / "eplusout.mdd").write_text("", encoding="latin-1")

    state = get_state()
    state.simulation_result = SimulationResult(
        run_dir=run_dir,
        success=True,
        exit_code=0,
        stdout="",
        stderr="",
        runtime_seconds=0.1,
    )
    return state
