# Research: Model Knowledge Graph for Agents

Phase 0 output of `/speckit-plan`. Each entry records a decision, the reason for it, and the alternatives
considered. The background reports in [`background/`](background/README.md) hold the underlying measurements; this
file decides. Entries marked **checked** were verified during planning against the code or the data, not taken
from the reports.

Planning input from the user: *"a pure Python stack as much as possible; no external dependencies except for the
PNNL standards library."* Since the standards layer was deferred (spec, Clarifications, 2026-11-11), the exception
is unused: this feature adds no third-party dependency at all.

**Revision 2 (2026-11-11).** Re-planned after the spec review and the standards deferral. R-08 to R-11 and R-26 to
R-30 moved to [deferred-standards-research.md](deferred-standards-research.md). R-12, R-13 and R-14 are rewritten,
R-01, R-02, R-15 to R-18, R-20 to R-25 are revised, and R-31 to R-37 are new. Numbers are never reused.

---

## R-01 Stack and dependencies

**Decision.** Everything new is pure Python 3.10+ using the standard library only (`dataclasses`, `enum`, `re`,
`json`, `sqlite3`, `hashlib`, `subprocess`, `random`, `statistics`). No third-party dependency is added to idfkit
or idfkit-mcp. idfkit-mcp's existing runtime dependencies (FastMCP, `mcp`, Pydantic, `openstudio`) are unchanged,
and its idfkit dependency stays an exact `idfkit==X` pin.

**Rationale.** idfkit's core has zero third-party dependencies, and that is a published property. Every capability
left in this feature fits in the standard library:
- Topology is graph traversal over in-memory objects.
- Result linking reads EnergyPlus's SQLite output, which idfkit already reads with `sqlite3`.
- The evaluation's statistics are a paired bootstrap, which `random` and `statistics` cover (R-32).

The user's instruction is read as "no *new* external dependencies". Removing idfkit-mcp's existing FastMCP or
Pydantic would break the server and its constitution (Principle II requires Pydantic models).

**Alternatives considered.**
- `networkx` for graph algorithms. Rejected: traversal here is bounded BFS over at most about 10k nodes, which
  takes a few dozen lines.
- `rdflib` or `brickschema` for semantic output. Rejected: an ontology export is out of scope, and brickschema
  needs Python 3.11 or later.
- `scipy` or `numpy` for confidence intervals. Rejected: a percentile bootstrap over at most a few hundred tasks
  takes well under a second in pure Python.

## R-02 Where the code lands, and the parity ledger

**Decision.** All domain logic lands in **idfkit**, in three places:

| Capability | idfkit location | New capability unit? |
|---|---|---|
| HVAC topology, connection checks, node rename | new subpackage `idfkit.hvac`, plus `IDFDocument.rename_node` | **Yes** |
| Result linking, message catalogue, diagnosis | `idfkit.simulation.linking` and `idfkit.simulation.parsers.err_catalog` (inside the existing `idfkit.simulation` unit) | No |
| Component categories (R-36) | `idfkit.hvac` | (same unit) |
| Combined graph view and node-link export | new subpackage `idfkit.graph` (R-23) | **Yes** |

idfkit-mcp adds tool modules that call these and hold no domain knowledge.

**Rationale.**
- Constitution Principle I forbids domain knowledge in idfkit-mcp.
- **checked:** idfkit's `scripts/check_parity_ledger.py` treats every public subpackage as a *capability unit*. A
  new unit fails `make check` unless the parity ledger (`idfkit-conformance/governance/parity.toml`) and the naming
  register carry a matching row at the governance tag pinned in idfkit's `pyproject.toml`. So `idfkit.hvac` and
  `idfkit.graph` each need a ledger row, recorded as Python-only for now (idfkit-js has neither), in a paired
  change to idfkit-conformance.
- Result linking deliberately extends the existing `idfkit.simulation` unit, so it needs no ledger change.

**Alternatives considered.**
- Topology inside `idfkit.references`. Rejected: node names are not object references, and mixing them would
  corrupt `get_referencing` and rename semantics (report 01, §3).
- A single new `idfkit.graph` unit for everything. Rejected: it would mix domain logic with the cross-layer view.
  `idfkit.graph` exists only as a thin, read-only view **over** the layer units. The domain logic stays in
  `idfkit.hvac` and `idfkit.simulation` (R-23).

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
- **Full coverage from the start, verified by EnergyPlus (clarification, 2026-11-11).** Every node-bearing object
  type in the latest supported schema gets rules at first release. **EnergyPlus's own connection report is the only
  source of truth.** Field naming is a cross-check and never decides a role.

  **Why naming is not trusted. Measured or observed during clarification:**
  - **Boundaries named as inlets.** Report 01's prototype misread `AirTerminal:DualDuct:VAV:OutdoorAir`'s
    `outdoor_air_inlet_node_name`, which is fed by an outdoor-air system's splitter, not by the outdoors (11 nodes).
    The 26.2 schema has 29 fields named like outdoor or condenser inlets. Some connect to the outdoors, some to
    other components, and for some a blank value means outdoors.
  - **Parents pair perfectly by name.** About two dozen of the name-pairable types are parent objects: unitary
    systems, coil systems and packaged terminal units. The count comes from a rough pattern match and is to be
    confirmed by generation. Their inlet and outlet repeat their children's nodes, so naming would add false flow
    edges. Only EnergyPlus's parent and non-parent connection rows tell them apart.
  - **Naming gives neither connection type nor stream.** It cannot tell a zone inlet from an inlet, or the
    evaporator stream from the condenser stream.
  - **Value-dependent roles.** For example, an air-cooled versus water-cooled condenser.

  **Coverage**, measured over the 26.2 schema and the 735 EnergyPlus 24.1 example models:

  | Node-bearing object types in 26.2 | Count | Source of rules |
  |---|---|---|
  | Total | 257 | |
  | Used in at least one example model | 247 | EnergyPlus connection report from the example models |
  | Name-pairable but in no example model | 7 (`Generator:FuelCell:StackCooler`, `HeatPump:AirToWater`, `PlantEquipmentOperation:OutdoorDewpointDifference`, `SetpointManager:FollowSystemNodeTemperature`, `SetpointManager:MultiZone:Cooling:Average`, `SetpointManager:MultiZone:Heating:Average`, `ThermalStorage:PCM`) | EnergyPlus connection report from a minimal test model |
  | Neither | 3 (`Lights:Instance`, `SpaceHVAC:ZoneReturnMixer`, `ThermalStorage:HotWater:Stratified`) | EnergyPlus connection report from a minimal test model |

  The 169 name-pairable types are used only to cross-check: 162 of them also appear in example models.

