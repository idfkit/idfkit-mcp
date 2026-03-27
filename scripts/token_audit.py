"""Exhaustive token audit of the idfkit MCP server.

Exercises every tool and resource through the FastMCP Client,
measuring both the tool listing overhead and per-call response sizes.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from idfkit import new_document
from idfkit.simulation.result import SimulationResult

from idfkit_mcp.server import mcp
from idfkit_mcp.state import get_state, reset_sessions

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def measure_result(result: Any) -> dict[str, int]:
    """Measure content and structured_content sizes from a tool call result."""
    content_parts = result.content if hasattr(result, "content") else []
    content_text = ""
    for part in content_parts:
        if hasattr(part, "text"):
            content_text += part.text

    structured_text = ""
    if result.structured_content:
        structured_text = json.dumps(result.structured_content, default=str)

    return {
        "content_chars": len(content_text),
        "structured_chars": len(structured_text),
        "total_chars": len(content_text) + len(structured_text),
        "content_tokens": estimate_tokens(content_text),
        "structured_tokens": estimate_tokens(structured_text),
        "total_tokens": estimate_tokens(content_text + structured_text),
    }


async def setup_model_with_zones() -> None:
    """Set up a model with zones and surfaces for testing."""
    reset_sessions()
    state = get_state()
    state.persistence_enabled = False
    doc = new_document()
    state.document = doc
    state.schema = doc.schema

    doc.add("Zone", "Office")
    doc.add("Zone", "Corridor")
    doc.add(
        "BuildingSurface:Detailed",
        "Office_Wall",
        surface_type="Wall",
        construction_name="",
        zone_name="Office",
        outside_boundary_condition="Outdoors",
        sun_exposure="SunExposed",
        wind_exposure="WindExposed",
        validate=False,
    )
    doc.add(
        "Material",
        "Concrete",
        roughness="MediumRough",
        thickness=0.2,
        conductivity=1.0,
        density=2300.0,
        specific_heat=880.0,
    )
    doc.add(
        "Construction",
        "BasicWall",
        outside_layer="Concrete",
    )
    doc.add(
        "Schedule:Compact",
        "AlwaysOn",
        schedule_type_limits_name="",
        field_1="Through: 12/31",
        field_2="For: AllDays",
        field_3="Until: 24:00",
        field_4="1",
    )


async def setup_simulation_sql(tmp_path: Path) -> None:
    """Set up fake simulation results with SQL database."""
    state = get_state()
    run_dir = tmp_path
    conn = sqlite3.connect(str(run_dir / "eplusout.sql"))
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
    # Create ReportData and Time tables for timeseries queries
    cur.execute(
        "CREATE TABLE Time ("
        "  TimeIndex INTEGER PRIMARY KEY,"
        "  Year INTEGER, Month INTEGER, Day INTEGER, Hour INTEGER, Minute INTEGER,"
        "  Dst INTEGER, Interval INTEGER, IntervalType INTEGER,"
        "  SimulationDays INTEGER, DayType TEXT, WarmupFlag INTEGER,"
        "  Environment TEXT, EnvironmentType INTEGER"
        ")"
    )
    cur.execute(
        "INSERT INTO Time VALUES "
        "(1, 2024, 1, 1, 1, 0, 0, 60, 2, 1, 'WinterDesignDay', 0, 'AnnualRun', 3),"
        "(2, 2024, 1, 1, 2, 0, 0, 60, 2, 1, 'WinterDesignDay', 0, 'AnnualRun', 3),"
        "(3, 2024, 1, 1, 3, 0, 0, 60, 2, 1, 'WinterDesignDay', 0, 'AnnualRun', 3)"
    )
    cur.execute(
        "CREATE TABLE ReportData ("
        "  ReportDataIndex INTEGER PRIMARY KEY,"
        "  TimeIndex INTEGER,"
        "  ReportDataDictionaryIndex INTEGER,"
        "  Value REAL"
        ")"
    )
    cur.execute("INSERT INTO ReportData VALUES (1, 1, 1, 21.5),(2, 2, 1, 22.0),(3, 3, 1, 22.5)")
    conn.commit()
    conn.close()

    (run_dir / "eplusout.rdd").write_text("", encoding="latin-1")
    (run_dir / "eplusout.mdd").write_text("", encoding="latin-1")

    state.simulation_result = SimulationResult(
        run_dir=run_dir,
        success=True,
        exit_code=0,
        stdout="",
        stderr="",
        runtime_seconds=0.1,
    )


async def main() -> None:  # noqa: C901
    await setup_model_with_zones()

    async with Client(transport=FastMCPTransport(mcp)) as client:
        # =====================================================================
        # 1. TOOL LISTING
        # =====================================================================
        tools = await client.list_tools()
        print(f"\n{'=' * 80}")
        print("1. TOOL LISTING (tools/list)")
        print(f"{'=' * 80}")
        print(f"Total tools: {len(tools)}")

        tools_json = json.dumps([t.model_dump() for t in tools], indent=2, default=str)
        print(f"Full tools/list payload: {len(tools_json):,} chars ≈ {estimate_tokens(tools_json):,} tokens")

        tool_details = []
        for t in tools:
            desc = t.description or ""
            schema_json = json.dumps(t.inputSchema, indent=2) if t.inputSchema else "{}"
            tool_details.append((
                t.name,
                estimate_tokens(desc),
                estimate_tokens(schema_json),
                estimate_tokens(desc + schema_json),
            ))

        tool_details.sort(key=lambda x: x[3], reverse=True)
        print(f"\n{'Tool':<35} {'Desc':>6} {'Schema':>8} {'Total':>8}")
        print(f"{'-' * 35} {'-' * 6} {'-' * 8} {'-' * 8}")
        for name, desc_t, schema_t, total_t in tool_details:
            print(f"{name:<35} {desc_t:>6} {schema_t:>8} {total_t:>8}")
        total_listing = sum(t[3] for t in tool_details)
        print(f"{'TOTAL':<35} {'':>6} {'':>8} {total_listing:>8}")

        # =====================================================================
        # 2. RESOURCE LISTING
        # =====================================================================
        resources = await client.list_resources()
        resource_templates = await client.list_resource_templates()
        print(f"\n{'=' * 80}")
        print("2. RESOURCE LISTING")
        print(f"{'=' * 80}")
        print(f"Static resources: {len(resources)}")
        for r in resources:
            rj = json.dumps(r.model_dump(), indent=2, default=str)
            print(f"  {r.name}: {len(rj)} chars ≈ {estimate_tokens(rj)} tokens")
        print(f"Resource templates: {len(resource_templates)}")
        for rt in resource_templates:
            rtj = json.dumps(rt.model_dump(), indent=2, default=str)
            print(f"  {rt.name}: {len(rtj)} chars ≈ {estimate_tokens(rtj)} tokens")

        # =====================================================================
        # 3. EVERY TOOL CALL
        # =====================================================================
        print(f"\n{'=' * 80}")
        print("3. EVERY TOOL CALL — RESPONSE SIZES")
        print(f"{'=' * 80}")

        results: list[tuple[str, dict[str, int], str | None]] = []

        async def call_and_measure(name: str, args: dict[str, Any] | None = None, label: str | None = None) -> None:
            display = label or f"{name}({json.dumps(args) if args else ''})"
            try:
                result = await client.call_tool(name, args or {})
                m = measure_result(result)
                results.append((display, m, None))
            except Exception as e:
                results.append((
                    display,
                    {
                        "content_chars": 0,
                        "structured_chars": 0,
                        "total_chars": 0,
                        "content_tokens": 0,
                        "structured_tokens": 0,
                        "total_tokens": 0,
                    },
                    str(e)[:80],
                ))

        # --- Read tools ---
        await call_and_measure("get_model_summary")
        await call_and_measure("list_objects", {"object_type": "Zone"})
        await call_and_measure("list_objects", {"object_type": "Zone", "limit": 200}, "list_objects(Zone, limit=200)")
        await call_and_measure("get_object", {"object_type": "Zone", "name": "Office"})
        await call_and_measure("get_object", {"object_type": "BuildingSurface:Detailed", "name": "Office_Wall"})
        await call_and_measure("search_objects", {"query": "office"})
        await call_and_measure("search_objects", {"query": "a"}, "search_objects('a') [broad]")
        await call_and_measure("get_references", {"name": "Office"})
        await call_and_measure("get_references", {"name": "Concrete"})

        # --- Write tools ---
        await call_and_measure("new_model")
        # Re-setup model after new_model
        await setup_model_with_zones()
        await call_and_measure("add_object", {"object_type": "Zone", "name": "Lobby"})
        await call_and_measure(
            "add_object",
            {
                "object_type": "Material",
                "name": "Brick",
                "fields": {"thickness": 0.1, "conductivity": 0.7, "density": 1800, "specific_heat": 900},
            },
        )
        await call_and_measure(
            "batch_add_objects",
            {
                "objects": [
                    {"object_type": "Zone", "name": "Zone1"},
                    {"object_type": "Zone", "name": "Zone2"},
                    {"object_type": "Zone", "name": "Zone3"},
                ]
            },
            "batch_add_objects(3 zones)",
        )
        await call_and_measure(
            "batch_add_objects",
            {"objects": [{"object_type": "Zone", "name": f"BatchZone{i}"} for i in range(10)]},
            "batch_add_objects(10 zones)",
        )
        await call_and_measure("update_object", {"object_type": "Zone", "name": "Office", "fields": {"multiplier": 2}})
        await call_and_measure("duplicate_object", {"object_type": "Zone", "name": "Office", "new_name": "Office_Copy"})
        await call_and_measure(
            "rename_object", {"object_type": "Zone", "old_name": "Office_Copy", "new_name": "Office_Renamed"}
        )
        await call_and_measure("remove_object", {"object_type": "Zone", "name": "Office_Renamed"})

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".idf", delete=False) as f:
            save_path = f.name
        await call_and_measure("save_model", {"file_path": save_path})

        await call_and_measure("clear_session")
        # Re-setup after clear
        await setup_model_with_zones()

        # --- Schema tools ---
        await call_and_measure("list_object_types")
        await call_and_measure(
            "list_object_types", {"group": "Thermal Zones and Surfaces"}, "list_object_types(Thermal Zones)"
        )
        await call_and_measure("list_object_types", {"limit": 100}, "list_object_types(limit=100)")
        await call_and_measure("describe_object_type", {"object_type": "Zone"})
        await call_and_measure("describe_object_type", {"object_type": "Material"})
        await call_and_measure("describe_object_type", {"object_type": "BuildingSurface:Detailed"})
        await call_and_measure("describe_object_type", {"object_type": "Schedule:Compact"})
        await call_and_measure("describe_object_type", {"object_type": "AirLoopHVAC"})
        await call_and_measure("describe_object_type", {"object_type": "ZoneHVAC:EquipmentList"})
        await call_and_measure("search_schema", {"query": "zone"})
        await call_and_measure("search_schema", {"query": "a"}, "search_schema('a') [very broad]")
        await call_and_measure("search_schema", {"query": "material"})
        await call_and_measure("search_schema", {"query": "hvac"})
        await call_and_measure("search_schema", {"query": "zone", "limit": 5}, "search_schema('zone', limit=5)")
        await call_and_measure(
            "get_available_references", {"object_type": "BuildingSurface:Detailed", "field_name": "zone_name"}
        )
        await call_and_measure(
            "get_available_references", {"object_type": "BuildingSurface:Detailed", "field_name": "construction_name"}
        )

        # --- Validation tools ---
        await call_and_measure("validate_model")
        await call_and_measure("validate_model", {"check_references": False}, "validate_model(no refs)")
        await call_and_measure("validate_model", {"object_types": ["Zone"]}, "validate_model(Zone only)")
        await call_and_measure("check_references")

        # --- Documentation tools ---
        await call_and_measure("lookup_documentation", {"object_type": "Zone"})
        await call_and_measure("lookup_documentation", {"object_type": "AirLoopHVAC"})
        await call_and_measure("search_docs", {"query": "zone heat balance"})
        await call_and_measure("search_docs", {"query": "material properties"})
        await call_and_measure("search_docs", {"query": "hvac"})
        await call_and_measure("search_docs", {"query": "a", "limit": 20}, "search_docs('a', limit=20)")

        # search_docs then get_doc_section
        try:
            search_result = await client.call_tool("search_docs", {"query": "zone"})
            if search_result.structured_content:
                hits = search_result.structured_content.get("results", [])
                if hits:
                    loc = hits[0]["location"]
                    await call_and_measure("get_doc_section", {"location": loc}, f"get_doc_section('{loc[:40]}...')")
                    await call_and_measure(
                        "get_doc_section", {"location": loc, "max_length": 2000}, "get_doc_section(max_length=2000)"
                    )
        except Exception:  # noqa: S110
            pass  # search_docs may fail if docs index is not available

        # --- Simulation tools (with mock SQL) ---
        with tempfile.TemporaryDirectory() as tmp_dir:
            await setup_simulation_sql(Path(tmp_dir))

            await call_and_measure("list_output_variables")
            await call_and_measure(
                "list_output_variables", {"search": "Temperature"}, "list_output_variables('Temperature')"
            )
            await call_and_measure(
                "query_timeseries", {"variable_name": "Zone Mean Air Temperature", "key_value": "OFFICE"}
            )
            await call_and_measure(
                "query_timeseries",
                {"variable_name": "Zone Mean Air Temperature", "key_value": "OFFICE", "limit": 100},
                "query_timeseries(limit=100)",
            )
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
                csv_path = f.name
            await call_and_measure(
                "export_timeseries",
                {"variable_name": "Zone Mean Air Temperature", "key_value": "OFFICE", "output_path": csv_path},
            )

        # --- Weather tools (no network) ---
        await call_and_measure("search_weather_stations", {"query": "Boston"})
        await call_and_measure(
            "search_weather_stations",
            {"query": "Boston", "country": "USA", "state": "MA"},
            "search_weather_stations(Boston, USA, MA)",
        )
        await call_and_measure(
            "search_weather_stations",
            {"latitude": 42.36, "longitude": -71.06},
            "search_weather_stations(lat/lon Boston)",
        )
        await call_and_measure("search_weather_stations", {"query": "a"}, "search_weather_stations('a') [broad]")
        # download_weather_file skipped (requires network)

        # --- Load model from file ---
        await call_and_measure("load_model", {"file_path": save_path})

        # --- Resources ---
        print(f"\n{'=' * 80}")
        print("4. RESOURCE READS")
        print(f"{'=' * 80}")

        resource_results: list[tuple[str, int, str | None]] = []

        async def read_and_measure(uri: str) -> None:
            try:
                contents = await client.read_resource(uri)
                total_chars = sum(len(c.text) if hasattr(c, "text") else 0 for c in contents)
                resource_results.append((uri, total_chars, None))
            except Exception as e:
                resource_results.append((uri, 0, str(e)[:80]))

        await read_and_measure("idfkit://model/summary")
        await read_and_measure("idfkit://schema/Zone")
        await read_and_measure("idfkit://schema/Material")
        await read_and_measure("idfkit://schema/BuildingSurface:Detailed")
        await read_and_measure("idfkit://schema/AirLoopHVAC")
        await read_and_measure("idfkit://model/objects/Zone/Office")
        await read_and_measure("idfkit://model/objects/Material/Concrete")

        for uri, chars, err in resource_results:
            if err:
                print(f"  {uri}: ERROR — {err}")
            else:
                print(f"  {uri}: {chars:,} chars ≈ {estimate_tokens(str('x' * chars)):,} tokens")

        # =====================================================================
        # 5. PRINT ALL TOOL RESULTS
        # =====================================================================
        print(f"\n{'=' * 80}")
        print("5. ALL TOOL CALL RESULTS — SORTED BY SIZE")
        print(f"{'=' * 80}")

        results.sort(key=lambda x: x[1]["total_tokens"], reverse=True)
        print(f"\n{'Call':<50} {'Content':>8} {'Struct':>8} {'Total':>8} {'Error'}")
        print(f"{'-' * 50} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 20}")
        grand_total = 0
        for display, m, err in results:
            display_trunc = display[:50]
            err_str = err[:20] if err else ""
            print(
                f"{display_trunc:<50} {m['content_tokens']:>8} {m['structured_tokens']:>8} {m['total_tokens']:>8} {err_str}"
            )
            grand_total += m["total_tokens"]

        print(f"\n{'TOTAL across all calls':<50} {'':>8} {'':>8} {grand_total:>8}")

        # =====================================================================
        # 6. DUPLICATION ANALYSIS
        # =====================================================================
        print(f"\n{'=' * 80}")
        print("6. DUPLICATION: content vs structuredContent")
        print(f"{'=' * 80}")
        print("Tools returning Pydantic models send BOTH content (text) and structuredContent (JSON).")
        print("This doubles the token cost for every call.\n")

        duped_calls = [(d, m) for d, m, e in results if m["content_tokens"] > 0 and m["structured_tokens"] > 0]
        duped_calls.sort(key=lambda x: x[1]["structured_tokens"], reverse=True)
        total_waste = sum(min(m["content_tokens"], m["structured_tokens"]) for _, m in duped_calls)
        print(f"Calls with both content + structured: {len(duped_calls)}/{len(results)}")
        print(f"Estimated wasted tokens from duplication: ~{total_waste:,}")

        # =====================================================================
        # 7. SUMMARY
        # =====================================================================
        print(f"\n{'=' * 80}")
        print("7. TOKEN BUDGET SUMMARY")
        print(f"{'=' * 80}")
        print(f"  Tool listing (tools/list):        ~{total_listing:,} tokens")
        print(f"  Full tools/list wire payload:      ~{estimate_tokens(tools_json):,} tokens")
        print(f"  Instructions:                      ~{estimate_tokens(mcp.instructions or ''):,} tokens")
        print(
            f"  Resources listing:                 ~{sum(estimate_tokens(json.dumps(r.model_dump(), default=str)) for r in resources):,} tokens"
        )
        print(
            f"  Resource templates listing:        ~{sum(estimate_tokens(json.dumps(rt.model_dump(), default=str)) for rt in resource_templates):,} tokens"
        )
        print("")
        desc_zone_tokens = next(
            (m["total_tokens"] for d, m, _ in results if "describe_object_type" in d and "Zone" in d), 0
        )
        search_zone_tokens = next(
            (m["total_tokens"] for d, m, _ in results if "search_schema" in d and "zone" in d and "limit" not in d), 0
        )
        validate_tokens = next((m["total_tokens"] for d, m, _ in results if d == "validate_model({})"), 0)
        print(f"  Typical describe_object_type call: ~{desc_zone_tokens:,} tokens")
        print(f"  Typical search_schema call:        ~{search_zone_tokens:,} tokens")
        print(f"  Typical validate_model call:       ~{validate_tokens:,} tokens")


if __name__ == "__main__":
    asyncio.run(main())
