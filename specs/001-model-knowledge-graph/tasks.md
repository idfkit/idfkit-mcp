---

description: "Task list for the model knowledge graph feature (topology, results, combined view, evaluation)"
---

# Tasks: Model Knowledge Graph for Agents

**Input**: Design documents from `specs/001-model-knowledge-graph/` (plan.md revision 2, spec.md, research.md,
data-model.md, contracts/, quickstart.md)

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/idfkit-api.md, contracts/mcp-tools.md,
contracts/node-link-json.md, contracts/eval-harness.md

**Tests**: Requested. The spec requires protocol-boundary tests for every tool (FR-045, Constitution VII), a
public-API test (FR-050), coverage tests for rules and categories (FR-010a, FR-016a), corpus tests (SC-001,
SC-001a), linking tests on fixtures (SC-004), benchmark gates (FR-009) and harness tests with a fake runner. Test
tasks are therefore included in every phase. The evaluation itself is evidence, not a test (FR-045).

**Organization**: Tasks are grouped by user story, in the plan's delivery order (slices 0 to 5). User Story 5 is
deferred ([deferred-standards.md](deferred-standards.md)) and has no tasks. User Story 7 is delivered layer by
layer: each layer's snippet and reference page ship with that layer's story, and the US7 phase adds the combined
view, the export and the neighbourhood tool.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: The user story the task belongs to (US1, US2, US3, US4, US6, US7)
- Every description names the exact file it touches

## Path Conventions

Four sibling repositories are touched. Every path starts with its repository:

- `idfkit/` — upstream library (github.com/idfkit/idfkit). **Lands first** in every slice.
- `idfkit-mcp/` — this repository.
- `idfkit-conformance/` — parity ledger and naming register (`governance/parity.toml`, naming register file).
- `idfkit-developers/` — idfkit's human documentation site.

Code rules that apply to every task without being repeated: `from __future__ import annotations` at the top of every
new module; pyright strict with no `# type: ignore`; 120-character lines; standard library only (R-01, no new
third-party dependency in either repository); public dataclasses are `@dataclass(frozen=True, slots=True)`;
internal records are tuples (R-21, decision 2); identity is `ObjectKey(object_type, name)` compared with
`name.upper()`, responses keep the model's spelling. Never hand-edit idfkit's baked agent references; edit
`agent_references/templates/` and `agent_references/snippets/`, then run `uv run python -m idfkit.codegen.bake_references`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Branches, markers and packaging switches that every later task assumes.

- [X] T001 Create the idfkit feature branch from `main` and run `uv sync` in `idfkit/`; confirm `make check && make test` pass before any change (record the timing of `make test` in the PR description for comparison)
- [X] T002 [P] Register pytest markers `perf` ("performance budget gate, R-21") and `nodelink` ("networkx loads the node-link export; run with `uv run --with \"networkx>=3.6\"`") in `[tool.pytest.ini_options].markers` of `idfkit/pyproject.toml`, and deselect both in the default `addopts` (`-m "not integration and not perf and not nodelink"` or the existing equivalent)
- [X] T003 [P] Register the pytest marker `perf` in `idfkit-mcp/pyproject.toml` and deselect it from the default run, mirroring T002
- [X] T004 [P] Exclude `eval/` from the wheel and sdist in the hatch build configuration of `idfkit-mcp/pyproject.toml` (`[tool.hatch.build.targets.wheel]` / `sdist` `exclude`), and add `eval` to ruff and pyright `include` paths so the harness is linted and type-checked under strict mode
- [X] T005 [P] Add `eval/runs/*/transcripts/` and `eval/runs/*/outcomes.jsonl` to `idfkit-mcp/.gitignore` (run summaries `run.json` and `summary.md`, and everything under `eval/decisions/`, stay committable)
- [X] T006 [P] Add an `--corpus VERSION=PATH` repeatable pytest option (stored as `dict[str, Path]`, no environment variable) in `idfkit/tests/conftest.py`, used later by `tests/test_hvac_corpus.py` (R-34)

---

## Phase 2: Foundational (Slice 0 — Blocking Prerequisites)

**Purpose**: Revision counter and cache slot, SQL readers, fixtures, shared identity types, benchmark gates,
session v2, consumer-side API guard, tool-listing gate, the evaluation skeleton and the held-out faults.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. **T034 must be committed before the
first commit that adds `idfkit/src/idfkit/hvac/checks.py`** (R-33); the held-out check (T031) verifies it from git.

### idfkit: document revision and derived-view cache (R-06, R-21)

- [X] T007 Add private slots `_revision: int` (starts at 0) and `_derived: dict[str, tuple[int, object]]` to `IDFDocument.__slots__`, and a public read-only `revision` property ("Monotonic; bumped by add, removeidfobject, field assignment, rename, rename_node") in `idfkit/src/idfkit/document.py`
- [X] T008 Increment `_revision` in `IDFDocument.add`, `IDFDocument.removeidfobject`, `notify_name_change` and `notify_reference_change` in `idfkit/src/idfkit/document.py`, and add a direct bump for assignments to non-reference fields in the field-setter path of `idfkit/src/idfkit/objects.py` (every mutation path must bump exactly once per mutation)
- [X] T009 Implement a private helper `get_or_build(doc, view_name: str, build: Callable[[], T]) -> T` that returns the cached view while its stored revision equals `doc.revision` and otherwise rebuilds and stores `(doc.revision, view)` in `doc._derived`, in `idfkit/src/idfkit/_derived.py` (no global registry; the cache dies with the document)
- [X] T010 [P] Write tests that every mutation path bumps `revision`, that reads do not, and that `get_or_build` rebuilds only after a revision change, in `idfkit/tests/test_document_revision.py`

### idfkit: shared identity and coverage types (data-model "Shared", R-35)

- [X] T011 Create `ObjectKey(object_type: str, name: str)` with `__eq__`/`__hash__` on `(object_type.upper(), name.upper())` and pseudo-types `"Node"`, `"Aggregate"`, `"Unresolved"`; `UncoveredPart(kind: Literal["hvac_template", "ems_program", "unclassified_type", "unlinked_result"], count: int, examples: tuple[ObjectKey, ...], reason: str)` with `examples` "At most 3"; and `Coverage(partial: bool, uncovered: tuple[UncoveredPart, ...], resolved: int | None, unresolved: int | None)` where `partial` is "True when `uncovered` is not empty", in `idfkit/src/idfkit/_graph_common.py` (private module; re-exported publicly by `idfkit.hvac` in T040 and `idfkit.simulation` in T083)
- [X] T012 [P] Write tests for `ObjectKey` case-insensitive equality and hashing, `Coverage.partial` consistency and the 3-example cap, in `idfkit/tests/test_graph_common.py`

### idfkit: SQL readers and linking fixtures (R-07, R-19, FR-044)

- [X] T013 Add frozen dataclasses `ComponentSize`, `SQLErrorRow` (severity, message, count), `ZoneRow` (name, multiplier, list multiplier) and readers `SQLResult.component_sizes()`, `errors()`, `zones()` and `report_keys()` (ReportDataDictionary keys only, never `ReportData`), opening the file read-only (`mode=ro`, `PRAGMA query_only`) with one query per table, in `idfkit/src/idfkit/simulation/parsers/sql.py`
- [X] T014 Write `scripts/build_linking_fixtures.py` (needs EnergyPlus 26.2 via `ENERGYPLUS_DIR`): run about 10 reference models with `Output:SQLite SimpleAndTabular`, AllSummary and a small `Output:Variable` set with `*` keys; trim each SQL to the tables linking reads, `VACUUM`; copy `(IDF, SQL, ERR)` triples into `idfkit/tests/fixtures/simulation/linked/`; fail if the directory exceeds 10 MB, in `idfkit/scripts/build_linking_fixtures.py`
- [ ] T015 Run `T014` on a machine with EnergyPlus 26.2 and commit the triples (including `5ZoneAirCooled` and HospitalLowEnergy if within budget) under `idfkit/tests/fixtures/simulation/linked/`
- [X] T016 [P] Write fixture-based tests for the four new readers (row counts, multipliers carried, `report_keys` never touches `ReportData`) in `idfkit/tests/test_sql_readers.py`

### idfkit: benchmark harness and perf gate (R-21, FR-009)

