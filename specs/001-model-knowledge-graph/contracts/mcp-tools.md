# Contract: idfkit-mcp tools and resources

These are the agent-facing interfaces this feature adds or changes. Tool names, parameter names and response
fields are public API (Constitution Principle II). Response types are the Pydantic mirrors of
[`../data-model.md`](../data-model.md).

Annotation shorthands follow the existing modules:
- `_READ_ONLY` = read-only, non-destructive, idempotent, closed-world
- `_MUTATE` = not read-only, non-destructive, not idempotent, closed-world

Every mutating tool calls `state.record_change(...)`.

Errors use the existing `ToolError` mapping (`errors.py`). Each error names its cause and remedy, and none returns a
default (Principle III). The error conditions listed below are the ones each tool must raise.

---

## Layer 1: HVAC topology

### `trace_node` (`_READ_ONLY`)

| Param | Type | Default | Notes |
|---|---|---|---|
| `node` | `str` | required | Matched case-insensitively |
| `hops` | `int` | 2 | 0–10. Components to walk upstream and downstream |

Returns `NodeTrace`:
- `node`, `fluid`
- `uses: list[NodeUse]` (bounded)
- `producers` and `consumers: list[ObjectKey]`
- `controls: list[NodeUse]` (sensor, setpoint and actuator uses)
- `memberships: list[LoopMembership]`
- `upstream` and `downstream: list[FlowEdge]`
- `findings: list[TopologyFinding]` (only those touching this node)
- `coverage`

Errors: no model loaded; node not used by any object. The error lists the closest node names and never picks
one.

### `trace_component` (`_READ_ONLY`)

| Param | Type | Default |
|---|---|---|
| `object_type` | `str` | required |
| `name` | `str` | required |
| `hops` | `int` | 2 |

Returns `ComponentTrace`:
- `object`
- `ports: list[NodeUse]`, grouped by stream
- `memberships`
- `parent: ObjectKey | None` and `children: list[ObjectKey]`
- `upstream` and `downstream`
- `findings`
- `coverage`

Errors: object not found; object has no node fields. The second error says so and suggests
`idfkit://model/references/{name}`.

### `get_hvac_topology` (`_READ_ONLY`)

| Param | Type | Default | Notes |
|---|---|---|---|
| `loop` | `str \| None` | `None` | `None` returns every loop |
| `detail` | `"summary" \| "chain"` | `"summary"` | |
| `limit` | `int` | 20 | Loops per page |

Returns `HVACTopologySummary` with:
- `loops`: bounded list of `{loop: ObjectKey, kind, fluid, supply: str, demand: str, zones_served: int,
  setpoint_nodes: list[str], finding_counts: dict[str, int]}`
- `total`, `omitted`, `coverage`

With `detail="chain"`, `supply` and `demand` are compact flow-order strings with repeated parallel components
collapsed (`5× AirTerminal:SingleDuct:VAV:Reheat`). The budget is about 200 tokens per loop (SC-003).

### `rename_node` (`_MUTATE`)

| Param | Type |
|---|---|
| `old` | `str` |
| `new` | `str` |

Returns `NodeRenameResult` (`old`, `new`, `fields_updated`, `objects`). Records `rename_node` in the change log.

Errors: `old` not found; `new` empty, the same as `old`, or already used as a node name. The rename never merges
nodes implicitly.

### `check_model_integrity` (changed, `_READ_ONLY`)

Adds the check group `hvac_topology`. Each `TopologyFinding` maps onto the existing `IntegrityIssue` with
`category="hvac_topology"`, `object_type`/`object_name` taken from the first object, and the code prefixed to the
message (`[T010] …`). Findings beyond 50 are grouped by code with counts. **No existing field changes.**

### Resource `idfkit://model/hvac/{loop}`

Same content as `get_hvac_topology(loop=…, detail="chain")`.

---

## Layer 2: Results attached to the model

All tools in this layer require a simulation that the server ran in this session (FR-019). Otherwise they fail
with "No simulation run in this session; run `run_simulation` first." Every response carries
`results_state: "fresh" | "stale"` (FR-026).