- **Generation.** A codegen script, `idfkit.codegen.generate_port_rules`, needs EnergyPlus only when it runs. It
  works in six steps:
  1. Run each example model, and each of the 10 minimal test models committed under
     `src/idfkit/codegen/port_rule_models/`, for design days only, with `Output:Diagnostics` on so EnergyPlus writes
     `eplusout.bnd`.
  2. Parse the "Non-Parent Node Connection" and "Parent Node Connection" rows: object type, object name, node,
     connection type and fluid stream.
  3. Map each row back to a field by matching the node value in that object's input.
  4. Merge across files. A field whose role differs between files is emitted as a predicate candidate for review,
     never silently resolved. An object that uses the same node in two fields is an ambiguous match, which is also
     queued for review.
  5. Cross-check every generated role against field naming. Any disagreement fails generation until a person has
     reviewed it and recorded the resolution in the reviewed overrides file.
  6. Write `_port_rules.py`, recording each rule's provenance: `eplus_examples`, `eplus_test_model` or `hand_written`.

  A type whose test model cannot be made to run gets a hand-written rule with provenance `hand_written`. Its findings
  are capped at warning severity permanently. Provenance travels on every `NodeUse` and `TopologyFinding`. A
  coverage test fails if any node-bearing type in the latest schema has no rule. Generation is repeated when a new
  EnergyPlus version is adopted.
- **Predicates.** Rules that depend on a value are expressed as small predicates, for example "condenser type is
  AirCooled" makes the condenser nodes OutsideAir.
- **Unknown types.** An object type with no rule, which can only happen for a model newer than idfkit's schema,
  yields an `unclassified` finding at info severity, never an error (spec edge cases).

**Rationale.** The schema says *that* a field is a node, never *how* it connects. EnergyPlus decides that per
call site in C++. Mirroring its connection types lets idfkit's findings map one-to-one onto EnergyPlus's own node
connection errors. It also makes the branch-and-node report (`eplusout.bnd`) usable as an oracle later (FR-018).

**Alternatives considered.**
- A pure name heuristic, or naming as the source for name-pairable types. Rejected: it misreads boundaries,
  parents, streams and value-dependent roles (see above). Naming is kept only as a cross-check.
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

## R-12 Bounded responses and token cost

*Revised in revision 2. The tool list itself is decided in R-31.*

**Decision.**
- Every new tool takes a `limit` (default 20 rows) and returns `total` and `omitted` counts.
- Loop summaries render each side as one compact string and collapse repeated parallel components (`5×
  AirTerminal:SingleDuct:VAV:Reheat`).
- Messages are deduplicated by kind, with counts.
- **Listing cost (SC-010).** The cost is the whole `tools/list` response as an agent receives it: names,
  descriptions, input schemas **and output schemas**, at 4 characters per token, as `scripts/token_audit.py`
  counts it. **checked during planning:** at the base revision (`81d3cd6`, before this feature), the listing is
  39 tools and about 15,300 tokens, a mean of about 390 per tool. The cap is therefore about 2,300 tokens for
  every new tool together, plus the growth of the two changed tools, `check_model_integrity` and `analyze_peak_loads`.
- **Keeping output schemas small.** Response models reuse one set of shared sub-models (`ObjectKey`, `Coverage`,
  `NodeUse`, `FlowEdge`), so each appears once in `$defs`. Field descriptions live in the docs pages, not in the
  schema. Each slice's pull request records the listing before and after.

**Rationale.** Constitution Principle II. Report 01 measured a full connection dump of HospitalLowEnergy (2,607
nodes) at about 100k tokens, and BuildingGPT found that pasting a whole graph does not help. The spec review found
that the earlier plan's 13 tools could not fit the cap; R-31 cuts the list to six.

## R-13 Evaluation harness

*Rewritten in revision 2 for FR-040a, FR-040b, FR-042 to FR-042c, FR-046, SC-008 to SC-010a. Statistics are in
R-32, the task set in R-14 and R-33.*

**Decision.**
- **Location and code.** It lives in idfkit-mcp under `eval/`, is never packaged, and uses the standard library plus
  the FastMCP client idfkit-mcp already depends on.
- **Runner.** The agent is driven through a configurable runner command. The default is Claude Code in headless
  mode with an MCP config pointing at the server under test; its streamed JSON gives tool calls and tokens. No
  LLM SDK becomes a dependency.
- **Baseline (FR-042c).** The baseline is idfkit-mcp at the **revision just before the feature's first change**,
  pinned in `eval/baseline.toml` as a commit SHA and the idfkit level it pins. The harness builds both conditions
  from git (`uv run --with` the pinned idfkit, from a `git worktree` of that SHA), so the two differ only by this
  feature. A run against any other baseline, for example a released version, is allowed but labelled
  `baseline_kind = "other"` in the report, and its gate verdict is marked not valid for SC-009.
