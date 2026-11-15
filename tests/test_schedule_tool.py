"""Tests for schedule extraction behind the view_schedules tool."""

from __future__ import annotations

from idfkit_mcp.state import ServerState
from idfkit_mcp.tools.schedule import _extract_schedules  # pyright: ignore[reportPrivateUsage]


def _schedules(data: dict[str, object]) -> dict[str, dict[str, object]]:
    items: list[dict[str, object]] = data["schedules"]  # type: ignore[assignment]
    return {str(s["name"]): s for s in items}


class TestExtractSchedules:
    def test_type_limits_resolved(self, state_with_model: ServerState) -> None:
        doc = state_with_model.require_model()
        doc.add(
            "ScheduleTypeLimits",
            "Fraction",
            lower_limit_value=0.0,
            upper_limit_value=1.0,
            numeric_type="Continuous",
        )
        doc.add("Schedule:Constant", "Always Half", schedule_type_limits_name="Fraction", hourly_value=0.5)

        schedules = _schedules(_extract_schedules(None, 2024))

        sched = schedules["Always Half"]
        assert sched["objectType"] == "Schedule:Constant"
        assert sched["typeLimits"] == {
            "name": "Fraction",
            "lower": 0.0,
            "upper": 1.0,
            "numericType": "Continuous",
            "unitType": "Dimensionless",
        }

    def test_missing_type_limits_is_none(self, state_with_model: ServerState) -> None:
        doc = state_with_model.require_model()
        doc.add("Schedule:Constant", "No Limits", hourly_value=1.0)

        schedules = _schedules(_extract_schedules(None, 2024))

        assert schedules["No Limits"]["typeLimits"] is None

    def test_named_lookup(self, state_with_model: ServerState) -> None:
        doc = state_with_model.require_model()
        doc.add("Schedule:Constant", "A", hourly_value=1.0)
        doc.add("Schedule:Constant", "B", hourly_value=0.0)

        schedules = _schedules(_extract_schedules("B", 2024))

        assert list(schedules) == ["B"]
