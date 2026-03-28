"""Simulation tools."""

from __future__ import annotations

import logging
import re
from sqlite3 import OperationalError
from typing import Annotated, Any, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
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
_RUN = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
_EXPORT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Valid EnergyPlus reporting frequencies for time series queries.
ReportingFrequency = Literal["Timestep", "Hourly", "Daily", "Monthly", "RunPeriod", "Annual"]


def _open_sql_result(result: Any) -> Any:
    """Open a fresh SQLResult handle for the simulation output.

    Avoid reusing ``SimulationResult.sql`` across tool calls because that
    cached sqlite connection can be bound to a different worker thread.
    """
    from idfkit.simulation.parsers.sql import SQLResult

    sql_path = result.sql_path
    if sql_path is None:
        raise ToolError("No SQL output available. The simulation may not have produced an .sql file.")
    return SQLResult(sql_path)


def _build_output_variable_result(
    entries: list[dict[str, str | None]],
    *,
    total_available: int,
    limit: int,
) -> ListOutputVariablesResult:
    """Serialize output-variable metadata into the MCP response model."""
    return ListOutputVariablesResult.model_validate({
        "total_available": total_available,
        "returned": min(len(entries), limit),
        "variables": entries[:limit],
    })


def _resolve_weather_path(weather_file: str | None, design_day: bool) -> str | None:
    """Resolve the weather file path from arguments or saved session state."""
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


def _build_progress_handler(ctx: Context | None) -> Any:
    """Build an async progress callback for FastMCP context reporting."""
    from idfkit.simulation.progress import SimulationProgress

    async def on_progress(event: SimulationProgress) -> None:
        if ctx is not None and event.percent is not None:
            await ctx.report_progress(progress=event.percent, total=100.0)
        if ctx is not None:
            await ctx.info(f"[{event.phase}] {event.message}")

    return on_progress


@mcp.tool(annotations=_RUN)
async def run_simulation(
    weather_file: Annotated[str | None, Field(description="EPW path (default: last downloaded).")] = None,
    design_day: Annotated[bool, Field(description="Design-day only.")] = False,
    annual: Annotated[bool, Field(description="Annual simulation.")] = False,
    energyplus_dir: Annotated[str | None, Field(description="EnergyPlus install dir.")] = None,
    energyplus_version: Annotated[str | None, Field(description='Version filter "X.Y.Z".')] = None,
    output_directory: Annotated[str | None, Field(description="Output dir.")] = None,
    ctx: Context | None = None,
) -> RunSimulationResult:
    """Run EnergyPlus on the loaded model."""
    from idfkit.simulation import async_simulate
    from idfkit.simulation.config import find_energyplus

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

    result = await async_simulate(
        doc,
        weather="" if weather is None else weather,
        design_day=design_day,
        annual=annual,
        energyplus=config,
        output_dir=output_directory,
        on_progress=_build_progress_handler(ctx),
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
    """Build results summary from the last simulation."""
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


@mcp.tool(annotations=_READ_ONLY)
def list_output_variables(
    search: Annotated[str | None, Field(description="Regex filter on name.")] = None,
    limit: Annotated[int, Field(description="Max results.")] = 50,
) -> ListOutputVariablesResult:
    """List output variables and meters from last simulation."""
    state = get_state()
    result = state.require_simulation_result()

    limit = min(limit, 200)

    variables = result.variables
    if variables is not None and (variables.variables or variables.meters):
        from idfkit.simulation.parsers.rdd import OutputVariable

        all_items = variables.search(search) if search else [*variables.variables, *variables.meters]
        serialized: list[dict[str, str | None]] = []
        for item in all_items:
            entry: dict[str, str | None] = {"name": item.name, "units": item.units}
            if isinstance(item, OutputVariable):
                entry["key"] = item.key
                entry["type"] = "variable"
            else:
                entry["type"] = "meter"
            serialized.append(entry)

        total = len(variables.variables) + len(variables.meters)
        return _build_output_variable_result(serialized, total_available=total, limit=limit)

    with _open_sql_result(result) as sql:
        regex = re.compile(search, re.IGNORECASE) if search else None
        all_items = sql.list_variables()
        serialized = [
            {
                "name": item.name,
                "units": item.units,
                "key": item.key_value or None,
                "type": "meter" if item.is_meter else "variable",
            }
            for item in all_items
            if regex is None or regex.search(item.name)
        ]
    return _build_output_variable_result(serialized, total_available=len(all_items), limit=limit)


@mcp.tool(annotations=_READ_ONLY)
def query_timeseries(
    variable_name: Annotated[str, Field(description="Variable name.")],
    key_value: Annotated[str, Field(description='Zone/surface or "*".')] = "*",
    frequency: Annotated[ReportingFrequency | None, Field(description="Reporting frequency.")] = None,
    environment: Annotated[Literal["sizing", "annual"] | None, Field(description="Environment filter.")] = None,
    limit: Annotated[int, Field(description="Max data points.")] = 24,
) -> QueryTimeseriesResult:
    """Query time series data from simulation SQL output."""
    limit = min(limit, 500)

    state = get_state()
    result = state.require_simulation_result()

    try:
        with _open_sql_result(result) as sql:
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


@mcp.tool(annotations=_EXPORT)
def export_timeseries(
    variable_name: Annotated[str, Field(description="Variable name.")],
    key_value: Annotated[str, Field(description='Zone/surface or "*".')] = "*",
    frequency: Annotated[ReportingFrequency | None, Field(description="Reporting frequency.")] = None,
    environment: Annotated[Literal["sizing", "annual"] | None, Field(description="Environment filter.")] = None,
    output_path: Annotated[str | None, Field(description="CSV path (default: output dir).")] = None,
) -> ExportTimeseriesResult:
    """Export time series to CSV."""
    import csv
    import re
    from pathlib import Path

    state = get_state()
    result = state.require_simulation_result()

    try:
        with _open_sql_result(result) as sql:
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
