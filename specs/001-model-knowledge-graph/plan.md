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
3. **Standards knowledge.** The climate zone, construction U and SHGC, and cited envelope screening against every
   ASHRAE 90.1 edition from 2004 to 2025.

A fourth part, an evaluation harness, measures whether agents fix more faults with fewer requests than the
previous release.

All domain logic is pure Python and standard library in **idfkit**: two new subpackages, `idfkit.hvac` and
`idfkit.standards`, and extensions to `idfkit.simulation` and `idfkit.thermal`. PNNL's BSD-licensed standards data
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

**Storage**:
- No database. Derived views (topology, results index) are computed on demand and cached per document revision.
- Session state gains the standards context, asserted roles and the model hash at simulation time, in the existing
  session JSON file (v1 → v2, R-15).
- Result-linking fixtures are committed as trimmed SQLite files under 10 MB in total (R-19).

**Testing**: pytest in both repositories.
- idfkit: unit tests and fixture-based linking tests by default. Corpus qualification is marked `integration` and
  needs EnergyPlus 26.2. The standards hand-check sample needs the extra.
- idfkit-mcp: tests at the protocol boundary through FastMCP, with no AI client (Principle VII).
- The evaluation is evidence of benefit, not a test (FR-045).

**Target Platform**: wherever idfkit and idfkit-mcp run today: Linux, macOS and Windows, over stdio and Streamable
HTTP. EnergyPlus is needed only for simulation, corpus qualification, fixture building and the evaluation.

**Project Type**: a library (idfkit) and an MCP server (idfkit-mcp), changed together. The upstream lands first.

**Performance Goals**: performance is a requirement (spec FR-009, SC-011 to SC-013). The budgets come from
measurements on real models taken during planning
([background/04](background/04-performance-measurements.md)) and are enforced by a benchmark gate (research R-21).

| Operation, on HospitalLowEnergy (6,876 objects, 2,869 nodes) | Measured (prototype) | Budget |
|---|---|---|
| Load the IDF (existing, for scale) | 228 ms | — |
| Topology build with checks | 5.2 ms (core build only) | ≤ 50 ms, and ≤ 25% of load |
| One topology query | ~1.5 µs traversal, ~1 ms MCP overhead | ≤ 5 ms in idfkit, ≤ 10 ms through MCP |
| Results index build (32.5 MB SQL) | 1.8 ms | ≤ 50 ms, independent of timeseries volume |
| Standards first call per process (11.3 MB table) | 43 ms load + 3.9 ms index | ≤ 150 ms |
| Default response size | Existing unbounded tool: 110 KB | ≤ 8 KB |
| Extra memory per model | 1.5 MB | ≤ 10 MB |

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
- No guessed values (Principle III).

**Scale/Scope**: models up to about 10k objects and 3k nodes. 18 EnergyPlus versions (8.9–26.2). Eight 90.1
editions. About 12 new or changed MCP tools and resources. 12 fault types × at least 20 reference models.

## Constitution Check

*GATE: must pass before Phase 0 research. Re-checked after Phase 1 design (see the end of this section).*

| Principle | Gate | Pre-design | Post-design |
|---|---|---|---|
| I. The server exposes, idfkit knows | No domain knowledge in idfkit-mcp | Pass. Spec FR-001 puts all rules in idfkit | **Pass.** Topology rules, linking resolver, message catalogue, diagnosis weights, standards lookup and role inference all live in idfkit (R-02, R-16). idfkit-mcp only maps types and holds session state |
| II. Every tool is a typed contract | Pydantic responses, accurate annotations, family verbs, stated token cost | Pass | **Pass.** [contracts/mcp-tools.md](contracts/mcp-tools.md) gives each tool a typed response and the existing `_READ_ONLY`/`_MUTATE` annotations. `rename_node` and `assign_object_role` use family-consistent verbs and are change-logged. The token budget comes from `token_audit.py` (R-12) |
| III. An absent answer is stated, never fabricated | Actionable errors, no defaults, no name inference | Pass. FR-005, FR-032, FR-036 | **Pass.** No default edition. Framing classes are never inferred (R-09). Unresolved links are listed. Standards fall back to an "unavailable" error (R-08). Weak links are never ranked first |
| IV. Validation gates are named for what they prove | No claim of simulation or compliance | Pass. FR-008 | **Pass.** Topology findings are QA, not runtime proof. The screening report's `basis` says "prescriptive screening — not a compliance determination". Zone multipliers are carried (FR-025) |
| V. Sessions are isolated, persisted and bounded | Session-scoped state, persisted, restore failures reported | Pass | **Pass.** New state lives on `ServerState` and is persisted in the session file v2. HTTP sessions keep persistence off, as today. No new filesystem writes outside the allowed roots: the eval writes only under `eval/runs/` in the developer's checkout |
| VI. Levels are pinned, declared and reported | Exact pin; a dependency-form change pairs with a register change | **Attention** | **Pass with a paired change.** `idfkit[standards]==X` is still an exact pin in `project.dependencies`. If the consumer-register job treats the extra as a new dependency form, a paired register amendment in idfkit-conformance is required (Complexity Tracking) |
| VII. Behaviour is tested at the protocol boundary | Each tool and resource tested through FastMCP | Pass | **Pass.** Each contract maps to protocol tests. The evaluation is explicitly not a test |

