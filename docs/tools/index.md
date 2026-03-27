# Tool Reference Overview

`idfkit-mcp` exposes **28 tools** in nine categories, plus **8 MCP resources** for read-only data access.

## Categories

- Schema exploration: 4 tools
- Model read: 4 tools
- Model write: 9 tools
- Validation: 1 tool
- Simulation: 4 tools
- Geometry: 1 tool
- Schedules: 1 tool
- Weather: 2 tools
- Documentation: 2 tools

## Tool Catalog

| Category | Tool | Purpose |
|---|---|---|
| Schema | `list_object_types` | List available EnergyPlus object types |
| Schema | `describe_object_type` | Get full field contract for one type |
| Schema | `search_schema` | Search object types by name/memo |
| Schema | `get_available_references` | Resolve valid reference values from model |
| Read | `load_model` | Load IDF/epJSON into active server state |
| Read | `convert_osm_to_idf` | Convert OSM to IDF and load into active server state |
| Read | `list_objects` | List objects by type |
| Read | `search_objects` | Search model objects by substring |
| Write | `new_model` | Create empty model |
| Write | `add_object` | Add one object |
| Write | `batch_add_objects` | Add many objects in one call |
| Write | `update_object` | Update fields on one object |
| Write | `remove_object` | Remove object, optionally forced |
| Write | `rename_object` | Rename object and cascade references |
| Write | `duplicate_object` | Clone object to a new name |
| Write | `save_model` | Save IDF/epJSON |
| Write | `clear_session` | Clear persisted session and reset state |
| Validation | `validate_model` | Full schema and reference validation |
| Simulation | `run_simulation` | Execute EnergyPlus run |
| Simulation | `list_output_variables` | Enumerate meters/variables |
| Simulation | `query_timeseries` | Query time series data from SQL output |
| Simulation | `export_timeseries` | Export time series data to CSV |
| Weather | `search_weather_stations` | Find weather stations |
| Weather | `download_weather_file` | Download EPW/DDY and cache path |
| Geometry | `view_geometry` | Interactive 3D building geometry viewer (MCP Apps) |
| Schedules | `view_schedules` | Interactive schedule heatmap viewer (MCP Apps) |
| Documentation | `search_docs` | Full-text search across EnergyPlus documentation |
| Documentation | `get_doc_section` | Retrieve full content of a documentation section |

## MCP Resources

Read-only data is available via MCP resources without making tool calls:

| URI | Description |
|-----|-------------|
| `idfkit://model/summary` | Model version, zones, and object counts |
| `idfkit://schema/{object_type}` | Full field schema for an object type |
| `idfkit://model/objects/{object_type}/{name}` | All field values for a specific object |
| `idfkit://model/references/{name}` | Inbound and outbound references for an object |
| `idfkit://docs/{object_type}` | Documentation URLs for an object type |
| `idfkit://simulation/results` | Summary of the most recent simulation results |
| `ui://idfkit/geometry-viewer.html` | Interactive Three.js geometry viewer (MCP Apps) |
| `ui://idfkit/schedule-viewer.html` | Interactive schedule heatmap viewer (MCP Apps) |

## Global Best Practices

1. Use schema tools before mutations.
2. Prefer batched writes.
3. Validate immediately after writes.
4. Run simulation only after model health checks pass.
5. Treat each server session as stateful and sequential.
