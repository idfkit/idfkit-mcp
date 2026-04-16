"""Tests for the ``migrate_model`` tool and ``idfkit://migration/report`` resource."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp.exceptions import ToolError
from idfkit import new_document
from idfkit.exceptions import EnergyPlusNotFoundError, MigrationError, VersionMismatchError
from idfkit.migration import MigrationDiff, MigrationReport, MigrationStep
from idfkit.migration.progress import MigrationProgress
from idfkit.migration.report import FieldDelta

from idfkit_mcp.models import MigrateModelResult
from idfkit_mcp.state import ServerState
from tests.conftest import call_tool, read_resource_json


def _fake_config(version: tuple[int, int, int] = (25, 1, 0)) -> SimpleNamespace:
    """Build a minimal EnergyPlusConfig stand-in for patching find_energyplus."""
    return SimpleNamespace(
        version=version,
        install_dir=Path("/fake/energyplus"),
        executable=Path("/fake/energyplus/energyplus"),
        version_updater_dir=Path("/fake/energyplus/PreProcess/IDFVersionUpdater"),
    )


def _canned_report(
    *,
    source: tuple[int, int, int] = (22, 1, 0),
    target: tuple[int, int, int] = (25, 1, 0),
    migrated: Any,
) -> MigrationReport:
    """Build a MigrationReport that looks like a multi-step forward migration."""
    steps = (
        MigrationStep(from_version=source, to_version=(22, 2, 0), success=True, runtime_seconds=0.12),
        MigrationStep(from_version=(22, 2, 0), to_version=(23, 1, 0), success=True, runtime_seconds=0.08),
        MigrationStep(from_version=(23, 1, 0), to_version=target, success=True, runtime_seconds=0.05),
    )
    diff = MigrationDiff(
        added_object_types=("Output:Foo",),
        removed_object_types=("Legacy:Bar",),
        object_count_delta={"Zone": 0, "Output:Foo": 1, "Legacy:Bar": -1},
        field_changes={"Zone": FieldDelta(added=("newfield",), removed=("oldfield",))},
    )
    return MigrationReport(
        migrated_model=migrated,
        source_version=source,
        target_version=target,
        requested_target=target,
        steps=steps,
        diff=diff,
    )


def _install_fake_migrate(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    """Route both ``idfkit.async_migrate`` and the tool-module re-export at the fake."""
    import idfkit

    import idfkit_mcp.tools.migration as migration_module

    monkeypatch.setattr(idfkit, "async_migrate", fake)
    monkeypatch.setattr(migration_module.idfkit, "async_migrate", fake)


class TestMigrateModelHappyPath:
    async def test_auto_target_uses_installed_version(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = state_with_old_version_model
        captured: dict[str, Any] = {}

        async def fake(doc: Any, target: tuple[int, int, int], **kw: Any) -> MigrationReport:
            captured["target"] = target
            return _canned_report(target=target, migrated=new_document(version=target))

        _install_fake_migrate(monkeypatch, fake)
        monkeypatch.setattr(
            "idfkit.simulation.config.find_energyplus",
            lambda path=None: _fake_config((25, 1, 0)),
        )

        result = await call_tool(client, "migrate_model", model=MigrateModelResult)
        assert isinstance(result, MigrateModelResult)
        assert result.success is True
        assert result.source_version == "22.1.0"
        assert result.target_version == "25.1.0"
        assert captured["target"] == (25, 1, 0)

        assert state.document is not None
        assert state.document.version == (25, 1, 0)
        assert state.migration_report is not None
        assert state.file_path is None
        assert any(entry["tool"] == "migrate_model" for entry in state.change_log)

    async def test_explicit_target_overrides_autodetect(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake(doc: Any, target: tuple[int, int, int], **kw: Any) -> MigrationReport:
            captured["target"] = target
            return _canned_report(target=target, migrated=new_document(version=target))

        _install_fake_migrate(monkeypatch, fake)
        monkeypatch.setattr(
            "idfkit.simulation.config.find_energyplus",
            lambda path=None: _fake_config((25, 2, 0)),
        )

        result = await call_tool(
            client,
            "migrate_model",
            {"target_version": "24.2.0"},
            model=MigrateModelResult,
        )
        assert isinstance(result, MigrateModelResult)
        assert result.target_version == "24.2.0"
        assert captured["target"] == (24, 2, 0)

    async def test_populates_diff_and_steps(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake(doc: Any, target: tuple[int, int, int], **kw: Any) -> MigrationReport:
            return _canned_report(target=target, migrated=new_document(version=target))

        _install_fake_migrate(monkeypatch, fake)
        monkeypatch.setattr(
            "idfkit.simulation.config.find_energyplus",
            lambda path=None: _fake_config((25, 1, 0)),
        )

        result = await call_tool(client, "migrate_model", model=MigrateModelResult)
        assert isinstance(result, MigrateModelResult)
        assert len(result.steps) == 3
        assert result.steps[0].from_version == "22.1.0"
        assert result.steps[-1].to_version == "25.1.0"
        assert result.diff.added_object_types == ["Output:Foo"]
        assert result.diff.removed_object_types == ["Legacy:Bar"]
        assert result.diff.object_count_delta["Output:Foo"] == 1
        assert "Zone" in result.diff.field_changes
        assert result.diff.field_changes["Zone"].added == ["newfield"]
        assert "22.1.0 -> 25.1.0" in result.summary


class TestMigrateModelProgress:
    async def test_progress_events_forwarded_to_context(
        self,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unit-test the inner progress handler since FastMCP in-memory clients
        do not expose progress notifications back to the caller."""
        from idfkit_mcp.tools.migration import _build_progress_handler

        class _FakeCtx:
            def __init__(self) -> None:
                self.progress: list[tuple[float, float]] = []
                self.infos: list[str] = []

            async def report_progress(self, *, progress: float, total: float) -> None:
                self.progress.append((progress, total))

            async def info(self, message: str) -> None:
                self.infos.append(message)

        ctx = _FakeCtx()
        handler = _build_progress_handler(ctx)  # type: ignore[arg-type]

        await handler(MigrationProgress(phase="planning", message="Planning"))
        await handler(
            MigrationProgress(
                phase="transitioning",
                message="Step 1",
                from_version=(22, 1, 0),
                to_version=(22, 2, 0),
                percent=50.0,
            )
        )
        await handler(MigrationProgress(phase="complete", message="Done", percent=100.0))

        assert ctx.progress == [(50.0, 100.0), (100.0, 100.0)]
        assert any("22.1.0 -> 22.2.0" in m for m in ctx.infos)
        assert any("planning" in m for m in ctx.infos)

    async def test_progress_handler_tolerates_none_ctx(self) -> None:
        from idfkit_mcp.tools.migration import _build_progress_handler

        handler = _build_progress_handler(None)
        await handler(MigrationProgress(phase="planning", message="nothing to do"))


