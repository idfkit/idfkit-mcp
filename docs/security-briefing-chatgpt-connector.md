# Security Profile: idfkit-mcp ChatGPT Connector

**Prepared for:** Security team
**Date:** 2026-03-27

---

## Overview

idfkit-mcp is a server that allows engineers to create, edit, validate, and simulate building energy models through conversation with an AI assistant. We are evaluating it as a ChatGPT App/Connector.

---

## Data

| Question | Answer |
|----------|--------|
| Does it use employee data? | No |
| Does it need access to employee records? | No |
| Does it process PII? | No |
| Does it ingest project data? | Yes — building energy models (geometry, materials, HVAC systems, schedules) |
| Does it store data persistently? | No — session data is in-memory and ephemeral in the containerized deployment |
| Does it process credentials or secrets? | No |

### What data transits OpenAI?

When used as a ChatGPT Connector, the following passes through OpenAI's infrastructure:

- Building model content (geometry, construction materials, HVAC parameters)
- Simulation results (temperatures, energy consumption, equipment performance)
- User prompts and tool responses

No credentials, employee data, or authentication tokens are transmitted.

---

## Internet Access

| Question | Answer |
|----------|--------|
| Does it require internet access? | Partial |
| Can it function without internet? | Yes — 26 of 32 tools work fully offline |

Two features require outbound HTTPS:

| Feature | Destination | Purpose |
|---------|-------------|---------|
| Weather tools | `climate.onebuilding.org` | Download weather files on demand |
| Documentation tools | `docs.idfkit.com` | Download EnergyPlus reference search indexes |

No other outbound connections are made. All other data (schemas, validation rules, weather station index) is bundled with the application.

---

## Authentication and Authorization

| Question | Answer |
|----------|--------|
| Does the server authenticate callers? | No |
| Does it support role-based access control? | No |
| Does it have per-tool authorization? | No |

The server trusts any caller that can reach its endpoint.

---

## Capabilities

The server exposes 32 tools:

| Category | Count | Filesystem | Network | Subprocess |
|----------|-------|------------|---------|------------|
| Schema exploration | 4 | — | — | — |
| Model read | 4 | Read | — | — |
| Model write | 9 | Read/Write | — | — |
| Validation | 1 | — | — | — |
| Simulation | 4 | Read/Write | — | Yes |
| Weather | 2 | Write | Outbound HTTPS | — |
| Documentation | 2 | — | Outbound HTTPS | — |
| Geometry | 1 | — | — | — |

**Subprocess detail:** The `run_simulation` tool spawns the EnergyPlus binary. This is the only tool that executes an external process. It runs with the server process's privileges.

---

## Dependencies

| Package | Version | Purpose | Source |
|---------|---------|---------|--------|
| `idfkit` | >=0.6.2 | Core EnergyPlus library | First-party (zero third-party deps) |
| `fastmcp` | >=3.1.0 | MCP server framework | Open source |
| `mcp` | >=1.2.0 | MCP protocol SDK | Open source (Anthropic) |
| `openstudio` | ==3.11.0 | OSM-to-IDF conversion | Open source (NREL, C++ with Python bindings) |
| `pydantic` | >=2.0.0 | Data validation | Open source |

Dependency vulnerability scanning is not currently in the CI pipeline.

---

## Container Profile

| Property | Value |
|----------|-------|
| Base image | `python:3.12-slim` |
| Runtime user | Non-root (`appuser`, UID 10001) |
| Filesystem | Read-write |
| EnergyPlus binary | Optional; SHA256 verification available at build time |

---

## Discussion Topics

1. **Data classification** — Do building energy models contain proprietary information that should not transit OpenAI's infrastructure?
2. **Tool scope** — Should all 32 tools be exposed, or should high-privilege capabilities (simulation, file writes) be restricted?
3. **Internet egress** — Is outbound access to `climate.onebuilding.org` and `docs.idfkit.com` acceptable?
4. **Authentication** — Is network-level access control sufficient, or is an auth layer needed in front of the server?
5. **Logging and audit** — What level of tool invocation logging is required?
