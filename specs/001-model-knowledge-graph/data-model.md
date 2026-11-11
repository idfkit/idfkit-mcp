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

### StandardsContext

Lives in idfkit-mcp session state and is persisted (R-15).

| Field | Type | Rule |
|---|---|---|
| `standard` | `"ASHRAE 90.1"` | The only value in this feature |
| `edition` | `str \| None` | One of the editions present in the data (`2004` … `2025`) |
| `climate_zone` | `str \| None` | `0`–`8` with an optional `A`, `B` or `C` subtype |
| `building_category` | `"Nonresidential" \| "Residential" \| "Semiheated" \| None` | |
| `*_source` | `"asserted" \| "weather_station" \| None` | One per field. Edition and category are always asserted |

Validation: a screening requires every field to be non-null (FR-032).

### ObjectRole

| Field | Type | Rule |
|---|---|---|
| `object` | `ObjectKey` | |
| `role` | `"surface_class" \| "conditioned_status" \| "assembly_class"` | `space_type` is reserved for later |
| `value` | `str` | From PNNL vocabularies (`ExteriorWall`, `Mass`, `IEAD`, …) or `unknown` |
| `origin` | `"computed" \| "asserted" \| "unconfirmed"` | |
| `evidence` | `str` | For example "heat capacity 210 kJ/m²K ≥ 143", or "asserted 2026-11-11T10:02Z" |

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
| `edition` | `str` | |
| `climate_zone_set` | `str` | As in the data (`3`, `3A`, …). Subtype rows win (FR-033) |
| `surface_class` / `assembly_class` / `building_category` | `str` | |
| `metric` | `"u_factor" \| "c_factor" \| "f_factor" \| "shgc" \| "r_value"` | |
| `limit_ip` / `units_ip` | `float` / `str` | Verbatim from the row |
| `limit_si` / `units_si` | `float` / `str` | Converted (R-08) |
| `wwr_band` | `tuple[float \| None, float \| None]` | Fenestration rows |
| `includes_films` | `tuple[bool, bool]` | Interior, exterior |
| `citation` | `str` | The row's `annotation` |

### ScreeningVerdict

| Field | Type | Rule |
|---|---|---|
| `object` | `ObjectKey` | A construction or fenestration type |
| `check` | `str` | For example `roof u_factor` |
| `verdict` | `"meets" \| "does_not_meet" \| "cannot_tell"` | |
| `value_si` | `float \| None` | |
| `requirement` | `Requirement \| None` | `None` only for `cannot_tell` |
| `margin_si` | `float \| None` | `limit − value` for maxima |
| `area_m2` | `float` | Exterior area using this construction |
| `assumptions` | `list[str]` | Each role used, with its origin |
| `reason` / `resolve` | `str \| None` | Required when `cannot_tell` |

### ScreeningReport

| Field | Type |
|---|---|
| `basis` | `str` (standard, edition, "prescriptive screening — not a compliance determination") |
| `data_source` | `str` (package name and version) |
| `context` | `StandardsContext` |
| `summary` | counts per verdict |
| `verdicts` | bounded list of `ScreeningVerdict`, worst margin first |
| `not_checked` | `list[str]` (mandatory provisions, exceptions, trade-off paths, opaque doors if absent from data) |
| `coverage` | `Coverage` |

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
| `data_version` | `str` |

Loaded on first use under a lock and shared by every session. The parsed JSON is discarded after projection.
