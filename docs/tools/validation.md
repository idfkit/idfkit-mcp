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

## Recommended Gate

Run after any mutation batch:

```
validate_model(check_references=true)
```

Only proceed to simulation when validation is clean.
