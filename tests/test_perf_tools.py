"""Per-call server time and response size budgets on the reference model (R-21, SC-011 to SC-013).

Deselected by default; run with ``uv run pytest -m perf tests/test_perf_tools.py``.

The reference model is ``HospitalLowEnergy`` (``tests/fixtures/HospitalLowEnergy.idf.gz``, the EnergyPlus 26.1
example file vendored from ``idfkit/benchmarks/fixtures/``), the largest EnergyPlus example model. Each test gets
a fresh session with the model loaded through ``load_model`` over the in-memory FastMCP transport, so a case can
measure a tool's first call after load as well as a cached call.

What :func:`assert_call_within_budget` measures:

- **Server time**: wall time of ``client.call_tool`` over the in-memory transport, best of ``repeat`` calls. This
  includes argument validation, the tool body and result serialisation, plus well under a millisecond of
  in-process transport, so it is a slight over-estimate of server time, never an under-estimate.
- **Response size**: UTF-8 bytes of the compact JSON of ``structuredContent``, or of the text content when a tool
  returns no structured content, whichever is larger. The default budget is 8 KB (SC-013).

Time budgets are the R-21 figures. ``CI_ALLOWANCE`` (2x, as in idfkit's ``tests/test_perf_budgets.py``) absorbs
shared-runner noise; size budgets get no allowance, since response size is deterministic.

Later tasks (T060, T094, T109, T124, T136) append cases.
"""

from __future__ import annotations

import gc
import gzip
import json
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport

pytestmark = pytest.mark.perf

REFERENCE_MODEL_GZ = Path(__file__).parent / "fixtures" / "HospitalLowEnergy.idf.gz"
RESPONSE_BUDGET_BYTES = 8 * 1024
"""Default response size of any new tool (SC-013)."""
CI_ALLOWANCE = 2.0
"""Multiplier on time budgets only, for shared CI runners."""


@dataclass(frozen=True)
class CallMeasurement:
    """One tool call's cost."""

    tool: str
    seconds: float
    response_bytes: int
    result: Any


def _response_bytes(result: Any) -> int:
    structured = result.structured_content
    structured_size = (
        len(json.dumps(structured, separators=(",", ":"), default=str).encode()) if structured is not None else 0
    )
    text = "".join(part.text for part in result.content if hasattr(part, "text"))
    return max(structured_size, len(text.encode()))


async def measure_call(
    client: Client[FastMCPTransport], tool: str, arguments: dict[str, Any] | None = None, *, repeat: int = 1
) -> CallMeasurement:
    """Call ``tool`` ``repeat`` times and return the fastest call with its response size.

    ``repeat=1`` measures exactly one call, which is what a "first call after load" budget needs.

    A full garbage collection runs first. Loading the reference model adds some 73,000 tracked objects and
    leaves a full collection pending, which the next allocation-heavy call would trip: about 115 ms
    under pytest's heap, measured on ``check_model_integrity``. That pause belongs to the load, not to
    the tool, so it is taken before the clock starts.
    """
    gc.collect()
    best = float("inf")
    result: Any = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = await client.call_tool(tool, arguments or {})
        best = min(best, time.perf_counter() - start)
    return CallMeasurement(tool=tool, seconds=best, response_bytes=_response_bytes(result), result=result)


async def assert_call_within_budget(
    client: Client[FastMCPTransport],
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    max_seconds: float,
    max_bytes: int = RESPONSE_BUDGET_BYTES,
    repeat: int = 1,
) -> CallMeasurement:
    """Call ``tool`` and assert its server time (times ``CI_ALLOWANCE``) and serialised response size."""
    m = await measure_call(client, tool, arguments, repeat=repeat)
    assert not m.result.is_error, f"{tool} returned an error: {m.result.content}"
    limit = max_seconds * CI_ALLOWANCE
    assert m.seconds <= limit, (
        f"{tool}{arguments or ''} took {m.seconds * 1000:.1f} ms; budget {max_seconds * 1000:.1f} ms "
        f"(x{CI_ALLOWANCE} CI allowance = {limit * 1000:.1f} ms)"
    )
    assert m.response_bytes <= max_bytes, (
        f"{tool}{arguments or ''} returned {m.response_bytes} bytes; budget {max_bytes} bytes"
    )
    return m


