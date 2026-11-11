# Research: Model Knowledge Graph for Agents

Phase 0 output of `/speckit-plan`. Each entry records a decision, the reason for it, and the alternatives
considered. The background reports in [`background/`](background/README.md) hold the underlying measurements; this
file decides. Entries marked **checked** were verified during planning against the code or the data, not taken
from the reports.

Planning input from the user: *"a pure Python stack as much as possible; no external dependencies except for the
PNNL standards library."*

---

## R-01 Stack and dependencies

**Decision.** Everything new is pure Python 3.10+ using the standard library only (`dataclasses`, `enum`, `re`,
`json`, `sqlite3`, `importlib`, `hashlib`, `subprocess`). The one new third-party dependency is PNNL's
`building-energy-standards-data`, as an optional extra of idfkit. idfkit-mcp gains no new direct dependency: it
reaches the PNNL data through idfkit's extra. Its existing runtime dependencies (FastMCP, `mcp`, Pydantic,
`openstudio`) are unchanged.

**Rationale.** idfkit's core has zero third-party dependencies, and that is a published property. Every new
capability fits in the standard library:
- Topology is graph traversal over in-memory objects.
- Result linking reads EnergyPlus's SQLite output, which idfkit already reads with `sqlite3`.
- Screening is table lookups and arithmetic.

The user's instruction is read as "no *new* external dependencies". Removing idfkit-mcp's existing FastMCP or
Pydantic would break the server and its constitution (Principle II requires Pydantic models).

**Alternatives considered.**
- `networkx` for graph algorithms. Rejected: traversal here is bounded BFS over at most about 10k nodes, which
  takes a few dozen lines.
- `rdflib` or `brickschema` for semantic output. Rejected: an ontology export is out of scope, and brickschema
  needs Python 3.11 or later.
- `pandas` for table handling. Rejected: the data is JSON lists of dicts.
- Importing the PNNL package's query API. Rejected in R-08.

## R-02 Where the code lands, and the parity ledger

**Decision.** All domain logic lands in **idfkit**, in three places:

| Capability | idfkit location | New capability unit? |
|---|---|---|
| HVAC topology, connection checks, node rename | new subpackage `idfkit.hvac`, plus `IDFDocument.rename_node` | **Yes** |
| Result linking, message catalogue, diagnosis | `idfkit.simulation.linking` and `idfkit.simulation.parsers.err_catalog` (inside the existing `idfkit.simulation` unit) | No |
| Surface-appropriate films | `idfkit.thermal.properties` (existing unit) | No |
| Standards lookup, object roles, envelope screening | new subpackage `idfkit.standards` | **Yes** |

idfkit-mcp adds tool modules that call these and hold no domain knowledge.

**Rationale.**
- Constitution Principle I forbids domain knowledge in idfkit-mcp.
- **checked:** idfkit's `scripts/check_parity_ledger.py` treats every public subpackage as a *capability unit*. A
  new unit fails `make check` unless the parity ledger (`idfkit-conformance/governance/parity.toml`) and the naming
  register carry a matching row at the governance tag pinned in idfkit's `pyproject.toml`. So `idfkit.hvac` and
  `idfkit.standards` each need a ledger row, recorded as Python-only for now (idfkit-js has neither), in a paired
  change to idfkit-conformance.
- Result linking deliberately extends the existing `idfkit.simulation` unit, so it needs no ledger change.

**Alternatives considered.**
- Topology inside `idfkit.references`. Rejected: node names are not object references, and mixing them would
  corrupt `get_referencing` and rename semantics (report 01, §3).
- A single new `idfkit.graph` unit for everything. Rejected: it would bundle a core-only capability with one that
  needs an optional dependency, and it would make the ledger row lie about what is available without the extra.

## R-03 Identifying node fields