class TestMigrateModelErrors:
    async def test_version_mismatch_downgrade_surfaces_direction(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake(doc: Any, target: tuple[int, int, int], **kw: Any) -> MigrationReport:
            # direction is derived from current vs target; current > target => "backward".
            raise VersionMismatchError(
                current=(25, 1, 0),
                target=(22, 1, 0),
                migration_chain=(),
            )

        _install_fake_migrate(monkeypatch, fake)
        monkeypatch.setattr(
            "idfkit.simulation.config.find_energyplus",
            lambda path=None: _fake_config((22, 1, 0)),
        )

        with pytest.raises(ToolError, match="backward"):
            await call_tool(client, "migrate_model", {"target_version": "22.1.0"})

    async def test_partial_failure_preserves_state(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = state_with_old_version_model
        original_doc = state.document

        async def fake(doc: Any, target: tuple[int, int, int], **kw: Any) -> MigrationReport:
            raise MigrationError(
                "transition binary exit 1",
                from_version=(23, 1, 0),
                to_version=(23, 2, 0),
                exit_code=1,
                stderr="kaboom",
                completed_steps=(((22, 1, 0), (22, 2, 0)), ((22, 2, 0), (23, 1, 0))),
            )

        _install_fake_migrate(monkeypatch, fake)
        monkeypatch.setattr(
            "idfkit.simulation.config.find_energyplus",
            lambda path=None: _fake_config((25, 1, 0)),
        )

        with pytest.raises(ToolError) as exc_info:
            await call_tool(client, "migrate_model")

        msg = str(exc_info.value)
        assert "23.1.0 -> 23.2.0" in msg
        assert "exit 1" in msg
        assert "Completed steps" in msg
        assert "kaboom" in msg

        assert state.document is original_doc
        assert state.migration_report is None

    async def test_no_energyplus_maps_to_install_guidance(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(path: str | None = None) -> Any:
            raise EnergyPlusNotFoundError(["/fake/path"])

        monkeypatch.setattr("idfkit.simulation.config.find_energyplus", boom)

        with pytest.raises(ToolError, match="EnergyPlus installation not found"):
            await call_tool(client, "migrate_model", {"target_version": "25.1.0"})

    async def test_invalid_target_string(
        self,
        client: object,
        state_with_old_version_model: ServerState,
    ) -> None:
        with pytest.raises(ToolError, match="Invalid target_version"):
            await call_tool(client, "migrate_model", {"target_version": "not-a-version"})

    async def test_no_model_loaded(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "migrate_model", {"target_version": "25.1.0"})


class TestMigrationReportResource:
    async def test_resource_without_run_raises(self, client: object) -> None:
        with pytest.raises(Exception, match="No migration has run"):
            await read_resource_json(client, "idfkit://migration/report")

    async def test_resource_after_run(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake(doc: Any, target: tuple[int, int, int], **kw: Any) -> MigrationReport:
            return _canned_report(target=target, migrated=new_document(version=target))

        _install_fake_migrate(monkeypatch, fake)
        monkeypatch.setattr(
            "idfkit.simulation.config.find_energyplus",
            lambda path=None: _fake_config((25, 1, 0)),
        )

        await call_tool(client, "migrate_model", model=MigrateModelResult)

        payload = await read_resource_json(client, "idfkit://migration/report")
        assert payload["success"] is True
        assert payload["source_version"] == "22.1.0"
        assert payload["target_version"] == "25.1.0"
        assert len(payload["steps"]) == 3
        assert payload["diff"]["added_object_types"] == ["Output:Foo"]
        assert "field_changes" in payload["diff"]
        assert payload["diff"]["field_changes"]["Zone"]["added"] == ["newfield"]

    async def test_resource_truncates_long_streams(
        self,
        client: object,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        big = "x" * 10_000

        async def fake(doc: Any, target: tuple[int, int, int], **kw: Any) -> MigrationReport:
            step = MigrationStep(
                from_version=(22, 1, 0),
                to_version=target,
                success=True,
                stdout=big,
                stderr=big,
                audit_text=big,
                runtime_seconds=0.1,
            )
            return MigrationReport(
                migrated_model=new_document(version=target),
                source_version=(22, 1, 0),
                target_version=target,
                requested_target=target,
                steps=(step,),
                diff=MigrationDiff(),
            )

        _install_fake_migrate(monkeypatch, fake)
        monkeypatch.setattr(
            "idfkit.simulation.config.find_energyplus",
            lambda path=None: _fake_config((25, 1, 0)),
        )

        await call_tool(client, "migrate_model", model=MigrateModelResult)

        payload = await read_resource_json(client, "idfkit://migration/report")
        step = payload["steps"][0]
        from idfkit_mcp.tools.migration import _STREAM_TRUNCATE_CHARS

        assert len(step["stdout"]) <= _STREAM_TRUNCATE_CHARS
        assert len(step["stderr"]) <= _STREAM_TRUNCATE_CHARS
        assert step["audit_text"] is not None
        assert len(step["audit_text"]) <= _STREAM_TRUNCATE_CHARS


class TestSessionPersistenceIsCheap:
    async def test_save_session_does_not_serialize_migration_report(
        self,
        state_with_old_version_model: ServerState,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``save_session`` writes paths only; the live MigrationReport must stay in memory."""
        import json

        state = state_with_old_version_model
        state.persistence_enabled = True

        state.migration_report = _canned_report(
            target=(25, 1, 0),
            migrated=new_document(version=(25, 1, 0)),
        )

        session_file = tmp_path / "session.json"
        monkeypatch.setattr("idfkit_mcp.state._session_file_path", lambda: session_file)

        state.save_session()

        payload = json.loads(session_file.read_text())
        assert "migration_report" not in payload
        assert "migration" not in payload
        assert "migrated_model" not in json.dumps(payload)
