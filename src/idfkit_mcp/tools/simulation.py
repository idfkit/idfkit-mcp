"""Simulation tools."""

from __future__ import annotations

import logging
import re
from sqlite3 import OperationalError
from typing import Annotated, Any, Literal

from fastmcp import Context
from fastmcp.apps import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.exceptions import ToolError
from fastmcp.resources.function_resource import resource
from fastmcp.tools import tool
from idfkit import IDFDocument
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.models import (
    ClassifiedWarning,
    EndUseRow,
    ExportTimeseriesResult,
    GetResultsSummaryResult,
    ListOutputVariablesResult,
    QuerySimulationTableResult,
    QueryTimeseriesResult,
    ReportSection,
    ReportTable,
    ReportTableRow,
    RunSimulationResult,
    SimulationQAFlag,
    SimulationReportResult,
    TabularRow,
    UnmetHoursRow,
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


def _ensure_sqlite_output(doc: IDFDocument[Literal[True]]) -> None:
    """Ensure simulations produce SQLite tabular output for downstream tools.

    Many read-only tools and embedded apps rely on the EnergyPlus SQLite file.
    Upgrade an existing ``Output:SQLite`` object in place when possible rather
    than adding duplicates.  Also override ``OutputControl:Files`` when it
    explicitly suppresses SQLite or tabular output.
    """
    if "Output:SQLite" not in doc:
        doc.add("Output:SQLite", "", option_type="SimpleAndTabular")
        logger.info("Added Output:SQLite with option_type=SimpleAndTabular before simulation")
    else:
        obj = doc["Output:SQLite"].first()
        if not obj:
            doc.add("Output:SQLite", "", option_type="SimpleAndTabular")
            logger.info("Added missing Output:SQLite entry to existing collection before simulation")
        elif obj.option_type != "SimpleAndTabular":
            obj.option_type = "SimpleAndTabular"
            logger.info("Updated Output:SQLite to option_type=SimpleAndTabular before simulation")

    # OutputControl:Files can suppress SQLite/tabular file generation even when
    # Output:SQLite is present. Force the relevant flags to "Yes".
    if "OutputControl:Files" in doc:
        ctrl = doc["OutputControl:Files"].first()
        if ctrl:
            changed = False
            if ctrl.output_sqlite != "Yes":
                ctrl.output_sqlite = "Yes"
                changed = True
            if ctrl.output_tabular != "Yes":
                ctrl.output_tabular = "Yes"
                changed = True
            if changed:
                logger.info("Enabled output_sqlite and output_tabular in OutputControl:Files")


# Summary reports that downstream tools and viewers require.
_REQUIRED_SUMMARY_REPORTS = frozenset({
    "AnnualBuildingUtilityPerformanceSummary",
    "InputVerificationandResultsSummary",
    "SensibleHeatGainSummary",
    "SystemSummary",
    "HVACSizingSummary",
})


def _ensure_summary_reports(doc: IDFDocument[Literal[True]]) -> None:
    """Ensure ``Output:Table:SummaryReports`` includes reports needed by downstream tools."""
    if "Output:Table:SummaryReports" not in doc:
        doc.add(
            "Output:Table:SummaryReports",
            data={
                f"report_name{'_' + str(i) if i > 1 else ''}": name
                for i, name in enumerate(sorted(_REQUIRED_SUMMARY_REPORTS), 1)
            },
        )
        logger.info("Added Output:Table:SummaryReports with %s", sorted(_REQUIRED_SUMMARY_REPORTS))
        return

    obj = doc["Output:Table:SummaryReports"].first()
    if not obj:
        return

    # Collect existing report names and find the next available index.
    existing: set[str] = set()
    idx = 1
    while True:
        field = "report_name" if idx == 1 else f"report_name_{idx}"
        val = getattr(obj, field, None)
        if val is None:
            break
        existing.add(val)
        idx += 1

    # "AllSummary" or "AllSummaryAndMonthly" already include everything.
    if existing & {
        "All",
        "AllSummary",
        "AllSummaryAndMonthly",
        "AllSummaryAndSizingPeriod",
        "AllSummaryMonthlyAndSizingPeriod",
    }:
        return

    missing = _REQUIRED_SUMMARY_REPORTS - existing
    if not missing:
        return

    for name in sorted(missing):
        field = "report_name" if idx == 1 else f"report_name_{idx}"
        setattr(obj, field, name)
        idx += 1
    logger.info("Added missing summary reports: %s", sorted(missing))


def _resolve_simulation_output_dir(explicit: str | None, session_id: str) -> str | None:
    """Resolve the EnergyPlus run directory.

    Precedence:
      1. ``explicit`` output_directory argument (tool param) wins when set.
      2. ``IDFKIT_MCP_SIMULATION_DIR`` env var — each run gets its own subdir
         ``<env>/<session_id>-<utc-stamp>/`` so concurrent sessions don't clobber.
      3. ``None`` — idfkit picks its default (a tempdir).
    """
    if explicit is not None:
        return explicit
    import os
    from datetime import datetime, timezone

    env = os.environ.get("IDFKIT_MCP_SIMULATION_DIR")
    if not env:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    from pathlib import Path

    run_dir = Path(env) / f"{session_id}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return str(run_dir)


def _build_progress_handler(ctx: Context | None) -> Any:
    """Build an async progress callback for FastMCP context reporting."""
    from idfkit.simulation.progress import SimulationProgress

    async def on_progress(event: SimulationProgress) -> None:
        if ctx is not None and event.percent is not None:
            await ctx.report_progress(progress=event.percent, total=100.0)
        if ctx is not None:
            await ctx.info(f"[{event.phase}] {event.message}")

    return on_progress


@tool(annotations=_RUN)
async def run_simulation(
    weather_file: Annotated[str | None, Field(description="EPW path (default: last downloaded).")] = None,
    design_day: Annotated[bool, Field(description="Design-day only.")] = False,
    annual: Annotated[bool, Field(description="Annual simulation.")] = False,
    energyplus_dir: Annotated[str | None, Field(description="EnergyPlus install dir.")] = None,
    energyplus_version: Annotated[str | None, Field(description='Version filter "X.Y.Z".')] = None,
    output_directory: Annotated[str | None, Field(description="Output dir.")] = None,
    ctx: Context | None = None,
) -> RunSimulationResult:
    """Execute EnergyPlus on the loaded model — the authoritative runtime validation gate.

    Fatal or severe errors mean the model did not simulate correctly. A clean exit does
    not guarantee physically reasonable results. After this call, read the resource
    ``idfkit://simulation/results`` for full QA diagnostics: unmet hours by zone,
    end-use energy breakdown, classified warnings, and QA flags that drive the fix loop.

    Preconditions: model loaded; weather file set via download_weather_file, or design_day=True.
    Side effects: writes outputs to output_directory; updates session simulation result.
    Next step: read idfkit://simulation/results to assess result quality.
    """
    from idfkit.simulation import async_simulate
    from idfkit.simulation.config import find_energyplus

    state = get_state()
    doc = state.require_model()
    weather = _resolve_weather_path(weather_file, design_day)

    # Simulate on a copy so pre-flight injections (Output:SQLite,
    # Output:Table:SummaryReports) do not mutate the user's loaded model.
    sim_doc = doc.copy()
    _ensure_sqlite_output(sim_doc)
    _ensure_summary_reports(sim_doc)

    config = find_energyplus(path=energyplus_dir, version=energyplus_version)
    resolved_output_dir = _resolve_simulation_output_dir(output_directory, state.session_id)
    logger.info(
        "Starting simulation (EnergyPlus %s, weather=%s, design_day=%s, annual=%s)",
        ".".join(str(p) for p in config.version),
        weather,
        design_day,
        annual,
    )

    result = await async_simulate(
        sim_doc,
        weather="" if weather is None else weather,
        design_day=design_day,
        annual=annual,
        energyplus=config,
        output_dir=resolved_output_dir,
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


_GJ_TO_KWH = 277.778
"""Conversion factor: 1 GJ = 277.778 kWh (EnergyPlus tabular energy is in GJ by default)."""

_ABUPS = "AnnualBuildingUtilityPerformanceSummary"
"""EnergyPlus SQL report name for annual building utility performance."""

_SYSTEM_SUMMARY = "SystemSummary"
"""EnergyPlus SQL report name for system-level summaries including unmet hours."""

# End-use fuel columns that map to district energy (combined into district_heating_kwh)
_DISTRICT_HEATING_COLS = frozenset({"District Heating Water", "District Heating Steam"})
# All other non-Electricity, non-Natural Gas, non-district fuel columns
_OTHER_FUEL_COLS = frozenset({
    "Coal",
    "Diesel",
    "Fuel Oil No 1",
    "Fuel Oil No 2",
    "Gasoline",
    "Other Fuel 1",
    "Other Fuel 2",
    "Propane",
})

_WARNING_CATEGORIES: list[tuple[str, list[str]]] = [
    ("convergence", ["converge", "did not converge", "warmup", "iteration"]),
    ("geometry", ["surface", "vertices", "area", "normal", "tilt", "azimuth", "intersect"]),
    ("unusual_value", ["unusual", "out of range", "extreme", "very large", "very small"]),
    ("hvac", ["hvac", "air loop", "airloop", "coil", "zone equipment", "plant loop", "chiller"]),
]


def _try_float(s: str) -> float | None:
    """Parse a string to float, returning None on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _classify_warnings(errors: Any) -> list[ClassifiedWarning]:
    """Classify simulation warnings from the .err file by domain category."""
    classified: list[ClassifiedWarning] = []
    for msg in errors.warnings:
        text = (msg.message + " " + " ".join(msg.details)).lower()
        category = "other"
        for cat, keywords in _WARNING_CATEGORIES:
            if any(kw in text for kw in keywords):
                category = cat
                break
        classified.append(ClassifiedWarning(category=category, message=msg.message, details=list(msg.details)))
    return classified


def _query_unmet_hours(sql: Any) -> tuple[list[UnmetHoursRow], float, float]:
    """Query unmet heating/cooling hours by zone from SystemSummary SQL tabular data."""
    from collections import defaultdict

    # EnergyPlus stores "Time Setpoint Not Met" in SystemSummary, not ABUPS
    rows = sql.get_tabular_data(report_name=_SYSTEM_SUMMARY, table_name="Time Setpoint Not Met")
    zone_data: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        val = _try_float(row.value)
        if val is None or row.row_name.lower() in ("facility", "total"):
            continue
        zone_data[row.row_name][row.column_name] = val

    result_rows: list[UnmetHoursRow] = []
    total_heat = 0.0
    total_cool = 0.0
    for zone, cols in sorted(zone_data.items()):
        # Use "During Heating"/"During Cooling"; fall back to occupied variants
        heat = cols.get("During Heating", cols.get("During Occupied Heating", 0.0))
        cool = cols.get("During Cooling", cols.get("During Occupied Cooling", 0.0))
        result_rows.append(UnmetHoursRow(zone=zone, heating_hours=heat, cooling_hours=cool))
        total_heat += heat
        total_cool += cool
    return result_rows, total_heat, total_cool


def _query_end_uses(sql: Any) -> list[EndUseRow]:
    """Query end-use energy breakdown from SQL tabular data (all major fuel types)."""
    from collections import defaultdict

    _SKIP_ROWS = {"total end uses", "total"}
    rows = sql.get_tabular_data(report_name=_ABUPS, table_name="End Uses")

    # Pivot: {end_use: {column_name: value_gj}}
    pivot: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        if row.row_name.lower() in _SKIP_ROWS:
            continue
        val = _try_float(row.value)
        if val is not None and val > 0:
            pivot[row.row_name][row.column_name] = val

    result: list[EndUseRow] = []
    for end_use, fuels in sorted(pivot.items()):
        elec_gj = fuels.get("Electricity")
        gas_gj = fuels.get("Natural Gas")
        dc_gj = fuels.get("District Cooling")
        dh_gj = sum(fuels[c] for c in _DISTRICT_HEATING_COLS if c in fuels) or None
        other_gj = sum(fuels[c] for c in _OTHER_FUEL_COLS if c in fuels) or None
        result.append(
            EndUseRow(
                end_use=end_use,
                electricity_kwh=round(elec_gj * _GJ_TO_KWH, 1) if elec_gj is not None else None,
                natural_gas_kwh=round(gas_gj * _GJ_TO_KWH, 1) if gas_gj is not None else None,
                district_cooling_kwh=round(dc_gj * _GJ_TO_KWH, 1) if dc_gj is not None else None,
                district_heating_kwh=round(dh_gj * _GJ_TO_KWH, 1) if dh_gj else None,
                other_kwh=round(other_gj * _GJ_TO_KWH, 1) if other_gj else None,
            )
        )
    return result


def _build_qa_flags(
    errors: Any,
    total_unmet_heating: float,
    total_unmet_cooling: float,
    classified: list[ClassifiedWarning],
    sql_available: bool,
) -> list[SimulationQAFlag]:
    """Derive high-level QA flags from simulation diagnostics."""
    flags: list[SimulationQAFlag] = []

    if errors.has_fatal:
        flags.append(
            SimulationQAFlag(
                severity="critical",
                flag="fatal_errors",
                message=f"{errors.fatal_count} fatal error(s) — model did not simulate. Fix before proceeding.",
            )
        )
    if errors.has_severe:
        flags.append(
            SimulationQAFlag(
                severity="warning",
                flag="severe_errors",
                message=f"{errors.severe_count} severe error(s) — results may be unreliable.",
            )
        )

    total_unmet = total_unmet_heating + total_unmet_cooling
    if total_unmet > 1000:
        flags.append(
            SimulationQAFlag(
                severity="critical",
                flag="very_high_unmet_hours",
                message=f"{total_unmet:.0f} total unmet hours — HVAC system is severely undersized or misconfigured.",
            )
        )
    elif total_unmet > 300:
        flags.append(
            SimulationQAFlag(
                severity="warning",
                flag="high_unmet_hours",
                message=f"{total_unmet:.0f} total unmet hours — review HVAC sizing and thermostat setpoints.",
            )
        )

    convergence_count = sum(1 for w in classified if w.category == "convergence")
    if convergence_count > 0:
        flags.append(
            SimulationQAFlag(
                severity="warning",
                flag="convergence_warnings",
                message=f"{convergence_count} convergence warning(s) — check HVAC controls and timestep.",
            )
        )

    if not sql_available:
        flags.append(
            SimulationQAFlag(
                severity="info",
                flag="no_sql_output",
                message="SQL output not available. Add Output:SQLite to the model for energy diagnostics.",
            )
        )

    return flags


def get_results_summary() -> GetResultsSummaryResult:
    """Build results summary with QA diagnostics from the last simulation.

    This function powers the ``idfkit://simulation/results`` resource — the primary
    feedback signal for the agent QA loop.
    """
    state = get_state()
    result = state.require_simulation_result()

    errors = result.errors
    fatal_msgs = [{"message": m.message, "details": list(m.details)} for m in errors.fatal]
    severe_msgs = [{"message": m.message, "details": list(m.details)} for m in errors.severe[:10]]

    classified = _classify_warnings(errors)

    # --- SQL-based diagnostics (defensive: degrade gracefully if SQL unavailable) ---
    sql_available = False
    unmet_hours: list[UnmetHoursRow] = []
    total_unmet_heating = 0.0
    total_unmet_cooling = 0.0
    end_uses: list[EndUseRow] = []
    notes: list[str] = []

    if result.sql_path is not None:
        try:
            from idfkit.simulation.parsers.sql import SQLResult

            with SQLResult(result.sql_path) as sql:
                sql_available = True
                try:
                    unmet_hours, total_unmet_heating, total_unmet_cooling = _query_unmet_hours(sql)
                except Exception as e:
                    notes.append(f"Unmet hours unavailable: {e}")
                try:
                    end_uses = _query_end_uses(sql)
                except Exception as e:
                    notes.append(f"End-use data unavailable: {e}")
        except Exception as e:
            notes.append(f"SQL data unavailable: {e}")
    else:
        notes.append("No SQL output file. Add Output:SQLite to the model for energy diagnostics.")

    qa_flags = _build_qa_flags(errors, total_unmet_heating, total_unmet_cooling, classified, sql_available)

    return GetResultsSummaryResult.model_validate({
        "success": result.success,
        "runtime_seconds": round(result.runtime_seconds, 2),
        "output_directory": str(result.run_dir),
        "errors": {
            "fatal": errors.fatal_count,
            "severe": errors.severe_count,
            "warnings": errors.warning_count,
            "summary": errors.summary(),
        },
        "fatal_messages": fatal_msgs if fatal_msgs else None,
        "severe_messages": severe_msgs if severe_msgs else None,
        "sql_available": sql_available,
        "unmet_hours": [u.model_dump() for u in unmet_hours] if sql_available else None,
        "total_unmet_heating_hours": total_unmet_heating if sql_available else None,
        "total_unmet_cooling_hours": total_unmet_cooling if sql_available else None,
        "end_uses": [e.model_dump() for e in end_uses] if sql_available else None,
        "classified_warnings": [w.model_dump() for w in classified] if classified else None,
        "qa_flags": [f.model_dump() for f in qa_flags] if qa_flags else None,
        "notes": notes if notes else None,
    })


@tool(annotations=_READ_ONLY)
def list_output_variables(
    search: Annotated[str | None, Field(description="Regex filter on name (case-insensitive).")] = None,
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
        if search:
            try:
                regex = re.compile(search, re.IGNORECASE)
            except re.error as exc:
                raise ToolError(f"Invalid regex pattern: {exc}") from None
        else:
            regex = None
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


@tool(annotations=_READ_ONLY)
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


@tool(annotations=_READ_ONLY)
def query_simulation_table(
    report_name: Annotated[
        str,
        Field(
            description="Report name (e.g. 'AnnualBuildingUtilityPerformanceSummary', 'SystemSummary'). Use list_simulation_reports to discover available names."
        ),
    ],
    table_name: Annotated[
        str | None,
        Field(
            description="Table name within the report (e.g. 'End Uses', 'Time Setpoint Not Met'). Omit to return all tables in the report."
        ),
    ] = None,
    row_name: Annotated[str | None, Field(description="Filter to a specific row label.")] = None,
    column_name: Annotated[str | None, Field(description="Filter to a specific column label.")] = None,
) -> QuerySimulationTableResult:
    """Query tabular report data from the last simulation's SQL output.

    Use this for deeper analysis beyond the structured diagnostics in
    ``idfkit://simulation/results``. Tabular data covers every EnergyPlus
    summary report: energy use, envelope, HVAC sizing, comfort, and more.

    Omit ``table_name`` to retrieve all tables within a report at once.
    To discover available report names call ``list_simulation_reports`` first.
    Common report names:
      - ``AnnualBuildingUtilityPerformanceSummary`` — site/source energy, end uses, EUI
      - ``SystemSummary`` — unmet hours, HVAC sizing
      - ``EnvelopeSummary`` — U-values, areas, orientations
      - ``EquipmentSummary`` — HVAC component sizing
      - ``ZoneComponentLoadSummary`` — peak heating/cooling loads by zone
      - ``LightingSummary`` — lighting power density

    Preconditions: simulation completed with SQL output available (``sql_available: true``
    in ``idfkit://simulation/results``).
    Side effects: none — read-only.
    """
    state = get_state()
    result = state.require_simulation_result()

    with _open_sql_result(result) as sql:
        raw_rows = sql.get_tabular_data(
            report_name=report_name,
            table_name=table_name,
            row_name=row_name,
            column_name=column_name,
        )

    if not raw_rows:
        msg = f"No data found for report '{report_name}'"
        if table_name is not None:
            msg += f", table '{table_name}'"
        msg += ". Use list_simulation_reports to see available reports."
        raise ToolError(msg)

    rows = [
        TabularRow(
            report_name=r.report_name,
            report_for=r.report_for,
            table_name=r.table_name,
            row_name=r.row_name,
            column_name=r.column_name,
            units=r.units or "",
            value=r.value.strip(),
        )
        for r in raw_rows
    ]
    return QuerySimulationTableResult(
        report_name=report_name,
        table_name=table_name,
        row_count=len(rows),
        rows=rows,
    )


@tool(annotations=_READ_ONLY)
def list_simulation_reports() -> list[str]:
    """List all tabular report names available in the last simulation's SQL output.

    Use the returned names with ``query_simulation_table`` to retrieve specific tables.

    Preconditions: simulation completed with SQL output available.
    Side effects: none — read-only.
    """
    state = get_state()
    result = state.require_simulation_result()

    with _open_sql_result(result) as sql:
        return sql.list_reports()


# ---------------------------------------------------------------------------
# Simulation report viewer
# ---------------------------------------------------------------------------


def _collect_tabular_sections(sql: Any) -> tuple[list[ReportSection], int]:
    """Query all tabular data from SQL and organize into report sections."""
    from collections import defaultdict

    report_names = sql.list_reports()
    sections: dict[tuple[str, str], dict[str, dict[str, dict[str, str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )
    column_order: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    column_seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    row_order: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    row_seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    for report_name in report_names:
        for r in sql.get_tabular_data(report_name=report_name):
            for_str = r.report_for or "Entire Facility"
            sections[(report_name, for_str)][r.table_name][r.row_name][r.column_name] = r.value.strip()
            table_key = (report_name, for_str, r.table_name)
            if r.column_name not in column_seen[table_key]:
                column_seen[table_key].add(r.column_name)
                column_order[table_key].append(r.column_name)
            if r.row_name not in row_seen[table_key]:
                row_seen[table_key].add(r.row_name)
                row_order[table_key].append(r.row_name)

    result_sections: list[ReportSection] = []
    table_count = 0
    for (report_name, for_string), tables_dict in sections.items():
        tables: list[ReportTable] = []
        for table_name, rows_dict in tables_dict.items():
            table_key = (report_name, for_string, table_name)
            cols = column_order[table_key]
            table_rows = [
                ReportTableRow(label=rn, values=[rows_dict.get(rn, {}).get(c, "") for c in cols])
                for rn in row_order[table_key]
            ]
            tables.append(ReportTable(table_name=table_name, columns=cols, rows=table_rows))
            table_count += 1
        result_sections.append(ReportSection(report_name=report_name, for_string=for_string, tables=tables))
    return result_sections, table_count


def build_simulation_report() -> SimulationReportResult:
    """Build the full tabular report from the simulation SQL output."""
    state = get_state()
    result = state.require_simulation_result()

    # Single SQL connection for both tabular data and metadata extraction.
    energyplus_version = ""
    environment = ""
    timestamp = ""
    with _open_sql_result(result) as sql:
        report_sections, table_count = _collect_tabular_sections(sql)
        try:
            sim_rows = sql.query("SELECT EnergyPlusVersion, TimeStamp FROM Simulations LIMIT 1")
            if sim_rows:
                energyplus_version = str(sim_rows[0][0] or "")
                timestamp = str(sim_rows[0][1] or "")
            envs = sql.list_environments()
            if envs:
                environment = ", ".join(e.name for e in envs)
        except Exception:
            logger.debug("Could not extract simulation metadata from SQL", exc_info=True)

    building = "Unknown"
    doc = state.document
    if doc is not None and "Building" in doc:
        bldg = doc["Building"].first()
        if bldg is not None:
            building = bldg.name or "Unknown"

    return SimulationReportResult(
        building_name=building,
        environment=environment,
        energyplus_version=energyplus_version,
        timestamp=timestamp,
        report_count=len(report_sections),
        table_count=table_count,
        reports=report_sections,
    )


@tool(
    annotations=_READ_ONLY,
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                resourceUri="ui://idfkit/report-viewer.html",
                prefersBorder=False,
            )
        )
    },
)
def view_simulation_report() -> SimulationReportResult:
    """Browse the full EnergyPlus tabular report in an interactive viewer.

    Returns all tabular data from the simulation SQL output organized by
    report, section, and table. The companion viewer provides a searchable,
    browsable interface with a table-of-contents sidebar.

    Requires a completed simulation with SQL output.
    """
    return build_simulation_report()


@resource(
    "ui://idfkit/report-viewer.html",
    name="report_viewer",
    title="Simulation Report Viewer",
    description="Interactive browser for EnergyPlus tabular simulation reports.",
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                csp=ResourceCSP(resourceDomains=["https://unpkg.com"]),
                prefersBorder=False,
            )
        )
    },
)
def report_viewer_html() -> str:
    """Return the self-contained report viewer HTML."""
    from idfkit_mcp.report_viewer import REPORT_VIEWER_HTML

    return REPORT_VIEWER_HTML


@tool(annotations=_EXPORT)
def export_timeseries(
    variable_name: Annotated[str, Field(description="Variable name.")],
    key_value: Annotated[str, Field(description='Zone/surface or "*".')] = "*",
    frequency: Annotated[ReportingFrequency | None, Field(description="Reporting frequency.")] = None,
    environment: Annotated[Literal["sizing", "annual"] | None, Field(description="Environment filter.")] = None,
    output_path: Annotated[str | None, Field(description="CSV path (default: output dir).")] = None,
) -> ExportTimeseriesResult:
    """Export time series to CSV."""
    import csv
    from pathlib import Path

    # Validate output path early, before the (potentially slow) SQL query.
    validated_output_path: Path | None = None
    if output_path is not None:
        from idfkit_mcp.tools._path_validation import validate_output_path

        validated_output_path = validate_output_path(Path(output_path), label="Export path")

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

    if validated_output_path is not None:
        csv_path = validated_output_path
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
