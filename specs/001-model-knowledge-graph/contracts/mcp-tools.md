# Contract: idfkit-mcp tools and resources

These are the agent-facing interfaces this feature adds or changes. Tool names, parameter names and response
fields are public API (Constitution Principle II). Response types are the Pydantic mirrors of
[`../data-model.md`](../data-model.md).

The feature adds **six tools** (research R-31): `trace_hvac`, `get_hvac_topology`, `rename_node`,
`get_object_results`, `diagnose_symptom` and `get_object_neighbourhood`. The standards tools of earlier drafts were
deferred with the standards layer ([deferred-standards.md](../deferred-standards.md)).

Annotation shorthands follow the existing modules:
- `_READ_ONLY` = read-only, non-destructive, idempotent, closed-world
- `_MUTATE` = not read-only, non-destructive, not idempotent, closed-world

Every mutating tool calls `state.record_change(...)`.

Errors use the existing `ToolError` mapping (`errors.py`). Each error names its cause and remedy, and none returns a
default (Principle III). The error conditions listed below are the ones each tool must raise.

**Coverage.** Every response that answers from the graph carries `coverage` in the shared shape of research R-35:
`{partial, uncovered: [{kind, count, examples, reason}], resolved, unresolved}`, with `uncovered` kinds
`hvac_template`, `ems_program`, `unclassified_type` and `unlinked_result` (FR-004, FR-004a).

**Categories.** `categories` parameters take values from the closed `ComponentCategory` vocabulary of research
R-36 (`heating_coil`, `cooling_coil`, `fan`, `pump`, `terminal_unit`, … `other`). An unknown value is an error that
lists the vocabulary.

---

## Layer 1: HVAC topology

### `trace_hvac` (`_READ_ONLY`)

