# Installation

`idfkit-mcp` is distributed on PyPI and supports `stdio` and Streamable HTTP transports.

## Install the Package

=== "pip"

    ```bash
    pip install idfkit-mcp
    ```

=== "uv"

    ```bash
    uv add idfkit-mcp
    ```

## Runtime Requirements

- Python `3.10+`
- EnergyPlus installed and discoverable (required for simulation tools)
- Network access for weather station downloads (when using weather tools)

## Docker Images

This repo provides two Docker build targets:

- `runtime`: Small HTTP server image without EnergyPlus (`run_simulation` unavailable)
- `sim`: Includes EnergyPlus for full simulation support

### Build Base Image

```bash
docker build --target runtime -t idfkit-mcp:latest .
```

### Build Simulation Image

```bash
docker build \
  --target sim \
  --build-arg ENERGYPLUS_TARBALL_URL=<energyplus-linux-tarball-url> \
  -t idfkit-mcp:sim .
```

Optional integrity verification:

```bash
docker build \
  --target sim \
  --build-arg ENERGYPLUS_TARBALL_URL=<energyplus-linux-tarball-url> \
  --build-arg ENERGYPLUS_TARBALL_SHA256=<sha256> \
  -t idfkit-mcp:sim .
```

Architecture note:

- The tarball architecture must match the image architecture.
- On Apple Silicon, most official EnergyPlus Linux tarballs are `x86_64`; build with `--platform linux/amd64` when using those assets or use the `arm64` tarball if available.

### Build with Make Targets

```bash
make docker-build
make docker-build-sim ENERGYPLUS_TARBALL_URL=<energyplus-linux-tarball-url>
make docker-build-sim DOCKER_PLATFORM=linux/amd64 ENERGYPLUS_TARBALL_URL=<energyplus-linux-x86_64-tarball-url>
```

## Launch the Server

=== "Installed script"

    ```bash
    idfkit-mcp
    ```

=== "Module"

    ```bash
    python -m idfkit_mcp.server
    ```

=== "Without local install"

    ```bash
    uvx --from idfkit-mcp idfkit-mcp
    ```

## Transport Selection

`idfkit-mcp` can run either local stdio or network HTTP transport from the same codebase.

### stdio (default)

```bash
idfkit-mcp --transport stdio
```

### Streamable HTTP

```bash
idfkit-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

`--transport http` is also accepted as a shorter alias.

### Environment Variable Configuration

```bash
IDFKIT_MCP_TRANSPORT=streamable-http IDFKIT_MCP_HOST=0.0.0.0 IDFKIT_MCP_PORT=8000 idfkit-mcp
```

## Storage Directories

Hosted deployments (HTTP transport, multi-replica, shared volumes) can redirect
file storage away from the ephemeral container filesystem via environment
variables.

### `IDFKIT_MCP_UPLOAD_DIR`

Where files dropped into the `file_manager` UI are stored. When unset, uploads
live in-memory on the Python process and are lost when the container restarts —
fine for `stdio` and single-container deployments. When set, uploads are written
to `<IDFKIT_MCP_UPLOAD_DIR>/<session_id>/<filename>` with a sidecar
`<filename>.meta.json`. Point this at a shared volume (e.g. EFS) so concurrent
replicas can all resolve `load_model(upload_name=...)` calls.

```bash
IDFKIT_MCP_UPLOAD_DIR=/mnt/idfkit-uploads idfkit-mcp --transport http
```

Cleanup: `clear_session()` removes the caller's scope directory. Abandoned
sessions are not swept automatically — run a periodic cleanup (e.g. delete
scopes older than 24 h) in production.

### `IDFKIT_MCP_SIMULATION_DIR`

Default parent directory for EnergyPlus run output. When unset, each
`run_simulation` call creates a fresh temp directory. When set, each run writes
to `<IDFKIT_MCP_SIMULATION_DIR>/<session_id>-<utc-timestamp>/`. An explicit
`output_directory` argument on the tool call always wins.

```bash
IDFKIT_MCP_SIMULATION_DIR=/mnt/idfkit-simulations idfkit-mcp --transport http
```

### `IDFKIT_MCP_OUTPUT_DIRS`

Whitelist of directories that `save_model` (and any other tool that writes
user-named output paths) may resolve into. Prevents a misbehaving agent from
writing outside a sanctioned area.

- Colon-separated on POSIX, semicolon-separated on Windows.
- Defaults to the current working directory when unset.

```bash
IDFKIT_MCP_OUTPUT_DIRS=/workspace:/mnt/outputs idfkit-mcp
```

Paths that resolve outside every listed root are rejected with a `ToolError`,
including attempts via `..` traversal or symlinks.

## Log Verbosity

Control log output with the `IDFKIT_MCP_LOG_LEVEL` environment variable.
The default level is `INFO`.

```bash
IDFKIT_MCP_LOG_LEVEL=DEBUG idfkit-mcp
```

Available levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`.

At `DEBUG` level the server emits per-tool CALL/OK traces, idfkit core parsing
details (schema loading, IDF/epJSON parsing, validation internals), and
query/search parameters for every tool invocation.

At `INFO` (default) the server logs significant operations — model loads, saves,
simulation start/completion, object mutations, and weather downloads — without
the high-frequency per-call noise.

## EnergyPlus Discovery

Simulation tools rely on `idfkit`'s EnergyPlus discovery chain:

1. Explicit path passed by calling code
2. `ENERGYPLUS_DIR` environment variable
3. `energyplus` executable on `PATH`
4. Standard install locations by OS

If simulation fails with an EnergyPlus discovery error, see [Setup & Configuration](../troubleshooting/setup.md).

## Verify Installation Quickly

Use an MCP client and call:

1. `list_object_types()`
2. `new_model()`
3. Read the `idfkit://model/summary` resource

If all three succeed, your server is healthy.

## Next Steps

- [MCP Client Setup](client-setup.md)
- [First Session](first-session.md)
