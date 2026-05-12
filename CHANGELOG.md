# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.3] - 2026-05-11

### Added

- `remove_objects` tool for replace-all collection editing.

### Changed

- Simulation start log message now reports whether `readvars` is enabled.

## [0.9.2] - 2026-05-06

### Added

- `readvars` option on `run_simulation` to control post-processing of variable output.

## [0.9.1] - 2026-05-06

### Changed

- Bumped idfkit to 0.12.1 (via 0.11.0), pulling in upstream fixes and removing now-redundant type casts.

## [0.9.0] - 2026-04-27

### Added

- Object descriptions now include extensible-group field documentation and richer examples.

### Changed

- Bumped idfkit to 0.10.3; deprecation warnings from idfkit are now surfaced on tool responses so callers can react before behavior changes.
- Refactored extensible-field access to use the idfkit extensible API directly.

### Fixed

- Peak-load facility totals now account for zone multipliers, matching EnergyPlus aggregate rows.
- Session resolution uses stable identity instead of the rotating `Mcp-Session-Id`, so reconnects no longer lose state.

## [0.8.1] - 2026-04-22

### Fixed

- Auto-registered prefab renderer resources now have a `domain` set, preventing collisions between widget resources.

## [0.8.0] - 2026-04-22

### Added

- `include_all_fields` option on `list_objects` to return every field value rather than just headline columns.
- `run_simulation` responses now include `_meta.billing` for downstream cost accounting.
- Widget resources are tagged with a unique `AppConfig.domain` so multiple MCP Apps coexist cleanly.

## [0.7.0] - 2026-04-16

### Added

- `migrate_model` tool for forward-migrating IDF models via the IDFVersionUpdater transition binaries, plus a `migration/report` resource exposing per-step output and structural diffs.
- `load_model` accepts uploads from the MCP `FileUpload` provider.
- HTTP health-check endpoint for container orchestrators.

### Changed

- Bumped idfkit to 0.8.0.

### Fixed

- Embedded HTML widgets now enforce a minimum viewport height, preventing zero-sized iframes in some MCP clients.

## [0.6.0] - 2026-04-07

### Added

- `check_model_integrity` tool for domain-level QA (orphan objects, missing controls, boundary mismatches) beyond schema validation.
- `get_zone_properties` tool returning derived zone geometry and load metrics.
- `query_simulation_table` and `list_simulation_reports` tools for SQL-style access to EnergyPlus simulation results.
- `get_change_log` tool exposing the in-memory edit history of the loaded model.
- Simulation QA diagnostics in `get_results_summary` (unmet hours, end-use breakdowns, classified warnings, actionable flags).
- Peak load QA/QC analysis and simulation pre-flight checks.
- Interactive 3D geometry viewer (MCP Apps).
- Interactive schedule heatmap viewer (MCP Apps).
- Interactive simulation report viewer (MCP Apps).

### Changed

- Bumped idfkit minimum to 0.6.4.
- Polished server instructions and `validate_model` docstring to better steer agent workflows.

### Fixed

- Resource reads no longer drop session context over streamable HTTP transport.
- SQL queries open a fresh handle per call, fixing thread-affinity errors when the same session is hit concurrently.
- Resource templates no longer default to `text/plain`; the correct MIME type is now served.

### Security

- Hardened MCP tools against adversarial input shapes (oversized payloads, malformed types).

## [0.5.1] - 2026-03-27

### Changed

- Version bump only; no functional changes since 0.5.0.

## [0.5.0] - 2026-03-27

### Changed

- **Breaking:** Migrated read-only tools to MCP resources and slimmed the tool surface; callers that used the old `get_*`/`list_*` tools must switch to `idfkit://...` resource reads.
- Optimized docs search using a pre-computed index; large queries no longer block other concurrent session calls.

## [0.4.0] - 2026-03-26

### Added

- MCP resources for model summary, schema, objects, and simulation results.

### Changed

- **Breaking:** Migrated to FastMCP v3, which introduces middleware-based request handling and a new server lifecycle. Custom integrations that subclassed the old server may need updates.
- Tool parameters now use `Annotated[..., Field()]` for richer schemas, and default response limits were reduced to prevent oversized payloads.
- Response sizes are capped to prevent client OOM on large IDF models.

### Fixed

- `ctx: Context` parameters no longer leak into tool JSON schemas exposed to clients.
- MCP output discovery and object serialization for nested response models.

## [0.3.0] - 2026-03-26

### Added

- Comprehensive per-tool logging with configurable log levels for production debugging.

## [0.2.0] - 2026-03-26

### Added

- Per-session state isolation, so concurrent clients no longer share a single in-memory model.
- Singleton-object support via a `resolve_object` helper, simplifying access to objects like `Building` and `SimulationControl`.

## [0.1.1] - 2026-03-26

### Changed

- Bumped idfkit minimum to 0.6.1 to pick up an extensible-field bug fix.

## [0.1.0] - 2026-03-25

Initial public release.

### Added

- MCP server exposing idfkit to AI tools (Claude, Cursor, and 9 other client platforms documented in the README), with 25 tools spanning model authoring, simulation, weather lookup, and documentation search.
- Docker image and CLI entry point for running the server in different transports.
- Pydantic response models and structured output across all tools.
- Tool annotations, `Literal` parameter types, and OpenAI SDK compatibility.
- OpenStudio `.osm` → `.idf` conversion tool.
- Country filter and timeseries tools for weather and simulation results.
- Documentation tools with `doc_url` fields linking back to EnergyPlus docs.
- Session persistence across server restarts.
- PyPI trusted publishing (OIDC) for releases.

[unreleased]: https://github.com/idfkit/idfkit-mcp/compare/v0.9.3...HEAD
[0.9.3]: https://github.com/idfkit/idfkit-mcp/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/idfkit/idfkit-mcp/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/idfkit/idfkit-mcp/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/idfkit/idfkit-mcp/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/idfkit/idfkit-mcp/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/idfkit/idfkit-mcp/compare/0.1.1...v0.2.0
[0.1.1]: https://github.com/idfkit/idfkit-mcp/compare/v0.1.0...0.1.1
[0.1.0]: https://github.com/idfkit/idfkit-mcp/releases/tag/v0.1.0