- **Ablations without product flags.** To compare the targeted tools with the neighbourhood tool (R-31), a runner
  configuration can list tools the agent may not call, which the default runner passes as the CLI's disallowed-tools
  option. The server is unchanged; only the agent's tool list differs. Ablation runs are labelled and never used
  for the SC-009 gate.
- **Prompts (FR-042b).** Each task carries a modeller-style prompt written against the symptom or goal, from a
  small set of templates (`"The simulation of this model fails. Make it run."`, `"Zone {zone} is too cold in
  winter. Find out why and fix it."`). A lint in `test_eval_harness.py` fails when a prompt contains the injected
  object's name, the field name, the fault id, or the words "fault", "injected" or "bug".
- **Recorded per task and repeat (FR-042).** Fixed or not; verified by check, by simulation or skipped; tool calls;
  response tokens consumed; unwanted changes outside the fault's declared scope; for control tasks, any change or
  any reported fault (a false fix); for treatment runs, which new tool was used, attributed against the task's
  `intended_tools` (SC-010a); for diagnosis tasks, whether the agent edited the top-ranked candidate and whether
  it was the injected object (SC-009a).
- **Per-slice runs (FR-046).** The pull request that completes a user story includes a run over that story's fault
  types and the comparison with the previous slice's run, and a decision record `eval/decisions/<slice>.md` when
  the run shows no benefit on any SC-009 measure. The record names the maintainer, the decision and the reason.
- **Running it.** A maintainer runs it on demand. It is not part of default CI: it needs EnergyPlus and model
  credentials, and it costs money (spec, Assumptions).

**Rationale.** The review found the earlier design measured the checks rather than the agent: one run per task,
faults written alongside the checks, prompts that could reveal the fault, and a baseline that included unrelated
changes. The disallowed-tools ablation answers FR-059's "measured saving" question without adding product surface.

**Alternatives considered.**
- Baseline = last release (the earlier decision). Rejected by FR-042c: a release mixes in other changes.
- A `--disable-tools` server flag. Rejected: it adds product surface used only for testing. The runner-side
  disallowed list does the same from outside.
- An Anthropic or OpenAI SDK inside the harness. Rejected by R-01.

## R-14 Task set and reference models

*Rewritten in revision 2. The held-out process is R-33.*

**Decision.**
- **Designed fault types (10).** Each is an idfkit-based injector with a known fix and a verifier:
  - topology (6): outlet node typo, swapped inlet and outlet, branch missing from its branch list, setpoint
    manager on a node no flow component uses, terminal outlet not a zone inlet, water coil connected to the wrong
    plant loop side
  - results (4): undersized reheat coil, wrong heating setpoint schedule, uninsulated exterior wall, availability
    schedule off for a packaged unit
- **Held-out fault types (at least 5, a third of 15).** Defined by R-33's process, so their content is not known
  here. Their sources are listed there.
- **Control tasks.** At least one per five fault tasks: an unmodified reference model with the same prompt
  templates. A false fix is any model change or any reported fault.
- **Authoring tasks (4).** Build or change an HVAC system from a description on a reference model: add a hot-water
  reheat coil and connect it to the existing hot-water loop; add a second chiller in parallel on the chilled-water
  supply side; add a zone with a VAV reheat terminal on an existing air loop; replace a constant-volume fan with a
  variable-volume fan. Success is a model that passes the connection check with no error finding and simulates.
- **Open questions (6).** Questions about a model with an answer computed by idfkit from the unmodified model and
  committed as the key, for example "which zones served by this air loop had more than 300 unmet heating hours?"
  or "which plant loop serves the reheat coil of zone 3?". No single new tool answers any of them directly.
- **Reference models.** At least 20 from the 26.2 ExampleFiles, covering VAV with reheat, chilled and hot water
  plant, packaged units, zone lists and HVACTemplate, pinned by file name. Each fault type declares the model tags
  it applies to, and runs on every applicable model, capped at 8 models per type.

**Rationale.** FR-040, FR-040a, FR-040b and FR-041. The authoring and open-question tasks measure the two uses the
earlier set ignored: building systems, which is most of what agents do, and questions outside the canned tools.
The cap of 8 models per type keeps a full run near 100 tasks (R-32 sizes the repeats).

## R-15 Session persistence

*Revised in revision 2: the standards fields left with the standards layer.*

**Decision.** The idfkit-mcp session file moves from `"version": 1` to `2` and adds:
- `simulation_model_hash`, the SHA-256 of the IDF text written for the session's last run (R-06)
- `simulation_run_dir`, already held in memory today, so that linking can resume after a restart

Version-1 files still load, with no simulation recorded. Nothing is written into model files. HTTP sessions keep
persistence disabled, as today.

**Rationale.** Constitution Principle V requires persisted session state with reported restore failures, and
FR-026 requires staleness to be detected across restarts. The asserted roles and standards context of the earlier
plan are deferred with the standards layer, which leaves the session file change small.

## R-16 Diagnosis ranking

**Decision.** `idfkit.simulation.linking.diagnose(index, doc, symptom, target)` is rule-based. The message
catalogue lists, for each message kind and each symptom, the neighbour object types to inspect.

Candidates are scored by rule weight (from the catalogue) minus graph distance from the symptom object. Distance
is taken over the HVAC topology (upstream only) where available, and over the reference graph otherwise. Weak
links are never ranked first. Each candidate carries evidence, a reason and a verification step. No score is
shown without the reason behind it.

*Revised in revision 2 (FR-027, SC-009a):*
- **Evidence strength.** Each candidate's evidence is `strong` (a linked result value past the rule's threshold,
  or a connection finding), `moderate` (a linked value within the threshold, or a typed or convention link) or
  `weak` (a free-text match only).
- **No strong candidate.** When no candidate is `strong`, the `Diagnosis` sets `no_strong_candidate = true` and
  its first field is a one-line statement saying so. Ranking is unchanged; the statement comes first.
