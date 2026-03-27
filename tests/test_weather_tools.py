"""Tests for weather tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.models import SearchWeatherStationsResult
from tests.conftest import call_tool


class TestSearchWeatherStations:
    async def test_station_index_cached(self, client: object) -> None:
        from idfkit_mcp.state import get_state

        state = get_state()
        assert state.station_index is None
        await call_tool(client, "search_weather_stations", {"query": "Chicago"}, SearchWeatherStationsResult)
        assert state.station_index is not None
        cached = state.station_index
        await call_tool(client, "search_weather_stations", {"query": "Boston"}, SearchWeatherStationsResult)
        assert state.station_index is cached

    async def test_text_search(self, client: object) -> None:
        result = await call_tool(client, "search_weather_stations", {"query": "Chicago"}, SearchWeatherStationsResult)
        assert result.search_type == "text"
        assert result.count > 0

    async def test_spatial_search(self, client: object) -> None:
        result = await call_tool(
            client, "search_weather_stations", {"latitude": 41.88, "longitude": -87.63}, SearchWeatherStationsResult
        )
        assert result.search_type == "spatial"
        assert result.count > 0

    async def test_no_params(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "search_weather_stations")

    async def test_country_filter(self, client: object) -> None:
        result = await call_tool(
            client, "search_weather_stations", {"query": "Chicago", "country": "USA"}, SearchWeatherStationsResult
        )
        assert result.count > 0
        for station in result.stations:
            assert station["country"].upper() == "USA"


class TestStationModelValidation:
    """Ensure serialize_station output validates against WeatherStationModel."""

    def test_station_dict_matches_model(self) -> None:
        from idfkit_mcp.models import WeatherStationModel
        from idfkit_mcp.serializers import serialize_station
        from idfkit_mcp.state import get_state

        index = get_state().get_or_load_station_index()
        # Pick the first station from a known search
        results = index.search("Chicago", limit=1)
        assert results, "Expected at least one station for 'Chicago'"
        station_dict = serialize_station(results[0].station)
        # This will raise ValidationError if fields don't match
        model = WeatherStationModel.model_validate(station_dict)
        assert model.wmo
        assert model.city
        assert model.country


class TestDownloadWeatherFile:
    async def test_no_params(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "download_weather_file")

    async def test_query_no_match(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "download_weather_file", {"query": "zzz_nonexistent_place_xyz"})

    async def test_wmo_no_match(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "download_weather_file", {"wmo": "0000000"})
