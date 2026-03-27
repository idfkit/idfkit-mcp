# Documentation Tools

Documentation tools provide URL lookup, full-text search, and section retrieval for the EnergyPlus documentation hosted on [docs.idfkit.com](https://docs.idfkit.com).

## `lookup_documentation`

Get documentation URLs for an EnergyPlus object type.

Returns links to:

- I/O Reference page (with anchor to the specific object)
- Engineering Reference landing page
- Search page

Parameters:

- `object_type` (required): e.g., `"Zone"`, `"Material"`
- `version`: EnergyPlus version as `"X.Y.Z"` (default: latest or loaded model version)

## `search_docs`

Full-text search across the EnergyPlus documentation index (~20,000 sections).

Results include HTML-stripped text truncated to 250 characters. Use `get_doc_section` to read full content.

Parameters:

- `query` (required): search terms (e.g., `"zone heat balance"`)
- `version`: EnergyPlus version as `"X.Y"` (default: latest)
- `tags`: filter by documentation set
- `limit`: max results (default: 5)

Available tags:

- `Compliance`
- `Engineering Reference`
- `External Interfaces`
- `Getting Started`
- `Input Output Reference`
- `Module Developer`
- `Output Details`
- `Plant Application Guide`

## `get_doc_section`

Retrieve the full content of a specific documentation section by its location key.

Parameters:

- `location` (required): the location from a `search_docs` result
- `version`: EnergyPlus version as `"X.Y"` (default: latest)
- `max_length`: maximum characters to return (default: 8000)

Returns the text with HTML stripped, truncated to `max_length` characters.

## Typical Flows

### Find docs for an object type

```
lookup_documentation(object_type="Zone")
```

### Search and read documentation

1. `search_docs(query="zone heat balance", tags="Engineering Reference")`
2. Pick a result by its `location`
3. `get_doc_section(location="engineering-reference/.../#section")`

### Browse a specific documentation set

```
search_docs(query="infiltration", tags="Input Output Reference", limit=10)
```

## First-Use Download

On first use, `search_docs` and `get_doc_section` download the documentation search index from docs.idfkit.com (~2 MB) and cache it locally. The cache is refreshed automatically after 7 days.

Sources are checked in order:

1. `IDFKIT_DOCS_DIR` environment variable (path to a local `idfkit-docs/dist/` directory)
2. Local cache (`~/.cache/idfkit/docs/` on Linux, `~/Library/Caches/idfkit/docs/` on macOS)
3. Download from `https://docs.idfkit.com`

Set `IDFKIT_DOCS_DIR` for offline use or to point at a local docs build.
