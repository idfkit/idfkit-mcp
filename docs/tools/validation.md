# Validation Tools

Validation is the core reliability gate for agentic model editing.

## `validate_model`

Runs schema validation with optional filters.

Parameters:

- `object_types`: validate only selected types
- `check_references`: include reference integrity checks (default `true`)

Response highlights:

- `is_valid`
- counts by severity
- structured error and warning entries

Use the `idfkit://docs/{object_type}` resource to look up documentation for object types that appear in validation errors.

## `check_model_integrity`

Runs domain-level pre-simulation QA that catches issues schema validation does not.

Checks include:

- zones with no `BuildingSurface:Detailed` surfaces
- missing required control objects such as `Version`, `Building`, `Timestep`, `RunPeriod`, and `SimulationControl`
- orphan schedules that are defined but never referenced
- non-reciprocal surface boundary-condition pairs
- fenestration surfaces with missing host surfaces
- `ZoneHVAC:EquipmentConnections` rows that reference missing zones

## Recommended Gate

Run after any mutation batch:

```
validate_model(check_references=true)
check_model_integrity()
```

Only proceed to simulation when both checks are clean.
