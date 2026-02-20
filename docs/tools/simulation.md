# Simulation Tools

Simulation tools execute EnergyPlus and expose summarized outputs.

## `run_simulation`

Parameters:

- `weather_file`: explicit EPW path (optional if weather already downloaded)
- `design_day`: design-day-only run
- `annual`: annual run
- `energyplus_dir`: optional explicit EnergyPlus directory or executable path
- `energyplus_version`: optional EnergyPlus version filter (for example `25.1.0`)

Behavior:

- Uses server-cached weather path when available.
- Returns runtime, output directory, and error counts.
- Returns the resolved EnergyPlus executable, install directory, and version.
- Stores result in server state for follow-up tools.

## `get_results_summary`

Summarizes the latest simulation result:

- success flag
- runtime
- fatal/severe/warning counts
- severe/fatal messages
- first batch of HTML report tables when available

## `list_output_variables`

Lists available variables/meters from run output metadata.

Parameters:

- `search`: optional regex
- `limit`: default `50`

## Simulation Workflow

1. `download_weather_file` or provide `weather_file`
2. `run_simulation`
3. `get_results_summary`
4. `list_output_variables(search=...)`

## Common Guardrail

If `run_simulation` reports missing weather, either:

- call `download_weather_file`, or
- pass an explicit EPW path.
