# Tool Reference Overview

`idfkit-mcp` exposes **25 tools** in six categories.

## Categories

- Schema exploration: 4 tools
- Model read: 6 tools
- Model write: 8 tools
- Validation: 2 tools
- Simulation: 3 tools
- Weather: 2 tools

## Tool Catalog

| Category | Tool | Purpose |
|---|---|---|
| Schema | `list_object_types` | List available EnergyPlus object types |
| Schema | `describe_object_type` | Get full field contract for one type |
| Schema | `search_schema` | Search object types by name/memo |
| Schema | `get_available_references` | Resolve valid reference values from model |
| Read | `load_model` | Load IDF/epJSON into active server state |
| Read | `get_model_summary` | Summarize loaded model |
| Read | `list_objects` | List objects by type |
| Read | `get_object` | Fetch one object by type/name |
| Read | `search_objects` | Search model objects by substring |
| Read | `get_references` | Inspect inbound and outbound references |
| Write | `new_model` | Create empty model |
| Write | `add_object` | Add one object |
| Write | `batch_add_objects` | Add many objects in one call |
| Write | `update_object` | Update fields on one object |
| Write | `remove_object` | Remove object, optionally forced |
| Write | `rename_object` | Rename object and cascade references |
| Write | `duplicate_object` | Clone object to a new name |
| Write | `save_model` | Save IDF/epJSON |
| Validation | `validate_model` | Full schema validation |
| Validation | `check_references` | Detect dangling references |
| Simulation | `run_simulation` | Execute EnergyPlus run |
| Simulation | `get_results_summary` | Summarize previous run |
| Simulation | `list_output_variables` | Enumerate meters/variables |
| Weather | `search_weather_stations` | Find weather stations |
| Weather | `download_weather_file` | Download EPW/DDY and cache path |

## Global Best Practices

1. Use schema tools before mutations.
2. Prefer batched writes.
3. Validate immediately after writes.
4. Run simulation only after model health checks pass.
5. Treat each server session as stateful and sequential.
