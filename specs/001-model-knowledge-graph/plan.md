# Implementation Plan: Model Knowledge Graph for Agents

**Branch**: `001-model-knowledge-graph` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-model-knowledge-graph/spec.md`, plus the planning direction
*"a pure Python stack as much as possible; no external dependencies except for the PNNL standards library."*

## Summary

This feature adds three layers to idfkit's model graph and exposes them to agents through idfkit-mcp:

1. **HVAC topology.** Every node use gets a connection role. Loop membership is derived, connection faults are
   checked statically, and nodes can be renamed safely.
2. **Results attached to the model.** Sizing rows, report rows, output keys and messages from the session's
   simulation are linked to model objects, with ranked symptom-to-cause diagnosis on top.
3. **Standards knowledge.** Cited screening in three topics:
   - the envelope: the climate zone and construction U, C, F and SHGC, against every ASHRAE 90.1 edition from
     2004 to 2025
   - lighting power: each zone, by the 90.1 space-by-space method
   - outdoor-air ventilation: each zone, against every ASHRAE 62.1 edition from 1999 to 2022

   Lighting and ventilation rest on a zone space-type role that is asserted, never computed (clarified
   2026-11-11, research R-26 to R-30).

A fourth part, an evaluation harness, measures whether agents fix more faults with fewer requests than the
previous release.

**Developers are a first-class audience** (User Story 7, FR-050 to FR-058). Each layer is a public, typed and
documented idfkit API that works without a server. A thin combined view, `idfkit.graph.ModelGraph`, walks all
layers with one vocabulary of node and edge kinds and exports to node-link JSON that networkx loads unchanged.
idfkit-mcp reaches every capability only through that public API, which a test enforces. For agents, the server
adds one bounded cross-layer tool, `get_object_neighbourhood`. Export stays Python-only.

All domain logic is pure Python and standard library in **idfkit**: two new subpackages, `idfkit.hvac` and
`idfkit.standards`, and extensions to `idfkit.simulation` and `idfkit.thermal`. A third new subpackage,
`idfkit.graph`, holds no domain logic; it is a read-only adapter over the other layers. PNNL's BSD-licensed standards data
is the only new third-party dependency. It is an optional extra whose JSON files idfkit reads without importing
the package. idfkit-mcp adds thin tool modules, session state and an unpackaged `eval/` harness, and gains no new
direct dependency.

**Performance is designed in, not tuned afterwards.** It rests on planning-time measurements of real models, and
the budgets are enforced by a benchmark gate in both repositories (R-21). Deriving the connection view costs a
few percent of loading the model, a topology question costs microseconds in idfkit, the results index never reads
timeseries, and no default response exceeds 8 KB.

## Technical Context

**Language/Version**: Python 3.10–3.13 for everything. The standards data declares `<3.14`, so on 3.14 the
standards tools report themselves unavailable and everything else works (research R-08).

**Primary Dependencies**:
- idfkit: standard library only, plus the optional extra `standards = ["building-energy-standards-data>=0.3.3,<0.4;
  python_version < '3.14'"]`.
- idfkit-mcp: existing dependencies unchanged (FastMCP 3.x, `mcp`, Pydantic 2, `openstudio`), and `idfkit==X`
  becomes `idfkit[standards]==X` (R-20).
- Evaluation: standard library plus the existing FastMCP client. The agent is driven by an external CLI command
  (R-13).
- Node-link export: `json` from the standard library. networkx is used only by one CI test, through
  `uv run --with "networkx>=3.6"`, and is declared nowhere (R-24).

**Storage**:
- No database. Derived views (topology, results index) are computed on demand and cached per document revision.
- Session state gains the standards context, asserted roles and the model hash at simulation time, in the existing
  session JSON file (v1 → v2, R-15).
- Result-linking fixtures are committed as trimmed SQLite files under 10 MB in total (R-19).

**Testing**: pytest in both repositories.
- idfkit: unit tests and fixture-based linking tests by default. Corpus qualification is marked `integration` and
  needs EnergyPlus 26.2. The standards hand-check sample needs the extra.
- idfkit-mcp: tests at the protocol boundary through FastMCP, with no AI client (Principle VII), plus an AST test
  that idfkit-mcp uses only idfkit's public API (R-22).
- Developer API: every agent-reference snippet runs in idfkit's suite and type-checks under pyright strict. The
  node-link export is checked with the standard library by default, and loaded by networkx in a `nodelink`-marked
  job (R-24).
- The evaluation is evidence of benefit, not a test (FR-045).

**Target Platform**: wherever idfkit and idfkit-mcp run today: Linux, macOS and Windows, over stdio and Streamable
HTTP. EnergyPlus is needed only for simulation, corpus qualification, fixture building and the evaluation.

**Project Type**: a library (idfkit) and an MCP server (idfkit-mcp), changed together. The upstream lands first.
idfkit's human reference pages live in a third repository, idfkit-developers, which embeds idfkit's snippets
(R-22).

**Performance Goals**: performance is a requirement (spec FR-009, SC-011 to SC-013). The budgets come from
measurements on real models taken during planning
([background/04](background/04-performance-measurements.md)) and are enforced by a benchmark gate (research R-21).

| Operation, on HospitalLowEnergy (6,876 objects, 2,869 nodes) | Measured (prototype) | Budget |
|---|---|---|
| Load the IDF (existing, for scale) | 228 ms | — |
| Topology build with checks | 5.2 ms (core build only) | ≤ 50 ms, and ≤ 25% of load |
| One topology query | ~1.5 µs traversal, ~1 ms MCP overhead | ≤ 5 ms in idfkit, ≤ 10 ms through MCP |
| Results index build (32.5 MB SQL) | 1.8 ms | ≤ 50 ms, independent of timeseries volume |
| Standards first call per process (11.3 MB table) | 43 ms load + 3.9 ms index | ≤ 150 ms per topic |
| Screening of a loaded model, all three topics | — | ≤ 20 ms |
| Default response size | Existing unbounded tool: 110 KB | ≤ 8 KB |
| Extra memory per model | 1.5 MB | ≤ 10 MB |
| `ModelGraph` construction / one neighbourhood walk (3 hops, 200 nodes) | — | ≤ 0.1 ms / ≤ 10 ms |
| Node-link export, `model` and `topology` layers, whole model | — | ≤ 1 s (plan budget, R-21) |

The architecture behind these numbers (R-21):
- per-type plans, computed once
- integer-interned nodes with adjacency lists
- tuples inside, dataclasses only for returned items
- rebuild per revision instead of incremental upkeep
- derived views cached on the document
- results indexed without touching timeseries
- standards tables loaded lazily, projected and shared

**Constraints**:
- Bounded responses: default 20 rows, about 200 tokens per loop summary, and tool-listing growth ≤ 15% (SC-010).
- Model-only features work offline and without EnergyPlus (FR-006).
- No ASHRAE text copied into either repository (FR-038).
- No guessed values (Principle III). PNNL's space-type mapping is shown with every lighting and ventilation verdict
  and is never corrected locally. Mappings judged wrong produce "cannot tell" (R-27).

**Scale/Scope**: models up to about 10k objects and 3k nodes. 18 EnergyPlus versions (8.9–26.2). Eight 90.1
editions for the envelope and lighting, and eight 62.1 editions. About 13 new or changed MCP tools and resources.
13 fault types × at least 20 reference models. Three new
public idfkit units (`hvac`, `standards`, `graph`), with five new or updated agent-reference topics and three new
idfkit-developers reference pages.

## Constitution Check

*GATE: must pass before Phase 0 research. Re-checked after Phase 1 design (see the end of this section).*

| Principle | Gate | Pre-design | Post-design |
|---|---|---|---|
| I. The server exposes, idfkit knows | No domain knowledge in idfkit-mcp | Pass. Spec FR-001 puts all rules in idfkit | **Pass.** Topology rules, linking resolver, message catalogue, diagnosis weights, standards lookup, role inference, space-type resolution and zone lighting and outdoor-air measures all live in idfkit (R-02, R-16, R-27, R-28). The graph vocabulary and traversal are in idfkit as well (R-23). idfkit-mcp only maps types and holds session state, and a test keeps it on the public API (R-22, FR-050) |
| II. Every tool is a typed contract | Pydantic responses, accurate annotations, family verbs, stated token cost | Pass | **Pass.** [contracts/mcp-tools.md](contracts/mcp-tools.md) gives each tool a typed response and the existing `_READ_ONLY`/`_MUTATE` annotations. `rename_node` and `assign_object_role` use family-consistent verbs and are change-logged. The export follows the family verbs too (`write_node_link` returns text, `save_node_link` writes a path). The token budget comes from `token_audit.py`, including `get_object_neighbourhood` (R-12, R-25) |
| III. An absent answer is stated, never fabricated | Actionable errors, no defaults, no name inference | Pass. FR-005, FR-032, FR-036 | **Pass.** No default edition. Framing classes and space types are never inferred (R-09, R-27). The 62.1 rows carry no citation, so the citation table that fills the gap is labelled `citation_source: "idfkit"` and is checked by hand (R-26). Doubtful PNNL mappings produce "cannot tell" (R-27). Unresolved links are listed. Standards fall back to an "unavailable" error (R-08). Weak links are never ranked first. A missing graph layer is stated with its reason, never silently absent (R-23) |
| IV. Validation gates are named for what they prove | No claim of simulation or compliance | Pass. FR-008 | **Pass.** Topology findings are QA, not runtime proof. The screening report's `basis` says "prescriptive screening — not a compliance determination". Zone multipliers are carried (FR-025) |
| V. Sessions are isolated, persisted and bounded | Session-scoped state, persisted, restore failures reported | Pass | **Pass.** New state lives on `ServerState` and is persisted in the session file v2. HTTP sessions keep persistence off, as today. No new filesystem writes outside the allowed roots: the eval writes only under `eval/runs/` in the developer's checkout |
| VI. Levels are pinned, declared and reported | Exact pin; a dependency-form change pairs with a register change | **Attention** | **Pass with a paired change.** `idfkit[standards]==X` is still an exact pin in `project.dependencies`. If the consumer-register job treats the extra as a new dependency form, a paired register amendment in idfkit-conformance is required (Complexity Tracking) |
| VII. Behaviour is tested at the protocol boundary | Each tool and resource tested through FastMCP | Pass | **Pass.** Each contract maps to protocol tests, `get_object_neighbourhood` included. The evaluation is explicitly not a test |

Family position: the feature adds **three capability units** to idfkit (`idfkit.hvac`, `idfkit.standards`,
`idfkit.graph`), which
the idfkit parity gate requires to land with parity-ledger and naming-register rows in idfkit-conformance (R-02).
That is recorded below as a justified cross-repository cost, not a violation.

## Project Structure

### Documentation (this feature)

```text
specs/001-model-knowledge-graph/
├── spec.md              # Feature specification (clarified 2026-11-11)
├── plan.md              # This file
├── research.md          # Phase 0: decisions R-01 to R-30
├── data-model.md        # Phase 1: entities, fields, state transitions
├── quickstart.md        # Phase 1: validation scenarios per user story
├── contracts/
│   ├── idfkit-api.md    # Upstream Python surface
│   ├── mcp-tools.md     # Agent-facing tools and resources
│   ├── node-link-json.md # Versioned export format (Python only)
│   └── eval-harness.md  # Evaluation CLI, runner config, outputs
├── background/          # Research reports, literature scan, prototype
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code

Two repositories change. idfkit lands first. idfkit-mcp adopts the new level through its pinned dependency.

```text
idfkit/                                    # upstream (github.com/idfkit/idfkit)
├── src/idfkit/
│   ├── document.py                        # + revision counter, rename_node
│   ├── hvac/                              # NEW capability unit (parity ledger row)
│   │   ├── __init__.py
│   │   ├── types.py                       # ConnectionType, Fluid, NodeUse, LoopMembership, FlowEdge, TopologyFinding
│   │   ├── _node_fields.py                # GENERATED: (type, field) -> is fluid node
│   │   ├── _port_rules.py                 # curated connection rules and predicates
│   │   ├── topology.py                    # HVACTopology
│   │   └── checks.py                      # T001–T004, T010, T011, T030, T090, T091
│   ├── simulation/
│   │   ├── linking.py                     # NEW: ObjectKey, Resolution, ResultIndex, diagnose
│   │   └── parsers/
│   │       ├── sql.py                     # + component_sizes, errors, zones, report_keys
│   │       └── err_catalog.py             # NEW: message kinds, patterns, inspect lists
│   ├── thermal/properties.py              # + surface_class films, heat_capacity_per_area
│   ├── standards/                         # NEW capability unit (parity ledger row)
│   │   ├── __init__.py
│   │   ├── _data.py                       # find_spec + lazy JSON load; never imports PNNL code
│   │   ├── units.py                       # IP <-> SI
│   │   ├── context.py                     # StandardsContext, Topic, required items per topic
│   │   ├── roles.py                       # computed and unconfirmed roles; space-type vocabularies
│   │   ├── measures.py                    # zone_lighting, zone_outdoor_air (no extra needed)
│   │   ├── envelope.py                    # lookup_envelope
│   │   ├── lighting.py                    # lookup_lighting (SS and CS rows only)
│   │   ├── ventilation.py                 # lookup_ventilation
│   │   ├── _space_types.py                # level 1 -> level 2 -> row resolution (R-27)
│   │   ├── _mapping_review.py             # reviewed list of doubtful PNNL mappings; no values
│   │   ├── _citations_62_1.py             # reviewed 62.1 edition -> table number; no values (R-26)
│   │   └── screening.py                   # screen(doc, context, topics=...)
│   ├── graph/                             # NEW capability unit (parity ledger row); no domain logic
│   │   ├── __init__.py
│   │   ├── types.py                       # NodeKind, EdgeKind, Layer, GraphNode, GraphEdge, Subgraph
│   │   ├── view.py                        # ModelGraph: per-layer adapters, bounded BFS
│   │   └── node_link.py                   # to_node_link, write_node_link, save_node_link
│   └── codegen/
│       ├── generate_node_fields.py        # NEW
│       ├── generate_port_rules.py         # NEW: runs ExampleFiles + test models, harvests eplusout.bnd (needs EnergyPlus)
│       └── port_rule_models/              # NEW: 10 minimal IDFs for types absent from ExampleFiles
├── agent_references/{templates,snippets}/ # + hvac-topology, standards, model-graph; update result-parsing,
│                                          #   thermal-properties, reference-tracking, hvac-loops
├── scripts/build_linking_fixtures.py      # NEW (needs EnergyPlus 26.2)
├── benchmarks/
│   ├── bench_hvac_topology.py             # NEW: build, checks, queries (R-21)
│   ├── bench_result_index.py              # NEW: index build, per-object query
│   ├── bench_standards.py                 # NEW: first load, lookup, screening
│   ├── bench_graph.py                     # NEW: construction, neighbourhood, export
│   └── fixtures/HospitalLowEnergy.idf.gz  # NEW: reference model (0.24 MB compressed)
└── tests/
    ├── test_hvac_topology.py              # unit and injected faults
    ├── test_hvac_corpus.py                # @integration: SC-001 on 26.2 ExampleFiles
    ├── test_simulation_linking.py         # fixture-based; SC-004
    ├── test_err_catalog.py
    ├── test_thermal_films.py
    ├── test_standards_envelope.py         # skips without the extra
    ├── test_standards_lighting.py         # skips without the extra
    ├── test_standards_ventilation.py      # skips without the extra
    ├── test_standards_measures.py         # zone_lighting, zone_outdoor_air; no extra
    ├── test_standards_mapping.py          # R-27 qualification of PNNL's space-type mapping
    ├── test_standards_sample.py           # SC-006 hand-check sample, all three topics
    ├── test_graph_view.py                 # layers, vocabulary, bounds, staleness
    ├── test_graph_node_link.py            # stdlib format checks; @nodelink: networkx loads it (R-24)
    ├── test_perf_budgets.py               # @perf: R-21 budgets with a 2× CI allowance, on 3.10 and 3.12
    └── fixtures/simulation/linked/        # trimmed (IDF, SQL, ERR) triples, ≤ 10 MB

idfkit-mcp/                                # this repository
├── pyproject.toml                         # idfkit==X  ->  idfkit[standards]==X
├── src/idfkit_mcp/
│   ├── models.py                          # + Pydantic mirrors; QA flag and warning fields
│   ├── state.py                           # + standards_context, asserted_roles, simulation_model_hash; session v2
│   └── tools/
│       ├── topology.py                    # NEW: trace_node, trace_component, get_hvac_topology, rename_node
│       ├── results.py                     # NEW: get_object_results, diagnose_symptom
│       ├── standards.py                   # NEW: get/set_standards_context, lookup_standard, screen_standards,
│       │                                  #      get_object_roles, assign_object_role
│       ├── graph.py                       # NEW: get_object_neighbourhood (no export)
│       ├── integrity.py                   # + hvac_topology check group
│       ├── simulation.py                  # + affected_objects, kind, link_coverage; record run revision and hash
│       ├── peak_loads.py                  # + ObjectKey on zone rows and flags
│       ├── weather.py                     # + climate_zone filter and field
│       └── resources.py                   # + hvac/{loop}, simulation/objects/{type}/{name}, standards/context
├── eval/                                  # NEW, excluded from the wheel
│   ├── __main__.py                        # run, compare, list-faults
│   ├── faults/                            # 13 FaultType modules
│   ├── runners/claude_code.toml
│   └── reference_models.toml
├── docs/                                  # tool reference pages for every new or changed tool
└── tests/
    ├── test_topology_tools.py
    ├── test_results_tools.py
    ├── test_standards_tools.py
    ├── test_graph_tools.py
    ├── test_public_api_only.py            # AST: no private idfkit imports or attributes (FR-050)
    ├── test_session_persistence.py        # + v2 fields, v1 compatibility
    ├── test_perf_tools.py                 # @perf: per-call server time and response size budgets
    └── test_eval_harness.py               # harness logic with a fake runner, no LLM

idfkit-developers/                         # idfkit's documentation site (github.com/idfkit/idfkit-developers)
└── docs/reference/                        # + hvac, standards, graph pages; simulation and thermal updated.
                                           #   Pages embed idfkit's snippets, never their own copies (R-22)
```

**Structure Decision**: two existing projects, no new repository. Domain code goes in idfkit's existing layout
under the two new units and the two extended ones. idfkit-mcp follows its one-module-per-tool-family pattern under
`tools/`. The evaluation harness sits at the idfkit-mcp root as development tooling, outside `src/`, so hatchling
never packages it.

## Delivery Order

The order follows the spec's priorities and the one hard dependency: idfkit before idfkit-mcp.

| Slice | idfkit | idfkit-mcp | Gate to the next slice |
|---|---|---|---|
| 0 | `revision` and `_derived` cache slot, `SQLResult` readers, fixture builder and fixtures, **benchmark harness, reference model and `perf` gate** | Session v2 skeleton, `perf` protocol test harness, `test_public_api_only.py` | Fixtures committed; gate runs in CI |
| 1: US1 | `idfkit.hvac` (node fields, **rules for all 257 node-bearing types generated from EnergyPlus's connection report** (example models plus 10 minimal test models; naming only as a cross-check; provenance on every rule), coverage test, T010, T011, T030, T090, T091), corpus test, parity rows | `trace_node`, `hvac_topology` integrity group | SC-001 green on 26.2; **topology budget confirmed by benchmark before slice 3** |
| 2: US2 | — | `eval/` harness, topology and standards faults | First baseline/treatment run on topology faults |
| 3: US3 | `linking.py`, `err_catalog.py` (about 15 kinds) | `get_object_results`, `affected_objects`, peak-load object keys | SC-004 green on fixtures |
| 4: US4 + US7 | Memberships, `chain`, `rename_node`, T001–T004. **`idfkit.graph`** with the `model`, `topology` and `results` layers, node-link export, `nodelink` CI job, `model-graph` snippet and parity row | `trace_component`, `get_hvac_topology`, `rename_node`, resource, **`get_object_neighbourhood`** | SC-003; export loads in networkx; neighbourhood ≤ 8 KB |
| 5a: US5 envelope | Films, `idfkit.standards` (context, roles, envelope, `screen`), parity row, **`standards` layer of `ModelGraph`** | Standards tools, weather climate zone; the neighbourhood tool gains verdicts | SC-006 envelope sample green; US7 standalone script complete (SC-014) |
| 5b: US5 lighting and ventilation | `measures.py`, space-type roles, `lighting.py`, `ventilation.py`, mapping qualification and review list, 62.1 citation table; zone verdicts in `ModelGraph` | `topics` on `screen_standards` and `lookup_standard`; space-type roles on `assign_object_role`; `ventilation_edition` in the context | SC-006 lighting and ventilation sample green; R-27 mapping test green |
| 6: US6 | `diagnose`, catalogue to about 40 kinds | `diagnose_symptom` | Built only if the SC-009 gate passes on the slice 2–5 evaluation |

Each slice in idfkit ships with its agent-reference template and snippet, re-baked, a CHANGELOG entry, and its
idfkit-developers reference page (FR-052): User Story 7 is delivered layer by layer, not in a slice of its own.
`idfkit.graph` lands in slice 4, once three of its four layers exist, so its vocabulary is exercised by real
layers before it is released. Each slice in idfkit-mcp ships with docs pages and a token-audit figure. **Every slice's pull request includes the
benchmark table before and after, and none merges with a budget failing** (FR-009).

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| Two new idfkit capability units, each needing a parity-ledger and naming-register row in idfkit-conformance | The parity gate requires every new public subpackage to be declared. Topology and standards are genuinely new capabilities | Hiding them inside existing units (`references`, `thermal`) would misplace node semantics and an optional-dependency feature, and would make the ledger understate the surface |
| idfkit-mcp dependency becomes `idfkit[standards]==X` | idfkit-mcp must reach the standards data, and Principle I keeps it out of idfkit-mcp's own code | Depending on `building-energy-standards-data` directly would add a second third-party dependency to idfkit-mcp and split the level declaration. A register amendment is cheaper if the check requires one |
| Session file v1 → v2 | FR-037 requires asserted roles to survive restarts, and FR-026 requires staleness across restarts | Not persisting would violate FR-037, and a sidecar file was ruled out in Clarifications |
| Two new private slots on `IDFDocument` (`_revision`, `_derived`) | Performance (R-06, R-21). The document has no `__weakref__`, so derived views cannot be cached externally without leaks or id reuse | Recomputing per call wastes about 5 ms per question, and the results index would re-read SQL every time. An external cache keyed by `id(doc)` leaks memory under concurrent HTTP sessions |
| A `perf` benchmark gate in both repositories | FR-009 makes the budgets requirements, and a requirement needs a check | Reviewing timings by hand misses regressions. `pytest-benchmark` would add a dependency (R-01) |
| A third new idfkit unit, `idfkit.graph`, with its own ledger and register rows | FR-055 asks for a combined view with one vocabulary, and placing it in any one layer would make that layer import the others | A method on `IDFDocument` would pull every layer, including the optional standards data, into `document.py`. A materialised graph would duplicate the layers' data, which FR-056 forbids (R-23) |
| A third repository touched, idfkit-developers | FR-052 requires reference pages, and idfkit's human docs live there | Duplicating the pages in idfkit would recreate the drift that moving the docs out removed. The pages embed idfkit's tested snippets instead |
| A CI job that installs networkx ad hoc (`uv run --with`) | FR-057 requires proof that networkx loads the export unchanged | Declaring networkx as a dev dependency would add a third-party package to idfkit's lock file against R-01. A hand-written mimic of networkx's reader would not prove compatibility |
| Two small reviewed tables in `idfkit.standards`: the 62.1 citation numbers and the list of doubtful PNNL space-type mappings | FR-033 requires a cited table, and the 62.1 rows carry none. Principle III forbids a confident verdict from a mapping known to be wrong (R-26, R-27) | Leaving ventilation uncited fails FR-033. Correcting PNNL's mapping locally would make idfkit a source of standards judgement (FR-038). Both tables hold identifiers and reasons, no requirement values |
| An AST test in idfkit-mcp that forbids private idfkit names | FR-050 requires the server to use only the public API | Review alone misses it. Today's code already passes, so the test only guards against regressions (R-22) |
| `eval/` directory with its own CLI in idfkit-mcp | User Story 2 is P1, and FR-042 requires with/without runs | Putting it in idfkit would invert the dependency, since the eval drives the server. A separate repository is unwarranted for one harness |
