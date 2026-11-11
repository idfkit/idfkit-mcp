"""Install a committed simulation run into the session, as if ``run_simulation`` had run it (no EnergyPlus).

The fixtures are idfkit's result-linking fixtures (``idfkit/tests/fixtures/simulation/linked/``): the model each
run simulated and the SQLite output EnergyPlus wrote for it, gzipped. ``5ZoneAirCooled.idf.gz`` is the model
already in ``tests/fixtures``; ``MultiStory`` has zone multipliers of 1 to 32.

The fixtures carry no ERR file, so one is written from the SQL ``Errors`` table. EnergyPlus joins a message's ERR
lines with two spaces in SQL, so each message is split there again: its first line, then ``** ~~~ **``
continuation lines.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from pathlib import Path

from idfkit import load_idf
from idfkit.simulation.result import SimulationResult

from idfkit_mcp.state import ServerState, get_state
from idfkit_mcp.tools.simulation import model_text_hash

FIXTURES = Path(__file__).parent / "fixtures"
MODELS = {
    "5ZoneAirCooled": FIXTURES / "5ZoneAirCooled.idf.gz",
    "MultiStory": FIXTURES / "linked" / "MultiStory.idf.gz",
}

_SEVERITY = {0: "Warning", 1: "Severe", 2: "Fatal"}


def _gunzip(source: Path, target: Path) -> Path:
    with gzip.open(source, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return target


def _write_err(sql_path: Path, err_path: Path) -> None:
    lines = ["Program Version,EnergyPlus"]
    with sqlite3.connect(sql_path) as conn:
        rows = conn.execute("SELECT ErrorType, ErrorMessage FROM Errors ORDER BY ErrorIndex").fetchall()
    for error_type, message in rows:
        severity = _SEVERITY.get(error_type)
        if severity is None:
            continue
        first, *rest = [part.strip() for part in str(message).split("  ") if part.strip()] or [""]
        lines.append(f"   ** {severity:<7} ** {first}")
        lines.extend(f"   **   ~~~   ** {line}" for line in rest)
    lines.append(
        "   ************* EnergyPlus Completed Successfully-- 0 Warning; 0 Severe Errors; Elapsed Time=00hr 00min  1.00sec"
    )
    err_path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def model_path(name: str, directory: Path) -> Path:
    """Decompress the fixture model *name* into *directory*."""
    return _gunzip(MODELS[name], directory / f"{name}.idf")


def install_run(name: str, directory: Path, *, load: bool = True) -> ServerState:
    """Make the session look as if ``run_simulation`` had just run the fixture *name*.

    With ``load`` the fixture model is loaded first; otherwise the session's current document is taken as the
    simulated one (a test may edit it before the run, as an agent would).
    """
    state = get_state()
    if load:
        doc = load_idf(str(model_path(name, directory)), strict=True)
        state.document = doc
        state.schema = doc.schema
    doc = state.require_model()
    run_dir = directory / f"{name}-run"
    run_dir.mkdir()
    sql_path = _gunzip(FIXTURES / "linked" / f"{name}.sql.gz", run_dir / "eplusout.sql")
    _write_err(sql_path, run_dir / "eplusout.err")
    result = SimulationResult(run_dir=run_dir, success=True, exit_code=0, stdout="", stderr="", runtime_seconds=1.0)
    state.record_simulation(doc, result, run_revision=doc.revision, model_hash=model_text_hash(doc))
    return state
