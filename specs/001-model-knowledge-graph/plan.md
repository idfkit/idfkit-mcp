# Implementation Plan: Model Knowledge Graph for Agents

**Branch**: `001-model-knowledge-graph` | **Date**: 2026-11-11 (revision 2) | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-model-knowledge-graph/spec.md`, plus the planning direction
*"a pure Python stack as much as possible; no external dependencies except for the PNNL standards library."*

**Revision 2.** Re-planned after the spec review and the deferral of the standards layer (spec, Clarifications,
2026-11-11). What changed, in one place:
- The standards layer, `idfkit.standards`, its six tools, slices 5a and 5b and research R-08 to R-11 and R-26 to
  R-30 are out. Their decisions are kept in [deferred-standards-research.md](deferred-standards-research.md). The
  feature now adds **no** third-party dependency, and idfkit-mcp keeps its plain `idfkit==X` pin.
- The evaluation is redesigned: pre-feature baseline, three repeats, paired bootstrap intervals, held-out faults,
  control, authoring and open-question tasks, and a run in every story's slice (R-13, R-14, R-32, R-33).
- The tool surface drops from 13 new tools to 6, two of them conditional on a measured saving (R-31).
- New: false findings on EnergyPlus 9.6 and 23.2 with a per-version severity cap (R-34), a shared coverage shape
  that names blind spots such as EMS (R-35), component categories (R-36) and anchoring checks on diagnosis (R-37).

## Summary

This feature adds two layers to idfkit's model graph and exposes them to agents through idfkit-mcp:

1. **HVAC topology.** Every node use gets a connection role generated from EnergyPlus's own connection report.
   Loop membership is derived, connection faults are checked statically, components carry a category, and nodes
   can be renamed safely.
2. **Results attached to the model.** Sizing rows, report rows, output keys and messages from the session's
   simulation are linked to model objects, with ranked symptom-to-cause diagnosis on top once the evaluation
   allows it.

A third part, the evaluation harness, measures whether agents fix more faults, build systems more reliably and
answer questions with fewer requests than the same server without the feature. It runs in every story's slice and
hard-gates User Story 6.

**Developers are a first-class audience** (User Story 7, FR-050 to FR-058). Each layer is a public, typed and
documented idfkit API that works without a server. A thin combined view, `idfkit.graph.ModelGraph`, walks both
layers and the existing reference graph with one extensible vocabulary of node and edge kinds, and exports to
node-link JSON that networkx loads unchanged. idfkit-mcp reaches every capability only through that public API,
which a test enforces. For agents, the server adds six tools (R-31).

All domain logic is pure Python and standard library in **idfkit**: one new domain subpackage, `idfkit.hvac`, an
extension of `idfkit.simulation`, and `idfkit.graph`, a read-only adapter with no domain logic. idfkit-mcp adds
thin tool modules, one session field and an unpackaged `eval/` harness, and gains no dependency.

**Performance is designed in, not tuned afterwards.** It rests on planning-time measurements of real models, and
the budgets are enforced by a benchmark gate in both repositories (R-21). Deriving the connection view costs a
few percent of loading the model, a topology question costs microseconds in idfkit, the results index never reads
timeseries, and no default response exceeds 8 KB.

## Technical Context

**Language/Version**: Python 3.10 and later, every version idfkit and idfkit-mcp support. With the standards data
gone, no part of the feature has a Python upper bound.

**Primary Dependencies**:
- idfkit: standard library only. No new extra.
- idfkit-mcp: existing dependencies unchanged (FastMCP 3.x, `mcp`, Pydantic 2, `openstudio`), and the exact
  `idfkit==X` pin is unchanged in form (R-20).
- Evaluation: standard library (including `random` and `statistics` for the bootstrap, R-32) plus the existing
  FastMCP client. The agent is driven by an external CLI command (R-13).
- Node-link export: `json` from the standard library. networkx is used only by one CI test, through
  `uv run --with "networkx>=3.6"`, and is declared nowhere (R-24).

**Storage**:
- No database. Derived views (topology, results index) are computed on demand and cached per document revision.
- Session state gains the model hash and run directory of the session's last simulation, in the existing session
  JSON file (v1 → v2, R-15).
- Committed tables generated or reviewed in idfkit: node fields, port rules, version caps (R-34) and component
  categories (R-36).
- Result-linking fixtures are committed as trimmed SQLite files under 10 MB in total (R-19).

**Testing**: pytest in both repositories.
- idfkit: unit tests and fixture-based linking tests by default. Corpus qualification on 26.2 and the earlier-
  version measurement on 9.6 and 23.2 are marked `integration` and take `--corpus VERSION=PATH` (R-18, R-34).
- idfkit-mcp: tests at the protocol boundary through FastMCP, with no AI client (Principle VII), an AST test that
  idfkit-mcp uses only idfkit's public API (R-22), and harness tests with a fake runner: the prompt lint, the
  held-out date check and the statistics (R-13, R-32, R-33).
- Developer API: every agent-reference snippet runs in idfkit's suite and type-checks under pyright strict. The
  node-link export is checked with the standard library by default, and loaded by networkx in a `nodelink`-marked
  job (R-24).
- The evaluation is evidence of benefit, not a test (FR-045).

**Target Platform**: wherever idfkit and idfkit-mcp run today: Linux, macOS and Windows, over stdio and Streamable
HTTP. EnergyPlus is needed only for simulation, rule generation, corpus measurement, fixture building and the
evaluation.

**Project Type**: a library (idfkit) and an MCP server (idfkit-mcp), changed together. The upstream lands first.
idfkit's human reference pages live in a third repository, idfkit-developers, which embeds idfkit's snippets
(R-22).

**Performance Goals**: performance is a requirement (spec FR-009, SC-011 to SC-013). The budgets come from
measurements on real models taken during planning
([background/04](background/04-performance-measurements.md)) and are enforced by a benchmark gate (R-21).

| Operation, on HospitalLowEnergy (6,876 objects, 2,869 nodes) | Measured (prototype) | Budget |
|---|---|---|
| Load the IDF (existing, for scale) | 228 ms | — |
| Topology build with checks and categories | 5.2 ms (core build only) | ≤ 50 ms, and ≤ 25% of load |
| One topology query | ~1.5 µs traversal, ~1 ms MCP overhead | ≤ 5 ms in idfkit, ≤ 10 ms through MCP |
| Results index build (32.5 MB SQL) | 1.8 ms | ≤ 50 ms, independent of timeseries volume |
| Default response size | Existing unbounded tool: 110 KB | ≤ 8 KB |
| Extra memory per model | 1.5 MB | ≤ 10 MB |
| `ModelGraph` construction / one neighbourhood walk (3 hops, 200 nodes) | — | ≤ 0.1 ms / ≤ 10 ms |
| Node-link export, `model` and `topology` layers, whole model | — | ≤ 1 s (plan budget, R-21) |
| Tool listing growth (SC-010) | base: 39 tools, ~15,300 tokens | ≤ 15%, about 2,300 tokens (R-12) |

The architecture behind these numbers (R-21):
- per-type plans, computed once
- integer-interned nodes with adjacency lists
- tuples inside, dataclasses only for returned items
- rebuild per revision instead of incremental upkeep
- derived views cached on the document
- results indexed without touching timeseries

**Constraints**:
- Bounded responses: default 20 rows, about 200 tokens per loop summary, and tool-listing growth ≤ 15% counted
  with output schemas (SC-010, R-12).
- Model-only features work offline and without EnergyPlus (FR-006).
- Every graph answer states what it did not cover (FR-004a, R-35).
- No guessed values (Principle III): categories come from object types only, EMS links are labelled
  `convention`, and diagnosis says when no candidate is strong.

**Scale/Scope**: models up to about 10k objects and 3k nodes. 18 EnergyPlus versions (8.9–26.2); 26.2 qualifies
checks, 9.6 and 23.2 are measured. 6 new MCP tools, 2 changed tools, 2 new resources. At least 15 fault types (a
third held out), controls, 4 authoring tasks and 6 open questions, on at least 20 reference models. Two new public
idfkit units (`hvac`, `graph`), with two new and three updated agent-reference topics and two new
idfkit-developers reference pages.

## Constitution Check

*GATE: must pass before Phase 0 research. Re-checked after Phase 1 design (see the end of this section).*

| Principle | Gate | Pre-design | Post-design |
|---|---|---|---|
| I. The server exposes, idfkit knows | No domain knowledge in idfkit-mcp | Pass. Spec FR-001 puts all rules in idfkit | **Pass.** Topology rules, version caps, categories, EMS key resolution, the linking resolver, the message catalogue and the diagnosis rules all live in idfkit (R-02, R-16, R-34 to R-36). The graph vocabulary and traversal are in idfkit as well (R-23). idfkit-mcp maps types and holds session state, and a test keeps it on the public API (R-22, FR-050). The evaluation's statistics are development tooling, not domain knowledge |
| II. Every tool is a typed contract | Pydantic responses, accurate annotations, family verbs, stated token cost | Pass | **Pass.** [contracts/mcp-tools.md](contracts/mcp-tools.md) gives each of the six tools a typed response and the existing `_READ_ONLY`/`_MUTATE` annotations. `rename_node` is change-logged. The listing cost is measured with output schemas against a stated base, and two tools stay only on a measured saving (R-12, R-31) |
| III. An absent answer is stated, never fabricated | Actionable errors, no defaults, no name inference | Pass. FR-005, FR-027 | **Pass.** Coverage names every blind spot, EMS program text included (R-35). Unresolved links are listed. Weak links are never ranked first, and a diagnosis with no strong candidate says so first (R-16). A missing graph layer is stated with its reason (R-23). Categories never come from names (R-36) |
| IV. Validation gates are named for what they prove | No claim of simulation or correctness | Pass. FR-008 | **Pass.** Topology findings are QA, not runtime proof, and are capped per version where measurement shows false findings (R-34). Zone multipliers are carried (FR-025) |
| V. Sessions are isolated, persisted and bounded | Session-scoped state, persisted, restore failures reported | Pass | **Pass.** The run hash and run directory live on `ServerState` and are persisted in the session file v2. HTTP sessions keep persistence off, as today. The eval writes only under `eval/runs/` and `eval/decisions/` in the developer's checkout |
| VI. Levels are pinned, declared and reported | Exact pin; a dependency-form change pairs with a register change | Pass | **Pass.** The pin stays `idfkit==X` in `project.dependencies`, so no register change is needed (R-20). The earlier "attention" item left with the standards extra |
| VII. Behaviour is tested at the protocol boundary | Each tool and resource tested through FastMCP | Pass | **Pass.** Each contract maps to protocol tests. The evaluation is explicitly not a test |

Family position: the feature adds **two capability units** to idfkit (`idfkit.hvac`, `idfkit.graph`), which the
idfkit parity gate requires to land with parity-ledger and naming-register rows in idfkit-conformance (R-02). That
is recorded below as a justified cross-repository cost, not a violation.

## Project Structure

### Documentation (this feature)

```text
specs/001-model-knowledge-graph/
├── spec.md                         # Feature specification (clarified and reviewed 2026-11-11)
├── plan.md                         # This file (revision 2)
├── research.md                     # Phase 0: decisions R-01 to R-07, R-12 to R-25, R-31 to R-37
├── data-model.md                   # Phase 1: entities, fields, state transitions
├── quickstart.md                   # Phase 1: validation scenarios per user story
├── contracts/
│   ├── idfkit-api.md               # Upstream Python surface
│   ├── mcp-tools.md                # Agent-facing tools and resources
│   ├── node-link-json.md           # Versioned export format (Python only)
│   └── eval-harness.md             # Evaluation CLI, runner config, outputs
├── deferred-standards.md           # The deferred standards requirements, verbatim
├── deferred-standards-research.md  # The deferred standards decisions, verbatim
├── background/                     # Research reports, literature scan, prototype
├── checklists/
│   └── requirements.md             # Spec quality checklist
└── tasks.md                        # Phase 2 (/speckit-tasks, not created here)
```

### Source Code

Two repositories change. idfkit lands first. idfkit-mcp adopts the new level through its pinned dependency.

```text
idfkit/                                    # upstream (github.com/idfkit/idfkit)
├── src/idfkit/
│   ├── document.py                        # + revision counter, rename_node
│   ├── hvac/                              # NEW capability unit (parity ledger row)
│   │   ├── __init__.py
│   │   ├── types.py                       # ConnectionType, Fluid, ComponentCategory, NodeUse, LoopMembership,
│   │   │                                  #   FlowEdge, TopologyFinding, Coverage
│   │   ├── _node_fields.py                # GENERATED: (type, field) -> is fluid node
│   │   ├── _port_rules.py                 # GENERATED from eplusout.bnd, with provenance and reviewed overrides
│   │   ├── _version_caps.py               # GENERATED: (check, version) -> max severity (R-34)
│   │   ├── _categories.py                 # reviewed: object type -> ComponentCategory (R-36)
│   │   ├── topology.py                    # HVACTopology, EMS key links (R-35)
│   │   └── checks.py                      # T001–T004, T010, T011, T030, T090, T091
│   ├── simulation/
│   │   ├── linking.py                     # NEW: ObjectKey, Resolution, ResultIndex, diagnose
│   │   └── parsers/
│   │       ├── sql.py                     # + component_sizes, errors, zones, report_keys
│   │       └── err_catalog.py             # NEW: message kinds, patterns, cause families
│   ├── graph/                             # NEW capability unit (parity ledger row); no domain logic
│   │   ├── __init__.py
│   │   ├── types.py                       # NodeKind, EdgeKind, Layer, GraphNode, GraphEdge, Subgraph
│   │   ├── view.py                        # ModelGraph: per-layer adapters, bounded BFS, category filter
│   │   └── node_link.py                   # to_node_link, write_node_link, save_node_link
│   └── codegen/
│       ├── generate_node_fields.py        # NEW
│       ├── generate_port_rules.py         # NEW: runs ExampleFiles + test models, harvests eplusout.bnd
│       ├── generate_version_caps.py       # NEW: from the --corpus measurement (R-34)
│       └── port_rule_models/              # NEW: 10 minimal IDFs for types absent from ExampleFiles
├── agent_references/{templates,snippets}/ # + hvac-topology, model-graph; update result-parsing,
│                                          #   reference-tracking, hvac-loops
├── scripts/build_linking_fixtures.py      # NEW (needs EnergyPlus 26.2)
├── benchmarks/
│   ├── bench_hvac_topology.py             # NEW: build, checks, queries (R-21)
│   ├── bench_result_index.py              # NEW: index build, per-object query
│   ├── bench_graph.py                     # NEW: construction, neighbourhood, export
│   └── fixtures/HospitalLowEnergy.idf.gz  # NEW: reference model (0.24 MB compressed)
└── tests/
    ├── test_hvac_topology.py              # unit and injected faults
    ├── test_hvac_categories.py            # every node-bearing type categorised or listed (R-36)
    ├── test_hvac_coverage.py              # Coverage.uncovered kinds, EMS links (R-35)
    ├── test_hvac_corpus.py                # @integration: SC-001 on 26.2; SC-001a on 9.6 and 23.2 (R-34)
    ├── test_simulation_linking.py         # fixture-based; SC-004
    ├── test_err_catalog.py                # kinds and cause families
    ├── test_graph_view.py                 # layers, vocabulary, bounds, staleness, unknown kinds ignored
    ├── test_graph_node_link.py            # stdlib format checks; @nodelink: networkx loads it (R-24)
    ├── test_perf_budgets.py               # @perf: R-21 budgets with a 2× CI allowance, on 3.10 and 3.12
    └── fixtures/simulation/linked/        # trimmed (IDF, SQL, ERR) triples, ≤ 10 MB

