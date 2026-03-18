"""Tests for weather tools."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp.exceptions import ToolError


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return mcp._tool_manager._tools[name]


class TestSearchWeatherStations:
    def test_station_index_cached(self) -> None:
        from idfkit_mcp.state import get_state

        state = get_state()
        assert state.station_index is None
        _tool("search_weather_stations").fn(query="Chicago")
        assert state.station_index is not None
        cached = state.station_index
        _tool("search_weather_stations").fn(query="Boston")
        assert state.station_index is cached

    def test_text_search(self) -> None:
        result = _tool("search_weather_stations").fn(query="Chicago")
        assert result.search_type == "text"
        assert result.count > 0

    def test_spatial_search(self) -> None:
        result = _tool("search_weather_stations").fn(latitude=41.88, longitude=-87.63)
        assert result.search_type == "spatial"
        assert result.count > 0

    def test_no_params(self) -> None:
        with pytest.raises(ToolError):
            _tool("search_weather_stations").fn()

    def test_country_filter(self) -> None:
        result = _tool("search_weather_stations").fn(query="Chicago", country="USA")
        assert result.count > 0
        for station in result.stations:
            assert station["country"].upper() == "USA"


class TestDownloadWeatherFile:
    def test_no_params(self) -> None:
        with pytest.raises(ToolError):
            _tool("download_weather_file").fn()

    def test_query_no_match(self) -> None:
        with pytest.raises(ToolError):
            _tool("download_weather_file").fn(query="zzz_nonexistent_place_xyz")

    def test_wmo_no_match(self) -> None:
        with pytest.raises(ToolError):
            _tool("download_weather_file").fn(wmo="0000000")
