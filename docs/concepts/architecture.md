# System Architecture

This page describes how idfkit-mcp is structured, where data lives, and what crosses the network boundary.

## High-Level Overview

```mermaid
---
config:
  theme: 'neutral'
---
graph TB
    subgraph Clients["MCP Clients"]
        direction TB
        Claude["Claude Desktop / Code"]
        Cursor["Cursor / VS Code"]
        Custom["Custom MCP Client"]
    end

    subgraph Server["idfkit-mcp Server"]
        Transport["Transport Layer<br/><small>stdio | SSE | streamable-http</small>"]
        Middleware["Middleware<br/><small>logging, error handling, session binding</small>"]
        Tools["28 Tools<br/><small>schema, read, write, validation,<br/>simulation, geometry, schedules, weather, docs</small>"]
        Resources["8 Resources<br/><small>read-only model & result state</small>"]
        Session["Session Manager<br/><small>up to 20 concurrent sessions</small>"]
        State["ServerState<br/><small>document, schema, sim results,<br/>weather file, docs index</small>"]
    end

    subgraph Core["idfkit (core library)"]
        Parser["IDF / epJSON Parser"]
        Schema["Bundled Schemas<br/><small>EnergyPlus 8.9 &ndash; 25.2</small>"]
        Validator["Validator"]
        SimRunner["Simulation Runner"]
        WeatherIdx["Weather Station Index<br/><small>16,000+ stations</small>"]
        Docs["Doc URL Builder"]
    end

    subgraph Local["Local Disk"]
        ModelFiles["Model Files<br/><small>IDF / epJSON</small>"]
        SimOutput["Simulation Output<br/><small>SQL, HTML, CSV, error files</small>"]
        WeatherFiles["Weather Files<br/><small>EPW / DDY</small>"]
        SessionCache["Session Cache<br/><small>~/.cache/idfkit/sessions/</small>"]
        DocsCache["Docs Cache<br/><small>~/.cache/idfkit/docs/</small>"]
    end

    subgraph External["External (Internet)"]
        DocsSite["docs.idfkit.com<br/><small>search indexes</small>"]
        WeatherDL["EnergyPlus Weather<br/><small>EPW downloads (climate.onebuilding.org)</small>"]
    end

    Clients -->|"JSON-RPC"| Transport
    Transport --> Middleware --> Tools & Resources
    Tools --> Session --> State
    Resources --> State

    State --> Core
    State -->|"read / write"| Local
    State -.->|"download & cache"| DocsSite
    Core -.->|"download"| WeatherDL
    Core -->|"read / write"| ModelFiles
    SimRunner -->|"write"| SimOutput
```

## Layered Architecture

The server is organized in four layers:

```mermaid
---
config:
  theme: 'neutral'
---
block
    columns 1
    block:transport["Transport"]
        stdio["stdio<br/>(single client)"]
        sse["SSE<br/>(HTTP streaming)"]
        http["streamable-http<br/>(multi-session)"]
    end
    block:middleware["Middleware"]
        mw["Logging · Error mapping · Session binding"]
    end
    block:tools_resources["Tools & Resources"]
        schema_t["Schema (4)"]
        read_t["Read (4)"]
        write_t["Write (9)"]
        val_t["Validation (1)"]
        sim_t["Simulation (4)"]
        weather_t["Weather (2)"]
        geom_t["Geometry (1)"]
        sched_t["Schedules (1)"]
        docs_t["Docs (2)"]
        res["Resources (8)"]
    end
    block:state_layer["Session & State"]
        state["ServerState — per-session document, schema, results, caches"]
    end
    block:core["Core Library (idfkit)"]
        idfkit["Parsing · Validation · Simulation · Weather · Schemas"]
    end
```

## Data Flow

### Where data lives

| Data | Location | Lifetime |
|------|----------|----------|
| EnergyPlus schemas (IDD/epJSON) | Bundled with idfkit | Permanent (per idfkit version) |
| Weather station index (16,000+ stations) | Bundled with idfkit | Permanent (per idfkit version) |
| Model files (IDF/epJSON) | User's filesystem | User-managed |
| Weather files (EPW/DDY) | `~/.cache/idfkit/weather/` or user path | Cached after download |
| Session state | `~/.cache/idfkit/sessions/<cwd-hash>.json` | Persists across restarts; cleared with `clear_session` |
| Documentation search index | `~/.cache/idfkit/docs/v{X.Y}/search.json` | Cached 7 days after download |
| Simulation output | Temp directory or user-specified path | Per-simulation run |