### `get_object_results` (`_READ_ONLY`)

| Param | Type | Default |
|---|---|---|
| `object_type` | `str` | required (`"Node"` allowed) |
| `name` | `str` | required |
| `limit` | `int` | 20 |

Returns `ObjectResults`:
- `object`
- `facts: list[ResultFact]`; zone facts carry `multiplier`
- `messages: list[LinkedMessage]`, deduplicated by kind, with `occurrences`
- `available_variables: list[str]`, the output variables recorded for this key
- `neighbours: list[{object: ObjectKey, top_fact: ResultFact | None}]`, one hop over the topology or else the
  reference graph
- `coverage`, `results_state`

### `diagnose_symptom` (`_READ_ONLY`)

| Param | Type | Default | Notes |
|---|---|---|---|
| `symptom` | `str` | required | `unmet_heating`, `unmet_cooling`, `peak_outlier`, `sizing_zero`, `message:<kind>` |
| `object_type` / `name` | `str \| None` | `None` | Target object. Required for zone symptoms |
| `limit` | `int` | 5 | |

Returns `Diagnosis`:
- `symptom`, `target`
- `candidates: list[CandidateCause]`, ranked
- `shared_upstream: list[ObjectKey]`, objects common to every affected object (FR-027, US6-AS2)
- `coverage`, `results_state`

Errors: unknown symptom (the error lists the valid ones); target required but missing.

### Resource `idfkit://simulation/results` (changed)

- Each `SimulationQAFlag` gains `affected_objects: list[ObjectKey]` (default `[]`).
- Each `ClassifiedWarning` gains `kind: str` and `affected_objects: list[ObjectKey]`.
- The summary gains `link_coverage: Coverage`.
- Existing fields are unchanged (FR-023).

### `analyze_peak_loads` (changed)

Zone rows gain `object: ObjectKey` resolved to the model's spelling. Flags gain `affected_objects`. Existing fields
are unchanged.

### Resource `idfkit://simulation/objects/{type}/{name}`

Same content as `get_object_results`.

---

## Layer 3: Standards knowledge

Every tool in this layer fails with an actionable "unavailable" error when the standards data is not installed or
the Python version is 3.14 or later (research R-08).

### `get_standards_context` (`_READ_ONLY`)

No params. Returns `StandardsContext` with a source for each field, plus `missing: list[str]` and a one-line hint
per missing item.

### `set_standards_context` (`_MUTATE` on session state, not on the model)

| Param | Type | Notes |
|---|---|---|
| `edition` | `str \| None` | Validated against the editions in the data. The error lists them |
| `climate_zone` | `str \| None` | `0`–`8` with an optional `A`, `B` or `C`. Records the source as `asserted` |
| `building_category` | `"Nonresidential" \| "Residential" \| "Semiheated" \| None` | |

Omitted params leave the current value unchanged. Returns the updated `StandardsContext`. Records the change and
persists it to the session file.

### `lookup_standard` (`_READ_ONLY`)

| Param | Type | Notes |
|---|---|---|
| `topic` | `"envelope"` | The only topic in this feature |
| `surface_class` | `str` | Required. One of the nine PNNL surface types |
| `assembly_class` | `str \| None` | |
| `edition`, `climate_zone`, `building_category` | `str \| None` | Default to the session context. Fail if still missing |

Returns `RequirementLookup`: `requirements: list[Requirement]` (SI and IP, citation), `data_source`.

### `screen_envelope` (`_READ_ONLY`)

| Param | Type | Default |
|---|---|---|
| `limit` | `int` | 20 |

Uses the session `StandardsContext`. It fails, naming each missing item, unless edition, climate zone and building
category are all set (FR-032). Returns `ScreeningReport`.

### `get_object_roles` (`_READ_ONLY`)

| Param | Type | Default |
|---|---|---|
| `object_type` | `str \| None` | `None` |
| `role` | `str \| None` | `None` |
| `unknown_only` | `bool` | `False` |
| `limit` | `int` | 50 |

