<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/idfkit/idfkit-brand/identity-2026.5/marks/mark-on-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/idfkit/idfkit-brand/identity-2026.5/marks/mark-on-light.svg">
    <img alt="idfkit" width="72" src="https://raw.githubusercontent.com/idfkit/idfkit-brand/identity-2026.5/marks/tile.png">
  </picture>
</p>

# idfkit-mcp

An MCP server that lets an AI assistant author, validate and simulate EnergyPlus models with idfkit.

[idfkit](https://idfkit.com) · [Developers](https://developers.idfkit.com) · [EnergyPlus docs](https://docs.idfkit.com) · [Envelop](https://app.idfkit.com) · [MCP](https://mcp.idfkit.com) · [Shoebox](https://shoebox.idfkit.com) · [GitHub](https://github.com/idfkit)

[![Release](https://img.shields.io/github/v/release/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/releases) [![Build status](https://img.shields.io/github/actions/workflow/status/idfkit/idfkit-mcp/main.yml?branch=main)](https://github.com/idfkit/idfkit-mcp/actions/workflows/main.yml?query=branch%3Amain) [![License](https://img.shields.io/github/license/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/blob/main/LICENSE)

An [MCP](https://modelcontextprotocol.io/) server that lets AI assistants work directly with [EnergyPlus](https://energyplus.net/) building energy models. Connect it to Claude, ChatGPT, Cursor, Codex, or any MCP-compatible client and use natural language to:

- **Build models from scratch** — describe a building and let the agent create zones, surfaces, constructions, schedules, and HVAC systems
- **Edit existing models** — load an IDF or epJSON file, rename objects, swap materials, adjust setpoints, and validate as you go
- **Run simulations** — pick a weather file, launch EnergyPlus, and query or export the results without leaving the conversation
- **Explore the schema** — ask what fields a `ZoneHVAC:IdealLoadsAirSystem` accepts, what values are valid, and get links to the official EnergyPlus documentation
- **Search the docs** — full-text search across the EnergyPlus I/O Reference, Engineering Reference, and other documentation sets hosted on [docs.idfkit.com](https://docs.idfkit.com)

Built on [idfkit](https://github.com/idfkit/idfkit), it supports **EnergyPlus 8.9 through 26.2** (18 versions with bundled schemas). Schema exploration, model editing, and validation work out of the box with no external dependencies. Running simulations requires a local [EnergyPlus](https://energyplus.net/downloads) install — the server discovers it automatically via `PATH`, the `ENERGYPLUS_DIR` env var, or standard OS install locations. The repository's Dockerfile builds a container image locally, with or without EnergyPlus bundled (see [Commands](#commands)); no prebuilt image is published.

**[Documentation](https://mcp.idfkit.com/docs/)** | **[GitHub](https://github.com/idfkit/idfkit-mcp/)**

## Tools

The server exposes **42 tools** across twelve categories, plus **10 MCP resources** and **5 resource templates** for read-only data access:

| Category | Tools | What they do |
| --- | --- | --- |
| **Schema** | 4 | Explore object types, fields, constraints, and valid references |
| **Model Read** | 6 | Load IDF/epJSON/OSM files, inspect objects, search, and read change history |
| **Model Write** | 10 | Create models, add/update/remove/rename/duplicate objects, save, and manage sessions |
| **Validation** | 2 | Schema validation and pre-simulation integrity checks |
| **HVAC Topology** | 3 | Trace a node or component, summarise loops in flow order, and rename a node everywhere it is used |
| **Simulation** | 8 | Run EnergyPlus, query variables and tabular reports, export time series, analyze peak loads, and view reports |
| **Weather** | 2 | Search weather stations worldwide and download EPW/DDY files |
| **Geometry** | 1 | Interactive 3D building geometry viewer (MCP Apps) |
| **Schedules** | 1 | Interactive schedule heatmap viewer (MCP Apps) |
| **Migration** | 1 | Migrate IDF models forward across EnergyPlus versions |
| **Documentation** | 2 | Search and read EnergyPlus documentation from [docs.idfkit.com](https://docs.idfkit.com) |
| **Uploads** | 2 | `file_manager` (MCP Apps upload UI) and `list_files`, so clients without a shared filesystem can upload an IDF or epJSON file and load it with `load_model(upload_name=...)` |

Most tools return structured Pydantic models with an output schema. The exceptions are `add_object`, `update_object` and `duplicate_object`, which return plain dictionaries, and the MCP Apps tools `view_geometry`, `view_schedules` and `file_manager`, which return UI results. Schema, validation, and search results include direct `doc_url` links to the relevant EnergyPlus documentation.

With the stdio transport, session state (loaded model, simulation results, weather file) is persisted to disk automatically, so clients that restart the server between turns (e.g. Codex) can resume where they left off. HTTP sessions keyed only by the `Mcp-Session-Id` header are not persisted, because that identifier changes on reconnect; persistence applies over HTTP only to sessions bound to an authenticated principal or an OpenAI session identifier.

## Installation

```bash
pip install idfkit-mcp
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add idfkit-mcp
```

## Usage

Run as stdio MCP server (default):

```bash
idfkit-mcp
```

Run as Streamable HTTP MCP server:

```bash
idfkit-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Run with the legacy SSE transport:

```bash
idfkit-mcp --transport sse --host 127.0.0.1 --port 8000
```

`--transport` accepts `stdio`, `sse`, `http` and `streamable-http` (an alias of `http`). `--host` and `--port` apply to the HTTP and SSE transports only. Print the server version and the idfkit version it runs against:

```bash
idfkit-mcp --version
```

The server reads these environment variables:

| Variable | Default | Effect |
| --- | --- | --- |
| `IDFKIT_MCP_TRANSPORT` | `stdio` | Default for `--transport` |
| `IDFKIT_MCP_HOST` | `127.0.0.1` | Default for `--host` |
| `IDFKIT_MCP_PORT` | `8000` | Default for `--port` |
| `IDFKIT_MCP_LOG_LEVEL` | `INFO` | Log level for the server and idfkit |
| `IDFKIT_MCP_UPLOAD_DIR` | unset (in memory) | Directory for disk-backed uploads |

`IDFKIT_MCP_OUTPUT_DIRS` (allowed directories for files written by `save_model` and `export_timeseries`) and `IDFKIT_MCP_SIMULATION_DIR` (parent directory for simulation runs) are described in the [documentation](https://mcp.idfkit.com/docs/).

## Quick MCP Setup

Add `idfkit-mcp` to your MCP client. Example for Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "idfkit": {
      "command": "uvx",
      "args": ["--from", "idfkit-mcp", "idfkit-mcp"]
    }
  }
}
```

See [MCP Client Setup](https://mcp.idfkit.com/docs/getting-started/client-setup/) for all supported clients (Claude Desktop, Cursor, VS Code, Claude Code, Windsurf, ChatGPT, Codex, JetBrains, Cline, Continue, and Zed).

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and
[Zensical](https://zensical.io/) for documentation.

### Setup

```bash
# Clone the repository
git clone https://github.com/idfkit/idfkit-mcp.git
cd idfkit-mcp

# Install dependencies and pre-commit hooks
make install
```

### Commands

```bash
make install    # Install dependencies and pre-commit hooks
make check      # Run linting, formatting, and type checks
make test       # Run tests with coverage
make docs       # Serve documentation locally
make docs-test  # Test documentation build
make docker-build  # Build base Docker image (no EnergyPlus)
make docker-build-sim ENERGYPLUS_TARBALL_URL=<linux-tarball-url>  # Build simulation image
make docker-build-sim DOCKER_PLATFORM=linux/amd64 ENERGYPLUS_TARBALL_URL=<linux-x86_64-tarball-url>  # Apple Silicon + x86 tarball
make docker-run    # Run the base image idfkit-mcp:latest over HTTP, mapping host port 8000 to container port 8000
make docker-run-sim  # Run the simulation image idfkit-mcp:sim the same way
```

## Releasing

Create a [new release](https://github.com/idfkit/idfkit-mcp/releases/new) on GitHub with a `v`-prefixed tag (e.g., `v0.11.1`).

The `release-main` workflow (`.github/workflows/on-release-main.yml`) writes the tag into the `version` field of `pyproject.toml` before building, then publishes to PyPI.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
