# Installation

`idfkit-mcp` is distributed on PyPI and runs as a stdio MCP server.

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
