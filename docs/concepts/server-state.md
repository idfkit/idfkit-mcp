# Server State

`idfkit-mcp` keeps an in-memory state object across tool calls in a session.

## State Fields

- `document`: active EnergyPlus model
- `schema`: active schema (usually from model)
- `file_path`: current model path
- `simulation_result`: last run result
- `weather_file`: last downloaded EPW path
- `docs_index`: cached documentation search index (loaded on first `search_docs` / `get_doc_section` call)
- `docs_version`: version of the cached docs index
- `docs_separator`: tokenization regex from the docs index config

## Implications for Agent Design

- Calls are stateful, not stateless RPC.
- Sequence matters.
- Loading a new model replaces prior context.
- Simulation and weather data are session-local.

## Required Preconditions

Some tools require prior state:

- model required: most read/write/validation/simulation tools
- simulation result required: `get_results_summary`, `list_output_variables`

If missing, tools return descriptive errors such as:

- `No model loaded. Use load_model or new_model first.`
- `No simulation results available. Use run_simulation first.`

## Session Persistence

Server state is automatically persisted to a JSON file on disk so that clients that restart the server between turns (e.g. Codex) can resume transparently.

Saved state:

- `file_path` — reloaded via `load_model` on restore
- `simulation_run_dir` — simulation result rebuilt from output directory
- `weather_file` — weather file path restored

Behavior:

- Auto-saved after `load_model`, `convert_osm_to_idf`, `save_model`, `run_simulation`, and `download_weather_file`.
- Auto-restored lazily on the first call that requires state (e.g. `require_model()`).
- Session file is keyed by working directory (SHA-256 hash) and stored in `~/.cache/idfkit/sessions/` (Linux) or `~/Library/Caches/idfkit/sessions/` (macOS).
- Use `clear_session` to delete the session file and reset all state.

## Session Strategy

For deterministic automation:

1. start with `load_model` or `new_model` (or let session persistence restore a previous model)
2. complete one workflow at a time
3. persist artifacts with `save_model`