**Decision.** A new codegen script (`idfkit.codegen.generate_node_fields`) writes a frozen table
`idfkit/hvac/_node_fields.py`, mapping `(object type, field)` to "is a fluid node field". It is built from the
26.2 schema's `"data_type": "node"` tags, unioned with the field-name rule `node(_or_nodelist)?_names?$` applied to
every bundled schema. It excludes non-fluid "nodes": electric circuit, AirflowNetwork and RoomAir nodes. A `make
check` target regenerates the table and diffs it, as the existing stub and doc-location generators do.

**Rationale.** **checked:** V26-2-0 has 819 `data_type: node` tags and V24-1-0 has none. Field names are stable
across versions (97–98% overlap), so the 26.2 tags carry back to older schemas by field name. The rule catches
fields the tags miss, and the reverse is also true (report 01, §2a).

**Alternatives considered.**
- Computing the table at runtime from the loaded schema. Rejected: older schemas carry no tags, and a generated
  table is reviewable in a diff.
- Parsing the IDD's `\type node`. Rejected: idfkit does not ship IDDs.

## R-04 Connection roles

**Decision.**
- **Roles.** A curated rule table `idfkit/hvac/_port_rules.py` mirrors EnergyPlus's own node-connection model:
  connection type (Inlet, Outlet, Internal, ZoneNode, Sensor, Actuator, OutsideAir, ReliefAir, ZoneInlet,
  ZoneReturn, ZoneExhaust, Setpoint), fluid stream number, and a parent flag.
