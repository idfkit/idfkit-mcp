"""Simulation tools."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

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


@_safe_tool
def run_simulation(
    weather_file: str | None = None,
    design_day: bool = False,
    annual: bool = False,
    energyplus_dir: str | None = None,
    energyplus_version: str | None = None,
) -> dict[str, Any]:
    """Run an EnergyPlus simulation on the loaded model.

    Args:
        weather_file: Path to EPW weather file. Uses previously downloaded file if None.
        design_day: Run design-day-only simulation.
        annual: Run annual simulation.
        energyplus_dir: Optional explicit EnergyPlus installation directory or executable path.
        energyplus_version: Optional EnergyPlus version filter (e.g. "25.1.0").
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

    weather = epw_path if epw_path is not None else ""
    result = simulate(doc, weather=weather, design_day=design_day, annual=annual, energyplus=config)

    state.simulation_result = result

    errors = result.errors
    return {
        "success": result.success,
        "runtime_seconds": round(result.runtime_seconds, 2),
        "output_directory": str(result.run_dir),
        "energyplus": {
            "version": ".".join(str(part) for part in config.version),
            "install_dir": str(config.install_dir),
            "executable": str(config.executable),
        },
        "errors": {
            "fatal": errors.fatal_count,
            "severe": errors.severe_count,
            "warnings": errors.warning_count,
        },
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
