# Schema Tools

Schema tools let agents reason about object structure before editing models.

## `list_object_types`

List available object types, optionally filtered by group and version.

Use cases:

- discover object families
- constrain planning space for autonomous agents

## `describe_object_type`

Returns detailed field metadata:

- required fields
- defaults
- enums
- min/max constraints
- reference lists

Use this before any `add_object` or `update_object` call.

## `search_schema`

Find types by name or schema memo text.

Useful when the agent only has conceptual intent, such as "infiltration" or "internal gains".

## `get_available_references`

Given an object type and reference field, returns valid names from current model state.

Typical usage:

1. `describe_object_type("BuildingSurface:Detailed")`
2. `get_available_references(object_type="BuildingSurface:Detailed", field_name="zone_name")`
3. choose value from `available_names`

## Schema-First Editing Pattern

```text
describe_object_type -> add/update -> validate_model
```