Replaces `trace_node` and `trace_component` from earlier drafts. Conditional: see
[Conditional tools](#conditional-tools-fr-059).

| Param | Type | Default | Notes |
|---|---|---|---|
| `object_type` | `str` | required | `"Node"` to start from a node, otherwise a component type |
| `name` | `str` | required | Matched case-insensitively |
| `hops` | `int` | 2 | 0–10. Components to walk upstream and downstream |
| `categories` | `list[ComponentCategory] \| None` | `None` | Keeps only components of these categories in the upstream and downstream walks |

Returns `HVACTrace`:
- `start`: the node, or the component as `ObjectKey` with its `category`
- `fluid` (node start), or `ports: list[NodeUse]` grouped by stream (component start)
- `producers` and `consumers: list[ObjectKey]` (node start)
- `controls: list[NodeUse]` (sensor, setpoint and actuator uses, EMS sensors and actuators included)
- `memberships: list[LoopMembership]`
- `parent: ObjectKey | None` and `children: list[ObjectKey]` (component start)
- `upstream` and `downstream: list[FlowEdge]`
- `findings: list[TopologyFinding]` (only those touching the start)
- `coverage`

Errors: no model loaded; node not used by any object, or object not found (each lists the closest names and never
picks one); object has no node fields (the error says so and suggests `get_object_neighbourhood`).

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
message (`[T010] …`). Severities respect the per-version caps of research R-34. Findings beyond 50 are grouped by
code with counts. **No existing field changes.**

### Resource `idfkit://model/hvac/{loop}`

Same content as `get_hvac_topology(loop=…, detail="chain")`.

---

## Layer 2: Results attached to the model

All tools in this layer require a simulation that the server ran in this session (FR-019). Otherwise they fail
with "No simulation run in this session; run `run_simulation` first." Every response carries
`results_state: "fresh" | "stale"` (FR-026).

### `get_object_results` (`_READ_ONLY`)

Conditional: see [Conditional tools](#conditional-tools-fr-059).

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

Built only if the SC-009 gate passes (slice 6).

| Param | Type | Default | Notes |
|---|---|---|---|
| `symptom` | `str` | required | `unmet_heating`, `unmet_cooling`, `peak_outlier`, `sizing_zero`, `message:<kind>` |
| `object_type` / `name` | `str \| None` | `None` | Target object. Required for zone symptoms |
| `limit` | `int` | 5 | |

Returns `Diagnosis`, with fields in this order (research R-16, R-37):
- `statement`: present when `no_strong_candidate` is true, saying that no candidate has strong evidence
- `no_strong_candidate: bool`
- `symptom`, `target`
- `candidates: list[CandidateCause]`, ranked. Each has `evidence`, `evidence_strength` (`strong`, `moderate` or
  `weak`), `reason` and `verify`. A `weak` candidate is never ranked first
- `families_covered: list[str]`, the rule families examined for this symptom
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

## Combined view

### `get_object_neighbourhood` (`_READ_ONLY`)

This is the cross-layer neighbourhood of one object or node (FR-058, research R-25). It is built from
`idfkit.graph.ModelGraph` with the session's document and, if this session ran a simulation, its `ResultIndex`.

| Param | Type | Default | Notes |
|---|---|---|---|
| `object_type` | `str` | required | Use `"Node"` to start from a node |
| `name` | `str` | required | Matched case-insensitively |
| `hops` | `int` | 1 | 1–3 |
| `node_kinds` | `list[NodeKind] \| None` | `None` | From `object`, `node`, `result_fact`, `message` |
| `edge_kinds` | `list[EdgeKind] \| None` | `None` | From `reference`, `flow`, `control`, `membership`, `result_link` |
| `categories` | `list[ComponentCategory] \| None` | `None` | Keeps object nodes of these categories, and always the start |
| `max_nodes` | `int` | 40 | 1–100 |

Returns `ObjectNeighbourhood`, the Pydantic mirror of `Subgraph`:
- `start`
- `nodes` and `edges`; object nodes carry `category`
- `layers` and `unavailable`, each missing layer with its reason, for example "results: no simulation run in this
  session"
- `truncated`, `omitted_nodes`, `frontier`
- `results_state`, `coverage`

When the serialised response would exceed 8 KB, the tool lowers the node count until it fits and sets
`truncated`. It never returns a partial node or edge.

Errors:
- no model loaded
- object or node not found: the error lists the closest names and never picks one
- `hops` or `max_nodes` out of range: the error states the range
- an unknown kind or category: the error lists the vocabulary

A missing layer is never an error. It is reported in `unavailable`.

There is **no** export tool and no graph resource (FR-058).

---

## Conditional tools (FR-059)

`trace_hvac` and `get_object_results` answer questions that `get_object_neighbourhood` can also reach, already
interpreted. They ship in their slices on a condition (research R-31):

- In slice 4, when `get_object_neighbourhood` lands, the evaluation runs an ablation with both tools disallowed
  ([eval-harness.md](eval-harness.md#runner-configuration-evalrunnerstoml)).
- A tool stays only if removing it costs at least 20% more tool calls or response tokens at no lower fix rate.
- A tool that fails the condition is removed before the release that would first publish it, so no deprecation is
  needed.

**Nearest neighbour in every description.** Each new tool's description says which other tool is closest and when to
use it instead:

| Tool | Nearest neighbour | Use this one when |
|---|---|---|
| `trace_hvac` | `get_object_neighbourhood` | you need loop, side, branch, position and controls of one node or component |
| `get_hvac_topology` | `trace_hvac` | you need a whole loop, or every loop, in flow order |
| `rename_node` | `rename_object` | the name is a node name, not an object name |
| `get_object_results` | `get_object_neighbourhood` | you need every result and message for one object, with counts |
| `diagnose_symptom` | `get_object_results` | you have a symptom and want ranked candidate causes |
| `get_object_neighbourhood` | `trace_hvac`, `get_object_results` | you need to cross layers, or the object has no node fields |

---

## Performance budget

Every new or changed tool and resource meets these server-side budgets on the reference model (HospitalLowEnergy),
as measured by the `perf` protocol tests in idfkit-mcp (spec SC-011 to SC-013, research R-21):

| Call | Server time | Default response |
|---|---|---|
| `trace_hvac`, `get_hvac_topology` (one loop), `rename_node` | ≤ 50 ms the first time after load or an edit; ≤ 10 ms when cached | ≤ 8 KB |
| `get_hvac_topology` (all loops, summary) | same | ≤ 8 KB, paged |
| `check_model_integrity` with the `hvac_topology` group | ≤ 60 ms (existing checks plus topology) | ≤ 8 KB, grouped |
| `get_object_results`, `diagnose_symptom` | ≤ 250 ms the first time after a run; ≤ 10 ms afterwards | ≤ 8 KB |
| `get_object_neighbourhood` | ≤ 50 ms when the topology and results views are cached. The first call after a load, edit or run pays that view's build, within the budgets above | ≤ 8 KB, enforced |

## Token budget

The cost is the whole `tools/list` response as an agent receives it, **output schemas included**, measured with
`scripts/token_audit.py` at 4 characters per token (research R-12).

| Figure | Value |
|---|---|
| Base, at `81d3cd6` (before the feature) | 39 tools, about 15,300 tokens, about 390 per tool |
| Cap on growth (SC-010) | 15%, about 2,300 tokens for all new tools plus the growth of changed tools |
| Average allowed per new tool | about 380 tokens across six tools |

Response models share one set of sub-models (`ObjectKey`, `Coverage`, `NodeUse`, `FlowEdge`) so each appears once
in `$defs`. Each change that adds a tool states the listing before and after. If slice 4's measurement exceeds the
cap, the two conditional tools are the first cut.