- **Cause families.** The catalogue groups its rules into families per symptom (for unmet heating: capacity,
  control and setpoint, availability, envelope, air distribution). Every `Diagnosis` lists `families_covered`, so
  a cause outside them, such as an EMS override, is visibly unexamined.

**Rationale.** FR-027 and spec "Out of Scope" (no machine-learned ranking). The ranking is domain knowledge, so
it lives in idfkit (Principle I).

## R-17 HVACTemplate models

**Decision.** Topology, checks and result linking do **not** expand templates (expansion needs EnergyPlus's
ExpandObjects). When template objects are present, responses carry `coverage.partial = true` and list the
template systems not covered. Their absent nodes are never reported as faults. Revision 2 folds this into the
general `Coverage.uncovered` list of R-35.

## R-18 Reference corpus for qualifying checks

**Decision.** An opt-in integration test (`pytest -m integration`) loads every 26.2 ExampleFile from
`$ENERGYPLUS_DIR/ExampleFiles` and asserts zero error-severity topology findings. A check moves from warning to
error only with that test green (FR-013, clarification 4). The files are not committed. Earlier versions are
measured, not used for qualification (R-34).

## R-19 Fixtures for result linking

**Decision.** A script in idfkit (`scripts/build_linking_fixtures.py`, which needs EnergyPlus 26.2) runs about 10
reference models. Each run includes `Output:SQLite SimpleAndTabular`, AllSummary and a small set of
`Output:Variable` with `*` keys. Each SQL is trimmed to the tables linking reads, then `VACUUM`ed.

The `(IDF, SQL, ERR)` triples are committed under `tests/fixtures/simulation/linked/`, with a total budget of
10 MB. Default CI tests read the fixtures and never need EnergyPlus (FR-044).

## R-20 Consumer register impact in idfkit-mcp

*Revised in revision 2.*

**Decision.** No impact. idfkit-mcp's dependency stays `idfkit==X`, an exact pin in `project.dependencies`, so the
consumer register needs no amendment. The earlier change to `idfkit[standards]==X` left with the standards layer.

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
| `ModelGraph` construction | — (stores its arguments) | ≤ 0.1 ms, with no layer built (FR-056) |
| `ModelGraph.neighbourhood`, 3 hops, up to 200 nodes, after the topology view is cached | — | ≤ 10 ms |
| Node-link export of the `model` and `topology` layers of the whole reference model | — | ≤ 1 s and ≤ 50 MB peak extra memory. A plan-level budget: export is a one-off developer call, not a question, so it has no SC. To be confirmed by benchmark in its slice |
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
9. **Bounded responses are a performance rule.** Every tool has a `limit` with a small default, summaries before
    detail, deduplication with counts, and the 8 KB default response budget. *Measured:* an existing unbounded
    response, `get_zone_properties` on all hospital zones, takes 87 ms and returns 110 KB.
10. **No blocking surprises in the server.** Every new tool's server-side work stays within the budgets above,
    so a call never holds the event loop longer than an existing read tool.

### Enforcement

- **Benchmarks in idfkit.** `benchmarks/bench_hvac_topology.py`, `bench_result_index.py` and `bench_graph.py`
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

## R-22 The developer API: public, typed and independent of the server

**Context.** Clarifications 6 to 9 (2026-11-11) make developers who use idfkit directly in Python a first-class
audience (User Story 7, FR-050 to FR-054). The layer designs in R-03 to R-11 already put every capability in
idfkit. This entry sets the rules that make that code a public API, not just an upstream for idfkit-mcp.

**Decision.**
- **One public surface per layer.** Each unit exports its public names from its package `__init__` and lists them
  in `__all__`: `idfkit.hvac`, `idfkit.simulation` (the linking names are re-exported) and `idfkit.graph`
  (R-23). Everything else lives in an underscore module or carries an
  underscore name. [contracts/idfkit-api.md](contracts/idfkit-api.md) is the full list.
- **The server uses only the public surface (FR-050).** idfkit-mcp gains a test, `tests/test_public_api_only.py`,
  that parses every module under `src/idfkit_mcp/` and fails on:
  - any import from an `idfkit` module whose path has an underscore segment
  - any imported `idfkit` name that starts with an underscore
  - any attribute access to an underscore attribute of an idfkit object (`doc._derived`, `topology._uses`)

  **checked:** idfkit-mcp passes this rule today. A grep of `src/` finds no private idfkit imports and no private
  attribute access, so the test starts green and only catches regressions.
- **Session concepts are arguments (FR-054).** No idfkit function reads session, server or global mutable state.
  The caller passes in the run identity (`run_revision` and `run_model_hash` on `ResultIndex.build`) and the
  `ResultIndex` itself, where a function needs results. The only process-wide state is the per-schema-version plan
  cache (R-21, decision 1), which holds no caller data.
- **Strict typing (FR-051).** Every public name passes pyright strict with no `# type: ignore`. Public containers
  are frozen, slotted dataclasses or `Literal` and `Enum` types, never `dict[str, Any]`. The node-link export
  (R-24) is the one place that returns JSON-shaped data, and it is typed with a recursive `JSONValue` alias.
- **Runnable documentation (FR-052, SC-014).** Each layer gets an agent-reference template and snippet in idfkit:
  `hvac-topology` and `model-graph` (R-23) are new, and `result-parsing`, `reference-tracking` and `hvac-loops`
  are updated. They are typed under the existing
  strict snippet environment, run in `tests/test_agent_references.py`, and are re-baked by the existing
  `check-baker` gate. The human reference pages live in **idfkit-developers**, idfkit's documentation repository,
  and embed the same snippets, so a page cannot show code the test suite has not run. One snippet,
  `model-graph.py:standalone-script`, is User Story 7's independent test written out. It loads a model, lists
  findings, traces a node and walks one component's neighbourhood, using only public names.