- [X] T017 [P] Vendor the reference model, gzip-compressed, as `idfkit/benchmarks/fixtures/HospitalLowEnergy.idf.gz` (from the 26.2 ExampleFiles)
- [X] T018 [P] Implement a stdlib timing helper (`best_of(fn, n) -> float` with `time.perf_counter`, plus a `tracemalloc` peak helper) and a loader for the vendored reference model in `idfkit/benchmarks/_timing.py`
- [X] T019 Create the `perf`-marked gate module asserting, with a 2× CI allowance, the `load_idf` baseline time of the reference model (later tasks append budgets to it), in `idfkit/tests/test_perf_budgets.py`
- [X] T020 Add CI jobs `perf` (Python 3.10 and 3.12, `uv run pytest -m perf`) and `nodelink` (`uv run --with "networkx>=3.6" pytest -m nodelink`; networkx is never declared in `pyproject.toml` or the lock file) to `idfkit/.github/workflows/main.yml`

### idfkit-mcp: session v2, shared mirrors, consumer guards

- [ ] T021 Move the session file from `"version": 1` to `2` in `idfkit-mcp/src/idfkit_mcp/state.py`: add `simulation_model_hash: str | None` ("SHA-256 of the IDF text written for the session's last run") and `simulation_run_dir: str | None` to `ServerState`, write both, load version-1 files with both `None`, and report restore failures as today (R-15; HTTP sessions keep persistence off)
- [ ] T022 [P] Extend `idfkit-mcp/tests/test_session_persistence.py` with v2 round-trip, v1 compatibility (both fields `None`) and an unknown-version restore failure
- [ ] T023 [P] Add Pydantic mirrors `ObjectKey`, `UncoveredPart` and `Coverage` (field names identical to T011; shared sub-models so each appears once in `$defs`, field descriptions kept out of the schema) to `idfkit-mcp/src/idfkit_mcp/models.py`
- [ ] T024 [P] Write the AST test that parses every module under `idfkit-mcp/src/idfkit_mcp/` and fails on an import from an `idfkit` module path with an underscore segment, an imported idfkit name starting with `_`, or attribute access to an underscore attribute of an idfkit object, in `idfkit-mcp/tests/test_public_api_only.py` (FR-050, R-22; must start green)
- [ ] T025 Extend `idfkit-mcp/scripts/token_audit.py` to count the full `tools/list` response including output schemas at 4 characters per token and to print JSON (`tools`, `tokens`); record the base measured at `81d3cd6` (39 tools, about 15,300 tokens) in `idfkit-mcp/tests/fixtures/tool_listing_base.json`, and write `idfkit-mcp/tests/test_tool_listing_budget.py` asserting the current listing is ≤ base × 1.15 (SC-010, R-12)
- [ ] T026 [P] Create the `perf` protocol test harness: a fixture that loads the vendored reference model (copy `HospitalLowEnergy.idf.gz` into `idfkit-mcp/tests/fixtures/`) through FastMCP and a helper asserting server time and serialised response size (≤ 8 KB) per call, in `idfkit-mcp/tests/test_perf_tools.py`

### idfkit-mcp: evaluation skeleton (R-13, R-32, R-33)

- [ ] T027 Create the harness data model as dataclasses mirroring data-model.md "Evaluation" exactly — `FaultType`, `TaskSpec`, `EvaluationTask`, `TaskOutcome` (`condition: "baseline" | "treatment" | "ablation"`, `repeat` "0-based", `verified_by: "check" | "simulation" | "answer_key" | "skipped"`, `skip_reason` "Required when skipped"), `EvaluationRun` (`repeats` "At least 3", `baseline_kind: "pre_feature" | "other"`), `Comparison`, `GateVerdict` — in `idfkit-mcp/eval/model.py`
- [ ] T028 Implement the CLI with subcommands `run`, `compare` (one or two run dirs) and `list-faults [--check-held-out]`, exit codes 0 (completed), 2 (bad configuration or invalid held-out fault), 3 (no runnable tasks), and fault/task discovery from `eval/faults/*.py`, `eval/faults/held_out/*.py` (`FAULT: FaultType`), `eval/tasks/controls.toml`, `eval/tasks/authoring/*.py` and `eval/tasks/questions/*.py` (`TASK: TaskSpec`), in `idfkit-mcp/eval/__main__.py` and `idfkit-mcp/eval/registry.py`
- [ ] T029 [P] Implement the paired percentile bootstrap (per-task treatment − baseline on repeat means; 10,000 resamples; seed recorded), `descriptive_only` for fault-type scopes whose interval includes zero, the SC-008 spread (range of overall fix rate across repeat passes) and the `GateVerdict` (20-point fix-rate gain or ≥ 30% fewer calls at no lower fix rate, CI excludes zero, held-out direction, no more unwanted changes, no more false fixes; `valid` false for `baseline_kind = "other"` or ablations), using only `random` and `statistics`, in `idfkit-mcp/eval/stats.py`
- [ ] T030 [P] Implement the prompt lint: a rendered prompt fails if it contains the injected object's name, the field name, the fault id, or the words "fault", "injected" or "bug" (case-insensitive), in `idfkit-mcp/eval/lint.py`
- [ ] T031 [P] Implement the held-out check: for each file under `eval/faults/held_out/`, `git log --diff-filter=A --format=%H%x09%cI` gives its first commit; compare with the first commit adding `src/idfkit/hvac/checks.py` in the idfkit checkout at the level the treatment pins; mark later ones `held_out_invalid`, in `idfkit-mcp/eval/held_out.py`
- [ ] T032 [P] Write `idfkit-mcp/eval/baseline.toml` (`kind = "pre_feature"`, `idfkit_mcp_sha = "81d3cd6"`, `idfkit = "idfkit==<level pinned at 81d3cd6>"`), `idfkit-mcp/eval/runners/claude_code.toml` (fields exactly as contracts/eval-harness.md "Runner configuration", `disallowed_tools = []`), `idfkit-mcp/eval/prompts.toml` (modeller-style templates, e.g. "The simulation of this model fails. Make it run.", "Zone {zone} is too cold in winter. Find out why and fix it.") and `idfkit-mcp/eval/reference_models.toml` (≥ 20 entries `{id, file, version = "26.2", tags}` from the 26.2 ExampleFiles covering VAV reheat, chilled and hot water plant, packaged units, zone lists and HVACTemplate)
- [ ] T033 [P] Write harness tests with a fake runner and no LLM: prompt lint positives and negatives, held-out check against a temporary git repo, bootstrap determinism with a fixed seed, gate verdict clauses, exit codes, in `idfkit-mcp/tests/test_eval_harness.py`
- [ ] T034 **HUMAN (maintainer who writes no connection checks or result linking for this feature):** write and commit at least 5 held-out fault types, one module each exposing `FAULT: FaultType` with `held_out = True`, `intended_tools = []`, a symptom-only `prompt_template`, `inject` and `verify`, sourced per R-33 (agent transcripts, Zhang/Chen/Ford 2024 wrong-reference failures, OSTI agentic-workflow debugging failures, idfkit/idfkit-mcp issues), under `idfkit-mcp/eval/faults/held_out/`. Must be committed before T047 lands

**Checkpoint**: fixtures committed; `perf`, `nodelink`, public-API and listing-budget gates run in CI; held-out
faults dated before any check. User story work can start.

---

## Phase 3: User Story 1 — Catch HVAC connection faults before simulating (Priority: P1) 🎯 MVP

**Goal**: `idfkit.hvac` derives every node use with an EnergyPlus-verified role, runs T010, T011, T030, T090 and
T091 offline, and idfkit-mcp exposes them through `check_model_integrity` and `trace_hvac`.

**Independent Test**: Load `5ZoneAirCooled.idf`, set `Coil:Cooling:Water "Main Cooling Coil 1"`
`air_outlet_node_name` to `TYPO NODE`, call `check_model_integrity`: expect `[T010]` naming branch, coil, field,
expected and actual node, plus a `T030` warning for `TYPO NODE`. The unmodified model reports no `hvac_topology`
error. A model with `EnergyManagementSystem:Program` reports `coverage.partial` with kind `ems_program`.

### Governance for the new unit

- [ ] T035 [US1] Add the `idfkit.hvac` capability-unit row (Python-only) to `idfkit-conformance/governance/parity.toml` and its public names (contracts/idfkit-api.md, `idfkit.hvac` section, plus `IDFDocument.revision`) to the naming register in `idfkit-conformance/governance/`, cut a governance tag, and bump the governance tag pinned in `idfkit/pyproject.toml` (paired change, R-02)

### Tests for User Story 1 (write first; they fail until implementation lands)

