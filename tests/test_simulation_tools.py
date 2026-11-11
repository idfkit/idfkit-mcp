"""Tests for simulation tools."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError
from idfkit.simulation.result import SimulationResult

from idfkit_mcp.models import ListOutputVariablesResult
from idfkit_mcp.state import ServerState
from tests.conftest import call_tool, read_resource_json
from tests.linked_runs import install_run


class TestResolveSimulationOutputDir:
    """IDFKIT_MCP_SIMULATION_DIR default and explicit-override behavior."""

    def test_explicit_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from idfkit_mcp.tools.simulation import _resolve_simulation_output_dir

        monkeypatch.setenv("IDFKIT_MCP_SIMULATION_DIR", str(tmp_path))
        assert _resolve_simulation_output_dir("/explicit/path", "sess-x") == "/explicit/path"

    def test_env_var_creates_per_run_subdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from idfkit_mcp.tools.simulation import _resolve_simulation_output_dir

        monkeypatch.setenv("IDFKIT_MCP_SIMULATION_DIR", str(tmp_path))
        resolved = _resolve_simulation_output_dir(None, "sess-y")
        assert resolved is not None
        run_dir = Path(resolved)
        assert run_dir.is_dir()
        assert run_dir.parent == tmp_path
        assert run_dir.name.startswith("sess-y-")

    def test_env_unset_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from idfkit_mcp.tools.simulation import _resolve_simulation_output_dir

        monkeypatch.delenv("IDFKIT_MCP_SIMULATION_DIR", raising=False)
        assert _resolve_simulation_output_dir(None, "sess-z") is None


class TestRunSimulation:
    async def test_no_model(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "run_simulation")

    async def test_no_weather(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "run_simulation")

    async def test_annual_without_weather_is_refused(self, client: object, state_with_model: ServerState) -> None:
        state_with_model.weather_file = None
        with pytest.raises(ToolError, match="weather_file"):
            await call_tool(client, "run_simulation", {"design_day": True, "annual": True})

    async def test_output_directory_accepted(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError, match=r"weather|No weather"):
            await call_tool(client, "run_simulation", {"output_directory": "/tmp/test_out"})  # noqa: S108

    async def test_defaults_to_latest_energyplus(self, client: object, state_with_model: ServerState) -> None:
        with patch("idfkit.simulation.config.find_energyplus") as mock_find:
            mock_find.side_effect = RuntimeError("test stop")
            with pytest.raises(ToolError):
                await call_tool(client, "run_simulation", {"design_day": True})
            mock_find.assert_called_once_with(path=None, version=None)

    async def test_adds_output_sqlite_when_missing(
        self, client: object, state_with_model: ServerState, tmp_path: Path
    ) -> None:
        fake_config = SimpleNamespace(
            version=(25, 2, 0),
            install_dir=Path("/fake/energyplus"),
            executable=Path("/fake/energyplus/energyplus"),
        )
        fake_errors = SimpleNamespace(
            fatal_count=0,
            severe_count=0,
            warning_count=0,
            has_fatal=False,
            has_severe=False,
            simulation_complete=True,
        )
        fake_result = SimpleNamespace(
            success=True,
            runtime_seconds=0.1,
            run_dir=tmp_path / "fake-run",
            errors=fake_errors,
        )

        async def _fake_simulate(doc: object, **_kwargs: object) -> object:
            collection = doc.get_collection("Output:SQLite")  # type: ignore[union-attr]
            sqlite_object = collection.first()
            assert sqlite_object is not None
            assert sqlite_object.option_type == "SimpleAndTabular"
            return fake_result

        with (
            patch("idfkit.simulation.config.find_energyplus", return_value=fake_config),
            patch("idfkit.simulation.async_simulate", side_effect=_fake_simulate),
        ):
            result = await call_tool(client, "run_simulation", {"design_day": True})

        assert result["success"] is True
        # The original model must NOT be mutated — simulation runs on a copy.
        assert "Output:SQLite" not in state_with_model.document  # type: ignore[operator]

    async def test_design_day_without_weather_passes_none(
        self, client: object, state_with_model: ServerState, tmp_path: Path
    ) -> None:
        """idfkit 1.1.0 runs a design-day-only simulation for weather=None and refuses ``""``."""
        fake_config = SimpleNamespace(
            version=(25, 2, 0),
            install_dir=Path("/fake/energyplus"),
            executable=Path("/fake/energyplus/energyplus"),
        )
        fake_errors = SimpleNamespace(
            fatal_count=0,
            severe_count=0,
            warning_count=0,
            has_fatal=False,
            has_severe=False,
            simulation_complete=True,
        )
        fake_result = SimpleNamespace(
            success=True,
            runtime_seconds=0.1,
            run_dir=tmp_path / "fake-run",
            errors=fake_errors,
        )
        state_with_model.weather_file = None

        with (
            patch("idfkit.simulation.config.find_energyplus", return_value=fake_config),
            patch("idfkit.simulation.async_simulate", return_value=fake_result) as mock_simulate,
        ):
            await call_tool(client, "run_simulation", {"design_day": True})

        assert mock_simulate.call_args.kwargs["weather"] is None

    async def test_upgrades_existing_output_sqlite(
        self, client: object, state_with_model: ServerState, tmp_path: Path
    ) -> None:
        doc = state_with_model.document
        doc.add("Output:SQLite", "", option_type="Simple")  # type: ignore[union-attr]

        fake_config = SimpleNamespace(
            version=(25, 2, 0),
            install_dir=Path("/fake/energyplus"),
            executable=Path("/fake/energyplus/energyplus"),
        )
        fake_errors = SimpleNamespace(
            fatal_count=0,
            severe_count=0,
            warning_count=0,
            has_fatal=False,
            has_severe=False,
            simulation_complete=True,
        )
        fake_result = SimpleNamespace(
            success=True,
            runtime_seconds=0.1,
            run_dir=tmp_path / "fake-run",
            errors=fake_errors,
        )

        async def _fake_simulate(doc: object, **_kwargs: object) -> object:
            collection = doc.get_collection("Output:SQLite")  # type: ignore[union-attr]
            sqlite_object = collection.first()
            assert sqlite_object is not None
            assert sqlite_object.option_type == "SimpleAndTabular"
            return fake_result

        with (
            patch("idfkit.simulation.config.find_energyplus", return_value=fake_config),
            patch("idfkit.simulation.async_simulate", side_effect=_fake_simulate),
        ):
            result = await call_tool(client, "run_simulation", {"design_day": True})

        assert result["success"] is True
        # The original model must NOT be mutated — simulation runs on a copy.
        collection = state_with_model.document.get_collection("Output:SQLite")  # type: ignore[union-attr]
        sqlite_object = collection.first()
        assert sqlite_object is not None
        assert sqlite_object.option_type == "Simple"  # unchanged

    async def test_emits_meta_billing_on_response(
        self, client: object, state_with_model: ServerState, tmp_path: Path
    ) -> None:
        """run_simulation attaches _meta.billing with runtime/cpu/artifact stats."""
        fake_config = SimpleNamespace(
            version=(25, 2, 0),
            install_dir=Path("/fake/energyplus"),
            executable=Path("/fake/energyplus/energyplus"),
        )
        fake_errors = SimpleNamespace(
            fatal_count=0,
            severe_count=0,
            warning_count=0,
            has_fatal=False,
            has_severe=False,
            simulation_complete=True,
        )
        run_dir = tmp_path / "fake-run"
        run_dir.mkdir()
        # Synthesise two artifacts so the emitter has something to report.
        (run_dir / "eplusout.sql").write_bytes(b"x" * 500)
        (run_dir / "eplusout.err").write_text("done")

        fake_result = SimpleNamespace(
            success=True,
            runtime_seconds=0.1,
            run_dir=run_dir,
            errors=fake_errors,
        )

        async def _fake_simulate(_doc: object, **_kwargs: object) -> object:
            return fake_result

        with (
            patch("idfkit.simulation.config.find_energyplus", return_value=fake_config),
            patch("idfkit.simulation.async_simulate", side_effect=_fake_simulate),
        ):
            # Use client.call_tool directly so we get the full CallToolResult
            # including meta — the conftest helper discards it.
            raw = await client.call_tool("run_simulation", {"design_day": True})  # type: ignore[attr-defined]

        assert raw.structured_content["success"] is True
        billing = (raw.meta or {}).get("billing")
        assert billing is not None, "run_simulation must emit _meta.billing"
        assert billing["schema_version"] == "1"
        assert billing["tool"] == "run_simulation"
        assert billing["runtime_ms"] >= 0
        assert billing["cpu_seconds"] >= 0.0
        artifact_names = {a["name"] for a in billing["artifacts"]}
        assert artifact_names == {"eplusout.sql", "eplusout.err"}
        eplusout_sql = next(a for a in billing["artifacts"] if a["name"] == "eplusout.sql")
        assert eplusout_sql["bytes"] == 500


class TestListOutputVariables:
    async def test_no_simulation(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "list_output_variables")

    async def test_falls_back_to_sql_when_rdd_and_mdd_are_empty(
        self, client: object, state_with_sql_only_simulation: ServerState
    ) -> None:
        result = await call_tool(client, "list_output_variables", model=ListOutputVariablesResult)
        assert result.total_available == 3
        assert result.returned == 3
        assert {item.name for item in result.variables} == {
            "Zone Mean Air Temperature",
            "Site Outdoor Air Drybulb Temperature",
            "Electricity:Facility",
        }

    async def test_sql_fallback_respects_search(
        self, client: object, state_with_sql_only_simulation: ServerState
    ) -> None:
        result = await call_tool(client, "list_output_variables", {"search": "Drybulb"}, ListOutputVariablesResult)
        assert result.total_available == 3
        assert result.returned == 1
        assert result.variables[0].name == "Site Outdoor Air Drybulb Temperature"

    async def test_search_invalid_regex_raises(
        self, client: object, state_with_sql_only_simulation: ServerState
    ) -> None:
        """An invalid regex pattern is rejected with a clear error."""
        with pytest.raises(ToolError, match="Invalid regex"):
            await call_tool(client, "list_output_variables", {"search": "[invalid"})

    async def test_search_regex_works(self, client: object, state_with_sql_only_simulation: ServerState) -> None:
        """Valid regex patterns still work as expected."""
        result = await call_tool(
            client, "list_output_variables", {"search": "^Zone.*Temperature$"}, ListOutputVariablesResult
        )
        assert result.returned == 1
        assert result.variables[0].name == "Zone Mean Air Temperature"

    async def test_sql_fallback_ignores_thread_bound_cached_sql(
        self, client: object, state_with_sql_only_simulation: ServerState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise_thread_error(_self: SimulationResult) -> object:
            msg = "SQLite objects created in a thread can only be used in that same thread"
            raise RuntimeError(msg)

        monkeypatch.setattr(SimulationResult, "sql", property(_raise_thread_error))

        result = await call_tool(client, "list_output_variables", model=ListOutputVariablesResult)
        assert result.total_available == 3
        assert result.returned == 3


class TestQueryTimeseries:
    async def test_no_simulation(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "query_timeseries", {"variable_name": "Zone Mean Air Temperature"})

    async def test_meter_with_null_key_value(
        self, client: object, state_with_sql_only_simulation: ServerState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ts = SimpleNamespace(
            variable_name="DistrictCooling:Facility",
            key_value=None,
            units="J",
            frequency="Hourly",
            timestamps=[datetime(2013, 1, 1, 1, 0, 0)],
            values=[123.0],
        )
        monkeypatch.setattr("idfkit.simulation.parsers.sql.SQLResult.get_timeseries", lambda *_args, **_kwargs: fake_ts)

        result = await call_tool(
            client,
            "query_timeseries",
            {
                "variable_name": "DistrictCooling:Facility",
                "key_value": "*",
                "frequency": "Hourly",
                "environment": "annual",
            },
        )

        assert result["variable_name"] == "DistrictCooling:Facility"
        assert result["key_value"] is None
        assert result["returned"] == 1


class TestExportTimeseries:
    async def test_no_simulation(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "export_timeseries", {"variable_name": "Zone Mean Air Temperature"})

    async def test_meter_with_null_key_value(
        self,
        client: object,
        state_with_sql_only_simulation: ServerState,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        fake_ts = SimpleNamespace(
            variable_name="DistrictCooling:Facility",
            key_value=None,
            units="J",
            frequency="Hourly",
            timestamps=[datetime(2013, 1, 1, 1, 0, 0)],
            values=[456.0],
        )
        monkeypatch.setattr("idfkit.simulation.parsers.sql.SQLResult.get_timeseries", lambda *_args, **_kwargs: fake_ts)

        monkeypatch.chdir(tmp_path)
        result = await call_tool(
            client,
            "export_timeseries",
            {
                "variable_name": "DistrictCooling:Facility",
                "key_value": "*",
                "frequency": "Hourly",
                "environment": "annual",
                "output_path": "district_cooling.csv",
            },
        )

        assert result["variable_name"] == "DistrictCooling:Facility"
        assert result["key_value"] is None
        assert result["rows"] == 1
        assert (tmp_path / "district_cooling.csv").exists()

    async def test_export_rejects_path_outside_cwd(
        self,
        client: object,
        state_with_sql_only_simulation: ServerState,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ToolError, match="allowed directory"):
            await call_tool(
                client,
                "export_timeseries",
                {"variable_name": "Test", "output_path": "/tmp/evil.csv"},  # noqa: S108
            )


class TestEnsureSqliteOutput:
    """Unit tests for _ensure_sqlite_output pre-flight function."""

    def test_adds_output_sqlite_when_missing(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _ensure_sqlite_output

        doc = state_with_model.require_model()
        assert "Output:SQLite" not in doc
        _ensure_sqlite_output(doc)
        obj = doc["Output:SQLite"].first()
        assert obj is not None
        assert obj.option_type == "SimpleAndTabular"

    def test_upgrades_simple_to_simple_and_tabular(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _ensure_sqlite_output

        doc = state_with_model.require_model()
        doc.add("Output:SQLite", "", option_type="Simple")
        _ensure_sqlite_output(doc)
        assert doc["Output:SQLite"].first().option_type == "SimpleAndTabular"

    def test_leaves_simple_and_tabular_unchanged(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _ensure_sqlite_output

        doc = state_with_model.require_model()
        doc.add("Output:SQLite", "", option_type="SimpleAndTabular")
        _ensure_sqlite_output(doc)
        assert len(list(doc["Output:SQLite"])) == 1

    def test_overrides_output_control_files(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _ensure_sqlite_output

        doc = state_with_model.require_model()
        doc.add("OutputControl:Files", output_sqlite="No", output_tabular="No")
        _ensure_sqlite_output(doc)
        ctrl = doc["OutputControl:Files"].first()
        assert ctrl.output_sqlite == "Yes"
        assert ctrl.output_tabular == "Yes"

    def test_leaves_output_control_files_yes_unchanged(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _ensure_sqlite_output

        doc = state_with_model.require_model()
        doc.add("OutputControl:Files", output_sqlite="Yes", output_tabular="Yes")
        _ensure_sqlite_output(doc)
        ctrl = doc["OutputControl:Files"].first()
        assert ctrl.output_sqlite == "Yes"
        assert ctrl.output_tabular == "Yes"


class TestEnsureSummaryReports:
    """Unit tests for _ensure_summary_reports pre-flight function."""

    def test_adds_reports_when_missing(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _REQUIRED_SUMMARY_REPORTS, _ensure_summary_reports

        doc = state_with_model.require_model()
        assert "Output:Table:SummaryReports" not in doc
        _ensure_summary_reports(doc)
        obj = doc["Output:Table:SummaryReports"].first()
        assert obj is not None
        names = {group.report_name for group in obj.reports}
        assert names == set(_REQUIRED_SUMMARY_REPORTS)

    def test_appends_missing_reports_to_existing(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _ensure_summary_reports

        doc = state_with_model.require_model()
        doc.add(
            "Output:Table:SummaryReports",
            fields={"reports": [{"report_name": "AnnualBuildingUtilityPerformanceSummary"}]},
        )
        _ensure_summary_reports(doc)
        obj = doc["Output:Table:SummaryReports"].first()
        existing = {group.report_name for group in obj.reports}
        # Original report preserved
        assert "AnnualBuildingUtilityPerformanceSummary" in existing
        # New ones appended
        assert "SensibleHeatGainSummary" in existing
        assert "HVACSizingSummary" in existing

    def test_skips_when_all_summary_present(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _ensure_summary_reports

        doc = state_with_model.require_model()
        doc.add("Output:Table:SummaryReports", fields={"reports": [{"report_name": "AllSummary"}]})
        _ensure_summary_reports(doc)
        obj = doc["Output:Table:SummaryReports"].first()
        # Should not append anything — AllSummary covers everything
        assert [group.report_name for group in obj.reports] == ["AllSummary"]

    def test_skips_when_already_present(self, state_with_model: ServerState) -> None:
        from idfkit_mcp.tools.simulation import _REQUIRED_SUMMARY_REPORTS, _ensure_summary_reports

        doc = state_with_model.require_model()
        doc.add(
            "Output:Table:SummaryReports",
            fields={"reports": [{"report_name": name} for name in sorted(_REQUIRED_SUMMARY_REPORTS)]},
        )
        _ensure_summary_reports(doc)
        obj = doc["Output:Table:SummaryReports"].first()
        # Nothing appended beyond what's already there
        assert len(obj.reports) == len(_REQUIRED_SUMMARY_REPORTS)


class TestRunIdentity:
    """run_simulation records what it ran: the revision, the hash of the text written, the run directory (T088)."""

    async def test_records_revision_hash_and_run_dir(
        self, client: object, state_with_model: ServerState, tmp_path: Path
    ) -> None:
        from idfkit_mcp.tools.simulation import model_text_hash

        fake_config = SimpleNamespace(
            version=(25, 2, 0), install_dir=Path("/fake/energyplus"), executable=Path("/fake/energyplus/energyplus")
        )
        fake_errors = SimpleNamespace(
            fatal_count=0, severe_count=0, warning_count=0, has_fatal=False, has_severe=False, simulation_complete=True
        )
        run_dir = tmp_path / "fake-run"
        run_dir.mkdir()
        fake_result = SimpleNamespace(success=True, runtime_seconds=0.1, run_dir=run_dir, errors=fake_errors)
        written: list[str] = []

        async def _fake_simulate(doc: object, **_kwargs: object) -> object:
            from idfkit import write_idf

            written.append(write_idf(doc))  # type: ignore[arg-type]
            return fake_result

        doc = state_with_model.require_model()
        with (
            patch("idfkit.simulation.config.find_energyplus", return_value=fake_config),
            patch("idfkit.simulation.async_simulate", side_effect=_fake_simulate),
        ):
            await call_tool(client, "run_simulation", {"design_day": True})

        import hashlib

        assert state_with_model.simulation_run_revision == doc.revision
        assert state_with_model.simulation_model_hash == hashlib.sha256(written[0].encode("utf-8")).hexdigest()
        assert state_with_model.simulation_model_hash == model_text_hash(doc)
        assert state_with_model.simulation_run_dir == str(run_dir.resolve())
        assert "Output:SQLite" not in doc  # the hash covers the pre-flighted copy, never the session model


def _without_new_fields(summary: dict[str, Any]) -> dict[str, Any]:
    old = {k: v for k, v in summary.items() if k != "link_coverage"}
    for key, new in (("classified_warnings", ("kind", "affected_objects")), ("qa_flags", ("affected_objects",))):
        if old.get(key):
            old[key] = [{k: v for k, v in item.items() if k not in new} for item in old[key]]
    return old


class TestResultsSummaryLinked:
    """idfkit://simulation/results gains kind, affected_objects and link_coverage, changing no field (T089)."""

    async def test_new_fields_from_linked_results(self, client: object, tmp_path: Path) -> None:
        install_run("5ZoneAirCooled", tmp_path)
        summary = await read_resource_json(client, "idfkit://simulation/results")  # type: ignore[arg-type]

        assert summary["link_coverage"] == {"partial": False, "uncovered": [], "resolved": 678, "unresolved": 0}
        (warning,) = summary["classified_warnings"]
        assert warning["kind"] == "sizing.system_flow_ratio"
        assert warning["affected_objects"] == [{"object_type": "AirLoopHVAC", "name": "VAV Sys 1"}]
        (flag,) = [f for f in summary["qa_flags"] if f["flag"] == "high_unmet_hours"]
        zones = flag["affected_objects"]
        assert {z["object_type"] for z in zones} == {"Zone"}
        assert {z["name"] for z in zones} == {
            r["zone"] for r in summary["unmet_hours"] if r["heating_hours"] + r["cooling_hours"] > 0
        }

    async def test_convergence_flag_names_the_units(self, client: object, tmp_path: Path) -> None:
        install_run("MultiStory", tmp_path)
        summary = await read_resource_json(client, "idfkit://simulation/results")  # type: ignore[arg-type]
        (flag,) = [f for f in summary["qa_flags"] if f["flag"] == "convergence_warnings"]
        assert {"object_type": "ZoneHVAC:WindowAirConditioner", "name": "Gnd West Window AC"} in flag[
            "affected_objects"
        ]
        kinds = {w["kind"] for w in summary["classified_warnings"]}
        assert {"zonehvac.max_iterations", "dxcoil.low_outlet_temp", "surface.shadowing"} <= kinds

    async def test_existing_fields_unchanged(self, client: object, tmp_path: Path) -> None:
        """The same run read with and without linking differs only in the new fields."""
        state = install_run("MultiStory", tmp_path)
        linked = await read_resource_json(client, "idfkit://simulation/results")  # type: ignore[arg-type]
        state.simulation_run_dir = None  # no run identity: results cannot be linked (FR-019)
        state.simulation_model_hash = None
        unlinked = await read_resource_json(client, "idfkit://simulation/results")  # type: ignore[arg-type]

        assert unlinked["link_coverage"] is None
        assert all(f["affected_objects"] == [] for f in unlinked["qa_flags"])
        assert all(w["affected_objects"] == [] for w in unlinked["classified_warnings"])
        assert _without_new_fields(linked) == _without_new_fields(unlinked)
        # Without linking, kind still comes from the message catalogue.
        assert [w["kind"] for w in unlinked["classified_warnings"]] == [
            w["kind"] for w in linked["classified_warnings"]
        ]

    async def test_summary_without_a_model(self, client: object, state_with_sql_only_simulation: ServerState) -> None:
        summary = await read_resource_json(client, "idfkit://simulation/results")  # type: ignore[arg-type]
        assert summary["link_coverage"] is None
