"""Simulation tools."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from idfkit_mcp.errors import format_error
from idfkit_mcp.state import get_state


def _safe_tool(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Convert exceptions into MCP-friendly error dicts."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return format_error(e)

    return wrapper


def register(mcp: FastMCP) -> None:
    """Register simulation tools on the MCP server."""
    mcp.tool()(run_simulation)
    mcp.tool()(get_results_summary)
    mcp.tool()(list_output_variables)
    mcp.tool()(query_timeseries)
    mcp.tool()(export_timeseries)


@_safe_tool
def run_simulation(
    weather_file: str | None = None,
    design_day: bool = False,
    annual: bool = False,
    energyplus_dir: str | None = None,
    energyplus_version: str | None = None,
    output_directory: str | None = None,
) -> dict[str, Any]:
    """Run an EnergyPlus simulation on the loaded model.

    Args:
        weather_file: Path to EPW weather file. Uses previously downloaded file if None.
        design_day: Run design-day-only simulation.
        annual: Run annual simulation.
        energyplus_dir: Optional explicit EnergyPlus installation directory or executable path.
        energyplus_version: Optional EnergyPlus version filter (e.g. "25.1.0").
        output_directory: Optional explicit output directory for simulation results.
    """
    from pathlib import Path

    from idfkit.simulation.config import find_energyplus
    from idfkit.simulation.runner import simulate

    state = get_state()
    doc = state.require_model()

    epw_path: Path | None = None
    if weather_file is not None:
        epw_path = Path(weather_file)
    elif state.weather_file is not None:
        epw_path = state.weather_file

    if epw_path is None and not design_day:
        return {
            "error": "No weather file specified. Provide weather_file or use download_weather_file first, or set design_day=True."
        }

    config = find_energyplus(path=energyplus_dir, version=energyplus_version)

    output_dir = Path(output_directory) if output_directory is not None else None
    weather = epw_path if epw_path is not None else ""
    result = simulate(
        doc, weather=weather, design_day=design_day, annual=annual, energyplus=config, output_dir=output_dir
    )

    state.simulation_result = result

    errors = result.errors

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

    return {
        "success": result.success,
        "runtime_seconds": round(result.runtime_seconds, 2),
        "output_directory": str(result.run_dir),
        "energyplus": {
            "version": ".".join(str(part) for part in config.version),
            "install_dir": str(config.install_dir),
            "executable": str(config.executable),
        },
        "errors": error_detail,
        "simulation_complete": errors.simulation_complete,
    }


@_safe_tool
def get_results_summary() -> dict[str, Any]:
    """Get a summary of the last simulation results.

    Returns energy metrics, error counts, and key tables from the HTML output.
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
        for table in html.tables[:20]:
            table_info: dict[str, Any] = {
                "title": table.title,
                "report": table.report_name,
                "for": table.for_string,
            }
            table_dict = table.to_dict()
            if table_dict:
                table_info["data"] = table_dict
            tables_summary.append(table_info)
        summary["tables"] = tables_summary

    return summary


@_safe_tool
def list_output_variables(search: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List available output variables from the last simulation.

    Args:
        search: Optional regex pattern to filter variables by name.
        limit: Maximum number of results (default 50).
    """
    state = get_state()
    result = state.require_simulation_result()

    variables = result.variables
    if variables is None:
        return {"error": "No output variable index available. The simulation may not have produced .rdd/.mdd files."}

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
    return {"total_available": total, "returned": len(serialized), "variables": serialized}


@_safe_tool
def query_timeseries(
    variable_name: str,
    key_value: str = "*",
    frequency: str | None = None,
    environment: Literal["sizing", "annual"] | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    """Query time series data from the last simulation's SQL output.

    Returns the first `limit` data points inline for quick inspection.

    Args:
        variable_name: The output variable name (e.g. "Zone Mean Air Temperature").
        key_value: Key value such as zone or surface name. Use "*" for environment-level variables.
        frequency: Optional frequency filter (e.g. "Hourly").
        environment: Filter by environment type: "sizing" or "annual".
        limit: Maximum number of data points to return (default 24).
    """
    state = get_state()
    result = state.require_simulation_result()

    sql = result.sql
    if sql is None:
        return {"error": "No SQL output available. The simulation may not have produced an .sql file."}

    ts = sql.get_timeseries(
        variable_name=variable_name,
        key_value=key_value,
        frequency=frequency,
        environment=environment,
    )

    rows = [
        {"timestamp": ts.timestamps[i].isoformat(), "value": ts.values[i]} for i in range(min(limit, len(ts.values)))
    ]

    return {
        "variable_name": ts.variable_name,
        "key_value": ts.key_value,
        "units": ts.units,
        "frequency": ts.frequency,
        "total_points": len(ts.values),
        "returned": len(rows),
        "data": rows,
    }


@_safe_tool
def export_timeseries(
    variable_name: str,
    key_value: str = "*",
    frequency: str | None = None,
    environment: Literal["sizing", "annual"] | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Export time series data from the last simulation to a CSV file.

    Args:
        variable_name: The output variable name (e.g. "Zone Mean Air Temperature").
        key_value: Key value such as zone or surface name. Use "*" for environment-level variables.
        frequency: Optional frequency filter (e.g. "Hourly").
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
        return {"error": "No SQL output available. The simulation may not have produced an .sql file."}

    ts = sql.get_timeseries(
        variable_name=variable_name,
        key_value=key_value,
        frequency=frequency,
        environment=environment,
    )

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

    return {
        "path": str(csv_path),
        "variable_name": ts.variable_name,
        "key_value": ts.key_value,
        "units": ts.units,
        "frequency": ts.frequency,
        "rows": len(ts.values),
    }
