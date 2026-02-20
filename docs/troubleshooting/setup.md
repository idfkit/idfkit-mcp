# Setup & Configuration

## Server Does Not Start

### Symptom

Client reports command not found for `idfkit-mcp`.

### Fix

- Install package in the runtime environment.
- Or switch to `uvx --from idfkit-mcp idfkit-mcp`.

## MCP Client Cannot Connect

### Checks

1. Confirm JSON config is valid (no comments).
2. Confirm command runs in terminal:
   ```bash
   uvx --from idfkit-mcp idfkit-mcp
   ```
3. Restart client after config changes.

## `EnergyPlus not found`

### Cause

Simulation tool cannot resolve EnergyPlus installation.

### Fix

1. Install EnergyPlus.
2. Set `ENERGYPLUS_DIR`.
3. Verify `energyplus` is on `PATH`.

## `No model loaded`

### Cause

Read/write/validation/simulation tool called before loading or creating a model.

### Fix

Call one of:

- `load_model(file_path=...)`
- `new_model()`

## Schema Version Errors

### Symptom

`Version must be in 'X.Y.Z' format` or schema not found.

### Fix

- Use strict semantic format, e.g. `24.1.0`.
- Use a supported version provided by installed `idfkit`.
