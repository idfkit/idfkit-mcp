# Model Read Tools

Read tools expose current model content, typed zone summaries, session history, and relationships.

## `load_model`

Loads IDF or epJSON into active server state.

Notes:

- File type inferred from extension.
- Optional `version` override (`X.Y.Z`) is supported.
- Loading resets previous simulation result state.
- Persists session state to disk for automatic recovery across server restarts.

## `convert_osm_to_idf`

Converts an OpenStudio `.osm` model to `.idf` using OpenStudio SDK and loads the
resulting IDF into active server state.

Parameters:

- `osm_path` (required): source `.osm` file path
- `output_path` (required): output `.idf` file path
- `allow_newer_versions` (default `true`)
- `overwrite` (default `false`)

Behavior:

- Validates input/output extensions and file existence.
- Fails safely if OpenStudio SDK is unavailable.
- Writes IDF, then loads it with the same state semantics as `load_model`.
- Returns conversion metadata plus standard model summary fields.

## `list_objects`

Returns brief serialized objects for one `object_type`.

Parameters:

- `object_type` (required)
- `limit` (default `50`)

## `search_objects`

Case-insensitive substring search across names and string fields.

Optional `object_type` filter narrows results.

## `get_zone_properties`

Returns a typed summary of one zone, or all zones when `zone_name` is omitted.

Highlights:

- floor area, volume, and ceiling height derived from geometry when surfaces exist
- surface counts for walls, floors, roofs, ceilings, windows, doors, and other surfaces
- unique construction names referenced by zone surfaces
- schedule names referenced by objects tied to that zone
- HVAC connection names and thermostat controls associated with the zone

Parameters:

- `zone_name`: optional zone name; omit to summarize every zone in the model

## `get_change_log`

Returns recent mutation history for the current session.

Parameters:

- `limit`: maximum entries to return (default `20`, capped at `100`)

Behavior:

- records `add`, `update`, `remove`, `rename`, `duplicate`, `load`, and `new_model` operations in chronological order
- is session-local and in-memory only
- resets when `clear_session()` is called

## MCP Resources for Model Inspection

The following read-only data is available via MCP resources instead of tool calls:

| Resource URI | Purpose |
|---|---|
| `idfkit://model/summary` | Model version, zones, object counts (replaces `get_model_summary`) |
| `idfkit://model/objects/{object_type}/{name}` | All field values for a specific object (replaces `get_object`) |
| `idfkit://model/references/{name}` | Inbound and outbound references (replaces `get_references`) |
