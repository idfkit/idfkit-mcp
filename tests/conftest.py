"""Shared fixtures for idfkit-mcp tests."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from idfkit import new_document
from idfkit.simulation.result import SimulationResult
from pydantic import BaseModel

from idfkit_mcp.state import ServerState, get_state, reset_sessions

T = TypeVar("T", bound=BaseModel)


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset the session registry before each test."""
    reset_sessions()
    state = get_state()
    state.persistence_enabled = False


@pytest.fixture()
async def client() -> AsyncIterator[Client[FastMCPTransport]]:
    """Yield an in-memory FastMCP client bound to the test server."""
    from idfkit_mcp.server import mcp

    async with Client(transport=mcp) as test_client:
        yield test_client


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


async def call_tool(
    client: Client[FastMCPTransport],
    name: str,
    arguments: dict[str, Any] | None = None,
    model: type[T] | None = None,
) -> T | dict[str, Any] | list[Any] | str:
    """Call a tool over the MCP protocol and decode the result payload."""
    result = await client.call_tool(name, arguments or {})
    data: Any = result.structured_content

    if data is None:
        text_parts = [part.text for part in result.content if hasattr(part, "text")]
        if len(text_parts) == 1:
            try:
                data = json.loads(text_parts[0])
            except json.JSONDecodeError:
                data = text_parts[0]
        else:
            data = text_parts

    if model is None:
        return data
    if isinstance(data, str):
        return model.model_validate_json(data)
    return model.model_validate(data)


async def read_resource_json(client: Client, uri: str) -> dict[str, Any]:
    """Read a JSON resource over MCP and decode the first text part."""
    contents = await client.read_resource(uri)
    if not contents:
        msg = f"Resource returned no content: {uri}"
        raise AssertionError(msg)
    return json.loads(contents[0].text)
