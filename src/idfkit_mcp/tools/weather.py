"""Weather station search and download tools."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from idfkit_mcp.app import mcp
from idfkit_mcp.models import DownloadWeatherFileResult, SearchWeatherStationsResult
from idfkit_mcp.serializers import serialize_station
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY_OPEN = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
_DOWNLOAD = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)


@mcp.tool(annotations=_READ_ONLY_OPEN)
def search_weather_stations(
    query: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    country: str | None = None,
    state: str | None = None,
    limit: int = 10,
) -> SearchWeatherStationsResult:
    """Search for weather stations by name/location or coordinates.

    Use this to find an EPW weather file for simulation. Provide either a text
    query or latitude/longitude for spatial search.

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
    index = get_state().get_or_load_station_index()

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
        logger.debug(
            "search_weather_stations: spatial lat=%s lon=%s found=%d", latitude, longitude, len(spatial_stations)
        )
        return SearchWeatherStationsResult(
            search_type="spatial",
            count=len(spatial_stations),
            stations=spatial_stations[:limit],
        )

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
        logger.debug("search_weather_stations: query=%r found=%d", query, len(text_stations))
        return SearchWeatherStationsResult(
            search_type="text",
            query=query,
            count=len(text_stations),
            stations=text_stations,
        )

    raise ToolError("Provide either 'query' for text search or 'latitude'/'longitude' for spatial search.")


def _matches_filters(station: Any, country: str | None, state: str | None) -> bool:
    """Check if a station matches the given country and state filters."""
    if country and station.country.upper() != country.upper():
        return False
    return not (state and station.state.upper() != state.upper())


@mcp.tool(annotations=_DOWNLOAD)
def download_weather_file(
    wmo: str | None = None,
    query: str | None = None,
    country: str | None = None,
    state: str | None = None,
) -> DownloadWeatherFileResult:
    """Download an EPW weather file for simulation.

    Use this to get a weather file before running a simulation. The downloaded
    file path is stored for reuse with run_simulation.

    IMPORTANT: Keep query short (just the city name). Use country/state params
    to disambiguate. For example, use query="Boston", country="USA", state="MA"
    instead of query="Boston MA USA TMYx".

    Args:
        wmo: WMO station number to download directly.
        query: Short search text — just the city or airport name (e.g. "Boston").
        country: Filter by country code (e.g. "USA").
        state: Filter by state/province code (e.g. "MA").
    """
    from idfkit.weather import WeatherDownloader

    index = get_state().get_or_load_station_index()

    if query is not None:
        results = index.search(query, limit=30)
        station = None
        for r in results:
            if not _matches_filters(r.station, country, state):
                continue
            station = r.station
            break
        if station is None:
            raise ToolError(f"No weather stations found for query '{query}'.")
    elif wmo is not None:
        results = index.search(wmo, limit=10)
        station = None
        for r in results:
            if r.station.wmo == wmo:
                station = r.station
                break
        if station is None:
            raise ToolError(f"No weather station found with WMO '{wmo}'.")
    else:
        raise ToolError("Provide either 'wmo' or 'query' to identify the weather station.")

    logger.info("Downloading weather file for station %s (%s)", station.wmo, station.city)
    downloader = WeatherDownloader()
    files = downloader.download(station)

    server_state = get_state()
    server_state.weather_file = files.epw
    server_state.save_session()
    logger.info("Downloaded weather file to %s", files.epw)

    return DownloadWeatherFileResult.model_validate({
        "status": "downloaded",
        "station": serialize_station(station),
        "epw_path": str(files.epw),
        "ddy_path": str(files.ddy),
    })


# Annotations are defined after functions to avoid forward-reference errors.