Returns a bounded list of `ObjectRole`, with `origin` and `evidence`.

### `assign_object_role` (`_MUTATE` on session state)

| Param | Type |
|---|---|
| `object_type` | `str` |
| `name` | `str` |
| `role` | `"conditioned_status" \| "assembly_class"` |
| `value` | `str` |

The value must be in the role's vocabulary; the error lists the allowed values. Returns the resulting
`ObjectRole` with `origin="asserted"`. Records the change and persists it (FR-037).

### `search_weather_stations` (changed)

- New optional parameter `climate_zone: str | None`, an exact match such as `5A`. A bare `5` matches all subtypes.
- `WeatherStationModel` gains `ashrae_climate_zone: str | None`, which is `None` when the index marks the zone as
  undetermined.

### Resource `idfkit://standards/context`

Same content as `get_standards_context`.

---

## Combined view

### `get_object_neighbourhood` (`_READ_ONLY`)

This is the cross-layer neighbourhood of one object or node (FR-058, research R-25). It is built from
`idfkit.graph.ModelGraph` with the session's document, its `ResultIndex` if this session ran a simulation, and its
standards context and asserted roles if the context is complete.

| Param | Type | Default | Notes |
|---|---|---|---|
| `object_type` | `str` | required | Use `"Node"` to start from a node |
| `name` | `str` | required | Matched case-insensitively |
| `hops` | `int` | 1 | 1–3 |
| `node_kinds` | `list[NodeKind] \| None` | `None` | From `object`, `node`, `result_fact`, `message`, `verdict` |
| `edge_kinds` | `list[EdgeKind] \| None` | `None` | From `reference`, `flow`, `control`, `membership`, `result_link`, `verdict` |
| `max_nodes` | `int` | 40 | 1–100 |

Returns `ObjectNeighbourhood`, the Pydantic mirror of `Subgraph`:
- `start`
- `nodes` and `edges`
- `layers` and `unavailable`, each layer with its reason, for example "results: no simulation run in this session"
- `truncated`, `omitted_nodes`, `frontier`
- `results_state`

When the serialised response would exceed 8 KB, the tool lowers the node count until it fits and sets
`truncated`. It never returns a partial node or edge.

Errors:
- no model loaded
- object or node not found: the error lists the closest names and never picks one
- `hops` or `max_nodes` out of range: the error states the range
- an unknown kind: the error lists the vocabulary

A missing layer is never an error. It is reported in `unavailable`.

There is **no** export tool and no graph resource (FR-058).

---

## Performance budget

Every new or changed tool and resource meets these server-side budgets on the reference model (HospitalLowEnergy),
as measured by the `perf` protocol tests in idfkit-mcp (spec SC-011 to SC-013, research R-21):

| Call | Server time | Default response |
|---|---|---|
| `trace_node`, `trace_component`, `get_hvac_topology` (one loop), `rename_node` | ≤ 50 ms the first time after load or an edit; ≤ 10 ms when cached | ≤ 8 KB |
| `get_hvac_topology` (all loops, summary) | same | ≤ 8 KB, paged |
| `check_model_integrity` with the `hvac_topology` group | ≤ 60 ms (existing checks plus topology) | ≤ 8 KB, grouped |
| `get_object_results`, `diagnose_symptom` | ≤ 250 ms the first time after a run; ≤ 10 ms afterwards | ≤ 8 KB |
| `get_standards_context`, `get_object_roles`, `assign_object_role`, `set_standards_context` | ≤ 10 ms | ≤ 8 KB |
| `lookup_standard`, `screen_envelope` | ≤ 500 ms the first time in a process; ≤ 50 ms afterwards | ≤ 8 KB |
| `get_object_neighbourhood` | ≤ 50 ms when the topology and results views are cached. The first call after a load, edit or run pays that view's build, within the budgets above. The first walk into `verdict` nodes pays the screening | ≤ 8 KB, enforced |

## Token budget

Every tool and resource above is measured with `scripts/token_audit.py` in the change that adds it. The total
growth of the tool listing must stay at or below 15% of the listing at the base revision (SC-010).
