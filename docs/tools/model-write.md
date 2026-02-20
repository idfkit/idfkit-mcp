# Model Write Tools

Write tools mutate the active model.

## `new_model`

Creates a new empty model, optionally pinned to an EnergyPlus version.

## `add_object`

Adds one object.

Recommended workflow:

1. `describe_object_type`
2. `add_object`
3. `validate_model`

## `batch_add_objects`

Adds many objects in one round-trip.

Why it matters:

- lower client/server latency
- easier atomic planning for agents
- per-item error reporting without aborting the whole batch

## `update_object`

Updates specific fields on an existing object.

Tip: only send changed fields to keep edits auditable.

## `remove_object`

By default, guarded against deleting referenced objects.

- without `force`: returns `referenced_by` details when blocked
- with `force=true`: removes anyway

## `rename_object`

Renames an object and cascades reference updates.

## `duplicate_object`

Clones an existing object under `new_name`.

## `save_model`

Writes current model to disk as:

- `idf` (default)
- `epjson`

If `file_path` is omitted, uses the original loaded path when available.
