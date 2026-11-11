# Data Model: Model Knowledge Graph for Agents

Phase 1 output of `/speckit-plan`. The entities come from the spec's Key Entities. Each one is defined in two
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

Attached to every response that matches, links or infers (FR-004).

| Field | Type | Rule |
|---|---|---|
| `partial` | `bool` | True when anything was skipped (templates, unknown types, missing data) |
| `skipped` | `list[str]` | Human-readable reasons, deduplicated |
| `resolved` / `unresolved` | `int` | For linking. Omitted elsewhere |

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
| `field` | `str` | |
| `connection` | `ConnectionType \| None` | `None` means unclassified, which yields an info finding |
| `stream` | `int` | |
| `fluid` | `Fluid` | |
| `is_parent` | `bool` | |
| `via_nodelist` | `str \| None` | The NodeList name when reached through one |
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
| `severity` | `"error" \| "warning" \| "info"` | Only qualified codes may be `error` (FR-013) |
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

### HVACTopology

A derived view, not stored. Built by `from_document(doc)`. Cached per `(document, revision)`.

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
| `rule` | `str` | `exact`, `typed`, `zonelist_composite`, `space_to_zone`, `mirrored_shading`, `aggregate`, `ideal_loads_suffix`, `substring` |
| `confidence` | `"exact" \| "typed" \| "convention" \| "weak"` | `substring` is always `weak` (FR-005) |
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

Symptoms: `unmet_heating`, `unmet_cooling`, `peak_outlier`, `sizing_zero`, `message:<kind>`.

---

## Layer 3: Standards knowledge (`idfkit.standards`)

Three topics: `envelope`, `lighting` (90.1, space-by-space method) and `ventilation` (62.1). See research R-26
to R-29.

### StandardsContext

A public frozen dataclass in idfkit (R-29). idfkit-mcp holds one per session and persists it (R-15).

| Field | Type | Rule |
|---|---|---|
| `standard` | `"ASHRAE 90.1"` | The only value in this feature |
| `edition` | `str \| None` | The 90.1 edition: one of the editions present in the data (`2004` … `2025`) |
| `ventilation_edition` | `str \| None` | The 62.1 edition: one of `1999` … `2022` |
| `climate_zone` | `str \| None` | `0`–`8` with an optional `A`, `B` or `C` subtype |
| `building_category` | `"Nonresidential" \| "Residential" \| "Semiheated" \| None` | |
| `*_source` | `"asserted" \| "weather_station" \| None` | One per field. Editions and category are always asserted |

Validation: the fields a topic requires must be non-null when that topic is requested (FR-032):

| Topic | Required |
|---|---|
| `envelope` | `edition`, `climate_zone`, `building_category` |
| `lighting` | `edition` |
| `ventilation` | `ventilation_edition` |

### ObjectRole

| Field | Type | Rule |
|---|---|---|
| `object` | `ObjectKey` | |
| `role` | `"surface_class" \| "conditioned_status" \| "assembly_class" \| "space_type" \| "lighting_space_type" \| "ventilation_space_type"` | The three space-type roles apply to zones only |
| `value` | `str` | From the data source's vocabularies (`ExteriorWall`, `Mass`, `IEAD`, `office`, `office_open_plan_lighting`, …) or `unknown` |
| `origin` | `"computed" \| "asserted" \| "unconfirmed"` | The space-type roles are never `computed` (R-27) |
| `evidence` | `str` | For example "heat capacity 210 kJ/m²K ≥ 143", "asserted 2026-11-11T10:02Z", or "suggested from zone name 'Office_Open'" |

Vocabularies:
- `space_type`: the 61 level-1 names
- `lighting_space_type`: the 119 lighting space-type names
- `ventilation_space_type`: the 98 ventilation space-type names

All of them are read from the data at run time. An assertion outside the vocabulary is refused, and the error lists
the closest values. For a topic, the topic-specific role wins over `space_type`.

**State transitions.**

```
computed ──assert──▶ asserted          (assertion always wins)
unknown  ──assert──▶ asserted
unconfirmed ─confirm (= assert)─▶ asserted
asserted ──session ends──▶ (gone; computed or unknown applies again)
```

Asserted roles are re-keyed when the object is renamed (FR-037). Only `computed` and `asserted` values may feed a
verdict (FR-036).

### Requirement

