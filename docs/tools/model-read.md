# Model Read Tools

Read tools expose current model content and relationships.

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

## MCP Resources for Model Inspection

The following read-only data is available via MCP resources instead of tool calls:

| Resource URI | Purpose |
|---|---|
| `idfkit://model/summary` | Model version, zones, object counts (replaces `get_model_summary`) |
| `idfkit://model/objects/{object_type}/{name}` | All field values for a specific object (replaces `get_object`) |
| `idfkit://model/references/{name}` | Inbound and outbound references (replaces `get_references`) |