Family position: the feature adds **two capability units** to idfkit (`idfkit.hvac`, `idfkit.standards`), which
the idfkit parity gate requires to land with parity-ledger and naming-register rows in idfkit-conformance (R-02).
That is recorded below as a justified cross-repository cost, not a violation.

## Project Structure

### Documentation (this feature)

```text
specs/001-model-knowledge-graph/
├── spec.md              # Feature specification (clarified 2026-11-11)
├── plan.md              # This file
├── research.md          # Phase 0: decisions R-01 to R-20
├── data-model.md        # Phase 1: entities, fields, state transitions
├── quickstart.md        # Phase 1: validation scenarios per user story
├── contracts/
│   ├── idfkit-api.md    # Upstream Python surface
│   ├── mcp-tools.md     # Agent-facing tools and resources
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
│   │   ├── roles.py                       # computed and unconfirmed roles
│   │   └── envelope.py                    # lookup_envelope, screen_envelope
│   └── codegen/
│       ├── generate_node_fields.py        # NEW
│       ├── generate_port_rules.py         # NEW: runs ExampleFiles + test models, harvests eplusout.bnd (needs EnergyPlus)
│       └── port_rule_models/              # NEW: 10 minimal IDFs for types absent from ExampleFiles
├── agent_references/{templates,snippets}/ # + hvac-topology, standards; update result-parsing, thermal
├── scripts/build_linking_fixtures.py      # NEW (needs EnergyPlus 26.2)
├── benchmarks/
│   ├── bench_hvac_topology.py             # NEW: build, checks, queries (R-21)
│   ├── bench_result_index.py              # NEW: index build, per-object query
│   ├── bench_standards.py                 # NEW: first load, lookup, screening
│   └── fixtures/HospitalLowEnergy.idf.gz  # NEW: reference model (0.24 MB compressed)
└── tests/
    ├── test_hvac_topology.py              # unit and injected faults
    ├── test_hvac_corpus.py                # @integration: SC-001 on 26.2 ExampleFiles
    ├── test_simulation_linking.py         # fixture-based; SC-004
    ├── test_err_catalog.py
    ├── test_thermal_films.py
    ├── test_standards_envelope.py         # skips without the extra
    ├── test_standards_sample.py           # SC-006 hand-check sample
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
│       ├── standards.py                   # NEW: get/set_standards_context, lookup_standard, screen_envelope,
│       │                                  #      get_object_roles, assign_object_role
│       ├── integrity.py                   # + hvac_topology check group
│       ├── simulation.py                  # + affected_objects, kind, link_coverage; record run revision and hash
│       ├── peak_loads.py                  # + ObjectKey on zone rows and flags
│       ├── weather.py                     # + climate_zone filter and field
│       └── resources.py                   # + hvac/{loop}, simulation/objects/{type}/{name}, standards/context
├── eval/                                  # NEW, excluded from the wheel
│   ├── __main__.py                        # run, compare, list-faults
│   ├── faults/                            # 12 FaultType modules
│   ├── runners/claude_code.toml
│   └── reference_models.toml
├── docs/                                  # tool reference pages for every new or changed tool
└── tests/
    ├── test_topology_tools.py
    ├── test_results_tools.py
    ├── test_standards_tools.py
    ├── test_session_persistence.py        # + v2 fields, v1 compatibility
    ├── test_perf_tools.py                 # @perf: per-call server time and response size budgets
    └── test_eval_harness.py               # harness logic with a fake runner, no LLM
```