- **Stability (FR-053).** idfkit's existing policy applies: no breaking change within a major release, and a
  `DeprecationWarning` at least one minor release before a removal. Two existing gates make a silent break fail
  the build:
  - `scripts/check_naming_register.py` fails when a registered name disappears from the surface.
  - `scripts/check_parity_ledger.py` fails when a unit appears without a ledger row.

  Each new unit is recorded as Python-only until idfkit-js implements it.

**Rationale.** A real consumer is the best test of a public API. If idfkit-mcp is allowed to use private helpers,
the public API is designed around nothing. The AST test is about 40 lines of standard library code. It enforces
FR-050 mechanically, as Principle VII prefers, not by review alone.

**Alternatives considered.**
- An `idfkit.api` facade module re-exporting everything. Rejected: it duplicates `__all__` and gives two import
  paths for every name.
- Relying on review to keep idfkit-mcp off private names. Rejected: review is what let earlier string joins
  between results and the model through (report 03, §1).
- A separate snapshot file of the public surface. Rejected: the naming register is already the normative list,
  and a second list would drift from it.

## R-23 The combined graph view (`idfkit.graph`)

**Decision.**
- **What it is.** A new unit, `idfkit.graph`, with one class, `ModelGraph`. It is a read-only adapter over the
  layer APIs (FR-055, FR-056). It holds references to the layers and no copies of their data:
  - the document and its `ReferenceGraph`
  - the cached `HVACTopology` (R-05), fetched through `HVACTopology.from_document` on every walk, so it is always
    current
  - an optional `ResultIndex` passed in by the caller

  Construction does no work. `ModelGraph(doc, results=...)` stores its arguments and
  returns, which meets "costs nothing until first used".
- **Vocabulary.** It is fixed and documented, and it is the same in Python, in the export and in the server:

  | Node kind | Layer | Identity passed back to the layer APIs |
  |---|---|---|
  | `object` | `model` | `ObjectKey` |
  | `node` | `topology` | node name |
  | `result_fact` | `results` | owning `ObjectKey`, `metric` and `where` |
  | `message` | `results` | message kind and index within the run |

  | Edge kind | Layer | From → to |
  |---|---|---|
  | `reference` | `model` | object → object it names (field recorded) |
  | `flow` | `topology` | object → node (outlet) and node → object (inlet), with fluid and connection type |
  | `control` | `topology` | object → node it senses, sets or actuates |
  | `membership` | `topology` | component → loop object, with side, branch and position |
  | `result_link` | `results` | result fact or message → object or node, with the link confidence (R-07) |

  `object` is in the `model` layer because objects exist without any of the three new layers. Reference edges come
  from the existing `ReferenceGraph`. Its targets are resolved to typed `ObjectKey`s through the field's object
  list, never by name alone (the shared-names edge case).
- **Layers present.** `model` and `topology` are always present, since both are core and need no data.
  - `results` is present only when a `ResultIndex` is passed in.

  `ModelGraph.layers` lists the layers present. `ModelGraph.unavailable` maps each missing layer to its reason, for
  example `"results: no ResultIndex was passed in"`. A walk
  that asks for a kind from a missing layer returns no items of that kind and reports the reason. It never raises,
  because a partial graph is a valid graph (FR-056).
- **Walking.** `neighbourhood(start, *, hops=1, node_kinds=None, edge_kinds=None, max_nodes=200)` is an iterative
  breadth-first search over the union of the layers' adjacency. Each layer answers "neighbours of this graph node"
  from its own index:
  - references: `get_references_with_fields` and `get_referencing_edges`
  - topology: the integer adjacency lists of R-21
  - results: the per-object fact and message lists

  It returns a `Subgraph` with `nodes`, `edges`, `truncated`, `omitted_nodes` and `frontier`, the nodes whose
  neighbours were not expanded. Graph nodes and edges are built as dataclasses only for the items returned, per
  R-21, decision 2.
- **Freshness.** A `ResultIndex` that is stale for the document (R-06) is still walked. Every result node carries
  `stale: true`, and the subgraph reports `results_state`. Staleness is never hidden (FR-026).

**Rationale.**
- The three layers stay usable on their own (FR-055), and the view adds no domain logic, so Principle I and R-02
  hold.
- Adapting at walk time, instead of materialising one big graph, is what makes construction free and keeps memory
  flat. A materialised graph of HospitalLowEnergy would hold about 7k object nodes, 2.9k topology nodes and tens of
  thousands of edges per session, all duplicating the layers (FR-056 forbids that).
- `ModelGraph` is a capability unit, so it needs a parity-ledger and naming-register row (R-02). It is
  Python-only.
- **Extensible vocabulary (FR-056, revision 2).** `NodeKind`, `EdgeKind` and `Layer` are closed sets in a given
  release, and adding a member is a minor-version change under FR-053, never a breaking one. Code that matches on
  kinds is documented to ignore unknown members, and the node-link reader contract (R-24) says the same. That is
  what lets a future standards feature add `verdict` kinds and a `standards` layer.
- **Categories (R-36).** Object nodes carry their component `category` as an attribute, and `neighbourhood` takes
  an optional `categories` filter that keeps object nodes of those categories (and always the start).

**Alternatives considered.**
- `IDFDocument.graph()` as a method. Rejected: it would import every layer into `document.py` and tie the
  document to optional data.
- A materialised graph built eagerly per revision. Rejected as above, and it would need its own invalidation.
- Using networkx as the in-memory graph. Rejected under R-01. It is also slower to build than the integer
  adjacency already in place.
- A free-form edge vocabulary ("any field name is an edge kind"). Rejected: filters and the export format need a
  closed, versioned set. Field names travel as edge attributes instead.