- [ ] T036 [P] [US1] Write unit and injected-fault tests: outlet typo on `5ZoneAirCooled` → T010 with branch, component, field, expected, actual; consecutive branch components disconnected → T011; one-sided node without boundary → T030 warning; outdoor-air inlet, relief outlet, exhaust fan and air-cooled condenser boundaries are not reported; `HVACTemplate:*` present → T091 info and no missing-node faults; unknown type → T090 info; `node_or_nodelist` resolves to the `NodeList` first; unmodified model → no error, each warning names its rule, in `idfkit/tests/test_hvac_topology.py`
- [ ] T037 [P] [US1] Write the coverage test that fails if any node-bearing type in the 26.2 schema lacks a port rule, and that every rule carries provenance `eplus_examples`, `eplus_test_model` or `hand_written`, in `idfkit/tests/test_hvac_rules.py`
- [ ] T038 [P] [US1] Write the category test listing every node-bearing type mapped to `other`, asserting categories are derived from type alone (two objects with category-suggesting names but type `Branch` stay uncategorised), in `idfkit/tests/test_hvac_categories.py`
- [ ] T039 [P] [US1] Write coverage tests: `EnergyManagementSystem:Program`/`:Subroutine` → `uncovered` kind `ems_program`; EMS sensor key and actuator component names resolved to objects become control `NodeUse`s with `rule="ems_key"`, unresolved ones listed; templates → `hvac_template`; program text is never searched, in `idfkit/tests/test_hvac_coverage.py`

### Implementation in idfkit

- [ ] T040 [US1] Create the public types in `idfkit/src/idfkit/hvac/types.py`: `ConnectionType` (exactly `Inlet`, `Outlet`, `Internal`, `ZoneNode`, `Sensor`, `Actuator`, `OutsideAir`, `ReliefAir`, `ZoneInlet`, `ZoneReturn`, `ZoneExhaust`, `Setpoint`), `Fluid` (`Air`, `Water`, `Steam`, `Refrigerant`, `Unknown`), `ComponentCategory` (`heating_coil`, `cooling_coil`, `fan`, `pump`, `terminal_unit`, `chiller`, `boiler`, `heat_rejection`, `humidifier`, `heat_exchanger`, `zone_equipment`, `unitary`, `outdoor_air`, `setpoint_manager`, `controller`, `other`), `NodeUse`, `LoopMembership`, `FlowEdge` (`kind: "component" | "branch_junction" | "zone"`), `TopologyFinding` (`severity: "error" | "warning" | "info"` effective after cap, `capped_from: "error" | None`, `cap_reason`, `objects` "At least one, or `node` set", `provenance` "The weakest provenance among the rules the finding relied on"), `NodeRenameResult`, all fields as in data-model.md; and `idfkit/src/idfkit/hvac/__init__.py` exporting them plus `ObjectKey`, `Coverage`, `UncoveredPart` from `_graph_common` in `__all__`
- [ ] T041 [US1] Write the codegen `idfkit/src/idfkit/codegen/generate_node_fields.py`: union of the 26.2 schema's `"data_type": "node"` tags with the field-name rule `node(_or_nodelist)?_names?$` applied to every bundled schema, excluding electric-circuit, AirflowNetwork and RoomAir nodes; write the frozen table `idfkit/src/idfkit/hvac/_node_fields.py`; add a `check-node-fields` target that regenerates and diffs, wired into `check` in `idfkit/Makefile`
- [ ] T042 [P] [US1] Write the 10 minimal test models, one per type absent from the example files (`Generator:FuelCell:StackCooler`, `HeatPump:AirToWater`, `PlantEquipmentOperation:OutdoorDewpointDifference`, `SetpointManager:FollowSystemNodeTemperature`, `SetpointManager:MultiZone:Cooling:Average`, `SetpointManager:MultiZone:Heating:Average`, `ThermalStorage:PCM`, `Lights:Instance`, `SpaceHVAC:ZoneReturnMixer`, `ThermalStorage:HotWater:Stratified`), each running design days with `Output:Diagnostics` so EnergyPlus writes `eplusout.bnd`, under `idfkit/src/idfkit/codegen/port_rule_models/`
- [ ] T043 [US1] Write the codegen `idfkit/src/idfkit/codegen/generate_port_rules.py` in the six R-04 steps: run example models and test models; parse "Non-Parent Node Connection" and "Parent Node Connection" rows of `eplusout.bnd`; map rows back to fields by node value; merge across files, queuing value-dependent disagreements as predicate candidates and same-node-in-two-fields as ambiguous; cross-check against field naming and **fail generation** on any unreviewed disagreement; write `PortRule` rows (`object_type`, `field` with `group.field` for extensible sub-fields, `connection`, `stream` "≥ 1", `fluid`, `is_parent`, `accepts_nodelist`, `when`, `provenance`). Reviewed resolutions live in `idfkit/src/idfkit/codegen/port_rule_overrides.toml`
- [ ] T044 [US1] Run T043 with EnergyPlus 26.2, review every queued disagreement into `port_rule_overrides.toml` (including the `AirTerminal:DualDuct:VAV:OutdoorAir` outdoor-air inlet case and the condenser `("condenser_type", "AirCooled")` predicate), and commit the generated `idfkit/src/idfkit/hvac/_port_rules.py` with provenance on every row; any type whose test model cannot run gets a `hand_written` rule
- [ ] T045 [P] [US1] Write the reviewed category table (prefix and exact-type mapping per R-36, e.g. `Coil:Heating:*` → `heating_coil`, `AirTerminal:*` and `ZoneHVAC:AirDistributionUnit` → `terminal_unit`, `ZoneHVAC:*` otherwise → `zone_equipment`) and `category_of(object_type: str) -> ComponentCategory` (unknown → `other`, never from names) in `idfkit/src/idfkit/hvac/_categories.py`
- [ ] T046 [US1] Implement `HVACTopology` in `idfkit/src/idfkit/hvac/topology.py` per data-model "Internal representation": module-level per-type plans cached by schema version; visit only node-bearing collections; intern nodes (`node_id`, `node_name`), dense object ids, `uses` tuples `(object id, field-plan index, connection code, stream)`, `out_adj`/`in_adj`; resolve `node_or_nodelist` to `NodeList` first; parent uses add no flow edges; EMS sensor/actuator key resolution as control uses with `rule="ems_key"`; `from_document(doc)` cached through `_derived.get_or_build(doc, "hvac", …)`; public methods `nodes`, `uses`, `producers`, `consumers`, `controls`, `ports`, `upstream`/`downstream` (iterative BFS with `hops` and `categories` filter that still walks through other components) and `coverage`. `memberships`, `loops`, `chain` and `zones_served` are added in US4 (T099)
- [ ] T047 [US1] Implement checks T010, T011, T030, T090 and T091 in one pass per check family over the integer structures, initial severities per data-model (T010/T011 `error` once T050 is green, others as listed), `hand_written` provenance never above `warning`, and `check_topology(doc)` wrapper, in `idfkit/src/idfkit/hvac/checks.py`; expose `HVACTopology.check()`
- [ ] T048 [US1] Apply the per-version severity cap: load `_version_caps.py` (initially an empty table), take the nearest measured version at or below the model's (older than 9.6.0 → 9.6.0; 26.2 uncapped), set `severity = min(qualified, cap)` and fill `capped_from`/`cap_reason`, in `idfkit/src/idfkit/hvac/checks.py` and `idfkit/src/idfkit/hvac/_version_caps.py`
- [ ] T049 [US1] Write the `@integration` corpus test: SC-001 loads every 26.2 ExampleFile from `$ENERGYPLUS_DIR/ExampleFiles` and asserts zero error-severity findings; with `--corpus VERSION=PATH` (T006) it records models, findings and false findings per version and check, in `idfkit/tests/test_hvac_corpus.py`
- [ ] T050 [US1] Run T049 on 26.2 (promote T010/T011 to error only if green; record the promotion in `idfkit/CHANGELOG.md`), then on 9.6.0 and 23.2.0 ExampleFiles; write `idfkit/src/idfkit/codegen/generate_version_caps.py` that turns the measurement into `VersionCap` rows (`max_severity: "warning" | "info"`, `models`, `false_findings`) and commit the regenerated `idfkit/src/idfkit/hvac/_version_caps.py` (SC-001a)
- [ ] T051 [P] [US1] Write `idfkit/benchmarks/bench_hvac_topology.py` (build plus checks, one query) printing a before/after table, and append to `idfkit/tests/test_perf_budgets.py`: first `from_document` + `check()` ≤ 50 ms and ≤ 25% of `load_idf`; cached `from_document` ≤ 0.1 ms; any single query ≤ 5 ms; extra memory ≤ 10 MB (2× CI allowance)
- [ ] T052 [P] [US1] Write the agent reference `idfkit/agent_references/templates/hvac-topology.md` and runnable snippet `idfkit/agent_references/snippets/hvac-topology.py` (sections: build view, trace a node, list findings, read coverage, category filter); replace the "update both ends by hand" node guidance in `idfkit/agent_references/templates/hvac-loops.md`; add the topic row to `idfkit/agent_references/templates/SKILL.md`; re-bake with `uv run python -m idfkit.codegen.bake_references`
- [ ] T053 [P] [US1] Add `[Unreleased]` entries (Added: `idfkit.hvac`, `IDFDocument.revision`, SQL readers; the published false-finding rates per version and check) to `idfkit/CHANGELOG.md`
- [ ] T054 [P] [US1] Add the `hvac` reference page embedding the `hvac-topology` snippets (never copies) to `idfkit-developers/docs/reference/hvac.md` and its nav entry
- [ ] T055 [US1] Run `make check && make test` in `idfkit/`, open the slice-1 idfkit PR with the benchmark table, and after release bump the exact `idfkit==X` pin in `idfkit-mcp/pyproject.toml` and `idfkit-mcp/uv.lock` through the bump procedure (no register change, R-20)

