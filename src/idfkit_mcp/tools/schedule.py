"""Schedule visualizer tool — renders EnergyPlus schedules as interactive heatmaps."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Annotated

from fastmcp.apps import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources.function_resource import resource
from fastmcp.tools import ToolResult, tool
from mcp.types import TextContent, ToolAnnotations
from pydantic import Field

from idfkit_mcp.schedule_viewer import SCHEDULE_VIEWER_HTML
from idfkit_mcp.state import get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

# Top-level schedule types that are meaningful to visualize standalone.
_TOP_LEVEL_SCHEDULE_TYPES = (
    "Schedule:Compact",
    "Schedule:Constant",
    "Schedule:Year",
    "Schedule:File",
)

# All schedule types that values() can evaluate.
_ALL_SCHEDULE_TYPES = (
    *_TOP_LEVEL_SCHEDULE_TYPES,
    "Schedule:Day:Hourly",
    "Schedule:Day:Interval",
    "Schedule:Day:List",
    "Schedule:Week:Daily",
    "Schedule:Week:Compact",
)

_MAX_SCHEDULES = 30


def _resolve_type_limits(doc: object, limits_name: str | None) -> dict[str, object] | None:
    """Look up ScheduleTypeLimits and extract bounds."""
    if not limits_name:
        return None
    collection = doc.get_collection("ScheduleTypeLimits")  # type: ignore[union-attr]
    if not collection:
        return None
    from typing import Any, cast

    obj: Any = cast(Any, collection).get(limits_name)
    if obj is None:
        return None
    lower = getattr(obj, "lower_limit_value", None)
    upper = getattr(obj, "upper_limit_value", None)
    numeric_type = getattr(obj, "numeric_type", None) or "Continuous"
    unit_type = getattr(obj, "unit_type", None) or "Dimensionless"
    return {
        "name": limits_name,
        "lower": float(lower) if lower is not None else None,  # type: ignore[arg-type]
        "upper": float(upper) if upper is not None else None,  # type: ignore[arg-type]
        "numericType": str(numeric_type),
        "unitType": str(unit_type),
    }


def _evaluate_one(
    obj: object,
    obj_type: str,
    doc: object,
    year: int,
) -> dict[str, object] | None:
    """Evaluate a single schedule object, returning None on failure."""
    from idfkit.schedules.evaluate import ScheduleEvaluationError, values

    try:
        vals = values(obj, year=year, document=doc)  # type: ignore[arg-type]
    except ScheduleEvaluationError as e:
        logger.warning("Failed to evaluate schedule '%s': %s", getattr(obj, "name", "?"), e)
        return None
    limits_name = getattr(obj, "schedule_type_limits_name", None)
    return {
        "name": getattr(obj, "name", "") or "",
        "objectType": obj_type,
        "values": [round(v, 4) for v in vals],
        "typeLimits": _resolve_type_limits(doc, str(limits_name) if limits_name else None),
    }


def _find_schedule_by_name(
    name: str,
    doc: object,
    year: int,
) -> tuple[list[dict[str, object]], list[str]]:
    """Search all schedule types for a specific named schedule."""
    from typing import Any, cast

    schedules: list[dict[str, object]] = []
    skipped: list[str] = []
    for obj_type in _ALL_SCHEDULE_TYPES:
        collection = doc.get_collection(obj_type)  # type: ignore[union-attr]
        if not collection:
            continue
        obj: Any = cast(Any, collection).get(name)
        if obj is not None:
            result = _evaluate_one(obj, obj_type, doc, year)
            if result is not None:
                schedules.append(result)
            else:
                skipped.append(name)
            return schedules, skipped
    from fastmcp.exceptions import ToolError

    msg = f"Schedule '{name}' not found in the model."
    raise ToolError(msg)


def _collect_all_schedules(
    doc: object,
    year: int,
) -> tuple[list[dict[str, object]], list[str]]:
    """Collect and evaluate all top-level schedules from the model."""
    from typing import Any, cast

    schedules: list[dict[str, object]] = []
    skipped: list[str] = []
    for obj_type in _TOP_LEVEL_SCHEDULE_TYPES:
        collection: Any = cast(Any, doc).get_collection(obj_type)
        if not collection:
            continue
        for obj in collection:
            if len(schedules) >= _MAX_SCHEDULES:
                break
            result = _evaluate_one(obj, obj_type, doc, year)
            if result is not None:
                schedules.append(result)
            else:
                skipped.append(str(getattr(obj, "name", "?") or "?"))
    return schedules, skipped


def _extract_schedules(name: str | None, year: int) -> dict[str, object]:
    """Evaluate schedule(s) and return hourly values for the viewer."""
    state = get_state()
    doc = state.require_model()

    schedules: list[dict[str, object]] = []
    skipped: list[str] = []

    if name is not None:
        schedules, skipped = _find_schedule_by_name(name, doc, year)
    else:
        schedules, skipped = _collect_all_schedules(doc, year)

    start_day_of_week = date(year, 1, 1).weekday()  # 0=Monday

    return {
        "schedules": schedules,
        "year": year,
        "startDayOfWeek": start_day_of_week,
        "skipped": skipped,
    }


@tool(
    annotations=_READ_ONLY,
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                resourceUri="ui://idfkit/schedule-viewer.html",
                prefersBorder=False,
            )
        )
    },
)
def view_schedules(
    name: Annotated[
        str | None,
        Field(description="Schedule name to visualize. If omitted, shows all top-level schedules."),
    ] = None,
    year: Annotated[
        int,
        Field(description="Year for schedule evaluation (affects day-of-week alignment).", ge=2000, le=2100),
    ] = 2024,
) -> ToolResult:
    """Show interactive schedule heatmap from the loaded model.

    Renders EnergyPlus schedules as a visual heatmap showing hourly values
    across days of the week (week view) or across the full year (year view).
    Supports Schedule:Compact, Schedule:Constant, Schedule:Year, and
    Schedule:File types.
    """
    data = _extract_schedules(name, year)
    schedule_list: list[dict[str, object]] = data["schedules"]  # type: ignore[assignment]
    skipped_list: list[str] = data["skipped"]  # type: ignore[assignment]
    count = len(schedule_list)
    logger.info("Extracted %d schedules for viewer (skipped %d)", count, len(skipped_list))

    # Text summary for non-Apps clients.
    names = [str(s["name"]) for s in schedule_list]
    summary_parts = [f"Schedule heatmap: {count} schedule(s) evaluated for year {year}."]
    if names:
        summary_parts.append("Schedules: " + ", ".join(names[:10]))
        if len(names) > 10:
            summary_parts.append(f"... and {len(names) - 10} more.")
    if skipped_list:
        summary_parts.append(f"Skipped {len(skipped_list)}: " + "; ".join(skipped_list))

    return ToolResult(
        content=[
            TextContent(type="text", text=json.dumps(data)),
            TextContent(type="text", text=" ".join(summary_parts)),
        ]
    )


@resource(
    "ui://idfkit/schedule-viewer.html",
    name="schedule_viewer",
    title="Schedule Heatmap Viewer",
    description="Interactive heatmap viewer for EnergyPlus schedules.",
    meta={
        "ui": app_config_to_meta_dict(
            AppConfig(
                csp=ResourceCSP(resourceDomains=["https://unpkg.com"]),
                prefersBorder=False,
            )
        )
    },
)
def schedule_viewer_html() -> str:
    """Return the self-contained schedule viewer HTML."""
    return SCHEDULE_VIEWER_HTML
