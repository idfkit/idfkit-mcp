"""Tests for the ``run_simulation_in_browser`` handoff tool.

The tool does **not** invoke EnergyPlus server-side — it serializes the
loaded model plus (optionally) the EPW bytes and returns a handoff payload
on ``_meta.browser_run`` that the ``ui://idfkit/simulator.html`` iframe
consumes.  These tests guard the contract shape, the payload contents, the
absence of any simulation-runtime imports, and the asset-route default.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.models import RunInBrowserHandoff
from idfkit_mcp.state import ServerState
from tests.conftest import call_tool


class TestRunSimulationInBrowser:
    async def test_no_model(self, client: object) -> None:
        with pytest.raises(ToolError):
            await call_tool(client, "run_simulation_in_browser", {"design_day": True})

    async def test_no_weather_and_not_design_day(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError, match=r"weather|No weather"):
            await call_tool(client, "run_simulation_in_browser")

    async def test_design_day_handoff_shape(self, client: Any, state_with_model: ServerState) -> None:
        """Design-day mode: handoff populated, no EPW required, no E+ invoked."""
        with patch("idfkit.simulation.async_simulate") as mock_sim:
            raw = await client.call_tool("run_simulation_in_browser", {"design_day": True})

        # Server-side simulation must never fire for the handoff tool.
        mock_sim.assert_not_called()

        assert raw.structured_content is not None
        structured = RunInBrowserHandoff.model_validate(raw.structured_content)
        assert structured.mode == "browser_handoff"
        assert structured.run_id
        assert "browser" in structured.message.lower()

        browser_run = (raw.meta or {}).get("browser_run")
        assert browser_run is not None, "_meta.browser_run must be present"
        assert browser_run["run_id"] == structured.run_id
        assert browser_run["design_day"] is True
        assert browser_run["annual"] is False
        assert browser_run["epw"] is None
        assert browser_run["upload_tool_name"] == "upload_simulation_result"
        assert browser_run["asset_tool_name"] == "fetch_energyplus_asset"
        assert "eplusout.sql" in browser_run["allowed_output_filenames"]

        # IDF was pre-flighted before serialization: Output:SQLite present.
        idf_text = browser_run["idf"]
        assert isinstance(idf_text, str) and idf_text.startswith("!-Generator archetypal")
        assert "Output:SQLite" in idf_text
        assert "Output:Table:SummaryReports" in idf_text

        # The user's loaded model must NOT have been mutated.
        assert "Output:SQLite" not in state_with_model.document  # type: ignore[operator]

    async def test_epw_payload_when_weather_provided(
        self, client: Any, state_with_model: ServerState, tmp_path: Path
    ) -> None:
        epw_path = tmp_path / "fake.epw"
        epw_bytes = b"LOCATION,Test,,,,,,,\n"
        epw_path.write_bytes(epw_bytes)

        raw = await client.call_tool(
            "run_simulation_in_browser",
            {"weather_file": str(epw_path)},
        )
        browser_run = (raw.meta or {})["browser_run"]
        assert browser_run["epw"] is not None
        assert base64.b64decode(browser_run["epw"]) == epw_bytes

    async def test_expected_version_reflects_doc_when_advisory_missing(
        self, client: Any, state_with_model: ServerState
    ) -> None:
        raw = await client.call_tool("run_simulation_in_browser", {"design_day": True})
        browser_run = (raw.meta or {})["browser_run"]
        doc_version = ".".join(str(p) for p in state_with_model.document.version)  # type: ignore[union-attr]
        assert browser_run["expected_energyplus_version"] == doc_version

    async def test_advisory_version_overrides_doc_version(self, client: Any, state_with_model: ServerState) -> None:
        raw = await client.call_tool(
            "run_simulation_in_browser",
            {"design_day": True, "energyplus_version": "99.9.9"},
        )
        browser_run = (raw.meta or {})["browser_run"]
        assert browser_run["expected_energyplus_version"] == "99.9.9"

    async def test_simulation_lock_rejects(self, client: Any, state_with_model: ServerState) -> None:
        state = state_with_model
        await state.simulation_lock.acquire()
        try:
            with pytest.raises(ToolError, match="in progress"):
                await call_tool(client, "run_simulation_in_browser", {"design_day": True})
        finally:
            state.simulation_lock.release()

    async def test_unreadable_weather_file_errors_cleanly(self, client: Any, state_with_model: ServerState) -> None:
        missing = "/definitely/not/a/real/weather/file.epw"
        with pytest.raises(ToolError, match="Could not read"):
            await call_tool(client, "run_simulation_in_browser", {"weather_file": missing})

    async def test_handoff_includes_wasm_candidates_from_disk(
        self, client: Any, state_with_model: ServerState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The iframe gets the concrete WASM filenames found on disk so a
        version bump never requires iframe code changes."""
        (tmp_path / "energyplus.js").write_text("// fake glue\n")
        (tmp_path / "energyplus.js-27.0.wasm").write_bytes(b"\x00asm")
        (tmp_path / "energyplus.wasm").write_bytes(b"\x00asm")
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))

        raw = await client.call_tool("run_simulation_in_browser", {"design_day": True})
        browser_run = (raw.meta or {})["browser_run"]
        candidates = browser_run["wasm_candidates"]
        assert "energyplus.js-27.0.wasm" in candidates
        assert "energyplus.wasm" in candidates
        # Versioned candidate must come before the unversioned fallback so
        # the iframe tries the specific bundle first.
        assert candidates.index("energyplus.js-27.0.wasm") < candidates.index("energyplus.wasm")


