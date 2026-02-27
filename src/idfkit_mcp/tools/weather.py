"""Weather station search and download tools."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from mcp.server.fastmcp import FastMCP

from idfkit_mcp.errors import format_error
from idfkit_mcp.serializers import serialize_station
from idfkit_mcp.state import get_state


def _safe_tool(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Convert exceptions into MCP-friendly error dicts."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return format_error(e)

    return wrapper


def register(mcp: FastMCP) -> None:
    """Register weather tools on the MCP server."""
    mcp.tool()(search_weather_stations)
    mcp.tool()(download_weather_file)


@_safe_tool
def search_weather_stations(
    query: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    country: str | None = None,
    state: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search for weather stations by name/location or coordinates.

    Provide either a text query or latitude/longitude for spatial search.

    IMPORTANT: Keep query short (just the city name). Use country/state params
    to disambiguate. For example, use query="Boston", country="USA", state="MA"
    instead of query="Boston MA USA".

    Args:
        query: Short search text — just the city or airport name (e.g. "Boston", "O'Hare").
        latitude: Latitude for nearest-station search.
        longitude: Longitude for nearest-station search.
        country: Filter by country code (e.g. "USA").
        state: Filter by state/province code (e.g. "MA", "IL").
        limit: Maximum results (default 10).
    """
    from idfkit.weather import StationIndex

    index = StationIndex.load()

    if latitude is not None and longitude is not None:
        spatial_results = index.nearest(latitude, longitude, limit=limit)
        spatial_stations: list[dict[str, Any]] = []
        for r in spatial_results:
            if not _matches_filters(r.station, country, state):
                continue
            spatial_stations.append({
                **serialize_station(r.station),
                "distance_km": round(r.distance_km, 1),
            })
        return {
            "search_type": "spatial",
            "count": len(spatial_stations),
            "stations": spatial_stations[:limit],
        }

    if query is not None:
        search_results = index.search(query, limit=limit * 3)
        text_stations: list[dict[str, Any]] = []
        for r in search_results:
            if not _matches_filters(r.station, country, state):
                continue
            text_stations.append({
                **serialize_station(r.station),
                "score": round(r.score, 3),
                "match_field": r.match_field,
            })
            if len(text_stations) >= limit:
                break
        return {
            "search_type": "text",
            "query": query,
            "count": len(text_stations),
            "stations": text_stations,
        }

    return {"error": "Provide either 'query' for text search or 'latitude'/'longitude' for spatial search."}


def _matches_filters(station: Any, country: str | None, state: str | None) -> bool:
    """Check if a station matches the given country and state filters."""
    if country and station.country.upper() != country.upper():
        return False
    return not (state and station.state.upper() != state.upper())


@_safe_tool
def download_weather_file(
    wmo: str | None = None,
    query: str | None = None,
    country: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Download an EPW weather file for simulation.

    The downloaded file path is stored for reuse with run_simulation.

    IMPORTANT: Keep query short (just the city name). Use country/state params
    to disambiguate. For example, use query="Boston", country="USA", state="MA"
    instead of query="Boston MA USA TMYx".

    Args:
        wmo: WMO station number to download directly.
        query: Short search text — just the city or airport name (e.g. "Boston").
        country: Filter by country code (e.g. "USA").
        state: Filter by state/province code (e.g. "MA").
    """
    from idfkit.weather import StationIndex, WeatherDownloader

    index = StationIndex.load()

    if query is not None:
        results = index.search(query, limit=30)
        station = None
        for r in results:
            if not _matches_filters(r.station, country, state):
                continue
            station = r.station
            break
        if station is None:
            return {"error": f"No weather stations found for query '{query}'."}
    elif wmo is not None:
        results = index.search(wmo, limit=10)
        station = None
        for r in results:
            if r.station.wmo == wmo:
                station = r.station
                break
        if station is None:
            return {"error": f"No weather station found with WMO '{wmo}'."}
    else:
        return {"error": "Provide either 'wmo' or 'query' to identify the weather station."}

    downloader = WeatherDownloader()
    files = downloader.download(station)

    server_state = get_state()
    server_state.weather_file = files.epw

    return {
        "status": "downloaded",
        "station": serialize_station(station),
        "epw_path": str(files.epw),
        "ddy_path": str(files.ddy),
    }
