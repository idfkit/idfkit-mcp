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

## `check_references`

Performs explicit dangling-reference detection.

Response:

- `dangling_count`
- list of source object, field, and missing target

## Recommended Gate

Run both tools after any mutation batch:

1. `validate_model(check_references=true)`
2. `check_references()`

Only proceed to simulation when both are clean.