class TestSimulatorUIResource:
    async def test_simulator_html_resource_is_registered(self, client: Any) -> None:
        """The iframe resource is discoverable and contains key markers."""
        contents = await client.read_resource("ui://idfkit/simulator.html")
        assert contents, "simulator.html resource must return content"
        html = contents[0].text
        assert "EnergyPlus Browser Simulator" in html
        assert "upload_simulation_result" in html
        assert "fetch_energyplus_asset" in html  # iframe uses MCP tool, not HTTP
        assert "eplusout.sql" in html  # allowlist was templated in


class TestFetchEnergyPlusAsset:
    """Proxy tool the iframe uses to load WASM + IDD + datasets."""

    async def test_rejects_disallowed_filename(self, client: Any) -> None:
        with pytest.raises(ToolError, match="allowlist"):
            await call_tool(client, "fetch_energyplus_asset", {"filename": "nope.wasm"})

    async def test_rejects_traversal_like_filename(self, client: Any) -> None:
        with pytest.raises(ToolError, match="allowlist"):
            await call_tool(client, "fetch_energyplus_asset", {"filename": "../../etc/passwd"})

    async def test_returns_bytes_when_override_points_at_populated_dir(
        self, client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Populate the override dir with the two allowlisted files we'll ask for.
        (tmp_path / "energyplus.js").write_text("// fake glue\n")
        idd_bytes = b"!Fake IDD header\n" + b"x" * 1024
        (tmp_path / "Energy+.idd").write_bytes(idd_bytes)
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))

        result = await call_tool(client, "fetch_energyplus_asset", {"filename": "Energy+.idd"})
        assert isinstance(result, dict)
        assert result["filename"] == "Energy+.idd"
        assert result["size"] == len(idd_bytes)
        assert result["offset"] == 0
        assert result["total_size"] == len(idd_bytes)
        assert result["is_last"] is True
        assert base64.b64decode(result["content_base64"]) == idd_bytes

    async def test_chunked_fetch_reassembles_correctly(
        self, client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pulling a file in slices via offset/chunk_size returns the original bytes."""
        (tmp_path / "energyplus.js").write_text("// fake glue\n")
        # Bytes that reveal any off-by-one slicing bug.
        idd_bytes = bytes(range(256)) * 40  # 10,240 bytes
        (tmp_path / "Energy+.idd").write_bytes(idd_bytes)
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))

        collected = bytearray()
        offset = 0
        step = 1024
        while True:
            result = await call_tool(
                client,
                "fetch_energyplus_asset",
                {"filename": "Energy+.idd", "offset": offset, "chunk_size": step},
            )
            assert isinstance(result, dict)
            assert result["total_size"] == len(idd_bytes)
            chunk = base64.b64decode(result["content_base64"])
            assert result["size"] == len(chunk)
            assert result["offset"] == offset
            collected.extend(chunk)
            offset += len(chunk)
            if result["is_last"]:
                break
            assert len(chunk) > 0, "non-terminal chunk must carry bytes"

        assert bytes(collected) == idd_bytes
        assert offset == len(idd_bytes)

    async def test_offset_past_eof_raises(self, client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "energyplus.js").write_text("// fake glue\n")
        (tmp_path / "Energy+.idd").write_bytes(b"hi")
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))
        with pytest.raises(ToolError, match="exceeds"):
            await call_tool(
                client,
                "fetch_energyplus_asset",
                {"filename": "Energy+.idd", "offset": 999},
            )

    async def test_503_style_error_when_bundle_not_installed(
        self, client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Empty override dir → no energyplus.js sentinel → bundle treated as not installed.
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))
        with pytest.raises(ToolError, match="WASM assets are not installed"):
            await call_tool(client, "fetch_energyplus_asset", {"filename": "Energy+.idd"})

    async def test_allowlist_reflects_installed_files_including_future_versions(
        self, client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A new envelop bundle with a different .wasm filename must be fetchable
        without editing the allowlist — the scan picks it up from disk."""
        (tmp_path / "energyplus.js").write_text("// fake glue\n")
        # Simulate a future EnergyPlus bump shipping a new .wasm filename.
        future_wasm = b"\x00asm future"
        (tmp_path / "energyplus.js-99.9.wasm").write_bytes(future_wasm)
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))

        result = await call_tool(client, "fetch_energyplus_asset", {"filename": "energyplus.js-99.9.wasm"})
        assert isinstance(result, dict)
        assert base64.b64decode(result["content_base64"]) == future_wasm

    async def test_allowlist_rejects_files_outside_glob_patterns(
        self, client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file that happens to sit in the assets dir but isn't covered by
        any allowed glob must be refused — the glob list is the security
        boundary, not the filesystem contents."""
        (tmp_path / "energyplus.js").write_text("// fake glue\n")
        (tmp_path / "secret.config").write_text("x=1")
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))
        with pytest.raises(ToolError, match="allowlist"):
            await call_tool(client, "fetch_energyplus_asset", {"filename": "secret.config"})


class TestEnergyPlusAssetRoute:
    """The /assets/energyplus/ route the iframe hits for WASM + IDD."""

    async def test_503_when_assets_not_synced(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no Emscripten glue the route reports the sync-needed hint."""
        from httpx import ASGITransport, AsyncClient

        from idfkit_mcp.server import mcp

        # Point the override at an empty dir so the test stays deterministic
        # regardless of whether developers have run `make sync-wasm-assets`.
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))

        http_app = mcp.http_app()
        async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as c:
            resp = await c.get("/assets/energyplus/energyplus.js")
        assert resp.status_code == 503
        assert "sync-wasm-assets" in resp.text
        assert resp.headers["access-control-allow-origin"] == "*"

    async def test_env_override_points_at_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """IDFKIT_MCP_ENERGYPLUS_DIR redirects reads and traversal is blocked."""
        from httpx import ASGITransport, AsyncClient

        from idfkit_mcp.server import mcp

        (tmp_path / "energyplus.js").write_text("// fake glue\n")
        (tmp_path / "Energy+.idd").write_text("!Fake IDD\n")
        monkeypatch.setenv("IDFKIT_MCP_ENERGYPLUS_DIR", str(tmp_path))

        http_app = mcp.http_app()
        async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as c:
            ok = await c.get("/assets/energyplus/energyplus.js")
            assert ok.status_code == 200
            assert "fake glue" in ok.text
            assert ok.headers["access-control-allow-origin"] == "*"

            missing = await c.get("/assets/energyplus/nope.wasm")
            assert missing.status_code == 404

            # Traversal attempt: resolves outside the override dir, expect 404.
            traversal = await c.get("/assets/energyplus/../../etc/passwd")
            assert traversal.status_code == 404
