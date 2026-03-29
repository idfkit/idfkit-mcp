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

If `file_path` is omitted, re-saves to the original loaded path (always
allowed).  When an explicit `file_path` is given, the path must resolve
within an allowed output directory and will not overwrite an existing
file unless `overwrite=True` is set.

By default the only allowed output directory is CWD.  Set
`IDFKIT_MCP_OUTPUT_DIRS` (colon-separated paths, semicolon on Windows)
to allow additional directories such as mounted volumes.

## `clear_session`

Clears the persisted session file and resets all in-memory state (model, schema, simulation result, weather file).

Use this to start fresh when restored state is stale or unwanted. Does not delete any model or simulation files on disk.
