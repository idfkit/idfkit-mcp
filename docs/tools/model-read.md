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

## `get_model_summary`

Returns:

- version
- file path
- object totals
- zone count
- grouped type counts

Use this as your first inspection call.

## `list_objects`

Returns brief serialized objects for one `object_type`.

Parameters:

- `object_type` (required)
- `limit` (default `50`)

## `get_object`

Fetches a specific object by type and name.

## `search_objects`

Case-insensitive substring search across names and string fields.

Optional `object_type` filter narrows results.

## `get_references`

Returns both:

- objects that reference the target name
- names referenced by the target object

Use this before renaming or removing high-connectivity objects.