| Field | Type | Rule |
|---|---|---|
| `topic` | `"envelope" \| "lighting" \| "ventilation"` | |
| `edition` | `str` | The 90.1 edition, or the 62.1 edition for ventilation |
| `climate_zone_set` | `str \| None` | Envelope only, as in the data (`3`, `3A`, …). Subtype rows win (FR-033) |
| `surface_class` / `assembly_class` / `building_category` | `str \| None` | Envelope only |
| `space_type_row` | `tuple[str, str] \| None` | Lighting and ventilation: the row's primary and secondary space type, verbatim |
| `method` | `"SS" \| "CS" \| None` | Lighting only |
| `metric` | `"u_factor" \| "c_factor" \| "f_factor" \| "shgc" \| "r_value" \| "lpd" \| "oa_per_person" \| "oa_per_area"` | |
| `limit_ip` / `units_ip` | `float` / `str` | Verbatim from the row |
| `limit_si` / `units_si` | `float` / `str` | Converted (R-08, R-26) |
| `wwr_band` | `tuple[float \| None, float \| None]` | Fenestration rows |
| `includes_films` | `tuple[bool, bool]` | Envelope: interior, exterior |
| `citation` | `str` | The row's `annotation`, or idfkit's reviewed 62.1 citation table (R-26) |
| `citation_source` | `"data" \| "idfkit"` | |

A ventilation requirement is a pair of rows `(oa_per_person, oa_per_area)` taken from one data row. Both are
returned.

### Zone measures

These are model-side, typed results of `zone_lighting(doc)` and `zone_outdoor_air(doc)`. They need no extra
(R-28).

| Entity | Fields |
|---|---|
| `ZoneLighting` | `zone: ObjectKey`, `floor_area_m2`, `installed_w`, `lpd_w_m2 \| None`, `multiplier`, `sources: list[ObjectKey]` (the `Lights` objects), `reason: str \| None` when no value |
| `ZoneOutdoorAir` | `zone: ObjectKey`, `method: str \| None`, `design_people`, `floor_area_m2`, `per_person_l_s \| None`, `per_area_l_s_m2 \| None`, `breathing_zone_l_s \| None`, `multiplier`, `source: ObjectKey \| None` (the outdoor-air specification), `reason: str \| None` |

### ScreeningVerdict

| Field | Type | Rule |
|---|---|---|
| `object` | `ObjectKey` | A construction or fenestration type (envelope), or a zone (lighting, ventilation) |
| `topic` | `"envelope" \| "lighting" \| "ventilation"` | |
| `check` | `str` | For example `roof u_factor`, `lighting lpd` or `ventilation breathing_zone_oa` |
| `verdict` | `"meets" \| "does_not_meet" \| "cannot_tell"` | |
| `value_si` | `float \| None` | Ventilation: the model's breathing-zone outdoor air in L/s |
| `requirement` | `Requirement \| None` | `None` only for `cannot_tell` |
| `required_si` | `float \| None` | Ventilation: Vbz = Rp·Pz + Ra·Az in L/s. Otherwise equal to `requirement.limit_si` |
| `margin_si` | `float \| None` | `limit − value` for maxima (envelope, lighting). `value − required` for minima (ventilation) |
| `area_m2` | `float` | Exterior area using the construction, or the zone floor area |
| `assumptions` | `list[str]` | Each role used with its origin, and the space-type resolution path (R-27) |
| `reason` / `resolve` | `str \| None` | Required when `cannot_tell` |

### ScreeningReport

| Field | Type |
|---|---|
| `basis` | `str` (standards, editions, "prescriptive screening — not a compliance determination") |
| `data_source` | `str` (package name and version) |
| `context` | `StandardsContext` |
| `topics` | `list[str]` (topics evaluated) |
| `not_evaluated` | `dict[str, str]` (topic to the missing context items, when `topics=None`) |
| `summary` | counts per topic and verdict |
| `verdicts` | bounded list of `ScreeningVerdict`, worst margin first |
| `not_checked` | `list[str]` (per topic: mandatory provisions, exceptions, trade-off paths, RCR and additional lighting allowances, lighting controls, Ez, Vot, DCV, IAQP; R-26) |
| `coverage` | `Coverage` |

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
| node kind `verdict` | `standards` |
| edge kind `reference` | `model` |
| edge kinds `flow`, `control`, `membership` | `topology` |
| edge kind `result_link` | `results` |
| edge kind `verdict` | `standards` |

`Layer = Literal["model", "topology", "results", "standards"]`. Adding a kind is an additive change. Removing or
redefining one is breaking (FR-053).

### GraphNode

