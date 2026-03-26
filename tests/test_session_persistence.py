"""Tests for session state persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from idfkit import new_document, write_idf

from idfkit_mcp.state import get_state
from tests.tool_helpers import get_tool_sync


def _tool(name: str):
    from idfkit_mcp.server import mcp

    return get_tool_sync(mcp, name)


@pytest.fixture()
def _enable_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Enable persistence with a temp session file for the test."""
    session_file = tmp_path / "test_session.json"
    monkeypatch.setattr("idfkit_mcp.state._session_file_path", lambda: session_file)
    state = get_state()
    state.persistence_enabled = True
    state._session_restored = False
    return session_file


class TestSaveSession:
    def test_save_and_restore_model(self, _enable_persistence: Path, tmp_path: Path) -> None:
        session_file = _enable_persistence
        state = get_state()

        # Create and save a model to disk
        doc = new_document()
        doc.add("Zone", "TestZone")
        idf_path = tmp_path / "test.idf"
        write_idf(doc, idf_path)

        # Load via the tool (which calls save_session)
        state.document = doc
        state.schema = doc.schema
        state.file_path = idf_path
        state.save_session()

        assert session_file.exists()
        data = json.loads(session_file.read_text())
        assert data["file_path"] == str(idf_path.resolve())

        # Reset state to simulate a new server process
        state.document = None
        state.schema = None
        state.file_path = None
        state._session_restored = False

        # Restore should bring the model back
        state._try_restore_session()
        assert state.document is not None
        assert state.file_path == idf_path
        assert "TestZone" in [obj.name for obj in state.document.get_collection("Zone")]

    def test_save_and_restore_weather(self, _enable_persistence: Path, tmp_path: Path) -> None:
        session_file = _enable_persistence
        state = get_state()

        weather_path = tmp_path / "test.epw"
        weather_path.write_text("LOCATION,Test")
        state.weather_file = weather_path
        state.save_session()

        data = json.loads(session_file.read_text())
        assert data["weather_file"] == str(weather_path.resolve())

        state.weather_file = None
        state._session_restored = False
        state._try_restore_session()
        assert state.weather_file == weather_path

    def test_save_and_restore_simulation(self, _enable_persistence: Path, tmp_path: Path) -> None:
        session_file = _enable_persistence
        state = get_state()

        # Create a fake simulation output directory with an .err file
        run_dir = tmp_path / "sim_output"
        run_dir.mkdir()
        (run_dir / "eplus.err").write_text("Program Version,EnergyPlus, 25.2.0\nEnergyPlus Completed Successfully.")

        from idfkit.simulation.result import SimulationResult

        state.simulation_result = SimulationResult.from_directory(run_dir)
        state.save_session()

        data = json.loads(session_file.read_text())
        assert data["simulation_run_dir"] == str(run_dir.resolve())

        state.simulation_result = None
        state._session_restored = False
        state._try_restore_session()
        assert state.simulation_result is not None
        assert state.simulation_result.run_dir == run_dir


class TestRestoreEdgeCases:
    def test_missing_file_skipped(self, _enable_persistence: Path, tmp_path: Path) -> None:
        session_file = _enable_persistence
        state = get_state()

        idf_path = tmp_path / "gone.idf"
        # Write session pointing to a file that doesn't exist
        session_file.write_text(
            json.dumps({
                "version": 1,
                "cwd": str(tmp_path),
                "file_path": str(idf_path),
                "updated_at": "2026-01-01T00:00:00+00:00",
            })
        )

        state._try_restore_session()
        assert state.document is None
        assert state.file_path is None

    def test_corrupt_session_file(self, _enable_persistence: Path) -> None:
        session_file = _enable_persistence
        session_file.write_text("not valid json {{{")

        state = get_state()
        # Should not raise
        state._try_restore_session()
        assert state.document is None

    def test_wrong_version_ignored(self, _enable_persistence: Path) -> None:
        session_file = _enable_persistence
        session_file.write_text(json.dumps({"version": 999}))

        state = get_state()
        state._try_restore_session()
        assert state.document is None

    def test_restore_called_once(self, _enable_persistence: Path) -> None:
        """_session_restored flag prevents repeated file reads."""
        session_file = _enable_persistence
        state = get_state()

        state._try_restore_session()
        assert state._session_restored is True

        # Write a session file AFTER the first restore
        session_file.write_text(
            json.dumps({
                "version": 1,
                "cwd": str(session_file.parent),
                "updated_at": "2026-01-01T00:00:00+00:00",
            })
        )

        # Second call should be a no-op (flag is set)
        state._try_restore_session()
        # If it re-read, it would have parsed the file — but since it's
        # a no-op, the state stays the same
        assert state.document is None


