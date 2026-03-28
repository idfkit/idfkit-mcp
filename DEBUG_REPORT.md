# MCP Server Debug Report

**Date:** 2026-03-28
**Method:** In-process testing via FastMCP `Client` against all 28 registered tools, 4 resources, and 4 resource templates. Tested with EnergyPlus 25.2.0 (real simulations), OpenStudio 3.11.0, and bundled example files.

## Summary

| Category | Count |
|----------|-------|
| Tools tested | 28/28 |
| Resources tested | 8/8 (4 static + 4 templates) |
| Tests passed (non-simulation) | 79 |
| Tests passed (simulation) | 41 |
| Bugs found & fixed | 3 |

## Bugs Found & Fixed

### Bug 1: `search_schema` returns results for empty query

**Severity:** Low
**File:** `src/idfkit_mcp/tools/schema.py:129`
**Status:** Fixed

**Description:** Calling `search_schema(query="")` returns the first 10 object types instead of 0 results. Python's `in` operator treats the empty string as a substring of every string (`"" in "anything"` is `True`).

**Fix:** Added early return for empty/whitespace-only queries, matching `search_docs` behavior.

---

### Bug 2: `search_objects` returns results for empty query

**Severity:** Low
**File:** `src/idfkit_mcp/tools/read.py:183`
**Status:** Fixed

**Description:** Same root cause as Bug 1. `search_objects(query="")` matches every object in the model.

**Fix:** Added early return for empty/whitespace-only queries.

---

### Bug 3: `test_write_failure_does_not_raise` test fails when running as root

**Severity:** Low (test-only, not a server bug)
**File:** `tests/test_session_persistence.py:162-180`
**Status:** Fixed

**Description:** The test creates a read-only directory and expects writes to fail. Root bypasses filesystem permission checks, so the test fails in Docker/CI.

**Fix:** Added `@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permission checks")`.

---

## Simulation Testing (EnergyPlus 25.2.0)

All simulation tools tested using the bundled `1ZoneUncontrolled.idf` example and `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw` weather file.

### Simulations Executed
- **Design-day simulation:** success=True, runtime=0.35s
- **Annual simulation:** success=True, runtime=1.67s, 8760 hourly data points

### Post-Simulation Tools
- `list_output_variables` — 28 variables found, search/regex filtering works
- `query_timeseries` — 8760 hourly points for Zone Mean Air Temperature, keyed query by zone name works, nonexistent variables produce proper errors
- `export_timeseries` — CSV export with 8760 rows, default path generation works
- `idfkit://simulation/results` resource — 10 HTML summary tables returned

### Weather Tools
- `search_weather_stations` — text search (Chicago: 5 results), spatial search (lat/lon: 3 results), country/state filtering
- `download_weather_file` — Downloads EPW+DDY files, auto-remembers for simulation use

### OSM Conversion (OpenStudio 3.11.0)
- `convert_osm_to_idf` — Successfully converts minimal OSM model, loads result as active model, proper errors for wrong extension/missing file

## All Tools Tested

### Schema Tools (4/4)
- `list_object_types` — No filter (truncated), group filter, version filter, invalid version error
- `describe_object_type` — Valid types (Zone, Material), nonexistent type error
- `search_schema` — Normal queries, limited results, empty query fix verified
- `get_available_references` — Reference fields, non-reference field error

### Write Tools (9/9)
- `new_model` — Default version, specific version (9.6.0)
- `add_object` — Normal, with fields, duplicate name error, invalid type error
- `batch_add_objects` — Success batch, mixed success/error batch
- `update_object` — Valid updates, nonexistent object error, singleton objects
- `duplicate_object` — Valid duplication from example file
- `rename_object` — Valid rename with reference update count
- `remove_object` — Referenced (blocked), unreferenced, force removal
- `save_model` — IDF format, epJSON format, no path error
- `clear_session` — State properly cleared, model access blocked after clear

### Read Tools (5/5)
- `load_model` — IDF files, epJSON files (roundtrip), nonexistent file error
- `list_objects` — Valid types, nonexistent type error
- `search_objects` — Normal queries, no-match queries, type-filtered, empty query fix verified
- `convert_osm_to_idf` — Full conversion with OpenStudio, error paths

### Validation Tools (1/1)
- `validate_model` — Full validation, type-specific, without reference checking, empty model

### Docs Tools (2/2)
- `search_docs` — Normal queries, empty query, tag filters, version override
- `get_doc_section` — Valid location retrieval, nonexistent location error

### Simulation Tools (5/5)
- `run_simulation` — Design-day and annual, with weather file, progress reporting
- `list_output_variables` — Full listing, text search, regex search
- `query_timeseries` — All data points, keyed by zone, frequency filter, error path
- `export_timeseries` — CSV export with explicit path and default path

### Weather Tools (2/2)
- `search_weather_stations` — Text, spatial, filtered, no-args error
- `download_weather_file` — By query with filters, by WMO, no-args error

### Visualization Tools (2/2)
- `view_geometry` — Color by type (6 surfaces, 1 zone), color by zone
- `view_schedules` — All schedules, named schedule (8784 hourly values), year override, nonexistent error

### Resources (8/8)
- `idfkit://model/summary` — Version, object counts, groups
- `idfkit://schema/{object_type}` — Zone (12 fields), Material
- `idfkit://model/objects/{type}/{name}` — Valid objects (with spaces in names), nonexistent error
- `idfkit://model/references/{name}` — Bidirectional references (8 referencing objects)
- `idfkit://docs/{object_type}` — I/O Reference, Engineering Reference, search URLs
- `idfkit://simulation/results` — 10 HTML summary tables after annual simulation
- `ui://idfkit/geometry-viewer.html` — 23,283 chars of Three.js viewer HTML
- `ui://idfkit/schedule-viewer.html` — 19,492 chars of heatmap viewer HTML

### Edge Cases Tested
- Singleton object handling (SimulationControl with no name field)
- Double removal of same object (proper error)
- Rename/duplicate of nonexistent object (proper error)
- Empty model validation
- Large limit values (capped at 100/200/30 correctly)
- HTTP transport startup (clean startup and shutdown)
- epJSON roundtrip (load IDF → save epJSON → reload epJSON)
- Object names with spaces in resource URIs

## Observations (Not Bugs)

1. **Version format inconsistency:** Schema tools use `X.Y.Z` format, docs tools use `X.Y`. Parameter descriptions are correct but could confuse users.

2. **`get_results_summary` is not a registered tool:** Only accessible via the `idfkit://simulation/results` resource. This is intentional.

3. **`GetResultsSummaryResult.tables` is `Optional`:** Returns `None` (not `[]`) when no HTML tables exist (e.g., design-day-only simulations). Consumers should use `r.get("tables") or []`.
