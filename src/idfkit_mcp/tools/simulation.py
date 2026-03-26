"""Simulation tools."""

from __future__ import annotations

import logging
from sqlite3 import OperationalError
from typing import Any, Literal

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from idfkit_mcp.models import (
    ExportTimeseriesResult,
    GetResultsSummaryResult,
    ListOutputVariablesResult,
    QueryTimeseriesResult,
    RunSimulationResult,
)
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_RUN = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
_EXPORT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Valid EnergyPlus reporting frequencies for time series queries.
ReportingFrequency = Literal["Timestep", "Hourly", "Daily", "Monthly", "RunPeriod", "Annual"]


def _resolve_weather_path(weather_file: str | None, design_day: bool) -> str | None:
    """Resolve the weather path from arguments or saved session state."""
    from pathlib import Path

    state = get_state()
    if weather_file is not None:
        return str(Path(weather_file))
    if state.weather_file is not None:
        return str(state.weather_file)
    if design_day:
        return None
    raise ToolError(
        "No weather file specified. Provide weather_file or use download_weather_file first, or set design_day=True."
    )


def _serialize_simulation_errors(errors: Any) -> dict[str, Any]:
    """Serialize simulation error counts and representative messages."""
    error_detail: dict[str, Any] = {
        "fatal": errors.fatal_count,
        "severe": errors.severe_count,
        "warnings": errors.warning_count,
    }
    if errors.has_fatal:
        error_detail["fatal_messages"] = [{"message": m.message, "details": list(m.details)} for m in errors.fatal]
    if errors.has_severe:
        error_detail["severe_messages"] = [
            {"message": m.message, "details": list(m.details)} for m in errors.severe[:10]
        ]
    if errors.warning_count > 0:
        error_detail["warning_messages"] = [
            {"message": m.message, "details": list(m.details)} for m in errors.warnings[:10]
        ]
    return error_detail


async def run_simulation(
    weather_file: str | None = None,
    design_day: bool = False,
    annual: bool = False,
    energyplus_dir: str | None = None,
    energyplus_version: str | None = None,
    output_directory: str | None = None,
    ctx: Context | None = None,
) -> RunSimulationResult:
    """Execute an EnergyPlus simulation on the loaded model.

    Use this to run the simulation after building or modifying a model.

    Args:
        weather_file: Path to EPW weather file. Uses previously downloaded file if None.
        design_day: Run design-day-only simulation.
        annual: Run annual simulation.
        energyplus_dir: Optional explicit EnergyPlus installation directory or executable path.
        energyplus_version: Optional EnergyPlus version filter (e.g. "25.1.0").
        output_directory: Optional explicit output directory for simulation results.
    """
    from idfkit.simulation import async_simulate
    from idfkit.simulation.config import find_energyplus
    from idfkit.simulation.progress import SimulationProgress

    state = get_state()
    doc = state.require_model()
    weather = _resolve_weather_path(weather_file, design_day)

    config = find_energyplus(path=energyplus_dir, version=energyplus_version)
    logger.info(
        "Starting simulation (EnergyPlus %s, weather=%s, design_day=%s, annual=%s)",
        ".".join(str(p) for p in config.version),
        weather,
        design_day,
        annual,
    )

    async def on_progress(event: SimulationProgress) -> None:
        if ctx is not None and event.percent is not None:
            await ctx.report_progress(progress=event.percent, total=100.0)
        if ctx is not None:
            await ctx.info(f"[{event.phase}] {event.message!s}")

    result = await async_simulate(
        doc,
        weather="" if weather is None else weather,
        design_day=design_day,
        annual=annual,
        energyplus=config,
        output_dir=output_directory,
        on_progress=on_progress,
    )

    state.simulation_result = result
    state.save_session()

    if result.success:
        logger.info("Simulation completed in %.1fs", result.runtime_seconds)
    else:
        logger.warning("Simulation failed after %.1fs", result.runtime_seconds)

    errors = result.errors

    return RunSimulationResult.model_validate({
        "success": result.success,
        "runtime_seconds": round(result.runtime_seconds, 2),
        "output_directory": str(result.run_dir),
        "energyplus": {
            "version": ".".join(str(part) for part in config.version),
            "install_dir": str(config.install_dir),
            "executable": str(config.executable),
        },
        "errors": _serialize_simulation_errors(errors),
        "simulation_complete": errors.simulation_complete,
    })