## R-24 Node-link JSON export

**Decision.**
- **API.** `ModelGraph.to_node_link(...) -> dict[str, JSONValue]` builds the document. `write_node_link(...) ->
  str` serialises it, and `save_node_link(graph, path, ...) -> None` writes it to a file. This follows the family
  verbs: `write` returns text, `save` writes a path. All three take the same scope arguments, which bound the
  export (FR-057):
  - `layers`, `node_kinds`, `edge_kinds`
  - `start` with `hops`, for the neighbourhood of one object, with no node cap because the caller asked for it
- **Shape.** It is networkx's node-link layout, written with `json` from the standard library:

  ```json
  {
    "directed": true,
    "multigraph": true,
    "graph": {
      "format": "idfkit-model-graph", "format_version": 1,
      "idfkit_version": "…", "energyplus_version": "26.2.0",
      "layers": ["model", "topology"], "unavailable": {"results": "…"},
      "scope": {"start": null, "hops": null, "node_kinds": null, "edge_kinds": null},
      "results_state": null
    },
    "nodes": [{"id": "object:ZONE:SPACE1-1", "kind": "object", "layer": "model",
               "object_type": "Zone", "name": "SPACE1-1"}],
    "edges": [{"source": "…", "target": "…", "key": "reference:zone_name", "kind": "reference",
               "layer": "model", "field": "zone_name"}]
  }
  ```

  - **Identity.** The `id` is `"<kind>:<OBJECT TYPE UPPER>:<NAME UPPER>"` for objects, `"node:<NAME UPPER>"` for
    nodes, and a similar composite for facts and messages. It is stable across runs of the same model. The
    display spelling and the `ObjectKey` fields travel as attributes, so a developer can pass them back to the
    layer APIs (FR-057).
  - **Multigraph.** Two objects can be joined by both a reference and a flow edge, or by two references through
    different fields. `key` keeps them apart.
  - **Version.** `format_version` starts at 1. A change that removes or renames a key, or changes a kind's meaning,
    is a breaking change under FR-053. Adding an optional attribute is not.
- **The edge key is `"edges"`.** **checked during planning** against networkx's reader:

  | networkx | `node_link_graph(data)` with `"edges"` | with `"links"` |
  |---|---|---|
  | 3.6, 3.7 (current) | loads | `KeyError` |
  | 3.4, 3.5 | needs `edges="edges"` | loads |
  | 3.2 | needs `link="edges"` | loads |

  "Loads unchanged into networkx's node-link reader" can therefore hold for only one generation at a time. The
  current generation is chosen. The reference page states the one keyword older networkx needs. d3-force expects
  `links`, so the page also shows the one-line rename for JavaScript users. Writing both keys was rejected because
  it doubles the file and makes the two copies drift.
- **Gate.** idfkit's default test suite checks the format with the standard library (shape, unique ids, every edge
  endpoint is a node). A separate test marked `nodelink` loads the export of the reference model with networkx. CI
  runs it as `uv run --with "networkx>=3.6" pytest -m nodelink`, so networkx is **never** declared in idfkit's
  `pyproject.toml` or lock file, not even as a development dependency (R-01).
- **Not through the server.** idfkit-mcp exposes no export tool or resource (FR-058, Out of Scope).

**Rationale.** Node-link JSON is the one format both networkx and browser graph libraries read without a
converter. The standard library writes it. A `format_version` in the `graph` block lets the format evolve under
FR-053 without guessing from the shape.

**Alternatives considered.**
- GraphML or RDF. Out of scope (spec). The closed vocabulary of R-23 keeps them possible later.
- Emitting `links` for compatibility with networkx before 3.6. Rejected: current networkx rejects it, and the
  spec asks for the current reader to load the file unchanged.
- Adding networkx as an optional extra providing `to_networkx()`. Rejected: one more dependency, and the JSON
  loads in one call anyway.

## R-25 The neighbourhood tool in idfkit-mcp

**Decision.**
- **The tool.** `get_object_neighbourhood` (`_READ_ONLY`) builds a `ModelGraph` from the session:
  - the document
  - the session's `ResultIndex`, if the server ran a simulation in this session (FR-019)

  It returns `ModelGraph.neighbourhood(...)` mapped onto Pydantic mirrors. idfkit-mcp adds no node or edge kinds
  and no traversal logic. Its only job is mapping types and holding session state, as Principle I requires.
- **Bounds (FR-058).**
  - `hops` defaults to 1, with a maximum of 3.
  - `max_nodes` defaults to 40, with a maximum of 100.
  - `node_kinds` and `edge_kinds` are optional filters from the R-23 vocabulary.
  - The serialised response stays under 8 KB. When the walk exceeds a bound, the tool cuts it at the bound and
    reports `truncated`, `omitted_nodes` and the `frontier`, so the agent can continue from a frontier node.
  - The default of 40 nodes comes from the response budget: one node with attributes serialises to about
    120–160 bytes, and one edge to about 80–100 bytes. To be confirmed by the `perf` protocol test in the slice
    that adds the tool.
- **Not added.** No export tool and no export resource (FR-058). No "whole graph" mode: `start` is required.
- **Token cost.** One tool with six parameters (R-36 adds `categories`). It is measured with
  `scripts/token_audit.py` and counts toward the 15% cap of SC-010.

**Rationale.** The literature scan found that a bounded graph neighbourhood helps an LLM, while the whole graph
does not. The targeted tools kept by R-31 (`trace_hvac`, `get_object_results`) remain the precise, layer-specific
questions, on the condition R-31 sets. The neighbourhood tool is the one cross-layer question, for example "this zone: its
terminal, the coil upstream, the coil's sizing facts and the warnings linked to it" in one call.