@pytest.fixture(scope="module")
def reference_model_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Decompress the reference model once per module."""
    target = tmp_path_factory.mktemp("reference_model") / "HospitalLowEnergy.idf"
    with gzip.open(REFERENCE_MODEL_GZ, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return target


@pytest.fixture()
async def hospital(
    client: Client[FastMCPTransport], reference_model_path: Path
) -> AsyncIterator[Client[FastMCPTransport]]:
    """Yield a client whose session has the reference model loaded through ``load_model``."""
    result = await client.call_tool("load_model", {"file_path": str(reference_model_path)})
    assert not result.is_error, result.content
    yield client


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


async def test_reference_model_loaded(hospital: Client[FastMCPTransport]) -> None:
    """The harness loads the model the budgets are written against."""
    result = await hospital.call_tool("list_objects", {"object_type": "Zone", "limit": 1})
    assert result.structured_content is not None
    assert result.structured_content["total"] > 100


async def test_list_objects_zone_brief(hospital: Client[FastMCPTransport]) -> None:
    """Sanity case: a cheap bounded read stays far inside the per-call budgets."""
    await assert_call_within_budget(
        hospital,
        "list_objects",
        {"object_type": "Zone", "limit": 20},
        max_seconds=0.05,
        repeat=5,
    )


TRACE_STARTS = [
    {"object_type": "Fan:VariableVolume", "name": "DOAS2_Fan"},
    {"object_type": "Coil:Cooling:Water:DetailedGeometry", "name": "DOAS2_CoolC 1"},
    {"object_type": "Coil:Heating:Water", "name": "Floor 2 Operating VAV Box Reheat Coil"},
    {"object_type": "Zone", "name": "Floor 1 Cafe"},
    {"object_type": "Connector:Splitter", "name": "SWHSys1 Supply Splitter"},
]
"""The largest default answers found on the reference model: a DOAS fan and coil, a reheat coil, a zone, a splitter."""


async def test_trace_hvac_first_call_after_load(hospital: Client[FastMCPTransport]) -> None:
    """The first trace builds the topology view and runs the checks (contracts/mcp-tools.md)."""
    await assert_call_within_budget(hospital, "trace_hvac", TRACE_STARTS[0], max_seconds=0.05)


@pytest.mark.parametrize("start", TRACE_STARTS, ids=lambda s: s["object_type"])
async def test_trace_hvac_cached(hospital: Client[FastMCPTransport], start: dict[str, Any]) -> None:
    """With the view cached, every default trace answers within 10 ms and 8 KB."""
    await hospital.call_tool("trace_hvac", start)
    await assert_call_within_budget(hospital, "trace_hvac", start, max_seconds=0.01, repeat=5)


async def test_check_model_integrity_with_topology(hospital: Client[FastMCPTransport]) -> None:
    """The existing checks plus the hvac_topology group, first call after load."""
    await assert_call_within_budget(hospital, "check_model_integrity", max_seconds=0.06)


TOPOLOGY_QUERIES = [
    {"loop": "CondenserLoop", "detail": "chain"},
    {},
    {"detail": "chain"},
]
"""One loop in chain detail (the PlantLoop ``CondenserLoop``, the reference model's loop with the most branches:
4 supply, 259 demand), then every loop in summary and in chain detail at the default limit of 20."""


def _topology_id(arguments: dict[str, Any]) -> str:
    return f"{arguments.get('loop', 'all')}-{arguments.get('detail', 'summary')}"


@pytest.mark.parametrize("arguments", TOPOLOGY_QUERIES, ids=_topology_id)
async def test_get_hvac_topology_first_call_after_load(
    hospital: Client[FastMCPTransport], arguments: dict[str, Any]
) -> None:
    """The first summary after load builds the topology view and runs the checks."""
    await assert_call_within_budget(hospital, "get_hvac_topology", arguments, max_seconds=0.05)


@pytest.mark.parametrize("arguments", TOPOLOGY_QUERIES, ids=_topology_id)
async def test_get_hvac_topology_cached(hospital: Client[FastMCPTransport], arguments: dict[str, Any]) -> None:
    """With the view cached, every summary answers within 10 ms and 8 KB."""
    await hospital.call_tool("get_hvac_topology", arguments)
    await assert_call_within_budget(hospital, "get_hvac_topology", arguments, max_seconds=0.01, repeat=5)


RENAMED_NODE = "DOAS6 Supply Equipment Outlet Node"
"""The reference model's most-used node: 18 uses across the DOAS6 supply equipment, setpoint managers and lists."""


async def test_rename_node(hospital: Client[FastMCPTransport]) -> None:
    """A rename rewrites every use and rebuilds the view; so does the rename back."""
    there = await assert_call_within_budget(
        hospital, "rename_node", {"old": RENAMED_NODE, "new": "DOAS6 Renamed Outlet Node"}, max_seconds=0.05
    )
    assert there.result.structured_content["fields_updated"] > 1
    back = await assert_call_within_budget(
        hospital, "rename_node", {"old": "DOAS6 Renamed Outlet Node", "new": RENAMED_NODE}, max_seconds=0.05
    )
    assert back.result.structured_content["fields_updated"] == there.result.structured_content["fields_updated"]