### Implementation in idfkit-mcp

- [ ] T056 [P] [US1] Add Pydantic mirrors `NodeUse`, `LoopMembership`, `FlowEdge`, `TopologyFinding` and `HVACTrace` (fields as data-model.md `HVACTrace`; component start carries `category`) to `idfkit-mcp/src/idfkit_mcp/models.py`, reusing the shared sub-models from T023
- [ ] T057 [US1] Add the `hvac_topology` check group to `idfkit-mcp/src/idfkit_mcp/tools/integrity.py`: map each `TopologyFinding` to `IntegrityIssue` with `category="hvac_topology"`, `object_type`/`object_name` from the first object, message prefixed `[T0xx]`; group findings beyond 50 by code with counts; change no existing field
- [ ] T058 [US1] Implement `trace_hvac(object_type, name, hops=2, categories=None)` (`_READ_ONLY`; `hops` 0–10; `object_type="Node"` for a node start; case-insensitive match) calling only public `idfkit.hvac`, returning `HVACTrace` with `memberships=[]` until T107; errors: no model loaded, node or object not found (list closest names, never pick one), object without node fields (suggest `get_object_neighbourhood`), unknown category (list the vocabulary); description names its nearest neighbour per contracts/mcp-tools.md, in `idfkit-mcp/src/idfkit_mcp/tools/topology.py`, registered in `idfkit-mcp/src/idfkit_mcp/server.py`
- [ ] T059 [P] [US1] Write protocol tests through FastMCP: the typo scenario through `check_model_integrity` and `trace_hvac`, unmodified model clean, EMS `coverage`, every error condition, in `idfkit-mcp/tests/test_topology_tools.py` and `idfkit-mcp/tests/test_integrity_tool.py`
- [ ] T060 [P] [US1] Add `perf` cases: `trace_hvac` ≤ 50 ms first call after load, ≤ 10 ms cached, ≤ 8 KB; `check_model_integrity` with the group ≤ 60 ms and ≤ 8 KB, in `idfkit-mcp/tests/test_perf_tools.py`
- [ ] T061 [P] [US1] Document `trace_hvac` in a new `idfkit-mcp/docs/tools/hvac-topology.md` (added to `idfkit-mcp/mkdocs.yml` nav) and the `hvac_topology` group on the page that documents `check_model_integrity` in `idfkit-mcp/docs/tools/validation.md`
- [ ] T062 [US1] Run `scripts/token_audit.py`, state the listing before and after in the PR, keep `test_tool_listing_budget.py` green, and add `[Unreleased]` entries to `idfkit-mcp/CHANGELOG.md`

**Checkpoint**: SC-001 and SC-001a green; topology budget confirmed by benchmark; US1 independently testable.

---

## Phase 4: User Story 2 — Measure whether the graph helps agents (Priority: P1)

**Goal**: A repeatable, paired evaluation with baseline at `81d3cd6`, 10 designed faults, held-out faults,
controls, authoring tasks and open questions, three repeats, bootstrap intervals and a gate verdict.

**Independent Test**: `uv run python -m eval run --faults all --repeat 3 --baseline-config eval/baseline.toml
--treatment "uv run idfkit-mcp" --runner eval/runners/claude_code.toml --out eval/runs/<id>` then `eval compare`:
`summary.md` holds paired differences with 95% intervals overall, per layer and per fault type, a separate
held-out table, the SC-008 spread and the SC-009 verdict; without EnergyPlus, results tasks are skipped, not failed.

### Tests for User Story 2

- [ ] T063 [P] [US2] Extend `idfkit-mcp/tests/test_eval_harness.py` with an end-to-end fake-runner run (canned stream-JSON transcripts): outcomes recorded per task × condition × repeat, skip reasons when EnergyPlus is absent (FR-043), unwanted-change diff, false fix on controls, `intended_tool_used` attribution, `compare` with two runs producing a slice delta, every rendered prompt passing the lint

### Implementation