| Field | Type | Rule |
|---|---|---|
| `id` | `str` | Stable composite id (research R-24). Upper-cased names, so equal ids mean equal identity |
| `kind` | `NodeKind` | |
| `layer` | `Layer` | Fixed by `kind` |
| `key` | `ObjectKey \| None` | Set for `object`, and for the owner of a `result_fact` or `verdict` |
| `node` | `str \| None` | Set for `node`, with the model's spelling |
| `label` | `str` | Short display text, for example `Zone "SPACE1-1"` or `unmet_heating_hours = 312 h` |
| `attrs` | `Mapping[str, str \| int \| float \| bool \| None]` | Kind-specific scalars only, for example `fluid`, `metric`, `value`, `units`, `severity`, `verdict`, `stale` |

### GraphEdge

| Field | Type | Rule |
|---|---|---|
| `source` / `target` | `str` | Graph node ids. Direction as in the edge table of research R-23 |
| `kind` | `EdgeKind` | |
| `layer` | `Layer` | Fixed by `kind` |
| `key` | `str` | Unique among edges with the same endpoints, for example `reference:zone_name` or `flow:air_outlet_node_name` |
| `attrs` | `Mapping[str, str \| int \| float \| bool \| None]` | `field`, `connection_type`, `fluid`, `side`, `branch`, `position`, `confidence`, `provenance` (FR-010a), as applicable |

### Subgraph

Returned by `ModelGraph.neighbourhood`.

| Field | Type | Rule |
|---|---|---|
| `start` | `str` | Graph node id |
| `nodes` / `edges` | `list[GraphNode]` / `list[GraphEdge]` | Breadth-first order from `start` |
| `layers` | `list[Layer]` | Layers present in the view |
| `unavailable` | `dict[Layer, str]` | Each missing layer and why (FR-056) |
| `partial` | `dict[Layer, str]` | Each present layer that covers only part of its scope, and what is missing. Today only `standards`, for topics without a complete context (R-29) |
| `truncated` | `bool` | True when a hop or node bound cut the walk |
| `omitted_nodes` | `int` | Nodes reached but not returned. A lower bound, since the walk stops at the cut |
| `frontier` | `list[str]` | Returned node ids whose neighbours were not expanded |
| `results_state` | `"fresh" \| "stale" \| None` | `None` when the results layer is absent |

**State: which layers are present.** It is decided per call, not stored:
- `model` and `topology`: always present.
- `results`: present when a `ResultIndex` was given, whether fresh or stale. Stale facts are marked, not dropped.
- `standards`: present when a `StandardsContext` completing at least one topic's required items (R-29) was given
  **and** the standards data is importable. Its verdicts cover only those topics. A partial context is not an
  error; the topics left out are named in the `standards` entry of a separate `partial` map, for example
  `{"standards": "lighting, ventilation: set edition, ventilation_edition"}`. Otherwise the layer is listed in
  `unavailable` with the reason.

### Node-link document

This is the export, a JSON object. Its normative definition is in
[contracts/node-link-json.md](contracts/node-link-json.md). The top-level keys are `directed`, `multigraph`,
`graph`, `nodes` and `edges`. Each element of `nodes` and `edges` is a `GraphNode` or `GraphEdge` flattened:
`attrs` is merged into the element, and `key` becomes `object_type` and `name`.

---

## Evaluation (idfkit-mcp `eval/`, not shipped)

### FaultType

`id`, `layer` (`topology`, `results` or `standards`), `description`, `inject(doc) -> InjectedFault`,
`verify(doc, result | None) -> bool`, `needs_energyplus: bool`.

### EvaluationTask

`fault_id`, `model_file`, `prompt`, `condition` (`baseline` or `treatment`).

### TaskOutcome

`fixed: bool`, `verified_by` (`check`, `simulation` or `skipped`), `skip_reason: str | None`, `tool_calls: int`,
`response_tokens: int`, `unwanted_changes: int` (objects changed outside the fault's scope), `transcript_path`.

### EvaluationRun

`run_id`, `started_at`, `runner_command`, `model_identifier`, `baseline_version`, `treatment_revision`,
`outcomes: list[TaskOutcome]`, and summary metrics per fault type and overall (SC-008, SC-009).

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

### Standards cache (process-wide, read-only)

| Structure | Type |
|---|---|
| `envelope_90_1` | `dict[tuple[str, str, str, str], tuple[tuple[...], ...]]` (edition, climate zone set, surface type, building category) to projected rows |
| `lighting_90_1` | `dict[str, tuple[tuple[...], ...]]` (edition to its `SS` and `CS` rows, by 1-based row id) |
| `ventilation_62_1` | `dict[str, tuple[tuple[...], ...]]` (edition to its rows, by 1-based row id) |
| `space_types` | level 1 to level 2 names, and level 2 name to `(table, row id)` per edition (R-27) |
| `data_version` | `str` |

Loaded on first use under a lock and shared by every session. The parsed JSON is discarded after projection.