### What comes from the internet

Only two things are fetched over the network:

1. **Documentation search indexes** from `docs.idfkit.com` -- full-text search data for EnergyPlus I/O Reference and Engineering Reference. Downloaded once per EnergyPlus version and cached locally for 7 days.

2. **Weather files** (EPW/DDY) from the EnergyPlus weather repository. Downloaded on demand via the `download_weather_file` tool and cached locally.

Everything else -- schemas, station indexes, parsing, validation -- is fully offline using data bundled with idfkit.

### What requires a local installation

**EnergyPlus** must be installed locally to run simulations. The server discovers it by checking (in order):

1. `ENERGYPLUS_DIR` environment variable
2. System `PATH`
3. Standard OS install locations (`/usr/local/EnergyPlus-*`, `C:\EnergyPlusV*`, etc.)

Simulation is the only feature that requires EnergyPlus. All other tools (modeling, validation, schema exploration, weather search) work without it.

## Session Management

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Server as idfkit-mcp
    participant Disk as Cache Directory

    Client->>Server: First tool call
    Server->>Disk: Check for persisted session<br/>(keyed by CWD hash)
    alt Session file exists
        Disk-->>Server: Restore file_path, sim_dir, weather_file
        Server->>Server: Lazy-load model & results on access
    end
    Server-->>Client: Tool result

    Note over Server: State mutating tools auto-persist

    Client->>Server: load_model("office.idf")
    Server->>Disk: Save session state
    Client->>Server: run_simulation(...)
    Server->>Disk: Save session state (+ sim_dir)

    Client->>Server: clear_session()
    Server->>Disk: Delete session file
    Server->>Server: Reset all in-memory state
```

**Transport behavior:**

- **stdio** (Claude Desktop, Codex): Single session, persistence enabled. Session survives server restarts.
- **SSE / streamable-http** (multi-client): Up to 20 concurrent sessions keyed by `mcp-session-id` header. LRU eviction when full. Persistence disabled (sessions are ephemeral).

## Tool Categories

```mermaid
graph LR
    subgraph Schema["Schema Exploration"]
        A1[list_object_types]
        A2[describe_object_type]
        A3[search_schema]
        A4[get_available_references]
    end

    subgraph Read["Model Read"]
        B1[load_model]
        B2[convert_osm_to_idf]
        B3[list_objects]
        B4[search_objects]
    end

    subgraph Write["Model Write"]
        C1[new_model]
        C2[add_object / batch_add_objects]
        C3[update_object]
        C4[remove_object]
        C5[rename_object / duplicate_object]
        C6[save_model]
        C7[clear_session]
    end

    subgraph Validation
        D1[validate_model]
    end

    subgraph Simulation
        E1[run_simulation]
        E2[list_output_variables]
        E3[query_timeseries]
        E4[export_timeseries]
    end

    subgraph Weather
        F1[search_weather_stations]
        F2[download_weather_file]
    end

    subgraph Geometry
        H1[view_geometry]
    end

    subgraph Schedules
        I1[view_schedules]
    end

    subgraph Documentation
        G1[search_docs]
        G2[get_doc_section]
    end
```

## Typical Workflow

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant MCP as idfkit-mcp
    participant EP as EnergyPlus

    Agent->>MCP: describe_object_type("Zone")
    MCP-->>Agent: Field schema with constraints

    Agent->>MCP: new_model(version="24.2")
    MCP-->>Agent: Empty model created

    Agent->>MCP: batch_add_objects([...zones, walls, windows...])
    MCP-->>Agent: Objects added

    Agent->>MCP: validate_model()
    MCP-->>Agent: Validation results (errors, warnings)

    Agent->>MCP: search_weather_stations("Chicago")
    MCP-->>Agent: Matching stations with WMO IDs

    Agent->>MCP: download_weather_file("725300")
    MCP-->>Agent: EPW path

    Agent->>MCP: run_simulation(design_day=true)
    MCP->>EP: Execute simulation
    EP-->>MCP: Results (SQL, HTML, errors)
    MCP-->>Agent: Success + runtime + error summary

    Agent->>MCP: query_timeseries("Zone Mean Air Temperature")
    MCP-->>Agent: Hourly temperature data

    Agent->>MCP: save_model("office.idf")
    MCP-->>Agent: File saved
```