- [ ] T064 [US2] Implement the runner: render `{prompt}` and a per-condition `{mcp_config}` file, append `disallowed_flag` + `disallowed_tools` when non-empty, enforce `max_turns`, capture raw output to `transcripts/`, in `idfkit-mcp/eval/runner.py`
- [ ] T065 [P] [US2] Implement the `claude_stream_json` parser extracting tool calls in order, response tokens consumed and the new tools used, in `idfkit-mcp/eval/parsers/claude_stream_json.py`
- [ ] T066 [US2] Implement condition building: baseline from a `git worktree` of `idfkit_mcp_sha` run with `uv run --with` the pinned idfkit; `--baseline "<command>"` alternative recorded as `baseline_kind = "other"`; treatment from `--treatment`, in `idfkit-mcp/eval/conditions.py`
- [ ] T067 [P] [US2] Implement unwanted-change detection (diff final vs starting model outside the task's `scope`) and control-task false-fix detection (any model change or any reported fault), in `idfkit-mcp/eval/diff.py`
- [ ] T068 [P] [US2] Write the 6 designed topology faults, each a module exposing `FAULT: FaultType` with `layer="topology"`, `applies_to` tags, symptom-only template, `intended_tools`, `inject` filling `scope`, and `verify`: `outlet_node_typo.py`, `swapped_inlet_outlet.py`, `branch_missing_from_list.py`, `setpoint_on_unused_node.py`, `terminal_outlet_not_zone_inlet.py`, `water_coil_wrong_plant_side.py` under `idfkit-mcp/eval/faults/`
- [ ] T069 [P] [US2] Write the 4 designed results faults (`needs_energyplus = True`): `undersized_reheat_coil.py`, `wrong_heating_setpoint_schedule.py`, `uninsulated_exterior_wall.py`, `packaged_unit_availability_off.py` under `idfkit-mcp/eval/faults/`
- [ ] T070 [P] [US2] Write control tasks, at least one per five fault tasks, on unmodified reference models with the same prompt templates, in `idfkit-mcp/eval/tasks/controls.toml`
- [ ] T071 [P] [US2] Write the 4 authoring tasks (success: no error finding from the connection check and the model simulates): `add_reheat_coil.py`, `add_parallel_chiller.py`, `add_vav_zone.py`, `cv_to_vav_fan.py` under `idfkit-mcp/eval/tasks/authoring/`
- [ ] T072 [P] [US2] Write the 6 open questions with `answer_key(doc)` computed by idfkit from the unmodified model (e.g. "which plant loop serves the reheat coil of zone 3?", "which zones served by this air loop had more than 300 unmet heating hours?"), keys committed alongside, under `idfkit-mcp/eval/tasks/questions/`
- [ ] T073 [US2] Wire `run`: held-out check and prompt lint first (exit 2 on failure), same task list and order for both conditions, `--repeat` (default 3), each fault type on every applicable model capped at 8, write `run.json`, `outcomes.jsonl`, `transcripts/`, in `idfkit-mcp/eval/__main__.py`
- [ ] T074 [US2] Write `summary.md` generation: paired differences of fix rate, median tool calls and median tokens with 95% intervals overall/per layer/per fault type, descriptive rows marked, held-out table, control false-fix rates, authoring success, question accuracy, SC-008 spread, SC-010a share per new tool, SC-009 verdict per layer with each clause, in `idfkit-mcp/eval/report.py`
- [ ] T075 [US2] **HUMAN (maintainer, needs EnergyPlus 26.2 and runner credentials):** run the first full evaluation (pre-feature baseline vs slice 1, 3 repeats), commit `run.json` and `summary.md` under `idfkit-mcp/eval/runs/<run_id>/`, and if no SC-009 measure shows benefit, write `idfkit-mcp/eval/decisions/slice-2.md` (maintainer, decision continue/change/stop, reason) before US3 starts (FR-046)

**Checkpoint**: first baseline/treatment comparison with intervals exists; decision record if no benefit.

---

## Phase 5: User Story 3 — Act on simulation results through the objects they concern (Priority: P2)

**Goal**: Results linked to model objects (sizing, timeseries keys, tabular rows, messages) with resolution rules
and confidence, exposed through the QA summary, `analyze_peak_loads` and `get_object_results`.

**Independent Test**: Simulate `5ZoneAirCooled` with one `AirTerminal:SingleDuct:VAV:Reheat` reheat capacity far too
low; `idfkit://simulation/results` flags name the zone; `get_object_results` on the terminal returns sizing facts
with `where`, linked messages with `occurrences`, `results_state: "fresh"`; after any edit it reports `"stale"`.
Offline: `uv run pytest tests/test_simulation_linking.py` asserts SC-004.

### Tests for User Story 3

- [ ] T076 [P] [US3] Write fixture-based linking tests: ≥ 95% of sizing rows, timeseries keys and tabular object rows linked or classified aggregate (SC-004); rest listed unresolved; shared names across types stay separate; case-insensitive match with model spelling returned; zone facts carry `multiplier`; `ReportData` never read during build, in `idfkit/tests/test_simulation_linking.py`
- [ ] T077 [P] [US3] Create a hand-checked sample of 100 links with expected `(raw key → ObjectKey, confidence)` and assert none labelled `exact` is wrong, in `idfkit/tests/fixtures/simulation/linked/hand_checked_links.json` and `idfkit/tests/test_simulation_linking.py`
- [ ] T078 [P] [US3] Write catalogue tests: each of about 15 message kinds matched on real fixture messages, named groups `type`/`name`/`key` extracted, unknown text → `other`, in `idfkit/tests/test_err_catalog.py`

### Implementation in idfkit

- [ ] T079 [US3] Create the message catalogue: `MessageKind(kind, pattern, hint, inspect, symptoms)` and about 15 kinds in `MESSAGE_KINDS`, plus `classify_message(text) -> tuple[MessageKind | None, list[tuple[str | None, str]]]`, in `idfkit/src/idfkit/simulation/parsers/err_catalog.py`
- [ ] T080 [US3] Implement the resolver chain as ordered pure functions `(raw key, context, doc) -> Resolution | None`: exact, typed by context, zone-list composite, space to zone, `Mir-` mirrored shading, aggregate stoplist (`Total`, `Total Facility`, …), ideal-loads suffix, EMS key, weak substring; `Resolution(key: ObjectKey | None, rule, confidence: "exact" | "typed" | "convention" | "weak", via: tuple[ObjectKey, ...])` where `substring` "is always `weak`" and `ems_key` "is always `convention`", in `idfkit/src/idfkit/simulation/linking.py`
- [ ] T081 [US3] Add `ResultFact` (`source: "sizing" | "tabular" | "timeseries_stat"`, snake-case `metric`, `where` as `Report/Table/Row/Column` or `ComponentSizes#<id>`, `multiplier` "Required for zone facts"), `LinkedMessage` (`severity: "info" | "warning" | "severe" | "fatal"`, `kind`, first-line `text`, `objects: list[Resolution]`, `occurrences` from `Errors.Count`, `first_seen` `"<environment> MM/DD HH:MM"` parsed from ERR continuation lines) and `ObjectResults` to `idfkit/src/idfkit/simulation/linking.py`
- [ ] T082 [US3] Implement `ResultIndex.build(doc, result, *, run_revision, run_model_hash)` (name index once from collections; one query per source table via T013 readers; never `ReportData`; cached on `_derived` stamped with the run), `for_object(key)` (messages deduplicated by kind with counts, available variables, one-hop neighbours), `objects_with(metric, *, top=10)`, `is_fresh(doc, model_hash=None)` and `coverage` (`unlinked_result` entries, `resolved`/`unresolved`), in `idfkit/src/idfkit/simulation/linking.py`
- [ ] T083 [US3] Re-export `ObjectKey`, `Resolution`, `ResultFact`, `LinkedMessage`, `ObjectResults`, `ResultIndex`, `Coverage`, `MessageKind`, `MESSAGE_KINDS` and `classify_message` from `idfkit/src/idfkit/simulation/__init__.py` `__all__`, and add them to the naming register in `idfkit-conformance/governance/`
- [ ] T084 [P] [US3] Write `idfkit/benchmarks/bench_result_index.py` and append budgets to `idfkit/tests/test_perf_budgets.py`: `ResultIndex.build` ≤ 50 ms independent of timeseries volume, `for_object` ≤ 10 ms
- [ ] T085 [P] [US3] Update `idfkit/agent_references/templates/result-parsing.md` and `idfkit/agent_references/snippets/result-parsing.py` with result linking and the new SQL readers; re-bake
- [ ] T086 [P] [US3] Add CHANGELOG entries in `idfkit/CHANGELOG.md` and update `idfkit-developers/docs/reference/simulation.md` to embed the new snippets
- [ ] T087 [US3] Run `make check && make test` in `idfkit/`, release, and bump `idfkit==X` in `idfkit-mcp/pyproject.toml` and `idfkit-mcp/uv.lock`

### Implementation in idfkit-mcp

- [ ] T088 [US3] In `idfkit-mcp/src/idfkit_mcp/tools/simulation.py`, record `doc.revision`, the SHA-256 of the IDF text written for EnergyPlus (`simulation_model_hash`) and `simulation_run_dir` on `ServerState` after every run; in `idfkit-mcp/src/idfkit_mcp/state.py` add a helper returning the session `ResultIndex` (built lazily via public `ResultIndex.build`) that raises `ToolError("No simulation run in this session; run `run_simulation` first.")` when none exists (FR-019) and reports `results_state` from `is_fresh`
- [ ] T089 [US3] Add `affected_objects: list[ObjectKey]` (default `[]`) to each `SimulationQAFlag`, `kind: str` and `affected_objects` to each `ClassifiedWarning`, and `link_coverage: Coverage` to the summary of the `idfkit://simulation/results` resource, changing no existing field, in `idfkit-mcp/src/idfkit_mcp/models.py` and `idfkit-mcp/src/idfkit_mcp/tools/simulation.py`
- [ ] T090 [P] [US3] Add `object: ObjectKey` (model spelling) to zone rows and `affected_objects` to flags in `idfkit-mcp/src/idfkit_mcp/tools/peak_loads.py`, changing no existing field
- [ ] T091 [US3] Implement `get_object_results(object_type, name, limit=20)` (`_READ_ONLY`; `"Node"` allowed) returning `ObjectResults` mirror with `facts`, `messages`, `available_variables`, `neighbours`, `coverage`, `results_state`, bounded with `total`/`omitted`; description names `get_object_neighbourhood` as nearest neighbour, in `idfkit-mcp/src/idfkit_mcp/tools/results.py`, registered in `idfkit-mcp/src/idfkit_mcp/server.py`
- [ ] T092 [US3] Add the resource `idfkit://simulation/objects/{type}/{name}` with the same content as `get_object_results` in `idfkit-mcp/src/idfkit_mcp/tools/resources.py`
- [ ] T093 [P] [US3] Write protocol tests (using the committed linking fixtures, no EnergyPlus): no-simulation error, fresh then stale after `update_object`, shared-name types separated, multipliers, unresolved listed, new QA and peak-load fields present and old ones unchanged, in `idfkit-mcp/tests/test_results_tools.py`, `idfkit-mcp/tests/test_simulation_tools.py` and `idfkit-mcp/tests/test_peak_loads_tool.py`
- [ ] T094 [P] [US3] Add `perf` cases: `get_object_results` ≤ 250 ms first call after a run, ≤ 10 ms afterwards, ≤ 8 KB, in `idfkit-mcp/tests/test_perf_tools.py`
- [ ] T095 [P] [US3] Document `get_object_results`, the resource and the changed fields in a new `idfkit-mcp/docs/tools/results.md` (nav in `idfkit-mcp/mkdocs.yml`) and `idfkit-mcp/docs/tools/simulation.md`
- [ ] T096 [US3] State the listing before and after (`scripts/token_audit.py`), add `idfkit-mcp/CHANGELOG.md` entries, run the slice-3 evaluation over the results faults and controls with `eval compare` against the slice-2 run, and add `idfkit-mcp/eval/decisions/slice-3.md` if no SC-009 measure shows benefit

**Checkpoint**: SC-004 green on fixtures; SC-005 met; slice run recorded.

---

## Phase 6: User Story 4 — Understand an HVAC system and rename its nodes safely (Priority: P2)

**Goal**: Loop memberships, flow-order chains, loop summaries, checks T001–T004 and an atomic node rename.

**Independent Test**: On `5ZoneAirCooled`, `get_hvac_topology(detail="chain")` gives one record per loop at ≤ about
200 tokens with terminals collapsed to `5×`; `trace_hvac("Node", "SPACE3-1 In Node")` gives the VAV air loop demand
side and the reheat coil's hot-water loop; `rename_node("Mixed Air Node 1", "AHU-1 Mixed Air")` updates every use,
`check_model_integrity` shows no new findings and `get_change_log` lists `rename_node`.

### Tests for User Story 4

- [ ] T097 [P] [US4] Write membership and chain tests: water coil on an air loop and on the demand side of a water loop; branch and 0-based position; `chain` in flow order; `zones_served`; T001–T004 injected-fault cases and their boundary exemptions, in `idfkit/tests/test_hvac_topology.py`
- [ ] T098 [P] [US4] Write rename tests: every node field and `NodeList` entry updated atomically, `revision` bumped, change notifications fired per field; `KeyError` if `old` unused; `ValueError` if `new` empty, equal to `old`, or already a node name (never merge), in `idfkit/tests/test_rename_node.py`

### Implementation in idfkit

- [ ] T099 [US4] Implement `memberships(obj)` (`LoopMembership` with `loop`, `kind: "air" | "plant" | "condenser" | "zone_equipment"`, `side: "supply" | "demand" | None` (None for zone equipment), `branch`, `position` 0-based, `stream`; lazy, memoised), `loops()`, `chain(loop, side)` (memoised per `(loop, side)`) and `zones_served(air_loop)` in `idfkit/src/idfkit/hvac/topology.py`
- [ ] T100 [US4] Implement checks T001 (flow inlet with no matching outlet or boundary, not a loop inlet), T002 (zone inlet nothing supplies), T003 (zone exhaust nothing draws from), T004 (setpoint, sensor or actuator node with no flow use), all initial severity `warning`, in `idfkit/src/idfkit/hvac/checks.py`; re-run T049/T050 on 26.2, 9.6 and 23.2 and commit any updated `_version_caps.py`
- [ ] T101 [US4] Implement `IDFDocument.rename_node(old, new) -> NodeRenameResult` (`old`, `new`, `fields_updated`, `objects`) in one pass over node fields from the topology view and every `NodeList` entry, bumping `revision`, in `idfkit/src/idfkit/document.py`
- [ ] T102 [P] [US4] Append to `idfkit/tests/test_perf_budgets.py` and `idfkit/benchmarks/bench_hvac_topology.py`: `memberships` and `chain` ≤ 5 ms each; build with all checks still ≤ 50 ms
- [ ] T103 [P] [US4] Extend `idfkit/agent_references/snippets/hvac-topology.py` and `hvac-loops.py` (memberships, chain, `rename_node`) and update `idfkit/agent_references/templates/hvac-loops.md` and `reference-tracking.md` (node names are not references; use `rename_node`); re-bake
- [ ] T104 [P] [US4] Add `rename_node`, memberships and T001–T004 to `idfkit/CHANGELOG.md`, the naming register in `idfkit-conformance/governance/`, and `idfkit-developers/docs/reference/hvac.md`

### Implementation in idfkit-mcp

- [ ] T105 [US4] Implement `get_hvac_topology(loop=None, detail="summary", limit=20)` (`_READ_ONLY`; `detail: "summary" | "chain"`) returning `HVACTopologySummary` (`loops` items `{loop, kind, fluid, supply, demand, zones_served, setpoint_nodes, finding_counts}`, `total`, `omitted`, `coverage`); in chain mode, render each side as one flow-order string collapsing repeated parallel components (`5× AirTerminal:SingleDuct:VAV:Reheat`), in `idfkit-mcp/src/idfkit_mcp/tools/topology.py`
- [ ] T106 [US4] Implement `rename_node(old, new)` (`_MUTATE`) calling `IDFDocument.rename_node`, mapping `KeyError`/`ValueError` to actionable `ToolError`s, and calling `state.record_change(...)`, in `idfkit-mcp/src/idfkit_mcp/tools/topology.py`
- [ ] T107 [US4] Populate `memberships` in `trace_hvac` from `HVACTopology.memberships` (removing the T058 placeholder) and add the resource `idfkit://model/hvac/{loop}` (same content as `get_hvac_topology(loop=…, detail="chain")`) in `idfkit-mcp/src/idfkit_mcp/tools/topology.py` and `idfkit-mcp/src/idfkit_mcp/tools/resources.py`
- [ ] T108 [P] [US4] Write protocol tests: chain records ≤ about 200 tokens per loop (SC-003), `5×` collapse, `trace_hvac` memberships for the reheat coil, rename end to end with change log and clean integrity, every rename error, in `idfkit-mcp/tests/test_topology_tools.py`
- [ ] T109 [P] [US4] Add `perf` cases for `get_hvac_topology` (one loop, all loops) and `rename_node`: ≤ 50 ms first, ≤ 10 ms cached, ≤ 8 KB, in `idfkit-mcp/tests/test_perf_tools.py`
- [ ] T110 [P] [US4] Document `get_hvac_topology`, `rename_node` and the resource in `idfkit-mcp/docs/tools/hvac-topology.md`, and add `idfkit-mcp/CHANGELOG.md` entries

**Checkpoint**: SC-003 met; rename safe; US4 testable on its own.

---

## Phase 7: User Story 7 — Build other applications on the model graph (Priority: P2)

**Goal**: `idfkit.graph.ModelGraph` walks the model, topology and results layers with one vocabulary, exports
versioned node-link JSON that networkx 3.6+ loads unchanged, and idfkit-mcp exposes one bounded
`get_object_neighbourhood` tool. The slice ends with the R-31 ablation deciding the two conditional tools.

**Independent Test**: In a plain script with no server, load the reference model, list findings, trace a node and
walk one component's neighbourhood using only `__all__` names (`model-graph.py:standalone-script`); it passes pyright
strict. `ModelGraph(doc).layers == ["model", "topology"]` with `results` in `unavailable`. The export loads in
networkx with equal node and edge counts.

### Governance

- [ ] T111 [US7] Add the `idfkit.graph` capability-unit row (Python-only) to `idfkit-conformance/governance/parity.toml` and its names (`NodeKind`, `EdgeKind`, `Layer`, `JSONValue`, `GraphNode`, `GraphEdge`, `Subgraph`, `ModelGraph`, `write_node_link`, `save_node_link`, `NODE_LINK_FORMAT_VERSION`) to the naming register; cut a governance tag and bump the pin in `idfkit/pyproject.toml`

### Tests for User Story 7

- [ ] T112 [P] [US7] Write view tests: construction does no work; `layers`/`unavailable` with and without a `ResultIndex`; vocabulary and layer fixed per kind; reference targets resolved to typed `ObjectKey` (shared-name case); hop and `max_nodes` bounds with `truncated`, `omitted_nodes`, `frontier`; category filter keeps start and non-object nodes on kept paths and applies before the node bound; stale results walked with `stale: true`; unknown kinds in filters ignored; `ValueError` for `hops < 0` or `max_nodes < 1`, in `idfkit/tests/test_graph_view.py`
- [ ] T113 [P] [US7] Write export tests: `json.loads` round trip, only JSON values, unique ids, every edge endpoint in `nodes`, `graph` metadata keys per contracts/node-link-json.md, `start`/`hops` together or `ValueError`; plus a `@pytest.mark.nodelink` test where `networkx.node_link_graph(data)` loads the reference model's export with no keyword arguments and equal counts, in `idfkit/tests/test_graph_node_link.py`

### Implementation in idfkit

- [ ] T114 [US7] Create `NodeKind = Literal["object", "node", "result_fact", "message"]`, `EdgeKind = Literal["reference", "flow", "control", "membership", "result_link"]`, `Layer = Literal["model", "topology", "results"]`, recursive `JSONValue`, and dataclasses `GraphNode` (`id`, `kind`, `layer` fixed by kind, `key`, `node`, `label`, scalar-only `attrs`), `GraphEdge` (`source`, `target`, `kind`, `layer`, `key` unique per endpoint pair such as `reference:zone_name`, `attrs`) and `Subgraph` (fields per data-model.md), in `idfkit/src/idfkit/graph/types.py`
- [ ] T115 [US7] Implement `ModelGraph(doc, *, results=None)` in `idfkit/src/idfkit/graph/view.py`: stores arguments only; `layers`, `unavailable` (e.g. `"results: no ResultIndex was passed in"`), `coverage`; `node_id(target)` with ids `object:<TYPE UPPER>:<NAME UPPER>`, `node:<NAME UPPER>` and stable composites for facts and messages; `neighbourhood(start, *, hops=1, node_kinds, edge_kinds, categories, max_nodes=200)` as iterative BFS over per-layer adapters (references via `get_references_with_fields`/`get_referencing_edges`; topology via `HVACTopology.from_document` adjacency; results via per-object facts and messages); EMS uses become `control` edges with `confidence: "convention"`; object nodes carry `category`; dataclasses built only for returned items; no domain logic
- [ ] T116 [US7] Implement `to_node_link(...)`, `write_node_link(graph, *, layers, node_kinds, edge_kinds, start, hops) -> str`, `save_node_link(graph, path, *, …) -> None` and `NODE_LINK_FORMAT_VERSION: Final = 1`, emitting `directed: true`, `multigraph: true`, `graph` (`format: "idfkit-model-graph"`, `format_version`, `idfkit_version`, `energyplus_version` `X.Y.Z`, `layers`, `unavailable`, `coverage`, `scope`, `results_state`), `nodes` and `edges` (key `"edges"`, not `"links"`), with `attrs` flattened and `key` split into `object_type`/`name`, in `idfkit/src/idfkit/graph/node_link.py`; export from `idfkit/src/idfkit/graph/__init__.py` `__all__`
- [ ] T117 [P] [US7] Write `idfkit/benchmarks/bench_graph.py` and append budgets to `idfkit/tests/test_perf_budgets.py`: construction ≤ 0.1 ms; `neighbourhood` 3 hops up to 200 nodes ≤ 10 ms with topology cached; `to_node_link()` of `model` + `topology` on the reference model ≤ 1 s and ≤ 50 MB peak extra memory
- [ ] T118 [P] [US7] Write `idfkit/agent_references/templates/model-graph.md` and `idfkit/agent_references/snippets/model-graph.py` with a `standalone-script` section (load model, list findings, trace a node, walk a component's neighbourhood, export) using only `__all__` names, plus the networkx < 3.6 `edges="edges"` keyword and the d3 `links` rename note; update `reference-tracking.md`; add the topic row to `SKILL.md`; re-bake
- [ ] T119 [P] [US7] Add `idfkit.graph` to `idfkit/CHANGELOG.md` and a `graph` reference page embedding the `model-graph` snippets to `idfkit-developers/docs/reference/graph.md` with its nav entry
- [ ] T120 [US7] Run `make check && make test` and `uv run --with "networkx>=3.6" pytest -m nodelink` in `idfkit/`, release, and bump `idfkit==X` in `idfkit-mcp/pyproject.toml` and `idfkit-mcp/uv.lock`

### Implementation in idfkit-mcp

- [ ] T121 [US7] Add Pydantic mirrors `GraphNode`, `GraphEdge` and `ObjectNeighbourhood` (mirror of `Subgraph`) to `idfkit-mcp/src/idfkit_mcp/models.py`
- [ ] T122 [US7] Implement `get_object_neighbourhood(object_type, name, hops=1, node_kinds=None, edge_kinds=None, categories=None, max_nodes=40)` (`_READ_ONLY`; `hops` 1–3; `max_nodes` 1–100) building `ModelGraph` from the session document and, if this session simulated, its `ResultIndex`; when the serialised response exceeds 8 KB lower the node count until it fits and set `truncated`, never returning a partial node or edge; errors: no model, not found (closest names, never pick one), out-of-range bounds (state the range), unknown kind or category (list the vocabulary); a missing layer goes to `unavailable`, never an error; no export tool or graph resource, in `idfkit-mcp/src/idfkit_mcp/tools/graph.py`, registered in `idfkit-mcp/src/idfkit_mcp/server.py`
- [ ] T123 [P] [US7] Write protocol tests per quickstart US7 steps 1–4 (zone and reheat coil as object nodes, flow edges via node nodes, membership edge, result facts fresh, category filter, `max_nodes=5` truncation under 8 KB, `hops=4` range error) in `idfkit-mcp/tests/test_graph_tools.py`
- [ ] T124 [P] [US7] Add the `perf` case `get_object_neighbourhood` ≤ 50 ms with views cached and ≤ 8 KB enforced, and confirm the default of 40 nodes against the response budget, in `idfkit-mcp/tests/test_perf_tools.py`
- [ ] T125 [P] [US7] Document `get_object_neighbourhood` (with the nearest-neighbour table from contracts/mcp-tools.md) in a new `idfkit-mcp/docs/tools/graph.md` (nav in `idfkit-mcp/mkdocs.yml`), and add `idfkit-mcp/CHANGELOG.md` entries
- [ ] T126 [US7] Write the ablation runner `idfkit-mcp/eval/runners/claude_code_ablation.toml` (`disallowed_tools = ["trace_hvac", "get_object_results"]`), run the ablation on topology and results tasks, and keep each conditional tool only if removing it costs ≥ 20% more tool calls or response tokens at no lower fix rate; record the outcome in `idfkit-mcp/eval/decisions/slice-4-ablation.md`
- [ ] T127 [US7] Remove any conditional tool that failed T126 (module function, registration, models, tests, docs) from `idfkit-mcp/src/idfkit_mcp/tools/topology.py` and/or `idfkit-mcp/src/idfkit_mcp/tools/results.py` before the release that would first publish it; confirm `test_tool_listing_budget.py` passes (SC-010) and state the listing figure in the PR
- [ ] T128 [US7] Run the slice-4 evaluation over US4 and US7 tasks with `eval compare` against the slice-3 run, check SC-010a shares, and add `idfkit-mcp/eval/decisions/slice-4.md` if no SC-009 measure shows benefit

**Checkpoint**: SC-014 standalone script complete; export loads in networkx; neighbourhood ≤ 8 KB; SC-010 within
the cap after the ablation.

---

## Phase 8: User Story 6 — Go from a symptom to its likely causes (Priority: P3, gated)

**Goal**: Rule-based, explained diagnosis with evidence strength, cause families and a "no strong candidate"
statement, exposed as `diagnose_symptom`.

**Gate**: Start only if the SC-009 verdict passes on the slice 2–4 runs. Merge only with SC-009a green (R-37).

**Independent Test**: With an undersized reheat terminal, `diagnose_symptom("unmet_heating", "Zone", <zone>)` puts
the terminal in the top three with its sizing fact as `strong` evidence and a `verify` call; with an EMS override
instead, it returns `no_strong_candidate: true` with the statement first and no family covering EMS.

- [ ] T129 [US6] **HUMAN (maintainer):** read the SC-009 verdicts in the slice 2–4 `summary.md` files and record go/no-go in `idfkit-mcp/eval/decisions/slice-5-gate.md`; stop this phase on no-go

### Tests for User Story 6

- [ ] T130 [P] [US6] Write diagnosis tests on fixtures: undersized coil in top 3 with `strong` evidence; no weak-only candidate at rank 1; `no_strong_candidate` with `statement` first when nothing is strong; `families_covered` for unmet heating (capacity, control and setpoint, availability, envelope, air distribution); `shared_upstream` for a warning shared by many coils; unknown symptom error, in `idfkit/tests/test_simulation_diagnose.py`

### Implementation

- [ ] T131 [US6] Extend the catalogue to about 40 kinds, with per-symptom `inspect` types, thresholds and cause families, in `idfkit/src/idfkit/simulation/parsers/err_catalog.py`
- [ ] T132 [US6] Implement `CandidateCause` (`rank` "1-based. A `weak`-only candidate is never rank 1", `evidence` "At least one", `verify`, `weight_basis`, `family`, `evidence_strength: "strong" | "moderate" | "weak"`) and `Diagnosis` (fields in order `statement`, `no_strong_candidate`, `symptom`, `target`, `candidates`, `families_covered`, `shared_upstream`, `coverage`, `results_state`) and `diagnose(index, doc, symptom, target=None, *, limit=5)` scoring rule weight minus upstream topology distance (reference-graph distance as fallback) for symptoms `unmet_heating`, `unmet_cooling`, `peak_outlier`, `sizing_zero`, `message:<kind>`, in `idfkit/src/idfkit/simulation/linking.py`; re-export from `idfkit/src/idfkit/simulation/__init__.py` and register names in `idfkit-conformance/governance/`
- [ ] T133 [P] [US6] Append the `diagnose` ≤ 10 ms budget to `idfkit/tests/test_perf_budgets.py`, add a diagnosis section to `idfkit/agent_references/snippets/result-parsing.py` and its template (re-bake), and add entries to `idfkit/CHANGELOG.md` and `idfkit-developers/docs/reference/simulation.md`
- [ ] T134 [US6] Release idfkit and bump `idfkit==X` in `idfkit-mcp/pyproject.toml` and `idfkit-mcp/uv.lock`
- [ ] T135 [US6] Implement `diagnose_symptom(symptom, object_type=None, name=None, limit=5)` (`_READ_ONLY`) returning the `Diagnosis` mirror; errors: unknown symptom (list the valid ones), target required but missing; description names `get_object_results` as nearest neighbour, in `idfkit-mcp/src/idfkit_mcp/tools/results.py` with models in `idfkit-mcp/src/idfkit_mcp/models.py`
- [ ] T136 [P] [US6] Write protocol and `perf` tests (≤ 250 ms first after a run, ≤ 10 ms afterwards, ≤ 8 KB) in `idfkit-mcp/tests/test_results_tools.py` and `idfkit-mcp/tests/test_perf_tools.py`
- [ ] T137 [P] [US6] Add out-of-catalogue diagnosis variants (e.g. EMS actuator overriding the zone heating setpoint), one per diagnosis fault, held out under R-33 where possible, in `idfkit-mcp/eval/faults/held_out/` or `idfkit-mcp/eval/faults/diagnosis_variants/`
- [ ] T138 [US6] Record `top_candidate_edited` and `top_candidate_correct` for runs that call `diagnose_symptom`, and the SC-009a comparison against the baseline's wrong first edits, in `idfkit-mcp/eval/parsers/claude_stream_json.py`, `idfkit-mcp/eval/__main__.py` and `idfkit-mcp/eval/report.py`
- [ ] T139 [US6] Document `diagnose_symptom` in `idfkit-mcp/docs/tools/results.md`, state the listing figure, add `idfkit-mcp/CHANGELOG.md` entries, run the slice-5 evaluation, and merge only with SC-009a green (`idfkit-mcp/eval/decisions/slice-5.md`)

**Checkpoint**: diagnosis shipped only behind a passed gate, with anchoring measured.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T140 [P] Verify no env-var lookup was added under `idfkit/src/idfkit/` (`grep -rn "os.environ\|os.getenv" src/idfkit/` unchanged vs `main`); if one was, update `idfkit-developers/docs/concepts/environment-variables.md` in the same change
- [ ] T141 [P] Verify every new public name has a runnable, type-checked snippet and a reference-page embed (SC-014) by cross-checking `__all__` of `idfkit.hvac`, `idfkit.graph` and the new `idfkit.simulation` names against `idfkit/agent_references/snippets/` and `idfkit-developers/docs/reference/`
- [ ] T142 Run every quickstart.md scenario end to end on both repositories (`specs/001-model-knowledge-graph/quickstart.md`) and record outcomes in the final PR description
- [ ] T143 Run the full quality gate `make check && make test` in `idfkit/` and `idfkit-mcp/`, plus `uv run pytest -m perf` in both and `uv run --with "networkx>=3.6" pytest -m nodelink` in `idfkit/`
- [ ] T144 [P] Fix the corrections that do not wait for this feature, listed in `specs/001-model-knowledge-graph/background/README.md` ("Corrections that do not wait for this feature"): idfkit's wrong node-validation guidance and idfkit-plugin's unit error, in their own PRs

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup. Blocks every story. T034 (held-out faults) must be committed before
  T047 adds `hvac/checks.py`.
- **US1 (Phase 3)**: after Foundational. idfkit tasks (T035–T055) before idfkit-mcp tasks (T056–T062).
- **US2 (Phase 4)**: harness tasks T063–T074 need only Foundational and can run in parallel with US1. The first full
  run T075 needs US1 merged (it compares the pre-feature baseline with slice 1).
- **US3 (Phase 5)**: after Foundational; independent of US1 in code. Its slice run (T096) needs the harness (US2).
- **US4 (Phase 6)**: after US1 (extends `HVACTopology`, `trace_hvac`, `checks.py`).
- **US7 (Phase 7)**: after US1 and US3 (its layers), and best after US4 (membership edges). The ablation (T126) needs
  US2's harness and both conditional tools.
- **US6 (Phase 8)**: after US3, US4 and US7, and only on a passed SC-009 gate (T129).
- **Polish (Phase 9)**: after the stories that are shipped.

### Within each story

- idfkit lands, is released and pinned before idfkit-mcp uses it (T055, T087, T120, T134).
- Tests are written first and fail until implementation lands.
- Types → generators/tables → views → checks → wrappers → server tools → docs → token figure → evaluation run.

### Cross-repository pairing

- Each new capability unit's governance rows (T035, T111) land as a pair with the idfkit change that adds the unit.

---

## Parallel Examples

### Foundational

```text
T010 tests/test_document_revision.py   ‖ T012 tests/test_graph_common.py ‖ T016 tests/test_sql_readers.py
T017 vendor reference model            ‖ T018 benchmarks/_timing.py
T022 session tests ‖ T023 shared mirrors ‖ T024 public-API AST test ‖ T026 perf harness
T029 eval/stats.py ‖ T030 eval/lint.py ‖ T031 eval/held_out.py ‖ T032 eval TOML files ‖ T033 harness tests
```

### User Story 1

```text
T036 test_hvac_topology.py ‖ T037 test_hvac_rules.py ‖ T038 test_hvac_categories.py ‖ T039 test_hvac_coverage.py
T042 port_rule_models/     ‖ T045 _categories.py
T051 bench ‖ T052 agent references ‖ T053 CHANGELOG ‖ T054 idfkit-developers page   (after T047)
```

### User Story 2

```text
T065 parser ‖ T067 diff ‖ T068 topology faults ‖ T069 results faults ‖ T070 controls ‖ T071 authoring ‖ T072 questions
```

### User Story 3

```text
T076 linking tests ‖ T077 hand-checked links ‖ T078 catalogue tests
T084 bench ‖ T085 agent refs ‖ T086 CHANGELOG + docs     (after T082)
T090 peak loads ‖ T093 protocol tests ‖ T094 perf ‖ T095 docs   (after T088)
```

### User Story 7

```text
T112 test_graph_view.py ‖ T113 test_graph_node_link.py
T117 bench ‖ T118 model-graph snippet ‖ T119 CHANGELOG + page   (after T116)
T123 protocol tests ‖ T124 perf ‖ T125 docs                    (after T122)
```

---

## Implementation Strategy

### MVP first (User Story 1)

1. Phase 1 Setup, Phase 2 Foundational (including the held-out faults, T034).
2. Phase 3 US1: idfkit lands `idfkit.hvac` with qualified checks; idfkit-mcp exposes them.
3. **Stop and validate**: SC-001, SC-001a, the typo scenario through the server, the topology budget.

### Incremental delivery (one slice per PR pair)

1. Slice 0 → Foundational.
2. Slice 1 → US1 (MVP).
3. Slice 2 → US2: first measured baseline/treatment comparison; decision record if no benefit.
4. Slice 3 → US3, with its evaluation run.
5. Slice 4 → US4 + US7, ablation of the two conditional tools, evaluation run.
6. Slice 5 → US6, only behind the SC-009 gate, merged only with SC-009a green.

Every slice's PR includes the benchmark table before and after, the tool-listing figure, CHANGELOG entries in both
repositories, and its evaluation run (from slice 2 on). No PR merges with a budget failing (FR-009).

### Human-only tasks

T034 (held-out faults, by a maintainer who writes no checks), T075, T096, T126, T128, T139 (evaluation runs needing
EnergyPlus and runner credentials), T129 (the SC-009 gate decision), and the EnergyPlus-dependent generation and
corpus runs T015, T044 and T050.

---

## Notes

- [P] tasks touch different files and depend on no incomplete task.
- Story labels map tasks to spec.md user stories; US5 is deferred and has none.
- Commit after each task or logical group; stop at any checkpoint to validate the story on its own.
- Never present a check, link or diagnosis as proof that a model simulates (FR-008, Principle IV).