def get_results_summary() -> GetResultsSummaryResult:
    """Get a summary of the last simulation results.

    Use this after run_simulation to review energy metrics, error counts, and key tables.
    """
    state = get_state()
    result = state.require_simulation_result()

    summary: dict[str, Any] = {
        "success": result.success,
        "runtime_seconds": round(result.runtime_seconds, 2),
        "output_directory": str(result.run_dir),
    }

    errors = result.errors
    summary["errors"] = {
        "fatal": errors.fatal_count,
        "severe": errors.severe_count,
        "warnings": errors.warning_count,
        "summary": errors.summary(),
    }

    if errors.has_fatal or errors.has_severe:
        severe_msgs = [{"message": m.message, "details": list(m.details)} for m in errors.severe[:10]]
        fatal_msgs = [{"message": m.message, "details": list(m.details)} for m in errors.fatal]
        summary["fatal_messages"] = fatal_msgs
        summary["severe_messages"] = severe_msgs

    html = result.html
    if html is not None:
        tables_summary: list[dict[str, Any]] = []
        for table in html.tables[:10]:
            table_info: dict[str, Any] = {
                "title": table.title,
                "report": table.report_name,
                "for_string": table.for_string,
            }
            table_dict = table.to_dict()
            if table_dict and len(table_dict) <= 100:
                table_info["data"] = table_dict
            elif table_dict:
                table_info["truncated"] = True
            tables_summary.append(table_info)
        summary["tables"] = tables_summary

    return GetResultsSummaryResult.model_validate(summary)


def list_output_variables(search: str | None = None, limit: int = 50) -> ListOutputVariablesResult:
    """List available output variables from the last simulation.

    Use this to discover what time series data is available for querying.

    Args:
        search: Optional regex pattern to filter variables by name.
        limit: Maximum number of results (default 50).
    """
    state = get_state()
    result = state.require_simulation_result()

    limit = min(limit, 200)

    variables = result.variables
    if variables is None:
        raise ToolError("No output variable index available. The simulation may not have produced .rdd/.mdd files.")

    from idfkit.simulation.parsers.rdd import OutputVariable

    all_items = variables.search(search) if search else [*variables.variables, *variables.meters]

    limited = all_items[:limit]
    serialized: list[dict[str, str]] = []
    for item in limited:
        entry: dict[str, str] = {"name": item.name, "units": item.units}
        if isinstance(item, OutputVariable):
            entry["key"] = item.key
            entry["type"] = "variable"
        else:
            entry["type"] = "meter"
        serialized.append(entry)

    total = len(variables.variables) + len(variables.meters)
    return ListOutputVariablesResult.model_validate({
        "total_available": total,
        "returned": len(serialized),
        "variables": serialized,
    })


