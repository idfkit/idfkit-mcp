# idfkit-mcp

[![Release](https://img.shields.io/github/v/release/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/releases)
[![Build status](https://img.shields.io/github/actions/workflow/status/idfkit/idfkit-mcp/main.yml?branch=main)](https://github.com/idfkit/idfkit-mcp/actions/workflows/main.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/idfkit/idfkit-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/idfkit/idfkit-mcp)
[![License](https://img.shields.io/github/license/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/blob/main/LICENSE)

An [MCP](https://modelcontextprotocol.io/) server that lets AI assistants work directly with [EnergyPlus](https://energyplus.net/) building energy models. Connect it to Claude, ChatGPT, Cursor, Codex, or any MCP-compatible client and use natural language to:

- **Build models from scratch** — describe a building and let the agent create zones, surfaces, constructions, schedules, and HVAC systems
- **Edit existing models** — load an IDF or epJSON file, rename objects, swap materials, adjust setpoints, and validate as you go
- **Run simulations** — pick a weather file, launch EnergyPlus, and query or export the results without leaving the conversation
- **Explore the schema** — ask what fields a `ZoneHVAC:IdealLoadsAirSystem` accepts, what values are valid, and get links to the official EnergyPlus documentation
- **Search the docs** — full-text search across the EnergyPlus I/O Reference, Engineering Reference, and other documentation sets hosted on [docs.idfkit.com](https://docs.idfkit.com)

Built on [idfkit](https://github.com/idfkit/idfkit), it supports **EnergyPlus 8.9 through 26.1** (17 versions with bundled schemas). Schema exploration, model editing, and validation work out of the box with no external dependencies. Running simulations requires a local [EnergyPlus](https://energyplus.net/downloads) install — the server discovers it automatically via `PATH`, the `ENERGYPLUS_DIR` env var, or standard OS install locations. A Docker image with EnergyPlus bundled is also available.

**[Documentation](https://mcp.idfkit.com/docs/)** | **[GitHub](https://github.com/idfkit/idfkit-mcp/)**

## Tools

The server exposes **32 tools** across seven categories:

| Category | Tools | What they do |
| --- | --- | --- |
| **Schema** | 4 | Explore object types, fields, constraints, and valid references |
| **Model Read** | 7 | Load IDF/epJSON/OSM files, inspect objects, search, and trace references |
| **Model Write** | 9 | Create models, add/update/remove/rename/duplicate objects, save, and manage sessions |
| **Validation** | 2 | Schema validation and dangling-reference detection |
| **Simulation** | 5 | Run EnergyPlus, summarize results, query output variables, and export time series |
| **Weather** | 2 | Search weather stations worldwide and download EPW/DDY files |
| **Documentation** | 3 | Look up, search, and read EnergyPlus documentation from [docs.idfkit.com](https://docs.idfkit.com) |

All tools return structured Pydantic models. Schema, validation, and search results include direct `doc_url` links to the relevant EnergyPlus documentation.

Session state (loaded model, simulation results, weather file) is persisted to disk automatically, so clients that restart the server between turns (e.g. Codex) can resume where they left off.

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
make docker-run    # Run Docker container
```

## Releasing

1. Bump the version: `uv version --bump <major|minor|patch>`
2. Commit and push
3. Create a [new release](https://github.com/idfkit/idfkit-mcp/releases/new) on GitHub with a tag matching the version (e.g., `1.0.0`)

The GitHub Action will automatically publish to PyPI.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
