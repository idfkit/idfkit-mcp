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
- HVAC node connections, the `hvac_topology` group (see below)

### The `hvac_topology` group

Node names are strings, not references, so schema validation passes a mistyped node. This group runs
idfkit's static connection checks and reports each finding as an issue with `category` set to
`hvac_topology`, the first object involved in `object_type` and `object_name`, and the check code at the
start of the message:

| Code | Severity | Meaning |
|---|---|---|
| `T010` | error | A branch lists a node its component does not have |
| `T011` | error | Consecutive branch components do not connect |
| `T001` | warning | A component inlet nothing supplies, neither a loop inlet nor outdoor air |
| `T002` | warning | A zone inlet nothing supplies |
| `T003` | warning | A zone exhaust nothing draws from |
| `T004` | warning | A node only setpoint managers, sensors, controllers or actuators name |
| `T030` | warning | A branch outlet nothing takes |
| `T012` | warning | A branch a loop side's splitter or mixer names that its BranchList omits, or a listed branch no splitter feeds |
| `T013` | warning | A heating or cooling coil on a PlantLoop's supply side, or a boiler on its demand side |
| `T090` | info | Object types the view has no rule for |
| `T091` | info | Unexpanded `HVACTemplate` systems, which the checks cannot see |

The first 50 findings are listed one by one. The rest are grouped by code, one issue per code with a
count, and `trace_hvac` shows the findings that touch one node or component. A finding that relies on a
rule written from a field's name, rather than one EnergyPlus reported, is never an error. A clean group
does not mean the model simulates.

## Recommended Gate

Run after any mutation batch:

```
validate_model(check_references=true)
check_model_integrity()
```

Only proceed to simulation when both checks are clean.
