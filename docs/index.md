---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

# idfkit-mcp

<p class="hero-tagline">
A production-ready MCP server for EnergyPlus workflows: schema discovery,
model editing, integrity checks, QA diagnostics, peak-load analysis, and simulation via idfkit.
</p>

<div class="badges" markdown>

[![Release](https://img.shields.io/github/v/release/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/releases)
[![Build status](https://img.shields.io/github/actions/workflow/status/idfkit/idfkit-mcp/main.yml?branch=main)](https://github.com/idfkit/idfkit-mcp/actions/workflows/main.yml?query=branch%3Amain)
[![License](https://img.shields.io/github/license/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/blob/main/LICENSE)

</div>

<div class="hero-buttons" markdown>

[Install & Configure :material-arrow-right:](getting-started/installation.md){ .md-button .md-button--primary }
[Tool Reference](tools/index.md){ .md-button }

</div>

</div>

<div class="feature-chips" markdown>

<span class="chip">:material-tools: 35 MCP tools</span>
<span class="chip">:material-shape-outline: Schema-aware edits</span>
<span class="chip">:material-shield-check-outline: Validation + integrity checks</span>
<span class="chip">:material-weather-cloudy: Weather search + download</span>
<span class="chip">:material-play-circle-outline: Simulation QA diagnostics</span>
<span class="chip">:material-chart-waterfall: Peak loads + report viewers</span>
<span class="chip">:material-cube-outline: Geometry + schedule viewers</span>
<span class="chip">:material-robot-outline: Codex + Claude workflows</span>

</div>

---

## What You Get

- A single MCP server that covers the EnergyPlus model lifecycle:
  - schema exploration
  - model read/write operations
  - schema validation and domain integrity checks
  - weather station search and EPW download
  - simulation runs with structured QA diagnostics
  - peak-load analysis and tabular report browsing
  - interactive geometry, schedule, and simulation viewers
- Predictable, structured tool responses for autonomous agents.
- Workflow compatibility across Codex, Claude, and other MCP-capable clients.

## Recommended Tool Order

1. `load_model` or `new_model` (or read `idfkit://model/summary` resource)
2. `describe_object_type` before edits
3. `batch_add_objects` for bulk creation
4. `validate_model` after modifications
5. `check_model_integrity`
6. `run_simulation`
7. Read `idfkit://simulation/results`, then `analyze_peak_loads` or `view_simulation_report`

## Quick Workflow Example

```text
1) new_model(version="24.1.0")
2) describe_object_type(object_type="Zone")
3) batch_add_objects(objects=[...])
4) validate_model(check_references=True)
5) check_model_integrity()
6) download_weather_file(query="Chicago")
7) run_simulation(annual=True)
8) read idfkit://simulation/results resource
9) analyze_peak_loads()
```

---

## Explore the Docs

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Get Started**

    ---

    Install the server, configure MCP clients, and run your first end-to-end session.

    [:octicons-arrow-right-24: Get Started](getting-started/installation.md)

-   :material-robot:{ .lg .middle } **Agent Workflows**

    ---

    Practical patterns for Codex, Claude, and multi-agent orchestration.

    [:octicons-arrow-right-24: Agent Workflows](workflows/codex.md)

-   :material-tools:{ .lg .middle } **Tool Reference**

    ---

    Parameter-by-parameter guidance for all tools and expected outputs.

    [:octicons-arrow-right-24: Tool Reference](tools/index.md)

-   :material-lightbulb-on-outline:{ .lg .middle } **Concepts**

    ---

    Understand state management, safety constraints, and failure semantics.

    [:octicons-arrow-right-24: Concepts](concepts/server-state.md)

-   :material-alert-circle-outline:{ .lg .middle } **Troubleshooting**

    ---

    Resolve setup, schema, weather, and simulation issues quickly.

    [:octicons-arrow-right-24: Troubleshooting](troubleshooting/setup.md)

-   :material-api:{ .lg .middle } **API Reference**

    ---

    Module-level reference generated from source docstrings.

    [:octicons-arrow-right-24: API Reference](api/index.md)

</div>
