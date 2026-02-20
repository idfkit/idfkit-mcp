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

### Environment Variable Configuration

```bash
IDFKIT_MCP_TRANSPORT=streamable-http IDFKIT_MCP_HOST=0.0.0.0 IDFKIT_MCP_PORT=8000 idfkit-mcp
```

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
3. `get_model_summary()`

If all three succeed, your server is healthy.

## Next Steps

- [MCP Client Setup](client-setup.md)
- [First Session](first-session.md)
