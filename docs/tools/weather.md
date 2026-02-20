# Weather Tools

Weather tools provide station discovery and EPW/DDY retrieval for simulation.

## `search_weather_stations`

Two query modes:

- Text mode: `query="Chicago"`
- Spatial mode: `latitude=..., longitude=...`

Optional filters:

- `country` (e.g., `USA`)
- `limit`

Returns station metadata, plus:

- relevance score for text search
- distance for spatial search

## `download_weather_file`

Two selection modes:

- direct by `wmo`
- best match by `query`

Downloads weather files and stores EPW path in server state for reuse by `run_simulation`.

Response includes:

- station metadata
- `epw_path`
- `ddy_path`

## Typical Flow

1. `search_weather_stations(query="Boston", country="USA")`
2. `download_weather_file(wmo="725090")` or by query
3. `run_simulation()` without explicit weather path
