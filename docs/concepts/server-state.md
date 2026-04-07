# Server State

`idfkit-mcp` keeps an in-memory state object across tool calls in a session.

## State Fields

- `document`: active EnergyPlus model
- `schema`: active schema (usually from model)
- `file_path`: current model path
- `simulation_result`: last run result
- `weather_file`: last downloaded EPW path
- `change_log`: recent mutating operations for `get_change_log`
- `docs_index`: cached documentation search index (loaded on first `search_docs` / `get_doc_section` call)
- `docs_version`: version of the cached docs index
- `docs_separator`: tokenization regex from the docs index config

## Implications for Agent Design

- Calls are stateful, not stateless RPC.
- Sequence matters.
- Loading a new model replaces prior context.
- Simulation and weather data are session-local.
- The change log is session-local and not persisted across `clear_session`.

## Required Preconditions

Some tools require prior state:

- model required: most model read/write/validation tools, plus `view_geometry`, `view_schedules`, and `get_zone_properties`
- simulation result required: `list_output_variables`, `query_timeseries`, `query_simulation_table`, `list_simulation_reports`, `view_simulation_report`, `analyze_peak_loads`, `export_timeseries`, and the `idfkit://simulation/results`, `idfkit://simulation/peak-loads`, and `idfkit://simulation/report` resources

If missing, tools return descriptive errors such as:

- `No model loaded. Use load_model or new_model first.`
- `No simulation results available. Use run_simulation first.`

## Session Persistence

Server state is automatically persisted to a JSON file on disk so that clients that restart the server between turns (e.g. Codex) can resume transparently.

Saved state:

- `file_path` — reloaded via `load_model` on restore
- `simulation_run_dir` — simulation result rebuilt from output directory
- `weather_file` — weather file path restored

Not persisted:

- `change_log` — stays in-memory only and resets with a fresh session or `clear_session`

Behavior:

- Auto-saved after `load_model`, `convert_osm_to_idf`, `save_model`, `run_simulation`, and `download_weather_file`.
- Auto-restored lazily on the first call that requires state (e.g. `require_model()`).
- Session file is keyed by working directory (SHA-256 hash) and stored in `~/.cache/idfkit/sessions/` (Linux) or `~/Library/Caches/idfkit/sessions/` (macOS).
- Use `clear_session` to delete the session file and reset all state.

## MCP Resources

In addition to tools, the server exposes read-only MCP resources that let clients subscribe to model state without making tool calls.

| URI | Description |
|-----|-------------|
| `idfkit://model/summary` | Current model summary (version, zones, object counts) |
| `idfkit://schema/{object_type}` | Full field schema for an object type |
| `idfkit://model/objects/{object_type}/{name}` | All field values for a specific object |
| `idfkit://model/references/{name}` | Inbound and outbound references for an object |
| `idfkit://docs/{object_type}` | Documentation URLs for an object type |
| `idfkit://simulation/results` | Structured QA diagnostics from the most recent simulation |
| `idfkit://simulation/peak-loads` | Peak heating/cooling load decomposition and QA analysis |
| `idfkit://simulation/report` | Full tabular simulation report for the latest run |

Resources return JSON (`application/json`) and are available whenever the corresponding state exists (e.g., `model/summary` requires a loaded model).

## Session Strategy

For deterministic automation:

1. start with `load_model` or `new_model` (or let session persistence restore a previous model)
2. complete one workflow at a time
3. persist artifacts with `save_model`
