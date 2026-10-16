# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.11.0] - 2026-10-16

### Fixed

- `run_simulation` runs a design-day-only simulation (`design_day=True`, `annual=False`) without a weather file, as documented. It passed an empty string as the weather file, which idfkit 1.0.0 could not run; it now passes `None`, which idfkit 1.1.0 accepts for such a run. A request with `annual=True` and no weather file is refused by the tool with a message naming `weather_file`. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- `save_model` writes epJSON that EnergyPlus accepts. idfkit 1.0.0 wrote choice values and sizing keywords in spellings EnergyPlus's epJSON reader refuses, integer fields in repeating groups as `1.0`, and blank group fields as `""`; idfkit 1.1.0 corrects all four ([idfkit#226](https://github.com/idfkit/idfkit/pull/226)). ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- `view_geometry` now draws surfaces where EnergyPlus places them. It resolves vertices with `idfkit.get_scene`, which applies zone origins, zone rotations and the building north axis under `GlobalGeometryRules`. Previously, models in relative coordinates were drawn up to 40 m from their simulated position ([#78](https://github.com/idfkit/idfkit-mcp/issues/78), [#83](https://github.com/idfkit/idfkit-mcp/pull/83)). Each surface's `azimuth` is consequently measured from true north rather than from building north, and the payload's `northAxis` is informational: it is already applied to the vertices and azimuths and must not be applied again.
- `view_geometry` reports surfaces it cannot place, with the reason, and geometry types it does not read, with their counts, in both the viewer payload (`unresolved`, `unattempted`) and the text summary. Previously such surfaces were omitted without notice. ([#83](https://github.com/idfkit/idfkit-mcp/pull/83))
- `analyze_peak_loads` no longer reports a 0 W peak after a design-day-only simulation, and no longer flags such a model as having no cooling or heating loads. EnergyPlus fills `SensibleHeatGainSummary` only from weather-file run periods. When it holds no peak, `cooling` and `heating` now report `available: false`, `peak_w: null` and an `unavailable_reason`, and `flags` states the same. The design-day loads remain in `sizing_cooling` and `sizing_heating`. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- The server reports its own version in the MCP `initialize` response. Previously it reported the FastMCP version (`3.2.0`). ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- `list_objects` returns an empty list for a valid object type with no objects in the model. Previously it returned an error. A type the model's EnergyPlus version does not define is still an error. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- Errors raised by `idfkit` now reach the client in the documented categories and with readable text. Previously, an unknown object type arrived wrapped in quotes and with an escaped newline, because FastMCP's wrapping bypassed the server's error mapping. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- A duplicate-name error names `update_object` as the remedy. `new_model` already creates `Building`, `GlobalGeometryRules` and `SimulationControl`, so adding them again is the usual cause. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- `get_change_log` entries carry a summary of each change, for example `add_object: Zone name=Office`. Previously every summary was `null`. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- Expected tool errors are logged as one line, without a traceback. Unanticipated exceptions keep their traceback. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))

### Changed

- Requires idfkit 1.1.0, up from 1.0.0 ([#85](https://github.com/idfkit/idfkit-mcp/pull/85), [#86](https://github.com/idfkit/idfkit-mcp/pull/86)). In models read through `load_model`, numeric `Schedule:Compact` values are now numbers and blank fields inside repeating groups are absent; tool results reflect both. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))
- `docs/concepts/error-semantics.md` now describes the error shape the server emits, an MCP tool error with a text message, instead of a structured `{"error": ...}` object it never returned. ([#86](https://github.com/idfkit/idfkit-mcp/pull/86))

## [0.10.0] - 2026-10-14

### Added

- `idfkit-mcp --version` prints the server's version and the version of idfkit it runs, both read from the installed distributions.

### Changed

- **Breaking:** requires idfkit 1.0.0, up from 0.12.1 in 0.9.3. The pin is exact, so an environment that pins another idfkit version cannot install this release alongside it.
- `new_model` without a version now creates an EnergyPlus 26.2.0 model, which EnergyPlus 26.1.0 and earlier reject. Pass the version explicitly to target an older release. The documentation tools default to the 26.2 documentation for the same reason.

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

[unreleased]: https://github.com/idfkit/idfkit-mcp/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/idfkit/idfkit-mcp/compare/v0.9.3...v0.10.0
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
