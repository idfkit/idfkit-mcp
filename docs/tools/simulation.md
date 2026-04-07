# Simulation Tools

Simulation tools execute EnergyPlus, expose structured QA diagnostics, and provide SQL-backed report analysis.

## `run_simulation`

Parameters:

- `weather_file`: explicit EPW path (optional if weather already downloaded)
- `design_day`: design-day-only run
- `annual`: annual run
- `energyplus_dir`: optional explicit EnergyPlus directory or executable path
- `energyplus_version`: optional EnergyPlus version filter (for example `25.1.0`)
- `output_directory`: optional output directory for simulation results

Behavior:

- Uses server-cached weather path when available.
- Ensures SQLite and required summary reports are enabled on the simulation copy.
- Returns runtime, output directory, and error counts.
- Returns the resolved EnergyPlus executable, install directory, and version.
- Stores result in server state for follow-up tools.

## `list_output_variables`

Lists available variables/meters from run output metadata.

Parameters:

- `search`: optional regex filter (case-insensitive); invalid patterns are rejected
- `limit`: default `50`

## `query_timeseries`

Query time series data from the last simulation's SQL output for quick inline inspection.

Parameters:

- `variable_name` (required): output variable name (e.g. `"Zone Mean Air Temperature"`)
- `key_value`: zone or surface name, `"*"` for environment-level variables (default `"*"`)
- `frequency`: reporting frequency filter (`"Timestep"`, `"Hourly"`, `"Daily"`, `"Monthly"`, `"RunPeriod"`, `"Annual"`)
- `environment`: filter by environment type (`"sizing"` or `"annual"`)
- `limit`: maximum data points to return (default `24`)

Requires `Output:SQLite` in the model. Returns a descriptive error if the SQL file is missing or the query fails.

## `query_simulation_table`

Query tabular report data from the last simulation's SQL output.

Parameters:

- `report_name` (required): report name such as `"AnnualBuildingUtilityPerformanceSummary"` or `"SystemSummary"`
- `table_name`: optional table name within that report
- `row_name`: optional row filter
- `column_name`: optional column filter

Use this when you need full EnergyPlus summary tables beyond the structured diagnostics in `idfkit://simulation/results`.

## `list_simulation_reports`

Lists all tabular report names available in the last simulation's SQL output.

Use the returned names with `query_simulation_table(...)` to discover and inspect report sections.

## `export_timeseries`

Export full time series data from the last simulation to a CSV file for external analysis.

Parameters:

- `variable_name` (required): output variable name (e.g. `"Zone Mean Air Temperature"`)
- `key_value`: zone or surface name, `"*"` for environment-level variables (default `"*"`)
- `frequency`: reporting frequency filter
- `environment`: filter by environment type (`"sizing"` or `"annual"`)
- `output_path`: output CSV file path (defaults to a file in the simulation output directory). Must resolve within an allowed output directory (see `IDFKIT_MCP_OUTPUT_DIRS`)

## `analyze_peak_loads`

Analyzes facility and zone-level heating/cooling peaks for QA/QC.

Highlights:

- decomposes peaks into components such as solar, people, lighting, equipment, infiltration, and envelope loads
- ranks zones by absolute and area-normalized peak intensity
- surfaces timing checks, dominant-component checks, and sizing-oriented QA flags
- requires SQL output plus the `SensibleHeatGainSummary` and `HVACSizingSummary` reports

## `view_simulation_report`

Builds the full tabular simulation report payload and opens the companion MCP Apps viewer when the client supports it.

Use this when you want a browsable report browser instead of pulling individual tables with `query_simulation_table(...)`.

## Simulation Resources

Simulation data is also exposed via read-only MCP resources:

- `idfkit://simulation/results`: structured summary of the latest run, including `sql_available`, `unmet_hours`, `end_uses`, `classified_warnings`, `qa_flags`, and any notes
- `idfkit://simulation/peak-loads`: the same peak-load QA/QC analysis returned by `analyze_peak_loads`
- `idfkit://simulation/report`: the full tabular simulation report as JSON
- `ui://idfkit/peak-loads-viewer.html`: companion MCP Apps viewer for peak-load analysis
- `ui://idfkit/report-viewer.html`: companion MCP Apps viewer for the full tabular report

## Simulation Workflow

1. `download_weather_file` or provide `weather_file`
2. `run_simulation`
3. Read `idfkit://simulation/results` resource
4. `list_output_variables(search=...)`
5. `query_timeseries(variable_name=...)` or `export_timeseries(...)`
6. `list_simulation_reports()` and `query_simulation_table(...)`, or `view_simulation_report()`
7. `analyze_peak_loads()` for facility and zone-level peak QA

## Common Guardrail

If `run_simulation` reports missing weather, either:

- call `download_weather_file`, or
- pass an explicit EPW path.
