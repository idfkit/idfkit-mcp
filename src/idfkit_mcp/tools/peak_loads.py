"""Peak load QA/QC analysis tool."""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

from fastmcp.apps import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources.function_resource import resource
from fastmcp.tools import tool
from mcp.types import ToolAnnotations

from idfkit_mcp.models import (
    DesignDaySizing,
    FacilityPeakSummary,
    PeakLoadAnalysisResult,
    PeakLoadComponent,
    ZonePeakLoad,
)
from idfkit_mcp.peak_loads_viewer import PEAK_LOADS_VIEWER_HTML
from idfkit_mcp.state import get_state

logger = logging.getLogger("idfkit_mcp")

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# ---------------------------------------------------------------------------
# Column-name → human-readable component mapping
# ---------------------------------------------------------------------------

# Components that ADD heat (positive = gains)
_GAIN_COMPONENTS: dict[str, str] = {
    "People Sensible Heat Addition": "People",
    "Lights Sensible Heat Addition": "Lighting",
    "Equipment Sensible Heat Addition": "Equipment",
    "Window Heat Addition": "Solar / Windows",
    "Infiltration Heat Addition": "Infiltration",
    "Opaque Surface Conduction and Other Heat Addition": "Envelope",
    "Interzone Air Transfer Heat Addition": "Interzone",
    "HVAC Zone Eq & Other Sensible Air Heating": "HVAC Heating",
    "HVAC Terminal Unit Sensible Air Heating": "HVAC Terminal Heating",
    "HVAC Input Heated Surface Heating": "HVAC Radiant Heating",
}

# Components that REMOVE heat (negative = losses)
_LOSS_COMPONENTS: dict[str, str] = {
    "Equipment Sensible Heat Removal": "Equipment (removal)",
    "Window Heat Removal": "Window (removal)",
    "Infiltration Heat Removal": "Infiltration (removal)",
    "Opaque Surface Conduction and Other Heat Removal": "Envelope (removal)",
    "Interzone Air Transfer Heat Removal": "Interzone (removal)",
    "HVAC Zone Eq & Other Sensible Air Cooling": "HVAC Cooling",
    "HVAC Terminal Unit Sensible Air Cooling": "HVAC Terminal Cooling",
    "HVAC Input Cooled Surface Cooling": "HVAC Radiant Cooling",
}

_ALL_COMPONENTS = {**_GAIN_COMPONENTS, **_LOSS_COMPONENTS}

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


def _open_sql(result: Any) -> Any:
    """Open a fresh SQLResult handle."""
    from idfkit.simulation.parsers.sql import SQLResult

    sql_path = result.sql_path
    if sql_path is None:
        from fastmcp.exceptions import ToolError

        raise ToolError("No SQL output available. Re-run the simulation with Output:SQLite enabled.")
    return SQLResult(sql_path)


def _get_zone_areas(sql: Any) -> dict[str, float]:
    """Return {zone_name: area_m2} from the InputVerification report."""
    rows = sql.get_tabular_data(
        report_name="InputVerificationandResultsSummary",
        table_name="Zone Summary",
        column_name="Area",
    )
    areas: dict[str, float] = {}
    for r in rows:
        with contextlib.suppress(ValueError, TypeError):
            areas[r.row_name] = float(r.value)
    return areas


def _parse_peak_components(
    sql: Any,
    table_name: str,
    zone_areas: dict[str, float],
) -> FacilityPeakSummary:
    """Parse a Peak Cooling/Heating Sensible Heat Gain Components table."""
    rows = sql.get_tabular_data(
        report_name="SensibleHeatGainSummary",
        table_name=table_name,
    )

    # Group rows by zone (row_name)
    by_zone: dict[str, dict[str, str]] = {}
    for r in rows:
        zone = by_zone.setdefault(r.row_name, {})
        zone[r.column_name] = r.value

    # Build zone-level results
    zones: list[ZonePeakLoad] = []
    facility_data: dict[str, str] | None = None

    for zone_name, columns in by_zone.items():
        if zone_name == "Total Facility":
            facility_data = columns
            continue

        components = _extract_components(columns)
        peak_w = sum(abs(c.value_w) for c in components if c.value_w > 0)
        area = zone_areas.get(zone_name)

        zones.append(
            ZonePeakLoad(
                zone_name=zone_name,
                peak_w=round(peak_w, 1),
                peak_w_per_m2=round(peak_w / area, 1) if area and area > 0 else None,
                floor_area_m2=round(area, 2) if area else None,
                peak_timestamp=columns.get("Time of Peak {TIMESTAMP}"),
                components=components,
            )
        )

    # Sort zones by peak descending
    zones.sort(key=lambda z: z.peak_w, reverse=True)

    # Facility total
    total_area = sum(zone_areas.values()) if zone_areas else 0
    if facility_data:
        fac_components = _extract_components(facility_data)
        fac_peak = sum(abs(c.value_w) for c in fac_components if c.value_w > 0)
    else:
        fac_components = []
        fac_peak = sum(z.peak_w for z in zones)

    fac_timestamp = facility_data.get("Time of Peak {TIMESTAMP}") if facility_data else None

    return FacilityPeakSummary(
        peak_w=round(fac_peak, 1),
        peak_w_per_m2=round(fac_peak / total_area, 1) if total_area > 0 else None,
        peak_timestamp=fac_timestamp,
        components=fac_components,
        zones=zones,
    )