**Alternatives considered.**
- No server tool, with the combined view available to Python only. Rejected in clarification 9.
- One tool per edge kind. Rejected: it adds listing cost for questions that `edge_kinds` already filters.
- A resource template `idfkit://model/graph/{type}/{name}`. Rejected as the primary interface: resources cannot
  take the hop and kind filters cleanly. It can be added later if clients ask for it.

---

---

## Revision 2: the spec review (2026-11-11)

The spec review added FR-004a, FR-013a, FR-016a, FR-040a, FR-040b, FR-042a to FR-042c, FR-046, FR-059, SC-001a,
SC-009a and SC-010a, and the standards layer was deferred. R-31 to R-37 decide how each is met.

## R-31 The tool surface (FR-059, SC-010, SC-010a)

**Decision.** The feature adds **six** tools, not thirteen:

| Tool | Story | Replaces in the earlier plan | Why it is not a special case of another tool |
|---|---|---|---|
| `trace_hvac` | US1, US4 | `trace_node` and `trace_component` | One addressing scheme (`object_type="Node"` or a component) like `get_object_neighbourhood`. Returns loop, side, branch, position and the controls acting on it already interpreted; the neighbourhood returns raw edges the agent must interpret. Kept on condition (below) |
| `get_hvac_topology` | US4 | — | Aggregates a whole loop into a compact chain. No walk produces that |
| `rename_node` | US4 | — | The only mutating tool |
| `get_object_results` | US3 | — | Adds deduplicated message counts, available variables and coverage that the neighbourhood's result nodes do not carry. Kept on condition (below) |
| `diagnose_symptom` | US6 | — | Ranking with evidence. Built only after the SC-009 gate |
| `get_object_neighbourhood` | US7 | — | The one cross-layer walk |

Changed, not new: `check_model_integrity` (a check group), `analyze_peak_loads` and the `idfkit://simulation/results`
resource (`affected_objects` fields). Resources added: `idfkit://model/hvac/{loop}` and
`idfkit://simulation/objects/{type}/{name}`. Resources are not in the tool listing.

**The condition on the two targeted tools.** In slice 4, when `get_object_neighbourhood` lands, the evaluation runs
an ablation (R-13) on the topology and results tasks: treatment with all tools, against treatment with
`trace_hvac` and `get_object_results` disallowed. A targeted tool stays only if removing it costs at least 20%
more tool calls or response tokens at no lower fix rate. Otherwise it is removed before the release that would
first publish it, so no deprecation is needed. Each tool's description names its nearest neighbour and when to use
it instead (FR-059).

**Budget.** About 2,300 tokens for six tools is about 380 per tool, the current mean. The two conditional tools
are the first cut if the slice 4 measurement exceeds the cap.

**Tool choice (SC-010a).** Each task declares `intended_tools`. The harness reports, for treatment runs, the share
of tasks whose intended tool was used, per tool.

**Rationale.** Tool-selection accuracy falls as the number of overlapping tools grows, and the cap measured in R-12
left about 175 tokens per tool for the earlier list. Fewer, broader tools meet the cap without stripping
descriptions.

**Alternatives considered.**
- Keep `trace_node` and `trace_component` separate. Rejected: they differ only in what the start is, which the
  neighbourhood tool already handles with one parameter.
- Neighbourhood only, no targeted tools. Not chosen yet: whether interpreted answers save calls is exactly what
  the slice 4 ablation measures.
- Exposing per-object results only as a resource. Rejected: several clients do not let the model read resources
  on its own initiative.

## R-32 Evaluation statistics (FR-042a, SC-008, SC-009)

**Decision.**
- **Repeats.** Every task runs 3 times per condition (`--repeat 3` is the default). A task's score in a condition
  is the mean of its repeats: fix rate, tool calls, tokens.
- **Paired comparison.** Differences are computed per task (treatment minus baseline) and summarised by their
  mean. The 95% confidence interval is a percentile bootstrap over tasks, 10,000 resamples, with the seed recorded
  in `run.json`. It is computed overall, per layer and per fault type.
- **Per-type figures.** A fault type whose interval includes zero is shown as descriptive and flagged as such in
  `summary.md`. SC-009 is decided on the pooled tasks of the relevant layer, not per type.
- **Gate verdict.** `summary.md` states the SC-009 verdict with each clause: effect size against 20 points or 30%
  fewer calls, interval excludes zero, direction on held-out types, unwanted changes, false fixes on controls.
- **Repeatability (SC-008).** The spread is the range of the overall fix rate across the 3 repeat passes of one
  run. A second run is not needed to check it.

**Rationale.** With about 20 tasks per fault type and one run, the standard error of a fix rate near 50% is about
11 points, wider than the effects the gate looks for. Pooling by layer and repeating three times brings the
interval for a layer of about 50 tasks to roughly ±8 points, enough to see a 20-point effect. A bootstrap needs no
distributional assumption and no third-party library.

**Cost.** About 100 tasks × 3 repeats × 2 conditions is about 600 agent runs for a full evaluation. Per-slice runs
(FR-046) cover only that slice's fault types and controls, about 150 to 250 runs.

## R-33 Held-out faults (FR-040a)

**Decision.**
- **Who and when.** Held-out fault types are written by a maintainer who does not write connection checks or
  result linking for this feature, and committed to `eval/faults/held_out/` before slice 1's first check lands.
- **Enforced by git.** `eval list-faults --check-held-out` compares, for each held-out fault file, the commit that
  first added it with the first commit that added `idfkit.hvac.checks` at the idfkit level the treatment pins. A
  held-out fault added later is reported as `held_out_invalid` and counted with the designed faults. The check is
  run by the harness at the start of every run.
- **Sources.** In order of preference: failures in idfkit-mcp agent transcripts the maintainer already holds and
  may use (stored without model content); failure categories in published LLM model-generation studies (wrong
  object references in Zhang, Chen and Ford 2024; debugging failures in the OSTI agentic workflow); faults
  modellers report in idfkit and idfkit-mcp issues.