def query_timeseries(
    variable_name: str,
    key_value: str = "*",
    frequency: ReportingFrequency | None = None,
    environment: Literal["sizing", "annual"] | None = None,
    limit: int = 24,
) -> QueryTimeseriesResult:
    """Query time series data from the last simulation's SQL output.

    Use this for quick inspection of simulation output data inline.
    Returns the first `limit` data points.

    Args:
        variable_name: The output variable name (e.g. "Zone Mean Air Temperature").
        key_value: Key value such as zone or surface name. Use "*" for environment-level variables.
        frequency: Reporting frequency filter (e.g. "Hourly", "Monthly").
        environment: Filter by environment type: "sizing" or "annual".
        limit: Maximum number of data points to return (default 24).
    """
    limit = min(limit, 500)

    state = get_state()
    result = state.require_simulation_result()

    sql = result.sql
    if sql is None:
        raise ToolError("No SQL output available. The simulation may not have produced an .sql file.")

    try:
        ts = sql.get_timeseries(
            variable_name=variable_name,
            key_value=key_value,
            frequency=frequency,
            environment=environment,
        )
    except OperationalError as e:
        raise ToolError(
            f"SQL query failed: {e}. "
            "The simulation may not have completed successfully, or Output:SQLite was not configured in the model. "
            "Check run_simulation results for errors."
        ) from e

    rows = [
        {"timestamp": ts.timestamps[i].isoformat(), "value": ts.values[i]} for i in range(min(limit, len(ts.values)))
    ]

    logger.debug(
        "query_timeseries: %s key=%s freq=%s total=%d returned=%d",
        variable_name,
        key_value,
        frequency,
        len(ts.values),
        len(rows),
    )
    return QueryTimeseriesResult.model_validate({
        "variable_name": ts.variable_name,
        "key_value": ts.key_value,
        "units": ts.units,
        "frequency": ts.frequency,
        "total_points": len(ts.values),
        "returned": len(rows),
        "data": rows,
    })


def export_timeseries(
    variable_name: str,
    key_value: str = "*",
    frequency: ReportingFrequency | None = None,
    environment: Literal["sizing", "annual"] | None = None,
    output_path: str | None = None,
) -> ExportTimeseriesResult:
    """Export time series data from the last simulation to a CSV file.

    Use this to save full simulation output data for external analysis.

    Args:
        variable_name: The output variable name (e.g. "Zone Mean Air Temperature").
        key_value: Key value such as zone or surface name. Use "*" for environment-level variables.
        frequency: Reporting frequency filter (e.g. "Hourly", "Monthly").
        environment: Filter by environment type: "sizing" or "annual".
        output_path: Output CSV file path. Defaults to a file in the simulation output directory.
    """
    import csv
    import re
    from pathlib import Path

    state = get_state()
    result = state.require_simulation_result()

    sql = result.sql
    if sql is None:
        raise ToolError("No SQL output available. The simulation may not have produced an .sql file.")

    try:
        ts = sql.get_timeseries(
            variable_name=variable_name,
            key_value=key_value,
            frequency=frequency,
            environment=environment,
        )
    except OperationalError as e:
        raise ToolError(
            f"SQL query failed: {e}. "
            "The simulation may not have completed successfully, or Output:SQLite was not configured in the model. "
            "Check run_simulation results for errors."
        ) from e

    if output_path is not None:
        csv_path = Path(output_path)
    else:
        safe_name = re.sub(r"[^\w]+", "_", variable_name).strip("_").lower()
        csv_path = result.run_dir / f"timeseries_{safe_name}.csv"

    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", ts.variable_name + f" [{ts.units}]"])
        for i in range(len(ts.values)):
            writer.writerow([ts.timestamps[i].isoformat(), ts.values[i]])

    logger.info("Exported timeseries %r to %s (%d rows)", variable_name, csv_path, len(ts.values))
    return ExportTimeseriesResult(
        path=str(csv_path),
        variable_name=ts.variable_name,
        key_value=ts.key_value,
        units=ts.units,
        frequency=ts.frequency,
        rows=len(ts.values),
    )


# Annotations are defined after functions to avoid forward-reference errors.
_TOOL_REGISTRY = [
    (run_simulation, _RUN),
    (get_results_summary, _READ_ONLY),
    (list_output_variables, _READ_ONLY),
    (query_timeseries, _READ_ONLY),
    (export_timeseries, _EXPORT),
]


def register(mcp: FastMCP) -> None:
    """Register simulation tools on the MCP server."""
    for func, hints in _TOOL_REGISTRY:
        mcp.tool(annotations=hints)(func)