class TestSaveSessionFailure:
    def test_write_failure_does_not_raise(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point to a path inside a read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)
        bad_path = readonly_dir / "session.json"
        monkeypatch.setattr("idfkit_mcp.state._session_file_path", lambda: bad_path)

        state = get_state()
        state.persistence_enabled = True
        state.file_path = tmp_path / "test.idf"
        (tmp_path / "test.idf").write_text("Version,25.2;")

        # Should not raise despite permission error
        state.save_session()

        # Cleanup: restore permissions so tmp_path can be deleted
        readonly_dir.chmod(0o755)
        assert not bad_path.exists()


class TestPersistenceDisabled:
    def test_save_is_noop_when_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_file = tmp_path / "should_not_exist.json"
        monkeypatch.setattr("idfkit_mcp.state._session_file_path", lambda: session_file)
        state = get_state()
        # persistence_enabled is False (set by conftest)
        assert state.persistence_enabled is False

        state.file_path = tmp_path / "test.idf"
        state.save_session()
        assert not session_file.exists()

    def test_restore_is_noop_when_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_file = tmp_path / "session.json"
        session_file.write_text(
            json.dumps({"version": 1, "cwd": str(tmp_path), "updated_at": "2026-01-01T00:00:00+00:00"})
        )
        monkeypatch.setattr("idfkit_mcp.state._session_file_path", lambda: session_file)

        state = get_state()
        state._session_restored = False
        # persistence_enabled is False
        state._try_restore_session()
        assert state._session_restored is False  # Never even set the flag


class TestClearSession:
    def test_clear_deletes_file_and_resets(self, _enable_persistence: Path, tmp_path: Path) -> None:
        session_file = _enable_persistence
        state = get_state()

        doc = new_document()
        idf_path = tmp_path / "model.idf"
        write_idf(doc, idf_path)
        state.document = doc
        state.schema = doc.schema
        state.file_path = idf_path
        state.save_session()
        assert session_file.exists()

        state.clear_session()
        assert not session_file.exists()
        assert state.document is None
        assert state.file_path is None
        assert state.simulation_result is None
        assert state.weather_file is None


class TestRequireAutoRestore:
    def test_require_model_auto_restores(self, _enable_persistence: Path, tmp_path: Path) -> None:
        state = get_state()

        doc = new_document()
        doc.add("Zone", "AutoZone")
        idf_path = tmp_path / "auto.idf"
        write_idf(doc, idf_path)
        state.document = doc
        state.schema = doc.schema
        state.file_path = idf_path
        state.save_session()

        # Simulate new process
        state.document = None
        state.schema = None
        state.file_path = None
        state._session_restored = False

        # require_model should auto-restore instead of raising
        restored_doc = state.require_model()
        assert restored_doc is not None
        assert "AutoZone" in [obj.name for obj in restored_doc.get_collection("Zone")]

    def test_require_model_raises_without_session(self, _enable_persistence: Path) -> None:
        """With no session file, require_model still raises."""
        state = get_state()
        state.document = None
        with pytest.raises(RuntimeError, match="No model loaded"):
            state.require_model()

    def test_require_simulation_raises_without_session(self, _enable_persistence: Path) -> None:
        state = get_state()
        state.simulation_result = None
        with pytest.raises(RuntimeError, match="No simulation results"):
            state.require_simulation_result()


class TestNewModelNoSession:
    def test_new_model_does_not_persist(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        session_file = tmp_path / "session.json"
        monkeypatch.setattr("idfkit_mcp.state._session_file_path", lambda: session_file)
        state = get_state()
        state.persistence_enabled = True
        state._session_restored = False

        # new_model sets file_path=None, so save_session writes no file_path
        _tool("new_model").fn()
        # Session might be written by a future save_model, but new_model
        # doesn't call save_session itself, so no file should exist
        assert not session_file.exists()
