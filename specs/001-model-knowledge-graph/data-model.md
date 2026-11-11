# Data Model: Model Knowledge Graph for Agents

Phase 1 output of `/speckit-plan`, revision 2 (2026-11-11): the standards layer is deferred
([deferred-standards.md](deferred-standards.md)), and the review requirements are added (research R-31 to R-37).
The entities come from the spec's Key Entities. Each one is defined in two
places:

- **idfkit** (core): a frozen, slotted dataclass. Standard library only, pyright strict.
- **idfkit-mcp**: a Pydantic model that mirrors the dataclass for the wire (Constitution Principle II).

Pydantic models only rename for clarity. They never add domain fields.

Common identity: an object is identified by **`ObjectKey(object_type, name)`**, compared case-insensitively. A
node is identified by its name, compared case-insensitively. Responses always use the model's own spelling.

**The dataclasses below are the public, returned shape, not the storage.** Performance is a requirement (spec
FR-009), and building a frozen dataclass costs 9.5× a tuple. Derived views therefore store compact integer-indexed
tuples, as set out in [Internal representation](#internal-representation-performance). Dataclasses are built only
for the bounded set of items a call returns (research R-21).

---

## Shared

### ObjectKey

| Field | Type | Rule |
|---|---|---|
| `object_type` | `str` | A schema object type, or the pseudo-types `Node` and `Aggregate` |
| `name` | `str` | Display spelling. Equality and hashing use `name.upper()` |

### Coverage

Attached to every response that answers from the graph: matching, linking, inference or walking (FR-004,
FR-004a, research R-35). One shape everywhere.

| Field | Type | Rule |
|---|---|---|
| `partial` | `bool` | True when `uncovered` is not empty |
| `uncovered` | `list[UncoveredPart]` | What the answer did not look at. Empty means the whole model was covered |
| `resolved` / `unresolved` | `int \| None` | For linking. `None` elsewhere |

### UncoveredPart

| Field | Type | Rule |
|---|---|---|
| `kind` | `"hvac_template" \| "ems_program" \| "unclassified_type" \| "unlinked_result"` | Closed set. Adding a kind is a minor change (FR-053) |
| `count` | `int` | Objects or items of this kind left out |
| `examples` | `list[ObjectKey]` | At most 3. For `unlinked_result`, the raw keys as `ObjectKey("Unresolved", key)` |
| `reason` | `str` | One sentence, for example "EMS program text is not parsed; what it controls is not visible" |

The kinds:
- `hvac_template`: unexpanded `HVACTemplate:*` systems (R-17)
- `ems_program`: `EnergyManagementSystem:Program` and `:Subroutine` objects
- `unclassified_type`: object types with node fields but no connection rule (T090)
- `unlinked_result`: result items listed as unresolved (R-07)

### Bounded list envelope

Every list response carries `items`, `total` and `omitted` (FR-003). `omitted = total - len(items)`.

---

## Layer 1: HVAC topology (`idfkit.hvac`)

### ConnectionType (enum)

Mirrors EnergyPlus: `Inlet`, `Outlet`, `Internal`, `ZoneNode`, `Sensor`, `Actuator`, `OutsideAir`,
`ReliefAir`, `ZoneInlet`, `ZoneReturn`, `ZoneExhaust`, `Setpoint`. Flow roles are `Inlet`, `Outlet`,
`ZoneInlet`, `ZoneReturn` and `ZoneExhaust`. Control roles are `Sensor`, `Actuator` and `Setpoint`. Boundary
roles are `OutsideAir` and `ReliefAir`.

### Fluid (enum)

`Air`, `Water`, `Steam`, `Refrigerant`, `Unknown`.

### ComponentCategory (enum)

`heating_coil`, `cooling_coil`, `fan`, `pump`, `terminal_unit`, `chiller`, `boiler`, `heat_rejection`,
`humidifier`, `heat_exchanger`, `zone_equipment`, `unitary`, `outdoor_air`, `setpoint_manager`, `controller`,
`other`. Derived from the object type alone, through the committed table `_categories.py` (research R-36). Never
from names. A node-bearing type missing from the table is `other`, and a coverage test lists such types. Adding a
member is a minor change (FR-053).

### PortRule

Generated and curated table rows. Internal, not on the wire.

| Field | Type | Rule |
|---|---|---|
| `object_type` | `str` | |
| `field` | `str` | Python field name. Extensible sub-fields use `group.field` |
| `connection` | `ConnectionType` | |
| `stream` | `int` | ≥ 1. Pairs an inlet with an outlet of the same fluid |
| `fluid` | `Fluid` | |
| `is_parent` | `bool` | Parent uses add no flow edges |
| `accepts_nodelist` | `bool` | |
| `when` | `tuple[str, str] \| None` | Value predicate, for example `("condenser_type", "AirCooled")` |
| `provenance` | `"eplus_examples" \| "eplus_test_model" \| "hand_written"` | Where the rule came from (FR-010a). `hand_written` rules can never yield an error-severity finding |

### NodeUse

One field of one object naming a node (spec: *Node use*).

| Field | Type | Rule |
|---|---|---|
| `node` | `str` | Display spelling |
| `object` | `ObjectKey` | |
| `category` | `ComponentCategory` | The owner's category (R-36) |
| `field` | `str` | |
| `connection` | `ConnectionType \| None` | `None` means unclassified, which yields an info finding |
| `stream` | `int` | |
| `fluid` | `Fluid` | |
| `is_parent` | `bool` | |
| `via_nodelist` | `str \| None` | The NodeList name when reached through one |
| `rule` | `str \| None` | `ems_key` for an EMS sensor or actuator use (R-35). `None` for port rules |
| `provenance` | `"eplus_examples" \| "eplus_test_model" \| "hand_written" \| None` | From the rule. `None` when unclassified |

### LoopMembership

| Field | Type | Rule |
|---|---|---|
| `loop` | `ObjectKey` | `AirLoopHVAC`, `PlantLoop` or `CondenserLoop`. Zone equipment uses the `ZoneHVAC:EquipmentConnections` key |
| `kind` | `"air" \| "plant" \| "condenser" \| "zone_equipment"` | |
| `side` | `"supply" \| "demand" \| None` | `None` for zone equipment |
| `branch` | `ObjectKey \| None` | |
| `position` | `int \| None` | 0-based index on the branch |
| `stream` | `int` | The component stream that carries this membership |

A component may have several memberships. A water coil, for example, is on an air loop and on the demand side of
a water loop (FR-011).

### FlowEdge

| Field | Type | Rule |
|---|---|---|
| `source` / `target` | `ObjectKey` | Non-parent components, or a zone |
| `node` | `str` | The node they share |
| `fluid` | `Fluid` | |
| `kind` | `"component" \| "branch_junction" \| "zone"` | `branch_junction` edges come from Splitter and Mixer rules |

### TopologyFinding

Spec: *Connection finding*.

| Field | Type | Rule |
|---|---|---|
| `code` | `str` | Stable code from the table below |
| `severity` | `"error" \| "warning" \| "info"` | The effective severity, after the version cap. Only qualified codes may be `error` (FR-013) |
| `capped_from` | `"error" \| None` | Set when the version cap lowered the severity (FR-013a) |
| `cap_reason` | `str \| None` | For example "T011 produced false errors on the EnergyPlus 9.6 example files" |
| `objects` | `list[ObjectKey]` | At least one, or `node` set (FR-002) |
| `node` | `str \| None` | |
| `field` | `str \| None` | |
| `expected` / `actual` | `str \| None` | For mismatch findings |
| `message` | `str` | |
| `provenance` | `str` | The weakest provenance among the rules the finding relied on |

| Code | Check (FR-012) | Initial severity |
|---|---|---|
| T001 | Flow inlet with no matching outlet or boundary, and not a loop inlet | warning |
| T002 | Zone inlet that nothing supplies | warning |
| T003 | Zone exhaust that nothing draws from | warning |
| T004 | Setpoint, sensor or actuator node with no flow use | warning |
| T010 | A branch's listed nodes differ from the component's own ports | **error** (qualified by the prototype; re-qualified on 26.2) |
| T011 | Consecutive branch components are not connected | **error** (same) |
| T030 | Node used on only one side, with no boundary rule explaining it | warning |
| T090 | Object type with node fields but no connection rule (`unclassified`) | info |
| T091 | Template system present; topology not covered | info |

**State transition, severity qualification:** `warning → error` happens only when the 26.2 corpus test (R-18)
reports zero findings for that code. The promotion is recorded in idfkit's CHANGELOG. `error → warning` happens
when a reported false finding is reproduced, and it must come with a regression test.

**Effective severity, per model version (FR-013a, research R-34).** The committed table `_version_caps.py` maps
`(code, schema version)` to a maximum severity, written by the earlier-version corpus measurement (9.6.0 and
23.2.0). For a model of version *v*, the cap is the entry for the nearest measured version at or below *v*;
versions older than 9.6.0 take 9.6.0's entry, and 26.2 has no cap. The effective severity is
`min(qualified severity, cap)`. When the cap lowers it, `capped_from` and `cap_reason` say so. The table changes
only with a new measurement, and the release notes list the rates.

### VersionCap

A row of `_version_caps.py`. Internal, not on the wire.

| Field | Type | Rule |
|---|---|---|
| `code` | `str` | A check code |
| `version` | `str` | A measured schema version, `9.6.0` or `23.2.0` |
| `max_severity` | `"warning" \| "info"` | |
| `models` / `false_findings` | `int` | The measurement behind the row |

### HVACTopology

A derived view, not stored. Built by `from_document(doc)`. Cached per `(document, revision)`.

### HVACTrace

The answer to one trace, from a node or from a component (`trace_hvac`, research R-31). Built only for the start
asked for, never stored.

| Field | Type | Rule |
|---|---|---|
| `start` | `ObjectKey` | `object_type="Node"` for a node start. A component start carries its `category` |
| `fluid` | `Fluid \| None` | Node start only |
| `ports` | `list[NodeUse]` | Component start only, grouped by stream |
| `producers`, `consumers` | `list[ObjectKey]` | Node start only |
| `controls` | `list[NodeUse]` | Sensor, setpoint and actuator uses, EMS uses included (rule `ems_key`) |
| `memberships` | `list[LoopMembership]` | Every loop the start touches |
| `parent`, `children` | `ObjectKey \| None`, `list[ObjectKey]` | Component start only |
| `upstream`, `downstream` | `list[FlowEdge]` | Bounded by `hops`, filtered by `categories` when given |
| `findings` | `list[TopologyFinding]` | Only those touching the start, severities after the version cap |
| `coverage` | `Coverage` | |

### Node rename result

| Field | Type |
|---|---|
| `old` / `new` | `str` |
| `fields_updated` | `int` |
| `objects` | `list[ObjectKey]` |

Validation: refuses when `new` is empty, equals `old`, or is already used as a node name elsewhere. Merging nodes
is never implicit.

---

## Layer 2: Results attached to the model (`idfkit.simulation.linking`)

### Resolution

Spec: *Result link*.

| Field | Type | Rule |
|---|---|---|
| `key` | `ObjectKey \| None` | `None` means unresolved |
| `rule` | `str` | `exact`, `typed`, `zonelist_composite`, `space_to_zone`, `mirrored_shading`, `aggregate`, `ideal_loads_suffix`, `ems_key`, `substring` |
| `confidence` | `"exact" \| "typed" \| "convention" \| "weak"` | `substring` is always `weak` (FR-005). `ems_key` is always `convention` |
| `via` | `tuple[ObjectKey, ...]` | A zone-list composite links to both the zone and the load object |

### ResultFact

| Field | Type | Rule |
|---|---|---|
| `source` | `"sizing" \| "tabular" \| "timeseries_stat"` | |
| `metric` | `str` | Snake-case, for example `design_capacity_w` or `unmet_heating_hours` |
| `value` | `float \| str \| None` | |
| `units` | `str \| None` | |
| `where` | `str` | `Report/Table/Row/Column`, or `ComponentSizes#<id>` |
| `multiplier` | `int \| None` | Required for zone facts (FR-025) |

### LinkedMessage

| Field | Type | Rule |
|---|---|---|
| `severity` | `"info" \| "warning" \| "severe" \| "fatal"` | From the SQL `Errors.ErrorType` |
| `kind` | `str` | Catalogue id, or `other` |
| `text` | `str` | First line only. Details are available on request |
| `objects` | `list[Resolution]` | |
| `occurrences` | `int` | From `Errors.Count` |
| `first_seen` | `str \| None` | `"<environment> MM/DD HH:MM"` when EnergyPlus reports it |

### MessageKind

A catalogue row. Internal data, version-tested.

| Field | Type |
|---|---|
| `kind` | `str` |
| `pattern` | regex with named groups `type`, `name` and `key` |
| `hint` | `str` (likely causes, one sentence) |
| `inspect` | `tuple[str, ...]` (neighbour object types to check) |
| `symptoms` | `tuple[str, ...]` (symptoms this kind can explain) |

### ResultIndex

Built by `ResultIndex.build(doc, result)`.

| Field | Type |
|---|---|
| `facts` | `dict[ObjectKey, list[ResultFact]]` |
| `series` | `dict[ObjectKey, list[VariableInfo]]` (keys only, never data) |
| `messages` | `list[LinkedMessage]` |
| `unresolved` | `list[tuple[str, str]]` (source, raw key) |
| `run_revision` / `run_model_hash` | `int` / `str` |

**State: freshness.** An index is `fresh` when the document revision equals `run_revision` and the model's text
hash equals `run_model_hash`. Otherwise it is `stale` (FR-026). Staleness is reported on every response and never
blocks one.

### CandidateCause

| Field | Type | Rule |
|---|---|---|
| `object` | `ObjectKey` | |
| `rank` | `int` | 1-based. A `weak`-only candidate is never rank 1 (FR-027) |
| `reason` | `str` | |
| `evidence` | `list[ResultFact \| str]` | At least one |
| `verify` | `str` | The next request that confirms it or rules it out |
| `weight_basis` | `str` | The catalogue rule and graph distance that produced the rank |
| `family` | `str` | The cause family of the rule, for example `capacity` or `availability` |
| `evidence_strength` | `"strong" \| "moderate" \| "weak"` | `strong`: a linked value past the rule's threshold, or a connection finding. `moderate`: a linked value within it, or a typed or convention link. `weak`: free text only (research R-16) |

Symptoms: `unmet_heating`, `unmet_cooling`, `peak_outlier`, `sizing_zero`, `message:<kind>`.

### Diagnosis

Returned by `diagnose(...)`. Fields in this order, so the statement is read first (FR-027).

| Field | Type | Rule |
|---|---|---|
| `statement` | `str \| None` | Set when `no_strong_candidate`, for example "No candidate has strong evidence; the causes below are possibilities only" |
| `no_strong_candidate` | `bool` | True when no candidate is `strong` |
| `symptom` / `target` | `str` / `ObjectKey \| None` | |
| `candidates` | `list[CandidateCause]` | Bounded, ranked |
| `families_covered` | `list[str]` | The cause families the rules examine for this symptom. A cause outside them was not examined |
| `shared_upstream` | `list[ObjectKey]` | Objects common to every affected object |
| `coverage` | `Coverage` | |
| `results_state` | `"fresh" \| "stale"` | |

---

## Layer 3: Standards knowledge (deferred)

Deferred to a future spec. See [deferred-standards.md](deferred-standards.md).

---

## Combined graph view (`idfkit.graph`)

Spec: *Model graph view* (FR-055 to FR-058). It is a read-only adapter over the layers, with no storage of its own
(research R-23).

### NodeKind and EdgeKind (closed `Literal` vocabularies)

| Kind | Layer |
|---|---|
| node kind `object` | `model` |
| node kind `node` | `topology` |
| node kinds `result_fact`, `message` | `results` |
| edge kind `reference` | `model` |
| edge kinds `flow`, `control`, `membership` | `topology` |
| edge kind `result_link` | `results` |

`Layer = Literal["model", "topology", "results"]`. The sets are closed within a release. **Adding** a kind or a
layer is a minor change, never a breaking one, and code that reads kinds must ignore members it does not know
(FR-056, research R-23). That is how a later feature adds, for example, a `standards` layer with `verdict` kinds.
Removing or redefining a kind is breaking (FR-053).

EMS sensor and actuator uses (rule `ems_key`) appear as `control` edges, with `confidence: "convention"` (R-35).

### GraphNode

| Field | Type | Rule |
|---|---|---|
| `id` | `str` | Stable composite id (research R-24). Upper-cased names, so equal ids mean equal identity |
| `kind` | `NodeKind` | |
| `layer` | `Layer` | Fixed by `kind` |
| `key` | `ObjectKey \| None` | Set for `object`, and for the owner of a `result_fact` |
| `node` | `str \| None` | Set for `node`, with the model's spelling |
| `label` | `str` | Short display text, for example `Zone "SPACE1-1"` or `unmet_heating_hours = 312 h` |
| `attrs` | `Mapping[str, str \| int \| float \| bool \| None]` | Kind-specific scalars only, for example `category` (object nodes, R-36), `fluid`, `metric`, `value`, `units`, `severity`, `stale` |

### GraphEdge

| Field | Type | Rule |
|---|---|---|
| `source` / `target` | `str` | Graph node ids. Direction as in the edge table of research R-23 |
| `kind` | `EdgeKind` | |
| `layer` | `Layer` | Fixed by `kind` |
| `key` | `str` | Unique among edges with the same endpoints, for example `reference:zone_name` or `flow:air_outlet_node_name` |
| `attrs` | `Mapping[str, str \| int \| float \| bool \| None]` | `field`, `connection_type`, `fluid`, `side`, `branch`, `position`, `rule`, `confidence`, `provenance` (FR-010a), as applicable |

### Subgraph

Returned by `ModelGraph.neighbourhood`.

| Field | Type | Rule |
|---|---|---|
| `start` | `str` | Graph node id |
| `nodes` / `edges` | `list[GraphNode]` / `list[GraphEdge]` | Breadth-first order from `start` |
| `layers` | `list[Layer]` | Layers present in the view |
| `unavailable` | `dict[Layer, str]` | Each missing layer and why (FR-056) |
| `coverage` | `Coverage` | What the walk could not see: templates, EMS programs, unclassified types, unlinked results (R-35) |
| `truncated` | `bool` | True when a hop or node bound cut the walk |
| `omitted_nodes` | `int` | Nodes reached but not returned. A lower bound, since the walk stops at the cut |
| `frontier` | `list[str]` | Returned node ids whose neighbours were not expanded |
| `results_state` | `"fresh" \| "stale" \| None` | `None` when the results layer is absent |

**State: which layers are present.** It is decided per call, not stored:
- `model` and `topology`: always present.
- `results`: present when a `ResultIndex` was given, whether fresh or stale. Stale facts are marked, not dropped.
  Otherwise it is listed in `unavailable` with the reason.

**Category filter.** `neighbourhood(..., categories=...)` keeps object nodes whose `category` is in the set, plus the
start and any non-object node that lies on a kept path. The filter applies before the node bound.

### Node-link document

This is the export, a JSON object. Its normative definition is in
[contracts/node-link-json.md](contracts/node-link-json.md). The top-level keys are `directed`, `multigraph`,
`graph`, `nodes` and `edges`. Each element of `nodes` and `edges` is a `GraphNode` or `GraphEdge` flattened:
`attrs` is merged into the element, and `key` becomes `object_type` and `name`.

---

## Evaluation (idfkit-mcp `eval/`, not shipped)

Research R-13, R-14 and R-31 to R-33, R-37.

### FaultType

| Field | Type | Rule |
|---|---|---|
| `id` | `str` | Stable |
| `layer` | `"topology" \| "results"` | |
| `description` | `str` | For maintainers. Never shown to the agent |
| `held_out` | `bool` | True for faults under `eval/faults/held_out/` (FR-040a) |
| `defined_in_commit` | `str` | The commit that first added the fault file. Checked against the first check commit (R-33) |
| `applies_to` | `list[str]` | Reference-model tags the fault can be injected into |
| `scope` | `list[ObjectKey]` | Filled by `inject`. Changes outside it count as unwanted |
| `intended_tools` | `list[str]` | The new tools the fault was built for, for SC-010a. Empty for held-out faults |
| `prompt_template` | `str` | Symptom-only (FR-042b). Linted for object names, field names and banned words |
| `needs_energyplus` | `bool` | |
| `inject(doc) -> InjectedFault` / `verify(doc, result \| None) -> bool` | | |

`held_out_invalid` is a derived status: a held-out fault whose `defined_in_commit` is later than the first
connection-check commit. It is reported and counted with the designed faults.

### EvaluationTask

| Field | Type | Rule |
|---|---|---|
| `id` | `str` | |
| `kind` | `"fault" \| "control" \| "authoring" \| "question"` | FR-040b |
| `fault_id` | `str \| None` | For `fault` tasks |
| `model_file` | `str` | A reference model |
| `prompt` | `str` | Rendered from a template. Never names the injected object, field or fault |
| `answer_key` | `str \| None` | For `question` tasks, computed by idfkit from the unmodified model and committed |
| `success` | `str` | How success is decided: fault fixed and verified, no change (control), connection check clean and simulates (authoring), answer matches the key (question) |
| `intended_tools` | `list[str]` | Copied from the fault type, or set per authoring and question task |

### TaskSpec

The definition of a non-fault task (`control`, `authoring`, `question`), one per module or table entry under
`eval/tasks/`. Fault tasks are defined by `FaultType`.

| Field | Type | Rule |
|---|---|---|
| `id` | `str` | Stable |
| `kind` | `"control" \| "authoring" \| "question"` | FR-040b |
| `layer` | `"topology" \| "results"` | |
| `applies_to` | `list[str]` | Reference-model tags |
| `prompt_template` | `str` | Symptom- or goal-only, linted like fault prompts (FR-042b) |
| `intended_tools` | `list[str]` | Empty for controls |
| `needs_energyplus` | `bool` | True for authoring tasks, which must simulate |
| `verify(doc, result \| None) -> bool` | | Authoring: no error finding and the model simulates. Question: the answer matches `answer_key(doc)`, computed by idfkit from the unmodified model and committed |

### TaskOutcome

One per task, condition and repeat.

| Field | Type | Rule |
|---|---|---|
| `task_id` / `condition` / `repeat` | `str` / `"baseline" \| "treatment" \| "ablation"` / `int` | `repeat` is 0-based |
| `fixed` | `bool` | Success under the task's rule |
| `verified_by` | `"check" \| "simulation" \| "answer_key" \| "skipped"` | |
| `skip_reason` | `str \| None` | Required when skipped (FR-043) |
| `tool_calls` / `response_tokens` | `int` | |
| `unwanted_changes` | `int` | Objects changed outside the fault's scope |
| `false_fix` | `bool` | Control tasks: any model change or any reported fault |
| `tools_used` | `list[str]` | New tools called, in order |
| `intended_tool_used` | `bool \| None` | Treatment runs only (SC-010a) |
| `top_candidate_edited` / `top_candidate_correct` | `bool \| None` | Set when `diagnose_symptom` was called: whether the first model change targeted rank 1, and whether rank 1 was the injected object (SC-009a) |
| `transcript_path` | `str` | |

### EvaluationRun

| Field | Type | Rule |
|---|---|---|
| `run_id` / `started_at` | `str` | |
| `runner_command` / `model_identifier` | `str` | Recorded so runs are comparable |
| `baseline_kind` | `"pre_feature" \| "other"` | `other` runs never decide SC-009 (FR-042c) |
| `baseline_sha` / `baseline_idfkit` | `str` | The idfkit-mcp commit and idfkit level of the baseline |
| `treatment_revision` | `str` | |
| `disallowed_tools` | `list[str]` | Non-empty only for ablation runs (R-31) |
| `repeats` | `int` | At least 3 (FR-042a) |
| `bootstrap_seed` / `bootstrap_resamples` | `int` | For the confidence intervals (R-32) |
| `outcomes` | `list[TaskOutcome]` | |

### Comparison

One per metric and scope, computed from paired task means (R-32).

| Field | Type | Rule |
|---|---|---|
| `scope` | `str` | `overall`, a layer, a fault type, `held_out` or `control` |
| `metric` | `"fix_rate" \| "tool_calls" \| "response_tokens" \| "unwanted_changes" \| "false_fix_rate" \| "wrong_top_candidate_rate"` | |
| `tasks` | `int` | Paired tasks in the scope |
| `baseline` / `treatment` / `difference` | `float` | Means over tasks |
| `ci_low` / `ci_high` | `float` | 95% percentile bootstrap |
| `descriptive_only` | `bool` | True when the interval includes zero for a fault-type scope |

### GateVerdict

The SC-009 decision in `summary.md`.

| Field | Type | Rule |
|---|---|---|
| `effect` | `"fix_rate" \| "tool_calls" \| None` | The clause that passed, if any |
| `ci_excludes_zero` | `bool` | |
| `held_out_direction` | `bool` | The gain holds in direction on held-out faults |
| `no_more_unwanted_changes` / `no_more_false_fixes` | `bool` | |
| `wrong_top_candidate_ok` | `bool \| None` | SC-009a, when diagnosis tasks ran |
| `valid` | `bool` | False when `baseline_kind` is `other` or the run is an ablation |
| `passes` | `bool` | All clauses true and `valid` |

---

## Session state (idfkit-mcp)

The session file moves from version 1 to version 2 (research R-15). It adds two fields and nothing else.

| Field | Type | Rule |
|---|---|---|
| `simulation_model_hash` | `str \| None` | SHA-256 of the IDF text written for the session's last run (R-06) |
| `simulation_run_dir` | `str \| None` | The run directory, so linking can resume after a restart |

Version-1 files load with both fields `None`, which means no simulation recorded. Nothing is written into model
files.

---

## Internal representation (performance)

This section is normative for idfkit's implementation (research R-21). It is not part of any public contract.

### Derived-view cache on `IDFDocument`

| Slot | Type | Rule |
|---|---|---|
| `_revision` | `int` | Bumped by every mutation path (R-06) |
| `_derived` | `dict[str, tuple[int, object]]` | View name to `(revision at build, view)`. A view is valid only while its revision equals `_revision`. The slot is freed with the document; there is no global registry |

### Topology view (`hvac` cache entry)

| Structure | Type | Contents |
|---|---|---|
| `node_id` | `dict[str, int]` | Upper-cased node name to a dense id |
| `node_name` | `list[str]` | Display spelling by id |
| `obj` | `list[IDFObject]` | Node-bearing objects by dense object id. Other objects are never visited |
| `uses` | `list[list[tuple[int, int, int, int]]]` | Per node: `(object id, field-plan index, connection code, stream)` |
| `out_adj` / `in_adj` | `list[list[int]]` | Per object: downstream and upstream object ids (flow edges only) |
| `findings` | `list[tuple[int, int, int, int, int]]` | `(code index, severity code, object id, node id or -1, field-plan index or -1)` |
| `memberships` | `dict[int, list[tuple[...]]] \| None` | Built on first request, then memoised |
| `chains` | `dict[tuple[int, int], list[list[int]]]` | Per (loop object id, side), built on first request |

**Per-type plans** (module-level cache keyed by schema version): object type to `(top-level fields, extensible
wrapper key, extensible fields)`, each field paired with its compiled rule `(connection code, stream, fluid code,
is_parent, accepts_nodelist, predicate or None)`.

### Results view (`results` cache entry, stamped with run id and revision)

| Structure | Type |
|---|---|
| `names` | `dict[str, tuple[str, ...]]` (upper-cased name to object types) |
| `facts` | `dict[tuple[str, str], list[tuple[str, str, float \| str \| None, str \| None, str, int \| None]]]` |
| `series` | `dict[tuple[str, str], list[int]]` (indexes into the report dictionary, never values) |
| `messages` | `list[tuple[int, str, str, tuple[int, ...], int, str \| None]]` |
| `unresolved` | `list[tuple[str, str]]` |