def _extract_components(columns: dict[str, str]) -> list[PeakLoadComponent]:
    """Extract named components from a row's column values."""
    components: list[PeakLoadComponent] = []
    total_abs = 0.0
    raw: list[tuple[str, float]] = []

    for col_name, label in _ALL_COMPONENTS.items():
        val_str = columns.get(col_name, "")
        try:
            val = float(val_str)
        except (ValueError, TypeError):
            continue
        if val == 0.0:
            continue
        raw.append((label, val))
        total_abs += abs(val)

    for label, val in raw:
        pct = round(abs(val) / total_abs * 100, 1) if total_abs > 0 else 0
        components.append(PeakLoadComponent(name=label, value_w=round(val, 1), percent=pct))

    # Sort by absolute magnitude descending
    components.sort(key=lambda c: abs(c.value_w), reverse=True)
    return components


def _parse_sizing(sql: Any, table_name: str, zone_areas: dict[str, float]) -> list[DesignDaySizing]:
    """Parse Zone Sensible Cooling/Heating sizing tables."""
    rows = sql.get_tabular_data(report_name="HVACSizingSummary", table_name=table_name)

    by_zone: dict[str, dict[str, str]] = {}
    for r in rows:
        zone = by_zone.setdefault(r.row_name, {})
        zone[r.column_name] = r.value

    results: list[DesignDaySizing] = []
    for zone_name, cols in by_zone.items():
        calc_load = _safe_float(cols.get("Calculated Design Load"))
        user_load = _safe_float(cols.get("User Design Load"))
        area = zone_areas.get(zone_name)
        load_per_m2 = None
        if user_load is not None and area and area > 0:
            load_per_m2 = round(user_load / area, 1)
        elif calc_load is not None and area and area > 0:
            load_per_m2 = round(calc_load / area, 1)

        results.append(
            DesignDaySizing(
                zone_name=zone_name,
                calculated_load_w=round(calc_load, 1) if calc_load is not None else None,
                user_load_w=round(user_load, 1) if user_load is not None else None,
                load_w_per_m2=load_per_m2,
                design_day=cols.get("Design Day Name"),
                peak_timestamp=cols.get("Date/Time Of Peak {TIMESTAMP}"),
            )
        )

    results.sort(key=lambda d: d.user_load_w or d.calculated_load_w or 0, reverse=True)
    return results


def _safe_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# QA flags
# ---------------------------------------------------------------------------


