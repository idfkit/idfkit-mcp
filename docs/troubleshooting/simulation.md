# Modeling & Simulation Troubleshooting

## Missing Weather File Error

### Symptom

`run_simulation` returns weather-related error.

### Fix

- Call `download_weather_file(query=...)` first, or
- pass explicit `weather_file` path.

## Validation Fails Repeatedly

### Strategy

1. Run `validate_model(object_types=[...])` to narrow scope.
2. Call `describe_object_type` for failing types.
3. Repair fields using `update_object`.
4. Re-run validation.

## Dangling References

### Symptom

`check_references` returns `dangling_count > 0`.

### Fix pattern

1. Inspect each entry's `source_type`, `field`, and `missing_target`.
2. Use `get_available_references` for that field.
3. Update to valid target names.

## Object Removal Is Blocked

### Symptom

`remove_object` returns "Object is referenced by other objects".

### Fix options

1. Preferred: rewire references first.
2. Last resort: `force=true`.

## No Output Variables Found

### Symptom

`list_output_variables` returns missing index error.

### Causes

- simulation failed early
- output metadata files were not produced

### Fix

- Inspect `get_results_summary` errors first.
- correct model issues and rerun simulation.
