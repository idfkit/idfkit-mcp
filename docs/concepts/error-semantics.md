# Error Semantics

Tools return structured dictionaries for both success and failure paths.

## Error Shape

Typical failure response:

```json
{
  "error": "...",
  "details": "..."
}
```

Some errors include targeted hints, for example EnergyPlus discovery failures include a `suggestion` field.

## Typed Error Mapping

The server normalizes common exceptions from `idfkit`:

- validation failures
- unknown object types
- duplicate object names
- missing schema/version
- simulation failures
- missing EnergyPlus installation

This allows clients and agents to build deterministic remediation branches.

## Safe Agent Handling Pattern

1. Check for `error` key on every tool response.
2. If present, halt dependent calls.
3. Apply the smallest argument change needed.
4. Retry that call.
5. Re-run validation gates after recovery edits.

## Why This Matters

Without explicit error branching, autonomous workflows tend to drift into invalid model states and compound failures.