**Structure Decision**: two existing projects, no new repository. Domain code goes in idfkit's existing layout
under the two new units and the two extended ones. idfkit-mcp follows its one-module-per-tool-family pattern under
`tools/`. The evaluation harness sits at the idfkit-mcp root as development tooling, outside `src/`, so hatchling
never packages it.

## Delivery Order

The order follows the spec's priorities and the one hard dependency: idfkit before idfkit-mcp.

| Slice | idfkit | idfkit-mcp | Gate to the next slice |
|---|---|---|---|
| 0 | `revision` and `_derived` cache slot, `SQLResult` readers, fixture builder and fixtures, **benchmark harness, reference model and `perf` gate** | Session v2 skeleton, `perf` protocol test harness | Fixtures committed; gate runs in CI |
| 1: US1 | `idfkit.hvac` (node fields, **rules for all 257 node-bearing types generated from EnergyPlus's connection report** (example models plus 10 minimal test models; naming only as a cross-check; provenance on every rule), coverage test, T010, T011, T030, T090, T091), corpus test, parity rows | `trace_node`, `hvac_topology` integrity group | SC-001 green on 26.2; **topology budget confirmed by benchmark before slice 3** |
| 2: US2 | — | `eval/` harness, topology and standards faults | First baseline/treatment run on topology faults |
| 3: US3 | `linking.py`, `err_catalog.py` (about 15 kinds) | `get_object_results`, `affected_objects`, peak-load object keys | SC-004 green on fixtures |
| 4: US4 | Memberships, `chain`, `rename_node`, T001–T004 | `trace_component`, `get_hvac_topology`, `rename_node`, resource | SC-003 |
| 5: US5 | Films, `idfkit.standards`, roles, parity row | Standards tools, weather climate zone | SC-006 sample green |
| 6: US6 | `diagnose`, catalogue to about 40 kinds | `diagnose_symptom` | Built only if the SC-009 gate passes on the slice 2–5 evaluation |

Each slice in idfkit ships with its agent-reference template and snippet, re-baked, and a CHANGELOG entry. Each
slice in idfkit-mcp ships with docs pages and a token-audit figure. **Every slice's pull request includes the
benchmark table before and after, and none merges with a budget failing** (FR-009).

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| Two new idfkit capability units, each needing a parity-ledger and naming-register row in idfkit-conformance | The parity gate requires every new public subpackage to be declared. Topology and standards are genuinely new capabilities | Hiding them inside existing units (`references`, `thermal`) would misplace node semantics and an optional-dependency feature, and would make the ledger understate the surface |
| idfkit-mcp dependency becomes `idfkit[standards]==X` | idfkit-mcp must reach the standards data, and Principle I keeps it out of idfkit-mcp's own code | Depending on `building-energy-standards-data` directly would add a second third-party dependency to idfkit-mcp and split the level declaration. A register amendment is cheaper if the check requires one |
| Session file v1 → v2 | FR-037 requires asserted roles to survive restarts, and FR-026 requires staleness across restarts | Not persisting would violate FR-037, and a sidecar file was ruled out in Clarifications |
| Two new private slots on `IDFDocument` (`_revision`, `_derived`) | Performance (R-06, R-21). The document has no `__weakref__`, so derived views cannot be cached externally without leaks or id reuse | Recomputing per call wastes about 5 ms per question, and the results index would re-read SQL every time. An external cache keyed by `id(doc)` leaks memory under concurrent HTTP sessions |
| A `perf` benchmark gate in both repositories | FR-009 makes the budgets requirements, and a requirement needs a check | Reviewing timings by hand misses regressions. `pytest-benchmark` would add a dependency (R-01) |
| `eval/` directory with its own CLI in idfkit-mcp | User Story 2 is P1, and FR-042 requires with/without runs | Putting it in idfkit would invert the dependency, since the eval drives the server. A separate repository is unwarranted for one harness |
