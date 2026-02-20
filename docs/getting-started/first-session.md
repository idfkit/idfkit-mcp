# First Session

This walkthrough demonstrates a complete first run in any MCP client.

## Goal

Create a model, add zones, validate, save, reload, and inspect.

## Step-by-Step Calls

### 1. Create a New Model

```json
{
  "tool": "new_model",
  "arguments": {
    "version": "24.1.0"
  }
}
```

### 2. Inspect Schema Before Writing

```json
{
  "tool": "describe_object_type",
  "arguments": {
    "object_type": "Zone"
  }
}
```

### 3. Add Multiple Objects Efficiently

```json
{
  "tool": "batch_add_objects",
  "arguments": {
    "objects": [
      {"object_type": "Zone", "name": "Office"},
      {"object_type": "Zone", "name": "Corridor"},
      {"object_type": "Zone", "name": "Storage"}
    ]
  }
}
```

### 4. Validate

```json
{
  "tool": "validate_model",
  "arguments": {
    "check_references": true
  }
}
```

### 5. Save

```json
{
  "tool": "save_model",
  "arguments": {
    "file_path": "./example.idf",
    "output_format": "idf"
  }
}
```

### 6. Reload and Verify

```json
{
  "tool": "load_model",
  "arguments": {
    "file_path": "./example.idf"
  }
}
```

```json
{
  "tool": "get_model_summary",
  "arguments": {}
}
```

## Expected Outcome

- `zone_count` is `3`
- `total_objects` includes your new zones
- validation returns `is_valid: true`

## Next Step: Add Simulation

1. `download_weather_file(query="Chicago")`
2. `run_simulation(annual=true)`
3. `get_results_summary()`