def _generate_flags(  # noqa: C901
    cooling: FacilityPeakSummary,
    heating: FacilityPeakSummary,
    sizing_cooling: list[DesignDaySizing],
    sizing_heating: list[DesignDaySizing],
    total_area: float,
) -> list[str]:
    """Generate QA/QC flags based on the analysis."""
    flags: list[str] = []

    # --- Peak timing checks ---
    cooling_hour = _parse_hour(cooling.peak_timestamp)
    if cooling_hour is not None and not (12 <= cooling_hour <= 20):
        flags.append(
            f"Cooling peak at hour {cooling_hour} - expected mid-to-late afternoon (12-20). "
            "Check schedules and internal gains."
        )

    heating_hour = _parse_hour(heating.peak_timestamp)
    if heating_hour is not None and (10 <= heating_hour <= 16):
        flags.append(
            f"Heating peak at hour {heating_hour} — expected early morning or evening. "
            "Check solar gains and setpoint schedules."
        )

    # --- Component dominance (cooling) ---
    for comp in cooling.components:
        if comp.percent is not None and comp.percent > 40 and "Solar" in comp.name:
            flags.append(
                f"Solar/windows contribute {comp.percent:.0f}% of cooling peak — verify SHGC, window area, and shading."
            )
        if comp.percent is not None and comp.percent > 50 and "Infiltration" in comp.name:
            flags.append(
                f"Infiltration contributes {comp.percent:.0f}% of cooling peak — verify ACH and outdoor air rates."
            )
        if comp.percent is not None and comp.percent > 40 and comp.name == "Equipment":
            flags.append(
                f"Equipment contributes {comp.percent:.0f}% of cooling peak — verify plug load density and schedules."
            )

    # --- Magnitude benchmarks (W/m²) ---
    if cooling.peak_w_per_m2 is not None:
        if cooling.peak_w_per_m2 > 300:
            flags.append(
                f"Cooling peak {cooling.peak_w_per_m2:.0f} W/m² is very high (>300) — "
                "check for unit errors or excessive loads."
            )
        elif cooling.peak_w_per_m2 < 20:
            flags.append(
                f"Cooling peak {cooling.peak_w_per_m2:.0f} W/m² is unusually low (<20) — "
                "verify the model has cooling loads."
            )

    if heating.peak_w_per_m2 is not None:
        if heating.peak_w_per_m2 > 200:
            flags.append(
                f"Heating peak {heating.peak_w_per_m2:.0f} W/m² is very high (>200) — "
                "check envelope assumptions and infiltration."
            )
        elif heating.peak_w_per_m2 < 5:
            flags.append(
                f"Heating peak {heating.peak_w_per_m2:.0f} W/m² is unusually low (<5) — "
                "verify the model has heating loads."
            )

    # --- Design-day vs annual discrepancy ---
    if sizing_cooling and cooling.peak_w > 0:
        total_sizing_clg = sum(d.user_load_w or d.calculated_load_w or 0 for d in sizing_cooling)
        if total_sizing_clg > 0:
            ratio = cooling.peak_w / total_sizing_clg
            if ratio > 1.3:
                flags.append(
                    f"Annual cooling peak is {ratio:.1f}x the design-day sizing — "
                    "design days may not capture worst conditions."
                )
            elif ratio < 0.5:
                flags.append(
                    f"Annual cooling peak is only {ratio:.1f}x the design-day sizing — "
                    "equipment may be significantly oversized."
                )

    # --- Zone-level outliers ---
    if cooling.zones:
        zone_peaks = [z.peak_w_per_m2 for z in cooling.zones if z.peak_w_per_m2 is not None]
        if zone_peaks:
            mean_peak = sum(zone_peaks) / len(zone_peaks)
            for z in cooling.zones[:5]:
                if z.peak_w_per_m2 is not None and z.peak_w_per_m2 > mean_peak * 2.5:
                    flags.append(
                        f"Zone '{z.zone_name}' cooling peak {z.peak_w_per_m2:.0f} W/m² is "
                        f">{2.5:.0f}x the mean — check zone inputs."
                    )

    return flags


def _parse_hour(timestamp: str | None) -> int | None:
    """Extract hour from EnergyPlus timestamp like '23-AUG-19:10'."""
    if not timestamp:
        return None
    match = re.search(r"(\d{1,2}):(\d{2})", timestamp)
    if match:
        return int(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Public analysis function (shared by tool and resource)
# ---------------------------------------------------------------------------


def build_peak_load_analysis() -> PeakLoadAnalysisResult:
    """Run the full peak load QA/QC analysis on the current simulation."""
    state = get_state()
    result = state.require_simulation_result()

    with _open_sql(result) as sql:
        zone_areas = _get_zone_areas(sql)
        total_area = sum(zone_areas.values())

        cooling = _parse_peak_components(sql, "Peak Cooling Sensible Heat Gain Components", zone_areas)
        heating = _parse_peak_components(sql, "Peak Heating Sensible Heat Gain Components", zone_areas)

        sizing_cooling = _parse_sizing(sql, "Zone Sensible Cooling", zone_areas)
        sizing_heating = _parse_sizing(sql, "Zone Sensible Heating", zone_areas)

    flags = _generate_flags(cooling, heating, sizing_cooling, sizing_heating, total_area)

    return PeakLoadAnalysisResult(
        cooling=cooling,
        heating=heating,
        sizing_cooling=sizing_cooling,
        sizing_heating=sizing_heating,
        total_floor_area_m2=round(total_area, 2),
        flags=flags,
    )


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


@tool(
    annotations=_READ_ONLY,
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                resourceUri="ui://idfkit/peak-loads-viewer.html",
                prefersBorder=False,
            )
        )
    },
)
def analyze_peak_loads() -> PeakLoadAnalysisResult:
    """Analyze peak heating and cooling loads for QA/QC.

    Decomposes facility and zone-level peaks into components (solar, people,
    lighting, equipment, infiltration, envelope) and flags potential issues
    such as unusual peak timing, excessive loads, or component dominance.

    Requires a completed simulation with SQL output and the
    SensibleHeatGainSummary and HVACSizingSummary reports.
    """
    return build_peak_load_analysis()


@resource(
    "ui://idfkit/peak-loads-viewer.html",
    name="peak_loads_viewer",
    title="Peak Load Viewer",
    description="Interactive peak load QA/QC viewer for heating and cooling load breakdowns.",
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                csp=ResourceCSP(resourceDomains=["https://unpkg.com"]),
                prefersBorder=False,
            )
        )
    },
)
def peak_loads_viewer_html() -> str:
    """Return the self-contained peak load viewer HTML."""
    return PEAK_LOADS_VIEWER_HTML
