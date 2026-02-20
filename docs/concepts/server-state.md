# Server State

`idfkit-mcp` keeps an in-memory state object across tool calls in a session.

## State Fields

- `document`: active EnergyPlus model
- `schema`: active schema (usually from model)
- `file_path`: current model path
- `simulation_result`: last run result
- `weather_file`: last downloaded EPW path

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

## Session Strategy

For deterministic automation:

1. start with explicit `load_model` or `new_model`
2. complete one workflow at a time
3. persist artifacts with `save_model`
