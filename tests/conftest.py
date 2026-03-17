"""Shared fixtures for idfkit-mcp tests."""

from __future__ import annotations

import pytest
from idfkit import new_document

from idfkit_mcp.state import ServerState, get_state


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset the module-level server state before each test."""
    state = get_state()
    state.document = None
    state.schema = None
    state.file_path = None
    state.simulation_result = None
    state.weather_file = None
    state.station_index = None


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