idfkit-mcp/                                # this repository
├── src/idfkit_mcp/
│   ├── models.py                          # + Pydantic mirrors; QA flag and warning fields
│   ├── state.py                           # + simulation_model_hash, simulation_run_dir; session v2
│   └── tools/
│       ├── topology.py                    # NEW: trace_hvac, get_hvac_topology, rename_node
│       ├── results.py                     # NEW: get_object_results, diagnose_symptom
│       ├── graph.py                       # NEW: get_object_neighbourhood (no export)
│       ├── integrity.py                   # + hvac_topology check group
│       ├── simulation.py                  # + affected_objects, kind, link_coverage; record run revision and hash
│       ├── peak_loads.py                  # + ObjectKey on zone rows and flags
│       └── resources.py                   # + hvac/{loop}, simulation/objects/{type}/{name}
├── eval/                                  # NEW, excluded from the wheel
│   ├── __main__.py                        # run, compare, list-faults [--check-held-out]
│   ├── stats.py                           # paired bootstrap, gate verdict (R-32)
│   ├── faults/                            # 10 designed FaultType modules
│   ├── faults/held_out/                   # ≥ 5 held-out fault types, committed before slice 1's checks (R-33)
│   ├── tasks/                             # control, authoring and open-question task definitions (R-14)
│   ├── prompts.toml                       # modeller-style templates, linted (R-13)
│   ├── baseline.toml                      # pre-feature SHA and the idfkit level it pins (R-13)
│   ├── runners/claude_code.toml           # with optional disallowed_tools for ablations
│   ├── decisions/                         # per-slice decision records (FR-046)
│   └── reference_models.toml
├── docs/                                  # tool reference pages for every new or changed tool
└── tests/
    ├── test_topology_tools.py
    ├── test_results_tools.py
    ├── test_graph_tools.py
    ├── test_public_api_only.py            # AST: no private idfkit imports or attributes (FR-050)
    ├── test_session_persistence.py        # + v2 fields, v1 compatibility
    ├── test_tool_listing_budget.py        # SC-010 against the recorded base (R-12)
    ├── test_perf_tools.py                 # @perf: per-call server time and response size budgets
    └── test_eval_harness.py               # fake runner: prompt lint, held-out check, stats, no LLM

