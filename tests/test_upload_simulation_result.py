"""Tests for ``upload_simulation_result`` — proves the browser/WASM architecture.

Covers two transports:

1. **In-memory FastMCPTransport** — fast round-trip, negative cases, contract parity
   with ``run_simulation``.
2. **Subprocess streamable-HTTP server** — the transport the user asked to validate.
   Proves ``mcp-session-id`` affinity: artifacts uploaded via one request are visible
   through a resource read on the same session.

A valid simulation result is produced without touching EnergyPlus by writing a
minimal ``eplusout.sql`` (with the schema downstream tools expect) plus empty
``eplusout.rdd`` / ``eplusout.mdd`` / ``eplusout.err`` files into a tmp directory.

Manual smoke test procedure (documented here for discoverability):
    Terminal 1: ``make serve-http``
    Terminal 2: run the block under ``MANUAL_SMOKE_SNIPPET`` below, adjusted to
    point at a real directory.
"""

from __future__ import annotations

import base64
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tests.conftest import call_tool, read_resource_json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_sim_run_dir(run_dir: Path) -> None:
    """Populate ``run_dir`` with a minimal, valid EnergyPlus-like output set.

    Mirrors the fixture ``state_with_sql_only_simulation`` in ``conftest.py`` so
    downstream tools (``list_output_variables``, the ``idfkit://simulation/results``
    resource, etc.) can execute against it.
    """
    import sqlite3

    run_dir.mkdir(parents=True, exist_ok=True)
    sql_path = run_dir / "eplusout.sql"
    conn = sqlite3.connect(str(sql_path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE ReportDataDictionary ("
        "  ReportDataDictionaryIndex INTEGER PRIMARY KEY,"
        "  IsMeter INTEGER,"
        "  Type TEXT,"
        "  IndexGroup TEXT,"
        "  TimestepType TEXT,"
        "  KeyValue TEXT,"
        "  Name TEXT,"
        "  ReportingFrequency TEXT,"
        "  ScheduleName TEXT,"
        "  Units TEXT"
        ")"
    )
    cur.execute(
        "INSERT INTO ReportDataDictionary VALUES "
        "(1, 0, 'Zone', 'Facility', 'Zone', 'OFFICE', 'Zone Mean Air Temperature', 'Hourly', '', 'C'),"
        "(2, 0, 'Zone', 'Facility', 'Zone', '*', 'Site Outdoor Air Drybulb Temperature', 'Hourly', '', 'C'),"
        "(3, 1, 'Zone', 'Facility', 'Zone', '', 'Electricity:Facility', 'Hourly', '', 'J')"
    )
    conn.commit()
    conn.close()

    (run_dir / "eplusout.rdd").write_text("", encoding="latin-1")
    (run_dir / "eplusout.mdd").write_text("", encoding="latin-1")
    (run_dir / "eplusout.err").write_text(
        "Program Version,EnergyPlus, Version 25.2.0-test\n************* EnergyPlus Completed Successfully.\n",
        encoding="latin-1",
    )


def _encode_run_dir(run_dir: Path) -> dict[str, str]:
    """Read every file in ``run_dir`` and return {filename: base64-bytes}."""
    return {p.name: base64.b64encode(p.read_bytes()).decode("ascii") for p in sorted(run_dir.iterdir()) if p.is_file()}


# ---------------------------------------------------------------------------
# In-memory (FastMCPTransport) coverage
# ---------------------------------------------------------------------------


class TestUploadSimulationResultInMemory:
    """Fast regression: tool contract, negative cases, resource parity."""

    async def test_round_trip(self, client: Any, tmp_path: Path) -> None:
        """Upload artifacts → read idfkit://simulation/results populates from them."""
        source = tmp_path / "source_run"
        _write_minimal_sim_run_dir(source)
        files = _encode_run_dir(source)

        result = await call_tool(
            client,
            "upload_simulation_result",
            {
                "files": files,
                "energyplus_version": "25.2.0",
                "run_id": "t-round-trip",
                "runtime_seconds": 4.2,
            },
        )

        assert isinstance(result, dict)
        assert result["mode"] == "upload"
        assert result["success"] is True
        assert result["runtime_seconds"] == 4.2
        assert result["energyplus"]["version"] == "25.2.0"
        assert "eplusout.sql" in result["artifacts_written"]

        # Run directory actually exists and contains what we uploaded.
        out_dir = Path(result["output_directory"])
        assert out_dir.is_dir()
        assert (out_dir / "eplusout.sql").is_file()

        # Resource endpoint reads the uploaded SQL file transparently — the
        # invariant the MVP is designed to prove.
        payload = await read_resource_json(client, "idfkit://simulation/results")
        assert payload["success"] is True
        assert payload["sql_available"] is True
        assert payload["output_directory"] == result["output_directory"]

    async def test_meta_billing_emitted(self, client: Any, tmp_path: Path) -> None:
        """_meta.billing present with matching artifact byte counts."""
        source = tmp_path / "source_run"
        _write_minimal_sim_run_dir(source)
        files = _encode_run_dir(source)

        raw = await client.call_tool("upload_simulation_result", {"files": files})
        billing = (raw.meta or {}).get("billing")
        assert billing is not None, "upload_simulation_result must emit _meta.billing"
        assert billing["schema_version"] == "1"
        assert billing["tool"] == "upload_simulation_result"
        assert billing["runtime_ms"] >= 0
        assert billing["cpu_seconds"] >= 0.0
        artifact_names = {a["name"] for a in billing["artifacts"]}
        assert "eplusout.sql" in artifact_names
        # Byte count matches the source file exactly.
        sql_bytes_on_disk = (source / "eplusout.sql").stat().st_size
        uploaded_sql = next(a for a in billing["artifacts"] if a["name"] == "eplusout.sql")
        assert uploaded_sql["bytes"] == sql_bytes_on_disk

    async def test_contract_parity_list_output_variables(self, client: Any, tmp_path: Path) -> None:
        """Uploaded SQL is queryable exactly like a native-run SQL."""
        source = tmp_path / "source_run"
        _write_minimal_sim_run_dir(source)
        files = _encode_run_dir(source)
        await call_tool(client, "upload_simulation_result", {"files": files})

        vars_result = await call_tool(client, "list_output_variables", {"limit": 10})
        assert isinstance(vars_result, dict)
        assert vars_result["total_available"] >= 1
        names = {v["name"] for v in vars_result["variables"]}
        assert "Zone Mean Air Temperature" in names

    async def test_missing_sql_rejected(self, client: Any, tmp_path: Path) -> None:
        files = {"eplusout.err": base64.b64encode(b"").decode("ascii")}
        with pytest.raises(ToolError, match=r"eplusout\.sql"):
            await call_tool(client, "upload_simulation_result", {"files": files})

    async def test_disallowed_filename_rejected(self, client: Any, tmp_path: Path) -> None:
        source = tmp_path / "source_run"
        _write_minimal_sim_run_dir(source)
        files = _encode_run_dir(source)
        files["../escape.sql"] = base64.b64encode(b"x").decode("ascii")
        with pytest.raises(ToolError, match="not allowed"):
            await call_tool(client, "upload_simulation_result", {"files": files})

    async def test_oversize_rejected(self, client: Any, tmp_path: Path) -> None:
        # 51 MB dummy — exceeds the 50 MB aggregate cap.
        big = base64.b64encode(b"\x00" * (51 * 1024 * 1024)).decode("ascii")
        files = {"eplusout.sql": big}
        with pytest.raises(ToolError, match="exceeds"):
            await call_tool(client, "upload_simulation_result", {"files": files})

    async def test_invalid_base64_rejected(self, client: Any, tmp_path: Path) -> None:
        files = {"eplusout.sql": "!!!not-base64!!!"}
        with pytest.raises(ToolError, match="base64"):
            await call_tool(client, "upload_simulation_result", {"files": files})

    async def test_second_upload_replaces_first(self, client: Any, tmp_path: Path) -> None:
        source = tmp_path / "source_run"
        _write_minimal_sim_run_dir(source)
        files = _encode_run_dir(source)

        first = await call_tool(client, "upload_simulation_result", {"files": files, "run_id": "first"})
        second = await call_tool(client, "upload_simulation_result", {"files": files, "run_id": "second"})
        assert isinstance(first, dict) and isinstance(second, dict)
        assert first["output_directory"] != second["output_directory"]

        # Session state now reflects the second upload.
        payload = await read_resource_json(client, "idfkit://simulation/results")
        assert payload["output_directory"] == second["output_directory"]


# ---------------------------------------------------------------------------
# Streamable-HTTP subprocess coverage
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_http_ready(url: str, timeout: float = 15.0) -> None:
    """Poll the health endpoint until 200 or raise."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:  # noqa: S310 - local 127.0.0.1
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError) as exc:
            last_err = exc
            time.sleep(0.2)
    msg = f"HTTP server at {url} did not become ready within {timeout}s"
    if last_err is not None:
        msg += f" (last error: {last_err!r})"
    raise RuntimeError(msg)


@pytest.fixture()
def http_server(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Launch idfkit-mcp in streamable-http mode on a free port for the test.

    Yields the base URL; the subprocess is terminated on teardown.
    """
    import os

    port = _free_port()
    sim_dir = tmp_path_factory.mktemp("http-upload-sim")
    env = {**os.environ, "IDFKIT_MCP_SIMULATION_DIR": str(sim_dir), "IDFKIT_MCP_LOG_LEVEL": "WARNING"}
    # sys.executable + module name only, no shell — trusted local invocation.
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "idfkit_mcp.server", "--transport", "http", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_http_ready(f"http://127.0.0.1:{port}/health", timeout=30.0)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


class TestUploadSimulationResultHTTP:
    """The transport check the user asked to verify.

    Proves ``mcp-session-id`` affinity: an upload via one HTTP request is
    visible when the same session reads a resource, which is the critical
    invariant for any future browser-side (iframe) execution path.
    """

    async def test_http_round_trip(self, http_server: str, tmp_path: Path) -> None:
        source = tmp_path / "source_run"
        _write_minimal_sim_run_dir(source)
        files = _encode_run_dir(source)

        async with Client(f"{http_server}/mcp/") as http_client:
            # Upload via HTTP.
            raw = await http_client.call_tool(
                "upload_simulation_result",
                {
                    "files": files,
                    "energyplus_version": "25.2.0",
                    "run_id": "http-roundtrip",
                    "runtime_seconds": 1.5,
                },
            )
            payload = raw.structured_content
            assert payload is not None
            assert payload["mode"] == "upload"
            assert payload["success"] is True
            out_dir = payload["output_directory"]

            # Resource read on the same session must see the uploaded run.
            contents = await http_client.read_resource("idfkit://simulation/results")
            assert contents, "idfkit://simulation/results returned no content"
            import json

            body = json.loads(contents[0].text)
            assert body["sql_available"] is True
            assert body["output_directory"] == out_dir

            # Second read on the same session still sees the same run —
            # confirms mcp-session-id affinity (not a fresh session per call).
            contents_again = await http_client.read_resource("idfkit://simulation/results")
            body_again = json.loads(contents_again[0].text)
            assert body_again["output_directory"] == out_dir
