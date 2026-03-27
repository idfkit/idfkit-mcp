"""Profile the idfkit MCP server startup, tool call latency, and serialization overhead.

Measures:
  1. Import time (cold start)
  2. Server creation + tool registration
  3. Schema loading (first load vs cached)
  4. Individual tool call latency (all 28 tools where possible)
  5. Serialization overhead
  6. Memory usage
"""

from __future__ import annotations

import gc
import json
import statistics
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TimingResult:
    name: str
    times_ms: list[float] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.times_ms) if self.times_ms else 0.0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.times_ms) if self.times_ms else 0.0

    @property
    def min_ms(self) -> float:
        return min(self.times_ms) if self.times_ms else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.times_ms) if self.times_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if len(self.times_ms) < 2:
            return self.max_ms
        sorted_times = sorted(self.times_ms)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[min(idx, len(sorted_times) - 1)]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "runs": len(self.times_ms),
            "mean_ms": round(self.mean_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
        }
        if self.extra:
            d["extra"] = self.extra
        return d


def timed(func: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    """Run func and return (result, elapsed_ms)."""
    gc.disable()
    start = time.perf_counter_ns()
    result = func(*args, **kwargs)
    elapsed_ns = time.perf_counter_ns() - start
    gc.enable()
    return result, elapsed_ns / 1_000_000


def bench(bench_name: str, func: Any, *args: Any, runs: int = 10, **kwargs: Any) -> TimingResult:
    """Benchmark a function over multiple runs."""
    result = TimingResult(name=bench_name)
    for _ in range(runs):
        _, elapsed = timed(func, *args, **kwargs)
        result.times_ms.append(elapsed)
    return result


def profile_imports() -> TimingResult:
    """Measure cold import time for idfkit and idfkit_mcp."""
    # We can't truly re-import, but we can measure what's already loaded
    # For a real cold-start measurement, we use subprocess
    import subprocess

    result = TimingResult(name="cold_import")
    cmd = [
        sys.executable,
        "-c",
        "import time; s=time.perf_counter_ns(); "
        "from idfkit_mcp.server import create_server; "
        "e=time.perf_counter_ns(); "
        "print((e-s)/1_000_000)",
    ]
    for _ in range(3):
        start = time.perf_counter_ns()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
        elapsed_ns = time.perf_counter_ns() - start
        if proc.returncode == 0:
            internal_ms = float(proc.stdout.strip())
            result.times_ms.append(internal_ms)
            result.extra["subprocess_total_ms"] = round(elapsed_ns / 1_000_000, 3)
        else:
            print(f"  Import subprocess failed: {proc.stderr[:200]}", file=sys.stderr)
            result.times_ms.append(-1)
    return result


def profile_import_breakdown() -> list[TimingResult]:
    """Measure import time for individual modules."""
    import subprocess

    modules = [
        ("import_idfkit", "import idfkit"),
        ("import_mcp_sdk", "from mcp.server.fastmcp import FastMCP"),
        ("import_idfkit_mcp_server", "from idfkit_mcp.server import create_server"),
        (
            "import_idfkit_mcp_tools",
            "from idfkit_mcp.tools import schema, read, write, validation, simulation, weather",
        ),
    ]
    results = []
    for name, stmt in modules:
        r = TimingResult(name=name)
        for _ in range(3):
            cmd = [
                sys.executable,
                "-c",
                f"import time; s=time.perf_counter_ns(); {stmt}; e=time.perf_counter_ns(); print((e-s)/1_000_000)",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
            if proc.returncode == 0:
                r.times_ms.append(float(proc.stdout.strip()))
            else:
                print(f"  {name} failed: {proc.stderr[:200]}", file=sys.stderr)
        results.append(r)
    return results


def profile_server_creation() -> TimingResult:
    """Measure server creation + tool registration time."""
    from idfkit_mcp.server import create_server

    return bench("server_creation", create_server, runs=10)


def profile_schema_loading() -> list[TimingResult]:
    """Measure schema loading for different versions."""
    from idfkit import get_schema

    results = []

    # Cold load (first time for each version)
    versions = [
        ((25, 2, 0), "schema_load_25.2.0"),
        ((24, 2, 0), "schema_load_24.2.0"),
        ((9, 6, 0), "schema_load_9.6.0"),
    ]

    for version, name in versions:
        r = TimingResult(name=name)
        for _ in range(5):
            _, elapsed = timed(get_schema, version)
            r.times_ms.append(elapsed)
        results.append(r)

    return results


def profile_tool_calls() -> list[TimingResult]:
    """Profile each tool call latency."""
    from idfkit import new_document

    from idfkit_mcp.state import get_state
    from idfkit_mcp.tools.read import list_objects, search_objects
    from idfkit_mcp.tools.schema import describe_object_type, get_available_references, list_object_types, search_schema
    from idfkit_mcp.tools.validation import validate_model
    from idfkit_mcp.tools.weather import search_weather_stations
    from idfkit_mcp.tools.write import (
        add_object,
        batch_add_objects,
        duplicate_object,
        new_model,
        remove_object,
        rename_object,
        update_object,
    )

    results = []

    # === Schema tools (no model needed) ===
    results.append(bench("tool:list_object_types", list_object_types, runs=20))
    results.append(
        bench("tool:list_object_types(group)", list_object_types, group="Thermal Zones and Surfaces", runs=20)
    )
    results.append(bench("tool:describe_object_type(Zone)", describe_object_type, object_type="Zone", runs=20))
    results.append(
        bench("tool:describe_object_type(large)", describe_object_type, object_type="BuildingSurface:Detailed", runs=20)
    )
    results.append(bench("tool:search_schema(zone)", search_schema, query="zone", runs=20))
    results.append(bench("tool:search_schema(no_match)", search_schema, query="xyznonexistent", runs=20))

    # === Tools requiring a loaded model ===

    # Set up a model with some objects
    state = get_state()
    doc = new_document()
    state.document = doc
    state.schema = doc.schema

    # Add zones and surfaces for realistic testing
    for i in range(50):
        doc.add("Zone", f"Zone_{i}")
    for i in range(50):
        doc.add(
            "BuildingSurface:Detailed",
            f"Wall_{i}",
            surface_type="Wall",
            construction_name="",
            zone_name=f"Zone_{i % 50}",
            outside_boundary_condition="Outdoors",
            sun_exposure="SunExposed",
            wind_exposure="WindExposed",
            validate=False,
        )
    for i in range(20):
        doc.add(
            "Material", f"Mat_{i}", roughness="Smooth", thickness=0.1, conductivity=1.0, density=2000, specific_heat=900
        )
    for i in range(10):
        doc.add("Construction", f"Const_{i}", outside_layer=f"Mat_{i}")

    results.append(bench("tool:list_objects(Zone)", list_objects, object_type="Zone", runs=20))
    results.append(
        bench(
            "tool:list_objects(Surface,limit=10)",
            list_objects,
            object_type="BuildingSurface:Detailed",
            limit=10,
            runs=20,
        )
    )
    results.append(bench("tool:search_objects(Zone_2)", lambda: search_objects(query="Zone_2"), runs=20))
    results.append(bench("tool:search_objects(all_types)", lambda: search_objects(query="0"), runs=20))
    results.append(
        bench(
            "tool:get_available_references",
            lambda: get_available_references(object_type="BuildingSurface:Detailed", field_name="zone_name"),
            runs=20,
        )
    )
    results.append(bench("tool:validate_model", validate_model, runs=10))

    # Write tools (need fresh state each time for some)
    results.append(bench("tool:new_model", new_model, runs=10))

    # Re-setup state for remaining write tools
    state.document = doc
    state.schema = doc.schema

    results.append(
        bench(
            "tool:update_object",
            lambda: update_object(object_type="Material", name="Mat_0", fields={"thickness": 0.2}),
            runs=10,
        )
    )

    # Single add + remove cycle
    add_times = TimingResult(name="tool:add_object")
    remove_times = TimingResult(name="tool:remove_object")
    for i in range(10):
        _, add_elapsed = timed(lambda idx=i: add_object(object_type="Zone", name=f"TempZone_{idx}"))
        add_times.times_ms.append(add_elapsed)
        _, rm_elapsed = timed(lambda idx=i: remove_object(object_type="Zone", name=f"TempZone_{idx}", force=True))
        remove_times.times_ms.append(rm_elapsed)
    results.append(add_times)
    results.append(remove_times)

    # Batch add
    batch_objects = [{"object_type": "Zone", "name": f"BatchZone_{i}"} for i in range(20)]
    results.append(bench("tool:batch_add_objects(20)", lambda: batch_add_objects(objects=batch_objects), runs=5))

    # Rename
    doc.add("Zone", "RenameMe")
    results.append(
        bench(
            "tool:rename_object",
            lambda: rename_object(object_type="Zone", old_name="RenameMe", new_name="Renamed"),
            runs=1,
        )
    )

    # Duplicate
    results.append(
        bench(
            "tool:duplicate_object",
            lambda: duplicate_object(object_type="Zone", name="Zone_0", new_name="Zone_0_copy"),
            runs=1,
        )
    )

    # Weather tools
    results.append(bench("tool:search_weather_stations", lambda: search_weather_stations(query="New York"), runs=5))

    return results


def profile_serialization() -> list[TimingResult]:
    """Profile serialization overhead for various object sizes."""
    from idfkit import new_document

    from idfkit_mcp.serializers import serialize_object, serialize_object_description
    from idfkit_mcp.state import get_state

    state = get_state()
    doc = new_document()
    state.document = doc
    state.schema = doc.schema

    results = []

    # Simple object
    doc.add("Zone", "TestZone")
    zone = doc.get_collection("Zone").get("TestZone")
    results.append(bench("serialize:Zone(full)", serialize_object, zone, runs=50))
    results.append(bench("serialize:Zone(brief)", serialize_object, zone, schema=doc.schema, brief=True, runs=50))

    # Complex object
    doc.add(
        "BuildingSurface:Detailed",
        "TestWall",
        surface_type="Wall",
        construction_name="",
        zone_name="TestZone",
        outside_boundary_condition="Outdoors",
        sun_exposure="SunExposed",
        wind_exposure="WindExposed",
        validate=False,
    )
    wall = doc.get_collection("BuildingSurface:Detailed").get("TestWall")
    results.append(bench("serialize:Surface(full)", serialize_object, wall, runs=50))
    results.append(bench("serialize:Surface(brief)", serialize_object, wall, schema=doc.schema, brief=True, runs=50))

    # Object description serialization
    from idfkit.introspection import describe_object_type

    zone_desc = describe_object_type(doc.schema, "Zone")
    results.append(bench("serialize:describe(Zone)", serialize_object_description, zone_desc, runs=50))

    surface_desc = describe_object_type(doc.schema, "BuildingSurface:Detailed")
    results.append(bench("serialize:describe(Surface)", serialize_object_description, surface_desc, runs=50))

    # JSON serialization (final step before sending over wire)
    zone_dict = serialize_object(zone)
    results.append(bench("json.dumps:Zone", json.dumps, zone_dict, runs=50))

    surface_dict = serialize_object(wall)
    results.append(bench("json.dumps:Surface", json.dumps, surface_dict, runs=50))

    # Large result set
    for i in range(100):
        doc.add("Zone", f"Z_{i}")
    all_zones = [serialize_object(obj, schema=doc.schema, brief=True) for obj in doc.get_collection("Zone")]
    results.append(bench("json.dumps:100_zones", json.dumps, all_zones, runs=20))

    return results


def profile_memory() -> dict[str, Any]:
    """Profile memory usage."""
    tracemalloc.start()

    from idfkit import get_schema, new_document

    from idfkit_mcp.server import create_server

    snapshot_baseline = tracemalloc.take_snapshot()
    baseline_mb = sum(stat.size for stat in snapshot_baseline.statistics("filename")) / (1024 * 1024)

    # Create server
    _server = create_server()
    snapshot_server = tracemalloc.take_snapshot()
    server_mb = sum(stat.size for stat in snapshot_server.statistics("filename")) / (1024 * 1024)

    # Load schema
    _schema = get_schema((25, 2, 0))
    snapshot_schema = tracemalloc.take_snapshot()
    schema_mb = sum(stat.size for stat in snapshot_schema.statistics("filename")) / (1024 * 1024)

    # Create document with objects
    doc = new_document()
    for i in range(100):
        doc.add("Zone", f"Zone_{i}")
    for i in range(100):
        doc.add(
            "BuildingSurface:Detailed",
            f"Wall_{i}",
            surface_type="Wall",
            construction_name="",
            zone_name=f"Zone_{i % 100}",
            outside_boundary_condition="Outdoors",
            sun_exposure="SunExposed",
            wind_exposure="WindExposed",
            validate=False,
        )
    snapshot_doc = tracemalloc.take_snapshot()
    doc_mb = sum(stat.size for stat in snapshot_doc.statistics("filename")) / (1024 * 1024)

    tracemalloc.stop()

    return {
        "baseline_mb": round(baseline_mb, 2),
        "after_server_creation_mb": round(server_mb, 2),
        "after_schema_load_mb": round(schema_mb, 2),
        "after_200_objects_mb": round(doc_mb, 2),
        "server_delta_mb": round(server_mb - baseline_mb, 2),
        "schema_delta_mb": round(schema_mb - server_mb, 2),
        "doc_200_objects_delta_mb": round(doc_mb - schema_mb, 2),
    }


def profile_response_sizes() -> list[dict[str, Any]]:
    """Measure response payload sizes for common tool calls."""
    from idfkit import new_document

    from idfkit_mcp.state import get_state
    from idfkit_mcp.tools.read import list_objects
    from idfkit_mcp.tools.schema import describe_object_type, list_object_types, search_schema

    state = get_state()
    doc = new_document()
    state.document = doc
    state.schema = doc.schema
    for i in range(50):
        doc.add("Zone", f"Zone_{i}")
    for i in range(50):
        doc.add(
            "BuildingSurface:Detailed",
            f"Wall_{i}",
            surface_type="Wall",
            construction_name="",
            zone_name=f"Zone_{i}",
            outside_boundary_condition="Outdoors",
            sun_exposure="SunExposed",
            wind_exposure="WindExposed",
            validate=False,
        )

    results_data = []
    calls: list[tuple[str, Any, dict[str, Any]]] = [
        ("list_object_types()", list_object_types, {}),
        ("describe_object_type(Zone)", describe_object_type, {"object_type": "Zone"}),
        ("describe_object_type(Surface)", describe_object_type, {"object_type": "BuildingSurface:Detailed"}),
        ("search_schema(zone)", search_schema, {"query": "zone"}),
        ("list_objects(Zone,50)", list_objects, {"object_type": "Zone"}),
        ("list_objects(Surface,50)", list_objects, {"object_type": "BuildingSurface:Detailed"}),
    ]

    for name, func, kwargs in calls:
        result = func(**kwargs)
        payload = json.dumps(result)
        results_data.append({
            "tool_call": name,
            "payload_bytes": len(payload.encode("utf-8")),
            "payload_kb": round(len(payload.encode("utf-8")) / 1024, 2),
        })

    return results_data


def _collect_results() -> dict[str, Any]:
    """Run all profiling phases and return aggregated results."""
    all_results: dict[str, Any] = {}

    print("\n[1/6] Profiling cold import time...")
    import_result = profile_imports()
    import_breakdown = profile_import_breakdown()
    all_results["cold_import"] = import_result.to_dict()
    all_results["import_breakdown"] = [r.to_dict() for r in import_breakdown]

    print("[2/6] Profiling server creation...")
    server_result = profile_server_creation()
    all_results["server_creation"] = server_result.to_dict()

    print("[3/6] Profiling schema loading...")
    schema_results = profile_schema_loading()
    all_results["schema_loading"] = [r.to_dict() for r in schema_results]

    print("[4/6] Profiling tool calls...")
    tool_results = profile_tool_calls()
    all_results["tool_calls"] = [r.to_dict() for r in tool_results]

    print("[5/6] Profiling serialization...")
    serial_results = profile_serialization()
    all_results["serialization"] = [r.to_dict() for r in serial_results]

    print("[6/6] Profiling memory usage...")
    all_results["memory"] = profile_memory()

    print("       Measuring response payload sizes...")
    all_results["response_sizes"] = profile_response_sizes()

    return all_results


def _print_report(all_results: dict[str, Any]) -> None:
    """Print the formatted profiling report."""
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    print("\n--- Cold Import Time ---")
    _print_timing(all_results["cold_import"])
    print("\n--- Import Breakdown ---")
    for r in all_results["import_breakdown"]:
        _print_timing(r)

    print("\n--- Server Creation ---")
    _print_timing(all_results["server_creation"])

    print("\n--- Schema Loading ---")
    for r in all_results["schema_loading"]:
        _print_timing(r)

    print("\n--- Tool Call Latency ---")
    sorted_tools = sorted(all_results["tool_calls"], key=lambda x: x["median_ms"], reverse=True)
    print(f"  {'Tool':<45} {'median':>8} {'p95':>8} {'min':>8} {'max':>8}")
    print(f"  {'-' * 45} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 8}")
    for r in sorted_tools:
        print(
            f"  {r['name']:<45} {r['median_ms']:>7.2f}ms {r['p95_ms']:>7.2f}ms {r['min_ms']:>7.2f}ms {r['max_ms']:>7.2f}ms"
        )

    print("\n--- Serialization ---")
    for r in all_results["serialization"]:
        _print_timing(r)

    print("\n--- Memory Usage ---")
    mem = all_results["memory"]
    print(f"  Baseline (after imports):     {mem['baseline_mb']:>8.2f} MB")
    print(
        f"  After server creation:        {mem['after_server_creation_mb']:>8.2f} MB  (+{mem['server_delta_mb']:.2f} MB)"
    )
    print(f"  After schema load (v25.2.0):  {mem['after_schema_load_mb']:>8.2f} MB  (+{mem['schema_delta_mb']:.2f} MB)")
    print(
        f"  After 200 objects:            {mem['after_200_objects_mb']:>8.2f} MB  (+{mem['doc_200_objects_delta_mb']:.2f} MB)"
    )

    print("\n--- Response Payload Sizes ---")
    print(f"  {'Tool Call':<45} {'Size':>10}")
    print(f"  {'-' * 45} {'-' * 10}")
    for r in all_results["response_sizes"]:
        size_str = f"{r['payload_kb']:.1f} KB" if r["payload_kb"] >= 1 else f"{r['payload_bytes']} B"
        print(f"  {r['tool_call']:<45} {size_str:>10}")

    _print_bottlenecks(all_results)


def _print_bottlenecks(all_results: dict[str, Any]) -> None:
    """Print bottleneck analysis section."""
    print("\n--- Bottleneck Analysis ---")
    slow_tools = [r for r in all_results["tool_calls"] if r["median_ms"] > 10]
    if slow_tools:
        print("  Tools >10ms median:")
        for r in sorted(slow_tools, key=lambda x: x["median_ms"], reverse=True):
            print(f"    {r['name']}: {r['median_ms']:.2f}ms")
    else:
        print("  All tools under 10ms median. Good!")

    large_payloads = [r for r in all_results["response_sizes"] if r["payload_kb"] > 10]
    if large_payloads:
        print("  Payloads >10KB:")
        for r in sorted(large_payloads, key=lambda x: x["payload_bytes"], reverse=True):
            print(f"    {r['tool_call']}: {r['payload_kb']:.1f} KB")

    cold_import_ms = all_results["cold_import"]["median_ms"]
    if cold_import_ms > 1000:
        print(f"  Cold import is slow: {cold_import_ms:.0f}ms (target: <1000ms)")
    elif cold_import_ms > 500:
        print(f"  Cold import is moderate: {cold_import_ms:.0f}ms")
    else:
        print(f"  Cold import is fast: {cold_import_ms:.0f}ms")


def main() -> None:
    print("=" * 70)
    print("idfkit-mcp Server Performance Profile")
    print("=" * 70)

    all_results = _collect_results()
    _print_report(all_results)

    # Save raw JSON
    output_path = Path(__file__).parent / "profile_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Raw results saved to: {output_path}")


def _print_timing(r: dict[str, Any]) -> None:
    print(
        f"  {r['name']}: median={r['median_ms']:.2f}ms, p95={r['p95_ms']:.2f}ms, min={r['min_ms']:.2f}ms, max={r['max_ms']:.2f}ms ({r['runs']} runs)"
    )


if __name__ == "__main__":
    main()
