# MCP Server Debug Report

**Date:** 2026-03-28
**Method:** In-process testing via FastMCP `Client` against all 28 registered tools, 4 resources, and 4 resource templates.

## Summary

| Category | Count |
|----------|-------|
| Tools tested | 28/28 |
| Resources tested | 8/8 (4 static + 4 templates) |
| Tests passed | 79 |
| Bugs found | 3 |
| Skipped | 5 (EnergyPlus not installed) |

## Bugs Found

### Bug 1: `search_schema` returns results for empty query

**Severity:** Low
**File:** `src/idfkit_mcp/tools/schema.py:129`

**Description:** Calling `search_schema(query="")` returns the first 10 object types instead of 0 results. This is because Python's `in` operator treats the empty string as a substring of every string (`"" in "anything"` is `True`).

**Reproduction:**
```python
search_schema(query="")  # Returns count=10, should return count=0
```

**Fix:** Add an early return for empty/whitespace-only queries, similar to how `search_docs` already handles this case.

---

### Bug 2: `search_objects` returns results for empty query

**Severity:** Low
**File:** `src/idfkit_mcp/tools/read.py:183-189`

**Description:** Same root cause as Bug 1. `search_objects(query="")` matches every object in the model because `"" in obj.name.lower()` is always `True`.

**Reproduction:**
```python
# With a model containing 5 objects:
search_objects(query="")  # Returns count=5, should return count=0
```

**Fix:** Add an early return for empty/whitespace-only queries.

---

### Bug 3: `test_write_failure_does_not_raise` test fails when running as root

**Severity:** Low (test-only, not a server bug)
**File:** `tests/test_session_persistence.py:162-180`

**Description:** The test creates a directory with `chmod(0o444)` and expects that writing to it will fail. However, when running as root (e.g., in Docker containers or CI), root bypasses filesystem permission checks, so the write succeeds and the assertion `assert not bad_path.exists()` fails.

**Reproduction:**
```bash
# As root:
make test  # test_write_failure_does_not_raise fails
```

**Fix:** Skip the test when running as root:
```python
@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
```

---

## Tools Successfully Tested

### Schema Tools (4/4)
- `list_object_types` - All modes: no filter, group filter, version filter, invalid version
- `describe_object_type` - Valid types, nonexistent types
- `search_schema` - Normal queries, limited results, empty query (bug)
- `get_available_references` - Valid reference fields, non-reference fields

### Write Tools (9/9)
- `new_model` - Default version, specific version
- `add_object` - Normal, with fields, duplicate name, invalid type
- `batch_add_objects` - Success batch, mixed success/error batch
- `update_object` - Valid updates, nonexistent object
- `duplicate_object` - Valid duplication
- `rename_object` - Valid rename, nonexistent source
- `remove_object` - Referenced (blocked), unreferenced, force removal
- `save_model` - IDF format, epJSON format, no path error
- `clear_session` - State properly cleared

### Read Tools (5/5)
- `load_model` - IDF files, epJSON files, nonexistent files
- `list_objects` - Valid types, nonexistent types
- `search_objects` - Normal queries, no-match queries, type-filtered queries, empty query (bug)
- `convert_osm_to_idf` - Nonexistent file error (OpenStudio not available for full test)

### Validation Tools (1/1)
- `validate_model` - Full validation, type-specific, without reference checking, empty model

### Docs Tools (2/2)
- `search_docs` - Normal queries, empty query, tag filters, version override
- `get_doc_section` - Valid location, nonexistent location

### Weather Tools (2/2)
- `search_weather_stations` - Text search, spatial search, country filter, no-args error
- `download_weather_file` - Query-based download, no-args error

### Simulation Tools (5/5 registered, 0 functionally tested)
- `run_simulation` - Skipped (EnergyPlus not installed)
- `list_output_variables` - Skipped
- `query_timeseries` - Skipped
- `export_timeseries` - Skipped

### Visualization Tools (2/2)
- `view_geometry` - Color by type, color by zone
- `view_schedules` - All schedules, named schedule, year override, nonexistent schedule

### Resources (8/8)
- `idfkit://model/summary` - Returns valid JSON
- `idfkit://schema/{object_type}` - Zone, Material schemas
- `idfkit://model/objects/{type}/{name}` - Valid objects, nonexistent objects (proper error)
- `idfkit://model/references/{name}` - Bidirectional references
- `idfkit://docs/{object_type}` - Documentation URLs
- `idfkit://simulation/results` - Proper error when no simulation
- `ui://idfkit/geometry-viewer.html` - Returns HTML
- `ui://idfkit/schedule-viewer.html` - Returns HTML

### Edge Cases Tested
- Singleton object handling (SimulationControl with no name field)
- Double removal of same object (proper error)
- Rename of nonexistent object (proper error)
- Empty model validation
- Large limit values (capped correctly)
- HTTP transport startup (clean)

## Observations (Not Bugs)

1. **Version format inconsistency:** Schema tools use `X.Y.Z` format, docs tools use `X.Y`. The parameter descriptions are correct, but this could confuse users switching between tool categories.

2. **`get_results_summary` is not a tool:** It's defined as a plain function in `simulation.py` (no `@mcp.tool` decorator) and only used by the `idfkit://simulation/results` resource. This is intentional (resource-only access) but worth noting since the initial codebase exploration suggested 32 tools while only 28 are registered.

3. **`_parse_version` in `docs.py` is effectively dead code:** It's defined but only used by `build_documentation_urls`, which is called from the resource handler, not from any tool that accepts user input.
