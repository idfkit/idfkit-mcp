# idfkit-mcp

[![Release](https://img.shields.io/github/v/release/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/releases)
[![Build status](https://img.shields.io/github/actions/workflow/status/idfkit/idfkit-mcp/main.yml?branch=main)](https://github.com/idfkit/idfkit-mcp/actions/workflows/main.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/idfkit/idfkit-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/idfkit/idfkit-mcp)
[![License](https://img.shields.io/github/license/idfkit/idfkit-mcp)](https://github.com/idfkit/idfkit-mcp/blob/main/LICENSE)

An MCP server based on idfkit

**[Documentation](https://mcp.idfkit.com/docs/)** | **[GitHub](https://github.com/idfkit/idfkit-mcp/)**

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

> **Note:** Run `git init -b main` first if you're starting from a cookiecutter template.

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

### First-time setup for new projects

If you just created this project from the cookiecutter template:

1. Create a GitHub repository with the same name
2. Push your code:

   ```bash
   git init -b main
   git add .
   git commit -m "Initial commit"
   git remote add origin git@github.com:idfkit/idfkit-mcp.git
   git push -u origin main
   ```

3. Install dependencies: `make install`
4. Fix formatting and commit:

   ```bash
   git add .
   uv run pre-commit run -a
   git add .
   git commit -m "Apply formatting"
   git push
   ```

For detailed setup instructions, see the [cookiecutter-gi tutorial](https://samuelduchesne.github.io/cookiecutter-gi/tutorial/).


## Releasing

1. Bump the version: `uv version --bump <major|minor|patch>`
2. Commit and push
3. Create a [new release](https://github.com/idfkit/idfkit-mcp/releases/new) on GitHub with a tag matching the version (e.g., `1.0.0`)

The GitHub Action will automatically publish to PyPI. See the [publishing guide](https://samuelduchesne.github.io/cookiecutter-gi/features/publishing/) for initial setup.

> **First release?** After the workflow completes, enable GitHub Pages: go to
> `Settings > Pages` and select the `gh-pages` branch.


## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

*Built with [cookiecutter-gi](https://github.com/samuelduchesne/cookiecutter-gi)*