- **Reporting.** Held-out types are a separate table in `summary.md`, and the SC-009 direction clause reads it.

**Rationale.** If every fault is one a check was written for, the treatment wins by calling that check. Separating
the authors and dating the commits makes "held out" a property anyone can verify, not a promise.

**Alternatives considered.**
- Generating faults with an LLM. Not excluded as a source, but its faults count as held out only under the same
  authorship and date rule.

## R-34 Earlier-version corpora (FR-013a, SC-001a)

**Decision.**
- **Corpora.** The ExampleFiles of EnergyPlus **9.6.0** (the last 9.x release idfkit supports) and **23.2.0**.
  Both are in idfkit's version registry.
- **Measurement.** The corpus test takes repeatable `--corpus VERSION=PATH` pytest options, so a maintainer points
  it at each installation's ExampleFiles. No new environment variable is read (idfkit's environment-variable rule
  applies to `src/` only, but the option keeps the test explicit). For each version and check it records models,
  findings and false findings.
- **The warning cap.** The measurement writes a committed table, `idfkit/hvac/_version_caps.py`, mapping
  `(check id, schema version)` to a maximum severity. At run time a check's severity is capped for a model whose
  version is in the table with a false finding. Versions between two measured ones take the cap of the nearest
  older measured version; versions older than 9.6 take 9.6's.
- **Publication.** The release notes of each idfkit release that changes the table list the false-finding rate per
  version and check.

**Rationale.** Most models agents receive are older than the latest release. Measuring two points, one per major
series, finds version-specific field layouts without the cost of seventeen corpora. Capping by measurement keeps
the clarification (26.2 qualifies checks) while stopping a known false error from reaching an older model.

**Alternatives considered.**
- Migrating older models to 26.2 before checking. Rejected: migration needs EnergyPlus, and the check must work
  offline (FR-006).
- Measuring every supported version. Deferred: the cost is a maintainer afternoon per version; two are enough to
  see whether the problem exists.

## R-35 Coverage and blind spots (FR-004, FR-004a)

**Decision.** One shared `Coverage` shape is returned by every graph-answering tool and function:
`{partial: bool, uncovered: list[{kind, count, examples, reason}], resolved, unresolved}`. The `uncovered` kinds
are a closed set:
- `hvac_template`: unexpanded `HVACTemplate:*` systems (R-17)
- `ems_program`: `EnergyManagementSystem:Program` and `:Subroutine` objects, whose Erl text is not parsed
- `unclassified_type`: object types with no connection rule (R-04, unknown types)
- `unlinked_result`: result items listed as unresolved (R-07)

**EMS sensors and actuators.** `EnergyManagementSystem:Sensor` key names and `EnergyManagementSystem:Actuator`
component names are resolved to objects of a type compatible with the sensed variable or actuator component type
where the schema allows, and linked with confidence `convention` and rule `ems_key`. They become `control` edges
in the graph. Unresolved ones are listed. Program text is never searched for names.

**Rationale.** An agent must tell "nothing found" from "not looked at" (FR-004a). EMS is the most common way a
model's behaviour departs from what its objects say, and it is invisible to every layer otherwise.

## R-36 Component categories (FR-016a)

**Decision.** A committed table, `idfkit/hvac/_categories.py`, maps object types to a closed `ComponentCategory`
vocabulary by exact type or by type prefix: `heating_coil` (`Coil:Heating:*`, and the heating halves of
`Coil:*:WaterToAirHeatPump:*` by type name), `cooling_coil` (`Coil:Cooling:*`), `fan` (`Fan:*`), `pump`
(`Pump:*`, `HeaderedPumps:*`), `terminal_unit` (`AirTerminal:*`, `ZoneHVAC:AirDistributionUnit`), `chiller`
(`Chiller:*`), `boiler` (`Boiler:*`), `heat_rejection` (`CoolingTower:*`, `FluidCooler:*`,
`EvaporativeFluidCooler:*`), `humidifier` (`Humidifier:*`), `heat_exchanger` (`HeatExchanger:*`), `zone_equipment`
(`ZoneHVAC:*` not listed above), `unitary` (`AirLoopHVAC:Unitary*`, `AirLoopHVAC:UnitarySystem`), `outdoor_air`
(`AirLoopHVAC:OutdoorAirSystem*`, `OutdoorAir:*`), `setpoint_manager` (`SetpointManager:*`), `controller`
(`Controller:*`), `other`. A coverage test lists every node-bearing type without a category, and the table is
reviewed when rules are regenerated.

Categories are exposed on `NodeUse` owners, in `trace_hvac` and in graph object nodes, and as a `categories`
filter on `trace_hvac` (upstream and downstream walks) and on `get_object_neighbourhood`.

**Rationale.** Questions such as "every heating coil upstream of this zone" cross many object types. The category
comes from the type alone, never from names, so it is a fact, not an inference (Principle III). It also gives a
later Brick export its equipment classes.

## R-37 Diagnosis anchoring (FR-027, SC-009a)

**Decision.** In addition to R-16's revised output:
- Every diagnosis fault in the catalogue has at least one variant whose true cause lies outside the rule families
  (for example an EMS actuator overriding a setpoint). It is a held-out type under R-33 where possible.
- The harness records, for treatment runs that call `diagnose_symptom`, whether the agent's first model change
  targeted the top-ranked candidate, and whether that was the injected object. SC-009a compares the rate of
  "changed a wrong top candidate" with the baseline rate of "changed a wrong object first".
- Slice 6 does not merge with SC-009a failing.

**Rationale.** A ranked list is a strong suggestion to an agent. Measuring wrong fixes made on its advice is the
only way to see whether diagnosis helps or anchors.