idfkit-developers/                         # idfkit's documentation site (github.com/idfkit/idfkit-developers)
└── docs/reference/                        # + hvac and graph pages; simulation updated.
                                           #   Pages embed idfkit's snippets, never their own copies (R-22)
```

**Structure Decision**: two existing projects, no new repository. Domain code goes in idfkit's existing layout
under the two new units and the extended `idfkit.simulation`. idfkit-mcp follows its one-module-per-tool-family
pattern under `tools/`. The evaluation harness sits at the idfkit-mcp root as development tooling, outside `src/`,
so hatchling never packages it.

## Delivery Order

The order follows the spec's priorities and the one hard dependency: idfkit before idfkit-mcp. Every slice from 1
on ends with an evaluation run over its story's tasks (FR-046, R-13).

| Slice | idfkit | idfkit-mcp | Gate to the next slice |
|---|---|---|---|
| 0 | `revision` and `_derived` cache slot, `SQLResult` readers, fixture builder and fixtures, **benchmark harness, reference model and `perf` gate** | Session v2 skeleton, `perf` protocol test harness, `test_public_api_only.py`, `test_tool_listing_budget.py` with the recorded base, **eval harness skeleton: `baseline.toml` at the pre-feature SHA, stats, prompt lint, held-out check**. **Held-out faults committed** by a maintainer not writing checks (R-33) | Fixtures committed; gates run in CI; held-out faults dated before any check |
| 1: US1 | `idfkit.hvac` (node fields; rules for all 257 node-bearing types generated from EnergyPlus's connection report, with provenance; categories; coverage with EMS; T010, T011, T030, T090, T091), 26.2 corpus test, **9.6 and 23.2 measurement and version caps**, parity rows | `trace_hvac`, `hvac_topology` integrity group | SC-001 and SC-001a green; topology budget confirmed by benchmark |
| 2: US2 | — | Designed topology faults, controls, authoring tasks and open questions; first full run: pre-feature baseline against slice 1, 3 repeats | First baseline/treatment comparison with intervals; decision record if no benefit (FR-046) |
| 3: US3 | `linking.py`, `err_catalog.py` (about 15 kinds) | `get_object_results`, `affected_objects`, peak-load object keys | SC-004 green on fixtures; slice run on results faults |
| 4: US4 + US7 | Memberships, `chain`, `rename_node`, T001–T004. **`idfkit.graph`** with the `model`, `topology` and `results` layers, category filter, node-link export, `nodelink` CI job, `model-graph` snippet and parity row | `get_hvac_topology`, `rename_node`, resource, **`get_object_neighbourhood`**; **ablation of `trace_hvac` and `get_object_results`** (R-31) | SC-003; export loads in networkx; neighbourhood ≤ 8 KB; SC-010 within cap after the ablation's removals; SC-014 standalone script complete |
| 5: US6 | `diagnose` with evidence strength, cause families and `no_strong_candidate`; catalogue to about 40 kinds | `diagnose_symptom`; out-of-catalogue diagnosis variants | Built only if the SC-009 gate passes on the slices 2–4 runs; merges only with SC-009a green (R-37) |

Each slice in idfkit ships with its agent-reference template and snippet, re-baked, a CHANGELOG entry, and its
idfkit-developers reference page (FR-052): User Story 7 is delivered layer by layer, not in a slice of its own.
`idfkit.graph` lands in slice 4, once both layers exist, so its vocabulary is exercised by real layers before it is
released. Each slice in idfkit-mcp ships with docs pages, a token-audit figure and its evaluation run. **Every
slice's pull request includes the benchmark table before and after, and none merges with a budget failing**
(FR-009).

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| Two new idfkit capability units, each needing a parity-ledger and naming-register row in idfkit-conformance | The parity gate requires every new public subpackage to be declared. Topology is a genuinely new capability, and the combined view must not live in one layer | Hiding topology inside `references` would misplace node semantics. A method on `IDFDocument` would pull every layer into `document.py` (R-23) |
| Session file v1 → v2 | FR-026 requires staleness across restarts | Not persisting the run hash would report stale results as fresh after a restart |
| Two new private slots on `IDFDocument` (`_revision`, `_derived`) | Performance (R-06, R-21). The document has no `__weakref__`, so derived views cannot be cached externally without leaks or id reuse | Recomputing per call wastes about 5 ms per question, and the results index would re-read SQL every time |
| A `perf` benchmark gate in both repositories | FR-009 makes the budgets requirements, and a requirement needs a check | Reviewing timings by hand misses regressions. `pytest-benchmark` would add a dependency (R-01) |
| A third repository touched, idfkit-developers | FR-052 requires reference pages, and idfkit's human docs live there | Duplicating the pages in idfkit would recreate the drift that moving the docs out removed |
| A CI job that installs networkx ad hoc (`uv run --with`) | FR-057 requires proof that networkx loads the export unchanged | Declaring networkx would add a third-party package to idfkit's lock file against R-01 |
| An AST test in idfkit-mcp that forbids private idfkit names | FR-050 requires the server to use only the public API | Review alone misses it. Today's code already passes, so the test only guards against regressions (R-22) |
| `eval/` directory with its own CLI, statistics and git-dated held-out faults | User Story 2 is P1, and FR-040a to FR-042c, FR-046 require a valid with/without comparison | Putting it in idfkit would invert the dependency. One run per task, or faults written by the check authors, would gate later work on noise or on the checks themselves (R-32, R-33) |
| About 600 agent runs per full evaluation, 150–250 per slice | FR-042a requires repeats and intervals wide enough to see the SC-009 effects | Fewer runs give intervals of about ±11 points per type, wider than the effects the gate looks for (R-32). The cost is accepted in the spec's Assumptions |
| Two EnergyPlus installations (9.6, 23.2) on the maintainer's machine for corpus measurement | FR-013a requires measured false findings on earlier versions | Assuming older versions behave like 26.2 is the accepted risk the review removed. Measuring every version would cost seventeen corpora for little extra signal (R-34) |
| Two conditional tools and an ablation run in slice 4 | FR-059 requires a measured saving for a targeted tool that overlaps the neighbourhood tool | Shipping them unconditionally risks the SC-010 cap and tool confusion. Dropping them before measuring might remove a real saving (R-31) |