- **Full coverage from the start (clarification, 2026-11-11).** Every node-bearing object type in the latest
  supported schema gets rules at first release. **Measured during clarification**, over the 26.2 schema and the 735
  EnergyPlus 24.1 example models:

  | Node-bearing object types in 26.2 | Count |
  |---|---|
  | Total | 257 |
  | Every node field pairs as inlet/outlet or is a control field (rules derivable from naming) | 169 |
  | Used in at least one example model (rules derivable from EnergyPlus's own output) | 247 |
  | Covered by one or the other | 254 |
  | Neither: hand-written | 3 (`Lights:Instance`, `SpaceHVAC:ZoneReturnMixer`, `ThermalStorage:HotWater:Stratified`) |

- **Generation.** A codegen script, `idfkit.codegen.generate_port_rules`, needs EnergyPlus only when it runs. It
  works in five steps:
  1. Run each example model for design days only, with `Output:Diagnostics` on so EnergyPlus writes
     `eplusout.bnd`.
  2. Parse the "Non-Parent Node Connection" and "Parent Node Connection" rows: object type, object name, node,
     connection type and fluid stream.
  3. Map each row back to a field by matching the node value in that object's input.
  4. Merge across files. A field whose role differs between files is emitted as a predicate candidate for review,
     never silently resolved. An object that uses the same node in two fields is an ambiguous match, which is also
     queued for review.
  5. Cross-check against the naming-derived roles of the 169 pairable types. Any disagreement fails generation
     until it is reviewed.

  The output, `_port_rules.py`, is committed, together with a reviewed overrides file holding the 3 hand-written
  types and the resolved predicates. A coverage test fails if any node-bearing type in the latest schema has no
  rule. Generation is repeated when a new EnergyPlus version is adopted.
- **Predicates.** Rules that depend on a value are expressed as small predicates, for example "condenser type is
  AirCooled" makes the condenser nodes OutsideAir.
- **Unknown types.** An object type with no rule and no clean pairing yields an `unclassified` finding at info
  severity, never an error (spec edge cases).

**Rationale.** The schema says *that* a field is a node, never *how* it connects. EnergyPlus decides that per
call site in C++. Mirroring its connection types lets idfkit's findings map one-to-one onto EnergyPlus's own node
connection errors. It also makes the branch-and-node report (`eplusout.bnd`) usable as an oracle later (FR-018).

**Alternatives considered.**
- A pure name heuristic. Rejected: report 01 measured a misclassification on dual-duct outdoor-air terminals.
- A hand-written table grown over several releases, the original plan with about 40 types first. Rejected after
  the measurement above showed 254 of 257 types are derivable. It is replaced by generation from EnergyPlus's own
  output.
- A developer API for registering custom rules. Rejected in clarification: full built-in coverage is more
  trustworthy, and it keeps the public API smaller.

## R-05 Topology model and node rename

**Decision.**
- `HVACTopology.from_document(doc)` derives node uses, flow edges, loop memberships and checks on demand.
- It is never stored in `ReferenceGraph`.
- Node identity is the upper-cased name. Responses keep the model's spelling.
- `node_or_nodelist` fields resolve to a `NodeList` first, as EnergyPlus does.
- `IDFDocument.rename_node(old, new)` updates every node field and every NodeList entry in one pass. It returns
  the fields changed and fires the existing change notifications for each one.

**Rationale.** The topology is a pure function of the model, so deriving it avoids keeping two indexes in sync.
**Measured:** the core node-graph build takes 5.2 ms on HospitalLowEnergy (6,876 objects, 2,869 nodes), against
228 ms to load the model ([background/04](background/04-performance-measurements.md), §1). A rename has no safe
path today: the agent docs tell agents to update both ends by hand. The internal representation is set by R-21.

**Alternatives considered.**
- Maintaining a live node index alongside `ReferenceGraph`. Rejected for phase 1: it adds a second
  mutation-tracking path, which a revision-keyed cache (R-06) makes unnecessary.

## R-06 Revision counter and staleness

**Decision.**
- **Counter.** `IDFDocument` gains a monotonically increasing integer `revision`. It is incremented by `add`,
  `removeidfobject`, field assignment (through the existing `notify_reference_change` and `notify_name_change`
  paths, plus a direct bump for non-reference fields) and `rename_node`.
- **Caching.** Derived views (topology, the results index) are cached in a new `IDFDocument` slot, `_derived`,
  as a dict of view name to `(revision, view)`. A view is reused while the revision is unchanged. **checked:**
  `IDFDocument.__slots__` has no `__weakref__`, so a `WeakKeyDictionary` keyed on the document is impossible.
  Keying on `id(doc)` would leak memory and could return another document's view after the id is reused. Holding
  the cache on the document ties its lifetime to the document, which matters under concurrent HTTP sessions.
- **Staleness within a session.** When idfkit-mcp runs a simulation it records the revision.
- **Staleness across restarts.** It also records a SHA-256 of the IDF text it wrote for EnergyPlus, persisted in
  the session file. Results are stale when the revision moved (same process) or, after a restart, when the hash
  of the current model's text differs (FR-026).

**Rationale.** The counter is cheap and exact within one process. The text hash survives restarts, where the
counter starts again from zero.

**Alternatives considered.**
- Hashing the model on every request. Rejected: it costs O(model) per call.
- Comparing file timestamps. Rejected: the in-memory model is the truth, not the file.

## R-07 Result sources for linking

**Decision.**
- **Source.** Link only from EnergyPlus's SQLite output, which idfkit-mcp already requests on every run
  (`Output:SQLite SimpleAndTabular`).
- **New readers on `SQLResult`:** `component_sizes()` (`ComponentSizes`), `errors()` (`Errors`, with severity
  and count), `zones()` (`Zones`, with multipliers) and `report_keys()` (`ReportDataDictionary`).
- **Existing reader** `get_tabular_data()` serves object rows of tabular reports.
- **Resolver.** An ordered list of pure functions `(raw key, context, doc) -> Resolution | None`:
  1. exact (type and name)
  2. typed by context
  3. zone-list composite (`"<ZONE> <OBJ>"`)
  4. space to zone
  5. `Mir-` mirrored shading
  6. aggregate stoplist (`Total`, `Total Facility`, …)
  7. ideal-loads suffix
  8. weak substring match

  Every link records the rule and a confidence: `exact`, `typed`, `convention` or `weak`.
- **Scope.** Linking applies only to runs the server started in the session (FR-019).

**Rationale.** **checked:** `simulation/parsers/sql.py` reads neither `ComponentSizes` nor `Errors` today. Report
03 measured 100% resolution for sizing rows, 97–99% for timeseries keys and 89% for object rows in tabular
reports, on public paired runs. The SQL `Errors` table carries severity and occurrence count in structured form,
so ERR text parsing is needed only for "first occurred" timestamps, which come from the continuation lines.

**Alternatives considered.**
- HTML tabular output. Rejected: it carries the same content and SQL is guaranteed on server runs.
- Making links first-class edges in `ReferenceGraph`. Rejected: results belong to one run, while the graph is live.

## R-08 Reading PNNL's standards data

**Decision.**
- **Locating the data.** idfkit finds the data directory with
  `importlib.util.find_spec("building_energy_standards_data")` and reads the JSON files under `database_files/`
  directly, lazily, one table at a time, caching each per process. It **never imports the package**.
- **Version.** It reads the data version from `importlib.metadata.version(...)` and puts it on every response.
- **The extra.** It is declared as `standards = ["building-energy-standards-data>=0.3.3,<0.4; python_version <
  '3.14'"]`.
- **Unavailable cases.** On Python 3.14, or without the extra, standards calls raise an actionable "unavailable"
  error naming the extra (Constitution Principle III).

**Rationale. checked during planning:**
- The package's `__init__.py` star-imports every submodule, and `client.py` opens a database and configures
  file logging at import. `find_spec` locates the data without running any of that: verified in a clean venv,
  where 139 files were found without importing the package.
- The wheel declares `Requires-Python >=3.10,<3.14`, while idfkit supports 3.10 to <4.0, so the marker is
  required.
- `envelope_requirements_90_1.json` has 6,315 rows, with templates `90-1975`, `90.1-2004`, `2007`, `2010`, `2013`,
  `2016`, `2019`, `2022` and `2025`. Values are in IP units (`Btu/h-ft2-F`, with 18 rows written `btu/h-ft2-F`).
- Climate zone sets are whole zones (`ClimateZone 3`) except for subtype rows (`ClimateZone 3A`, `3B`, `3C`).
- Surface types are the nine `intended_surface_type` values, and assembly classes are the
  `standards_construction_type` values (`Mass`, `SteelFramed`, `WoodFramed`, `Metal Building`, `IEAD`, `Attic and
  Other`, …).
- 6,015 rows carry an `annotation` citation such as "From 90.1-2019 Table 5.5-5". The 300 without one are
  `Adiabatic` building-category rows, which screening does not use.

**Correction to the spec, checked:** all 288 rows whose limits are heating-degree-day formulas belong to the
`90-1975` template. No 90.1 edition from 2004 to 2025 has one in this table. Report 02 had stated otherwise.
FR-033 and SC-006 were amended in this planning session to require the climate-zone subtype rule instead.

**Unit handling.** idfkit converts U from Btu/h·ft²·°F to W/m²·K using the factor 5.678263. It returns both
values, with the IP value taken verbatim from the row. Unit strings are compared case-insensitively.

**Alternatives considered.**
- The package's SQLite and query API. Rejected: it has import-time side effects, and an SQL layer is needed only
  for generic queries, which PNNL's own `besd-mcp` already offers.
- Vendoring the tables into idfkit. Rejected under FR-038, for licence posture and to avoid duplicated
  maintenance.

## R-09 Object roles needed by envelope screening

**Decision.** `idfkit.standards.roles` computes roles from physics and structure only (FR-036).

- **Surface class.** One of the nine PNNL surface types, from surface type, boundary condition and tilt:
  - roof when tilt is 60° or less, floor when 120° or more, wall otherwise
  - `GroundContact*` from a ground boundary condition
  - `Skylight` for fenestration on a roof
  - `GlassDoor` for a glass door
- **Conditioned status.** `conditioned` when the zone has a thermostat and HVAC equipment, `unconditioned` when
  it has neither, and `unknown` otherwise. Semiheated is never inferred; it must be asserted.
- **Assembly class.**
  - `Mass` when the construction's heat capacity per area reaches the 90.1 mass-wall threshold of 7 Btu/ft²·°F
    (143 kJ/m²·K), computed from layer density, specific heat and thickness.
  - `IEAD` for a roof whose insulation layer lies entirely above a structural deck, with no attic zone.
  - `Metal Building`, `SteelFramed`, `WoodFramed` and `Attic and Other` are **never inferred**, because no field
    of an EnergyPlus construction distinguishes them. They are `unknown` unless asserted.
- **Name-based suggestions.** For example, a construction called "Steel Frame Wall". These are returned only as
  `unconfirmed` and are never used in a verdict.

**Rationale.** Constitution Principle III forbids values inferred from name patterns. Physics-based mass
detection is the one framing class a model can show. Anything else is a judgement the modeller owns, which is
what the assertion path (FR-037) is for.

**Alternatives considered.**
- Inferring steel or wood framing from layer materials. Rejected: framing is usually modelled as an equivalent
  layer with no metal or wood material present.

## R-10 Surface films

**Decision.** `calculate_r_value` and `calculate_u_value` gain an optional `surface_class` argument: `wall`,
`roof` or `floor`, defaulting to `wall`, so existing results do not change. Interior still-air films are wall
0.12, roof (heat flow up) 0.11 and floor (heat flow down) 0.16 m²·K/W. The exterior film is 0.03 m²·K/W. Below
grade, where the exterior film is zero, it is handled by surface class. Envelope screening always passes the
class.

**Rationale.** **checked:** `thermal/properties.py` applies the wall interior film to every surface (report 02,
§1.1). The values are physical constants from the ASHRAE Handbook of Fundamentals and match the 90.1 Appendix A
assumptions. Screening also honours PNNL's `u_value_includes_*_film_coefficient` flags per row.

## R-11 Climate zone and standards context

**Decision.**
- **Source of the climate zone.** It comes from, in order:
  1. a user or agent assertion
  2. the weather station matching the session's weather file (by WMO, through the existing station index)
  3. unknown

  The source is reported. Station records labelled "could not be determined" count as unknown, since the index
  already flags them.
- **Standards context.** `{standard: "ASHRAE 90.1", edition, climate_zone, building_category}`, each with its
  source. It lives in idfkit-mcp session state and is persisted in the session file (R-15).
- **No defaults.** A screening with any required item missing fails with a message naming what to set (FR-032).

**Rationale.** **checked:** the station index already holds `ashrae_climate_zone`, and idfkit-mcp's
`WeatherStationModel` drops it.

## R-12 Bounded responses and token cost

**Decision.**
- Every new tool takes a `limit` (default 20 rows) and returns `total` and `omitted` counts.
- Loop summaries render each side as one compact string and collapse repeated parallel components (`5×
  AirTerminal:SingleDuct:VAV:Reheat`).
- Messages are deduplicated by kind, with counts.
- Each change that adds tools records its cost from `scripts/token_audit.py`. The sum of new tool descriptions is
  capped so the listing grows by no more than 15% (SC-010).

**Rationale.** Constitution Principle II. Report 01 measured a full connection dump of HospitalLowEnergy (2,607
nodes) at about 100k tokens, and BuildingGPT found that pasting a whole graph does not help.

## R-13 Evaluation harness

**Decision.**
- **Location.** It lives in idfkit-mcp under `eval/` and is never packaged.
- **Code.** Pure Python using the standard library, plus the FastMCP client idfkit-mcp already depends on.
- **Runner.** The agent is driven through a configurable **runner command**. The default is Claude Code in
  headless mode with an MCP config pointing at the server under test, and its streamed JSON output gives tool
  calls and tokens. So no LLM SDK becomes a dependency.
- **Conditions.** *Baseline* runs the last released idfkit-mcp (`uvx idfkit-mcp==<previous>`). *Treatment* runs
  the branch build. The comparison is therefore literally with and without the feature, with no feature flag in
  the product.
- **Running it.** A maintainer runs it on demand. It is not part of default CI: it needs EnergyPlus and model
  credentials, and it costs money.
- **Recorded per run.** The runner configuration, the model identifier and the git revisions.

**Rationale.**
- FR-042 needs with/without runs on the same agent configuration.
- A previous release is a clean baseline that cannot drift, and it keeps disable switches out of the server.
- Keeping the runner as an external command honours the dependency constraint and lets a maintainer swap agents.

**Alternatives considered.**
- An Anthropic or OpenAI SDK inside the harness. Rejected by the dependency constraint.
- A `--disable-tools` server flag. Rejected: it adds product surface used only for testing.

## R-14 Fault catalogue and reference models

**Decision.**
- **Catalogue.** 12 fault types, each an idfkit-based injector with a known fix and a verifier:
  - topology (6): outlet node typo, swapped inlet and outlet, branch missing from its branch list, setpoint
    manager on a node no flow component uses, terminal outlet not a zone inlet, water coil connected to the
    wrong plant loop side
  - results (4): undersized reheat coil, wrong heating setpoint schedule, uninsulated exterior wall, availability
    schedule off for a packaged unit
  - standards (2): roof insulation below the limit, window SHGC above the limit
- **Reference models.** At least 20 models are drawn from the 26.2 ExampleFiles, covering VAV with reheat,
  chilled and hot water plant, packaged units, zone lists and HVACTemplate. The list is pinned by file name.

**Rationale.** FR-040 and FR-041 need 10 or more fault types across all three layers and 20 or more models. The
topology faults reuse report 01's injection method, which caught a typo the current validation misses.

## R-15 Session persistence

**Decision.** The idfkit-mcp session file moves from `"version": 1` to `2` and adds:
- `standards_context`
- `asserted_roles`, a list of `{object_type, name, role, value, asserted_at}`
- `simulation_model_hash`

Version-1 files still load. Asserted roles are re-keyed on `rename_object`. Nothing is written into model files
(clarification 2). HTTP sessions keep persistence disabled, as today, so their assertions last only as long as
the connection, which is consistent with "session only".

**Rationale.** Constitution Principle V requires persisted session state with reported restore failures.
Clarification 2 rules out sidecar files.

## R-16 Diagnosis ranking

**Decision.** `idfkit.simulation.linking.diagnose(index, doc, symptom, target)` is rule-based. The message
catalogue lists, for each message kind and each symptom, the neighbour object types to inspect.

Candidates are scored by rule weight (from the catalogue) minus graph distance from the symptom object. Distance
is taken over the HVAC topology (upstream only) where available, and over the reference graph otherwise. Weak
links are never ranked first. Each candidate carries evidence, a reason and a verification step. No score is
shown without the reason behind it.

**Rationale.** FR-027 and spec "Out of Scope" (no machine-learned ranking). The ranking is domain knowledge, so
it lives in idfkit (Principle I).

## R-17 HVACTemplate models

**Decision.** Topology, checks and result linking do **not** expand templates (expansion needs EnergyPlus's
ExpandObjects). When template objects are present, responses carry `coverage.partial = true` and list the
template systems not covered. Their absent nodes are never reported as faults.

## R-18 Reference corpus for qualifying checks

**Decision.** An opt-in integration test (`pytest -m integration`) loads every 26.2 ExampleFile from
`$ENERGYPLUS_DIR/ExampleFiles` and asserts zero error-severity topology findings. A check moves from warning to
error only with that test green (FR-013, clarification 4). The files are not committed.

## R-19 Fixtures for result linking

**Decision.** A script in idfkit (`scripts/build_linking_fixtures.py`, which needs EnergyPlus 26.2) runs about 10
reference models. Each run includes `Output:SQLite SimpleAndTabular`, AllSummary and a small set of
`Output:Variable` with `*` keys. Each SQL is trimmed to the tables linking reads, then `VACUUM`ed.

The `(IDF, SQL, ERR)` triples are committed under `tests/fixtures/simulation/linked/`, with a total budget of
10 MB. Default CI tests read the fixtures and never need EnergyPlus (FR-044).

## R-20 Consumer register impact in idfkit-mcp

**Decision.** idfkit-mcp's dependency changes from `idfkit==X` to `idfkit[standards]==X`. The level is still
declared only in `project.dependencies`.

**Risk.** The `consumer-register` job may treat the extra as a new dependency form. If it does, the change needs a
paired register amendment in idfkit-conformance (Constitution Principle VI). This is recorded in the plan's
Complexity Tracking.

## R-21 Performance architecture

**Context.** The user stated that performance is critical. Spec FR-009 and SC-011 to SC-013 make it a requirement.
Every decision below rests on measurements of real models and outputs taken during planning
([background/04-performance-measurements.md](background/04-performance-measurements.md)). The budgets keep about
10× headroom over the prototype figures, because the shipped code adds rule tables and checks.

### Budgets

Measured on HospitalLowEnergy, the largest example model, on Python 3.12:

| Operation | Prototype measured | Budget (benchmark gate) |
|---|---|---|
| Node-graph build, connection roles, memberships and all checks | 5.2 ms (core build only) | ≤ 50 ms, and ≤ 25% of model load time (SC-011) |
| One topology query (trace, summary of one loop), server side, including serialization | ~1.5 µs traversal + ~1 ms framework | ≤ 5 ms per call, well under SC-011's 0.05 s |
| Results index build, once per run | 1.8–3.1 ms | ≤ 50 ms, whatever the timeseries volume (SC-012) |
| One results query | — | ≤ 10 ms |
| Standards: first call in a process (envelope table load and index) | 43 + 3.9 ms | ≤ 150 ms (SC-013 allows 0.5 s) |
| Standards: envelope screening of a loaded model | — | ≤ 20 ms |
| Default response size of any new tool | — | ≤ 8 KB (SC-013) |
| Additional resident memory per loaded model | 1.5 MB | ≤ 10 MB |

### Decisions

1. **Plan per type, once.** Per object type, the node fields (top-level and extensible), their connection rules and
   their predicates are compiled into a plan of tuples. The plan is cached per schema version, at module level, as
   idfkit's parsing cache already is. The build visits only collections whose type has a plan. *Measured:* about
   65% of objects in large models have no node fields. Skipping them is the main 4.6× gain, and plans cost
   0.3–0.6 ms to compute.
2. **Tuples inside, dataclasses at the boundary.** Internal records are plain tuples of integers and interned
   strings. The public dataclasses in [contracts/idfkit-api.md](contracts/idfkit-api.md) are built only for the
   bounded set of items a call returns. *Measured:* a frozen slotted dataclass costs 9.5× a tuple to construct.
3. **Integer IDs and adjacency lists.** Node names are interned to dense integers (`dict[str, int]` keyed by
   upper-cased name, plus a `list[str]` of display spellings). Objects are indexed to integers. Forward and reverse
   adjacency are `list[list[int]]`. Traversal is iterative breadth-first search with a hop limit and an integer
   visited set. Recursion is never used. *Measured:* 1.5 µs per 3-hop query.
4. **Rebuild on edit, no incremental maintenance.** A view is rebuilt when the document revision changes, and
   only when it is next asked for. *Measured:* the build costs about 2% of loading the model, so incremental
   upkeep would add a second mutation path for no measurable gain. This is revisited only if the slice 1
   benchmark exceeds the 50 ms budget.
5. **Cache on the document** (R-06). The `_derived` slot holds views keyed by name and stamped with the revision.
   It is freed with the document, with no global registries.
6. **Lazy sub-views.** The base build produces node uses, flow edges and findings. Loop chains, memberships per
   loop, and up- and downstream walks are computed on first request and memoised inside the view.
7. **Checks in one pass.** Connection checks run over the same integer structures in a single pass per check
   family, never one query per object.
8. **Results index without timeseries.**
   - The SQL file is opened read-only (`mode=ro`, `PRAGMA query_only`), with one query per source table.
   - `ReportData` is never read during the index build.
   - A name index (upper-cased name to object types) is built once from idfkit's collections.
   - Summary statistics over timeseries, when asked for, use SQL aggregation (`MIN`, `MAX`, `AVG`, `COUNT` with
     `WHERE`) for one key at a time, never row loops in Python.
   - The index is built on the first results question after a run, then cached on the document stamped with the
     run, so later questions never re-read the file.
   - *Measured:* 1.8 ms on a 32.5 MB file, independent of timeseries volume.
9. **Standards data: lazy, projected, shared.**
   - Each PNNL table is loaded on first use. Its rows are projected to the columns screening needs as tuples,
     indexed by `(edition, climate zone set, surface type, building category)`, and the parsed JSON is discarded.
   - The result is a process-wide, read-only cache guarded by a lock during the first load, and shared by every
     session.
   - Tables this feature never reads are never opened.
   - *Measured:* the envelope table takes 43 ms to parse and 0.085 µs per indexed lookup. All tables together are
     61.6 MB on disk.
10. **Bounded responses are a performance rule.** Every tool has a `limit` with a small default, summaries before
    detail, deduplication with counts, and the 8 KB default response budget. *Measured:* an existing unbounded
    response, `get_zone_properties` on all hospital zones, takes 87 ms and returns 110 KB.
11. **No blocking surprises in the server.** Every new tool's server-side work stays within the budgets above,
    so a call never holds the event loop longer than an existing read tool. The first standards load (≤ 150 ms)
    is the only cold-start cost, and it is paid once per process.

### Enforcement

- **Benchmarks in idfkit.** `benchmarks/bench_hvac_topology.py`, `bench_result_index.py` and `bench_standards.py`
  use stdlib `time.perf_counter` with best-of-N. They run against the committed reference model (HospitalLowEnergy
  from the 26.2 ExampleFiles, vendored gzip-compressed into `benchmarks/fixtures/`: 4.5 MB raw, 0.24 MB
  compressed for the 24.1 file) and the linking fixtures. The benchmark needs no EnergyPlus installation.
- **Gate.** A `perf`-marked pytest module asserts each budget with a 2× allowance for CI noise. It runs in CI on
  Python 3.10 and 3.12. A change that misses a budget fails the build. Moving a budget needs a stated reason in the
  CHANGELOG (FR-009).
- **idfkit-mcp.** A `perf`-marked protocol test calls each new tool on the reference model through FastMCP and
  asserts the per-call server time and response size budgets.
- **Reporting.** Each slice's pull request includes the benchmark table before and after.

**Alternatives considered.**
- Incremental graph maintenance through `notify_*` hooks. Rejected on measurement (decision 4).
- Arrays (`array.array`) or compressed sparse rows for adjacency. Rejected: no measurable gain over lists at
  3k nodes, and harder to read.
- A compiled extension (Cython, Rust). Rejected: the measured costs are milliseconds, and idfkit's core is pure
  Python.
- `pytest-benchmark` for the gate. Rejected under R-01 (no new dependency). A stdlib timer with best-of-N is
  enough for budgets with a 2× allowance.
- Caching standards data on disk in a pre-indexed form. Rejected: 43 ms once per process is within budget, and a
  disk cache adds invalidation and file-write concerns (Constitution Principle V).
