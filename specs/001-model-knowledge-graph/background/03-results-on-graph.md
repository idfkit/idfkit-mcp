# Direction 3: a results-aware model graph (results on graph nodes, root-cause navigation)

Research only. Neither repository was modified. The experiment scripts were throwaway scratch files and are not kept.
Statements marked **[speculation]** were not tested.

---

## 0. Bottom line

- **The join is easy for the result sources that matter.** On a real paired run (OpenStudio `test_example_model`,
  E+ 8.9, VAV + plant + DX), every component-sizing row resolved by exact case-insensitive (name, **and** type), and
  97% of timeseries keys resolved. In tables that have any object rows, 89% of the distinct row labels resolved; the
  rest were aggregate labels plus a couple of names covered by known rules. 92–99% of ERR messages named a resolvable
  object. The hard cases are a short, enumerable list of naming conventions (Section 2). They are not a research
  problem.
- **Name-only keying is wrong.** 44% of the 735 EnergyPlus 24.1 ExampleFiles have at least one name shared across
  object types (People/Zone, WaterUse:Connections/Equipment, AirLoopHVAC/SupplyPath). The index has to be keyed by
  `(type, NAME_UPPER)`, with type inferred from context (tabular `ComponentSizingSummary` subtables name the type;
  ERR messages usually carry `Type="NAME"`; variable-name prefixes give the type family).
- **What exists today** is a set of good aggregate QA signals in idfkit-mcp (unmet hours, peak decomposition, warning
  categories, QA flags). Exactly one place joins a result back to the model, and only by string: zone-area lookup by
  `zone_name.upper()` in `peak_loads.py`. Nothing goes from a result to an object, or from an object to its results.
- **Smallest valuable step:** a pure-stdlib `ResultIndex` in idfkit. It holds `ERR messages → (type, name)` links,
  SQL `ComponentSizes`, the `Time Setpoint Not Met` and `Peak … Components` tables, and an RDD key index, all resolved
  against the `IDFDocument`. On top of it, one MCP tool, `get_object_results(type, name)`, and an `affected_objects`
  field added to the existing `qa_flags`/`classified_warnings`. Roughly 1–1.5 weeks. A ranked `diagnose()` comes
  second.
- **Does it materially improve diagnosis?** Plausibly yes, through fewer tool calls and less mis-joining, but there is
  no published evidence specific to results-on-graph. Treat it as a hypothesis to measure with a small eval
  (Section 6). The literature on LLMs debugging EnergyPlus (2024–2025) works almost entirely from ERR text for fatal
  errors; none of it does symptom-to-cause traversal over a model graph.

---

## 1. Current state

### idfkit (`/home/user/idfkit`)

| Piece | Where | What it does / does not do |
|---|---|---|
| `ReferenceGraph` | `src/idfkit/references.py:23` | Name-based edges: `_referenced_by[NAME_UPPER] → {(obj, field, group_idx)}`. `get_referencing` (`:160`), `get_references` (`:211`), `get_referencing_with_fields` (`:190`). Keys are **uppercased names only, with no type**, so a People and a Zone of the same name share a bucket. Node names are plain strings, not graph nodes. |
| `IDFCollection` index | `src/idfkit/objects.py:1147–1217` | O(1) `NAME_UPPER → obj` per type. This is exactly the resolution primitive needed. |
| `IDFDocument.get_referencing` / `all_objects` | `src/idfkit/document.py:1042`, `:1161` | Graph access. |
| `SimulationResult` | `src/idfkit/simulation/result.py:37` | Lazy `errors` (`:106`), `sql` (`:127`), `variables` (`:155`), `html` (`:213`), `eso`/`mtr`. Has **no reference to the input document** (only `run_dir`), so no join is possible today. |
| `SQLResult` | `src/idfkit/simulation/parsers/sql.py:173` | `get_timeseries` (`:232`, case-insensitive `UPPER(KeyValue)`; returns only the *first* matching key for `"*"`), `get_tabular_data` (`:335`), `list_variables` (`:445`, has `key_value`), raw `query` (`:520`). It does **not** expose the `ComponentSizes`, `Errors`, `Zones`, `Surfaces`, `Nominal*` or `ZoneSizes` tables, which are the "model as EnergyPlus saw it" tables. |
| `ErrorReport` / `ErrorMessage` | `src/idfkit/simulation/parsers/err.py:25,40` | Severity, message and details. No object extraction, no message-kind classification, no timestamps ("Occurrence info = RUN PERIOD 1, 01/01 07:15"), no recurring-error counts. |
| `HTMLResult` | `src/idfkit/simulation/parsers/html.py:63` | Table access by title or report. Row labels are raw strings. |
| RDD/MDD | `src/idfkit/simulation/parsers/rdd.py:88,110`, `outputs.py:23` | Variable discovery, pre-run. Keys are `*`. |
| `expand.py` | `src/idfkit/simulation/expand.py:344,382` | Runs ExpandObjects and parses `expanded.idf`, but keeps **no provenance** (which template produced which object). |

### idfkit-mcp (`/home/user/idfkit-mcp/src/idfkit_mcp`)

| Piece | Where | Links results to objects? |
|---|---|---|
| `idfkit://simulation/results` → `get_results_summary` | `tools/simulation.py:522`, resource `tools/resources.py:85` | Per-zone unmet hours (`_query_unmet_hours` `:393`) with the zone **as a display string**. End uses. `_classify_warnings` (`:379`) uses keyword buckets (convergence/geometry/unusual_value/hvac/other, `:363`). `_build_qa_flags` (`:455`) gives facility-level flags only (fatal, severe, unmet > 300/1000, convergence count, no SQL). **No object links.** |
| `analyze_peak_loads` / `idfkit://simulation/peak-loads` | `tools/peak_loads.py:467,510`, resource `:99` | Zone peak decomposition (`_parse_peak_components` `:189`) and zone W/m² outlier flags (`_generate_flags` `:352`, zone outliers at `:438`). Joins zone areas by `zone_name.upper()` (`:229,257,315`). **This is the only existing result→object join**, and it is string-to-string inside SQL, not to the IDF. Flags are free-text strings. |
| `query_timeseries`, `query_simulation_table`, `list_output_variables`, `list_simulation_reports`, `export_timeseries`, `view_simulation_report` | `tools/simulation.py:641,693,590,768,916,881` | Raw access. The LLM has to know the key, report and table names. |
| `get_zone_properties` | `tools/zone_properties.py:122,147` | Model-only neighbourhood of a zone: surfaces, constructions (`:80`), schedules (`:92`), HVAC connections (`:102`), thermostats (`:117`). It already provides the "causes" half of a zone walk, with no results attached. |
| `idfkit://model/references/{name}` → `build_references` | `tools/resources.py:141`, `tools/read.py:252` | Bidirectional reference graph by name, model only. |
| `check_model_integrity` | `tools/integrity.py:38–216` | Pre-run QA that is object-linked (orphans, missing controls, boundary mismatches, HVAC zone refs). It is a good model for result-side `IntegrityIssue`-style objects (`models.py:764`). |
| Pre-run injection | `tools/simulation.py:118` (`Output:SQLite SimpleAndTabular`), `:164` (AllSummary) | Guarantees SQL tabular plus ERR on every MCP run. This is the precondition the proposal relies on. |
| Session state | `state.py:197` (`simulation_result`), `:338` | Document and result live side by side in `ServerState`, so a join is cheap to cache per session. |

**Not to re-propose** (already exists): facility QA flags, unmet hours by zone, peak decomposition by zone, warning
keyword classes, zone property summary, reference resource, report viewer.

---

## 2. Name-mapping feasibility: empirical results

### 2.1 Data used

EnergyPlus could not be run here: downloading 24.1 worked, but running the binary was blocked by the sandbox policy.
Real outputs were taken from public test fixtures instead:

- **Paired input + outputs (main evidence):** NREL/OpenStudio-resources
  `measures/openstudio_results/tests/output/{test_example_model, sm_hotel}/run/` with `in.idf` (E+ 8.9),
  `eplusout.sql`, `eplusout.err` and `eplustbl.htm`. `test_example_model` has VAV reheat, chilled/hot water plant,
  cooling tower, DX and gas coils, pumps and fans (451 objects). `sm_hotel` is a small hotel with PTACs and split DX
  (3347 objects, 564 warnings, but only zone-keyed timeseries and no SQL tabular).
- **Outputs only (12 SQL, 2 ERR):** ladybug-tools/honeybee-energy `tests/result/` (E+ 9.2–23.2, ideal loads).
- **Input-side prevalence:** all 735 parseable ExampleFiles shipped with EnergyPlus 24.1 (one failed to parse).
- The repo's own `tests/fixtures/simulation/` holds only tiny synthetic ERR/CSV/RDD/ESO files, which are not usable
  for this.

The resolver is case-insensitive exact `NAME_UPPER` lookup against all named input objects. Node names are any string
in a field whose key contains `node`.

### 2.2 Results

| Source | Run | n | Resolves to input object | Notes |
|---|---|---|---|---|
| SQL `ComponentSizes (CompType, CompName)` | test_example_model | 24 | **24/24 by name and type** | Type is given, so resolution is unambiguous. |
| | sm_hotel | 219 | **219/219 by name and type** | |
| SQL `ReportDataDictionary` keys (timeseries) | test_example_model | 58 | 56 (97%); 2 are `Environment` | Zone 10, BuildingSurface 40, Fenestration 4, InternalMass 2 |
| | sm_hotel | 203 | 201 (99%); 2 global | All zones |
| | 12 honeybee SQLs | 8–147 each | Zones and surfaces 100% against SQL's own `Zones`/`Surfaces` tables; HVAC keys follow the template convention `"<ZONE> IDEAL LOADS AIR SYSTEM"` or `"<ZONE>_IDEALAIR"`; one `"<ROOM>_SPACE"` key (E+ 23.2 Space) | No paired IDF, so resolution was checked against SQL's descriptive tables |
| SQL tabular (`TabularDataWithStrings`) | test_example_model | 182 tables | **59 tables are object-keyed.** Of 157 distinct row labels in them: 139 resolve (89%), 15 aggregate (`Total`, `Total Facility`, `Conditioned Total`, …; 10%), 2 `Mir-<SURFACE>` (mirrored shading), 1 `THERMAL ZONE 2 LIGHTS 1` (ZoneList composite: input `Lights,"Lights 1"` applied to ZoneList `"Space Type 1"`) | The **row label carries the object type implicitly**: ComponentSizingSummary subtable = type; EquipmentSummary/CoilSizingDetails → coils, fans, pumps; Envelope → surfaces; SystemSummary/SensibleHeatGain/OutdoorAir/62.1 → Zone and AirLoopHVAC |
| `eplustbl.htm` (via `HTMLResult`) | test_example_model | 1131 row labels | 139 object rows | Same content as SQL tabular. HTML adds nothing when SQL exists. |
| ERR messages | test_example_model | 38 | 26 structured (`Type="NAME"`, `key=NAME`) + 3 found only by substring scan = **29 (76%)**; 9 not object-related (unused-construction counts, Output:Meter keys, pressure check) | |
| | sm_hotel | 564 | 499 structured + 60 substring = **559 (99%)** | Dominated by `ProcessScheduleInput: Schedule:Day:Interval="…"` (472), `CalcDoe2DXCoil: Coil:Cooling:DX:SingleSpeed "…"` (25), `Calculated design cooling load for zone=… is zero` (18) |
| SQL `Errors` table | all runs | 37–76 rows | Same text as ERR, plus `ErrorType` (−1 info, 0 warning, 1 severe, 2 fatal) and `Count`. Schema: `Errors(ErrorIndex, SimulationIndex, ErrorType, ErrorMessage, Count)` | Usable as the ERR source when SQL exists. Continuation lines are joined. idfkit does not read it today. |

### 2.3 Prevalence of the hard cases (735 E+ 24.1 ExampleFiles)

| Failure category | Files affected | Mechanism | Resolution rule |
|---|---|---|---|
| Cross-type name collision | **325 (44%)**; 1.3% of all distinct names | Same name on People/Zone (983 pairs), WaterUse:Connections/Equipment (986), AirLoopHVAC/SupplyPath (471), … | Key by `(type, NAME)`. Infer type from context: tabular subtable, ERR `Type="…"` prefix, variable-name family (`Zone *` → Zone/Space; `Surface *` → surfaces; `People *` → People; `Fan *` → Fan:*; `System Node *` → node). For E+ ≥ 9 the family table can be derived once from `SetupOutputVariables.csv`, which ships with E+, or curated. **[speculation: coverage of that table]** |
| Node keys (`System Node *` variables) | **282 (38%)** request node-keyed outputs | Node names are not objects; each is referenced by 2+ objects (outlet of A = inlet of B) | Resolve to a **node** pseudo-entity with edges to every object field naming it. This is the natural attachment point for the HVAC topology graph (Direction 1). |
| EMS / PythonPlugin custom outputs | 71 (10%) | `EnergyManagementSystem:OutputVariable` keyed by the EMS object name, or arbitrary | Resolve to the EMS object. Fall back to unresolved. |
| Zone multiplier > 1 | 41 (6%) | Not a naming issue, but zone rows are **per instance** while facility totals include multipliers (already handled ad hoc in `peak_loads.py:196,253`) | Store `multiplier` on the zone result node; never sum zone rows without it. |
| HVACTemplate | 25 (3%) | Expanded objects (`"<ZONE> Ideal Loads Air System"`, `"<SYS> Cooling Coil"`, …) are absent from the input | Best: keep **provenance during `expand_objects`** (every object new in `expanded.idf` → its template, by name convention plus the referenced zone/system). Cheap fallback: a suffix-rule table, as honeybee does in `result/match.py` with `' IDEAL LOADS AIR SYSTEM'`. |
| ZoneList / SpaceList-applied loads | 11 (1%) here, **common in OpenStudio-translated models** (seen in the paired run) | Instance name = `"<ZONE or SPACE> <OBJ>"` | Split rule: for each space boundary, try `prefix ∈ Zone/Space names` and `suffix ∈ objects of that type`. Link to *both*. |
| Slab/Basement preprocessor | 5 (1%) | Generated surfaces and constructions | Provenance via `expand.py`. |
| Space (E+ ≥ 23) | 2 explicit; implicit spaces in honeybee | Keys like `<ROOM>_SPACE` | Resolve Space → Zone through Space's `zone_name`. Honeybee strips `_SPACE`. |
| Other observed conventions | n/a | `Mir-<SURFACE>` (mirrored shading), `<SURF>..N` (triangulated sub-surfaces), `..<zone>` (SHW), `Total`/`Total Facility` aggregates | Small prefix/suffix rule list plus an aggregate-label stoplist. |

**ERR resolution rules, in priority order:** (1) `Type="NAME"` or `Type = NAME` with the type in the schema, which is
an exact `(type, name)` lookup; (2) `key=NAME` where `key ∈ {zone, surface, construction, schedule, node, …}`, using a
**longest-known-name prefix**, because messages run on (`zone=FRONTSTAIRSFLR1 ZN is zero.`); (3) any quoted string;
(4) a word-boundary substring scan over names of 6 or more characters, marked `confidence="low"`. The scan produced
at least one false positive (a design-day message matched to an object). Also extract `Occurrence info = <ENV>, MM/DD
HH:MM` and the recurring-error `This error occurred N total times` so a message links to a time window and carries a
weight.

**Coverage gap (not measured):** no paired run with node-keyed or HVAC component timeseries keys was available, so the
38% node-key category is quantified only on the input side. The decisive next experiment is to run 5–10 ExampleFiles
that cover HVACTemplate, ZoneList, multi-loop plant, nodes and EMS with `Output:Variable,*,*` and measure the
resolution rate. This needs an EnergyPlus install (CI or a developer machine).

---

## 3. Proposed data model in idfkit core (stdlib only, pyright strict)

New module: `src/idfkit/simulation/linking.py`, with possibly `parsers/err_catalog.py`. Frozen, slotted dataclasses,
consistent with `ErrorMessage` and `TabularRow`.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Confidence = Literal["exact", "typed", "rule", "substring"]

@dataclass(frozen=True, slots=True)
class ObjectKey:
    obj_type: str            # schema type, or "Node", or "Aggregate"
    name_upper: str

@dataclass(frozen=True, slots=True)
class Resolution:
    key: ObjectKey | None    # None → unresolved
    rule: str                # "exact", "zonelist_composite", "template_suffix", "space_to_zone", "mir_prefix", ...
    confidence: Confidence
    via: tuple[ObjectKey, ...] = ()   # e.g. ZoneList composite → (Zone, People)

@dataclass(frozen=True, slots=True)
class ResultFact:
    """One scalar finding attached to an object."""
    source: Literal["tabular", "sizing", "err", "timeseries_stat"]
    metric: str              # "unmet_heating_hours", "peak_cooling_W", "design_capacity_W", "warning:dx_low_ambient"
    value: float | str | None
    units: str | None
    where: str               # "SystemSummary/Time Setpoint Not Met/During Heating" or "err#123"
    severity: Literal["info", "warning", "severe", "fatal"] | None = None

@dataclass(frozen=True, slots=True)
class LinkedErrorMessage:
    message: ErrorMessage
    kind: str                # catalog id, e.g. "schedule.blank_type_limits", "dxcoil.low_ambient", "sizing.zero_load"
    objects: tuple[Resolution, ...]
    occurrences: int         # from recurring summary, or SQL Errors.Count
    first_seen: str | None   # "RUN PERIOD 1 01/01 07:15"

@dataclass(slots=True)
class ResultIndex:
    facts: dict[ObjectKey, list[ResultFact]] = field(default_factory=dict)
    series: dict[ObjectKey, list[VariableInfo]] = field(default_factory=dict)   # RDD keys, not data
    errors: list[LinkedErrorMessage] = field(default_factory=list)
    unresolved: list[tuple[str, str]] = field(default_factory=list)            # (source, raw key): always reported

    @classmethod
    def build(cls, doc: IDFDocument, result: SimulationResult, *, expanded: IDFDocument | None = None) -> ResultIndex: ...
    def for_object(self, obj: IDFObject) -> ObjectResults: ...
    def objects_with(self, metric: str, *, top: int = 10) -> list[tuple[ObjectKey, ResultFact]]: ...
    def coverage(self) -> dict[str, float]: ...   # resolution rate per source: put it in every MCP response
```

Design points:

1. **Do not mutate `ReferenceGraph` or `IDFObject`.** Results are versioned per run, and the graph is live and
   rename-tracked. The index is a side table joined on `ObjectKey`, built lazily from
   `SimulationResult.link(doc) -> ResultIndex` (cached). If the doc changes after the run, mark the index stale by
   comparing a doc mutation counter; MCP already records changes in `state.record_change`.
2. **The resolver is a small ordered rule list** (Section 2.3), each rule a pure function
   `(raw, context, doc) -> Resolution | None`, so failures are inspectable and testable from fixtures.
3. **Extend `SQLResult` with typed readers** for `ComponentSizes`, `Errors`, `ZoneSizes`/`SystemSizes`, `Zones` (with
   multipliers) and `Nominal*`. These are cheap and generally useful even without linking.
4. **Error catalog (`err_catalog.py`).** About 40–60 regex patterns cover the long tail. In sm_hotel, 3 prefixes
   covered 515 of 564 messages. Each entry has `kind`, the regex with named `type`/`name`/`key` groups, a short
   "likely causes" hint, and **which neighbour types to inspect** (for example `sizing.zero_load` → Sizing:Zone,
   ZoneControl:Thermostat, internal gains; `dxcoil.low_ambient` → OA controller, availability schedule, condenser
   curves). This is data, so it type-checks and can be baked into the agent reference docs. **[speculation: 40–60 is
   enough to cover ~90% of real-world warnings by count; this matches the long-tail shape in both ERR files, but was
   measured on two models only.]**
5. **Typing:** everything is a concrete dataclass, no `Any`. `SQLResult` already returns tuples that need narrowing
   via `float()`/`str()`.

Timeseries are **not** materialised into the index. Only the RDD key → object map is stored, plus optional summary
stats (annual min/max/mean/hours-above-threshold) computed on request. That keeps the index small: thousands of facts,
not millions of points.

---

## 4. Proposed MCP surface

Principles: return **object keys** the LLM can feed straight into existing tools (`get_zone_properties`,
`idfkit://model/objects/{type}/{name}`, `update_object`); rank and cap the output; always include
`coverage`/`unresolved_count` so the model knows when the join is partial; keep each call under about 1–2k tokens.

**New or changed:**

| Surface | Kind | Returns |
|---|---|---|
| `get_object_results(object_type, name)` | tool + resource `idfkit://simulation/objects/{type}/{name}` | All facts for one object, linked ERR messages (deduplicated by kind, with counts), the available timeseries variables for this key, and a one-hop **model** neighbourhood, each neighbour with *its* top fact. |
| `diagnose(symptom, target?)` | tool | `symptom ∈ {unmet_heating, unmet_cooling, high_peak, err:<kind>, sizing_zero, oversized, …}`. Returns a ranked causal neighbourhood: candidate objects with a reason, the evidence fact, and the next tool call to verify. Ranking uses rule-based weights from the error catalog plus graph distance from the symptom node; no ML. |
| `idfkit://simulation/results` (existing) | resource change | Add `affected_objects: [{type, name}]` to each `qa_flag` and `classified_warning`; replace keyword categories with catalog `kind`; add `link_coverage`. Backward-compatible. |
| `analyze_peak_loads` (existing) | tool change | Zone rows carry `{type: "Zone", name}` resolved to the IDF casing; flags become structured (`{flag, objects, message}`), not strings. |
| `query_timeseries` (existing) | tool change | Accept `object_type` + `name` and resolve the key; resolve node keys from an object's inlet/outlet. |

### Scenario A: "Explain unmet heating hours"

```
→ read idfkit://simulation/results
  qa_flags: [{flag: high_unmet_hours, objects: [{Zone, "Perimeter_ZN_4"} 412h, {Zone,"Core_ZN"} 18h]}]
→ diagnose(symptom="unmet_heating", target="Perimeter_ZN_4")
  ranked:
   1 AirTerminal:SingleDuct:VAV:Reheat "PERIM4 VAV"
     evidence: sizing.design_heating_W=2,140 vs zone peak_heating_W=3,880 (ComponentSizingSummary, SensibleHeatGain)
     check: get_object_results(AirTerminal:SingleDuct:VAV:Reheat, "PERIM4 VAV")
   2 Schedule:Compact "HTGSETP_SCH" (thermostat): 06:00 step to 21C coincides with 68% of unmet hours
     evidence: timeseries_stat(Zone Mean Air Temperature < setpoint-0.2, hour histogram)
   3 Construction "ExtWall-Uninsulated": UA share 41% of zone envelope
   err: none linked to this zone
  coverage: tabular 0.91, err 0.97
```

Two calls replace the current 6–10 (results resource → query_simulation_table ×3 → get_zone_properties →
references → schedule view). **[speculation: the call count is reasoned, not measured.]**

### Scenario B: severe or recurring warning to object to fix

```
→ diagnose(symptom="err:dxcoil.low_ambient")
  kind: dxcoil.low_ambient (25 coils, 1,940 occurrences, first RUN PERIOD 1 01/01 00:00)
  objects (top 5 by occurrences): Coil:Cooling:DX:SingleSpeed "GUESTROOM104 ZN PTAC …" …
  shared upstream: ZoneHVAC:PackagedTerminalAirConditioner availability schedule "ALWAYS_ON" (25/25 coils)
  catalog hint: cooling coil runs below 0 C outdoor; check availability/economizer or add low-ambient curve
  next: get_object_results(ZoneHVAC:PackagedTerminalAirConditioner, "GUESTROOM104 ZN PTAC")
```

The "shared upstream" line is the graph payoff: the cause is one schedule, not 25 coils. Finding it needs the
reference graph, or better the HVAC topology (Direction 1).

### Scenario C: zone peak outlier

```
→ analyze_peak_loads → flags: [{flag: zone_peak_outlier, objects:[{Zone,"Lobby"}], ratio: 3.1}]
→ get_object_results(Zone, "Lobby")
  facts: peak_cooling 212 W/m² @ 07/21 15:00; components: Solar 58%, Equipment 9%
  neighbours: FenestrationSurface "Lobby_Win_S" (area 48 m², SHGC 0.61, no shading) ← top contributor
              ElectricEquipment "Lobby Equip" 8 W/m²
```

### Scenario D: fatal error to input object

```
→ run_simulation → fatal
→ read idfkit://simulation/results
  fatal_messages[0]: {kind: "surface.too_few_vertices", objects:[{BuildingSurface:Detailed,"WALL-1SOUTH"}]}
→ idfkit://model/objects/BuildingSurface:Detailed/WALL-1SOUTH  → fix
```

The existing loop already shows the message; the added value is the typed object link the model can act on without
string-searching.

---

## 5. Interaction with the parallel directions

- **Typed HVAC topology graph (Direction 1).** This is the main multiplier. Results attach to topology nodes in three
  ways: (a) **component** results (ComponentSizes, EquipmentSummary, coil ERR) on component nodes; (b) **node**
  timeseries (`System Node Temperature/Mass Flow`), which are 38% of example files, on the topology *edges/ports*,
  which a name graph cannot represent; (c) **loop/air-loop** results (SystemSummary, Standard62.1, plant sizing) on loop
  nodes. `diagnose()` then walks *upstream* (zone ← terminal ← air loop ← plant) instead of "anything that references
  this name". Without Direction 1, causal ranking falls back to graph distance in the reference graph, which is
  undirected in practice and noisier. Suggestion: define `ObjectKey` (type, NAME) as the shared node identity for both
  directions now.
- **Standards/ontology links (Direction 2, e.g. Brick/ASHRAE 223P, 90.1, 62.1).** Results become *evidence against a
  requirement*: unmet hours against the 300 h ASHRAE 90.1 G3.1.2.3 cap (already the threshold in `_build_qa_flags`);
  Standard62.1Summary rows (already zone/air-loop keyed, 100% resolvable in the paired run) against 62.1 Vbz;
  EnvelopeSummary U-values against prescriptive tables. Brick/223P point classes map cleanly onto output variables
  (`Zone Mean Air Temperature` → `Zone_Air_Temperature_Sensor`), so the RDD key index doubles as a "virtual point
  list". **[speculation]**

---

## 6. Effort, risks, phased plan

### Phase 0: measure (2–3 days, needs EnergyPlus in CI or locally)

Run about 10 diverse ExampleFiles (HVACTemplate-*, ZoneList, 5Zone VAV, plant loops, EMS, Space) with
`Output:Variable,*,*,RunPeriod` plus AllSummary, and run the resolver to produce a coverage table. Commit the
SQL/ERR/IDF triples **trimmed** (SQL `VACUUM`, without timeseries) as `tests/fixtures/simulation/linked/`. These
fixtures are missing today and are needed for any test anyway. Add 5–8 hand-written "diagnosis tasks" with known root
causes (undersized terminal, wrong setpoint schedule, missing insulation, swapped node) as an LLM eval for later
phases.

### Phase 1: smallest valuable step (about 1–1.5 weeks)

- idfkit: `SQLResult.component_sizes()` / `.errors_table()`; an ERR object extractor (rules 1–3) plus about 15
  catalog kinds; a `ResultIndex` covering ComponentSizes, `Time Setpoint Not Met`, the `Peak … Components` tables,
  RDD keys and ERR; resolver rules for exact, ZoneList composite, Space→Zone, `Mir-`, aggregate stoplist, and
  IdealLoads suffix. Tests from Phase 0 fixtures. Update the `result-parsing` agent reference template and snippet,
  plus CHANGELOG.
- idfkit-mcp: `get_object_results`; `affected_objects` on `qa_flags` and `classified_warnings`; structured peak flags.

### Phase 2 (about 1–2 weeks)

`diagnose(symptom)` with catalog-driven neighbour types; timeseries summary stats on demand (setpoint-miss hour
histogram); HVACTemplate provenance captured in `expand.py`; node pseudo-entities.

### Phase 3 (depends on Direction 1)

Directional upstream walks over the typed topology; node results on ports; loop-level rollups; standards checks
(Direction 2).

### Risks

| Risk | Mitigation |
|---|---|
| False links from ERR substring scans (one seen already) | Confidence levels; `substring` links shown but never ranked first; tests from real ERR files. |
| Version drift in ERR wording and tabular table names (8.9 → 26.2) | The catalog is data with per-version tests. Unknown kinds fall back to `other` with extracted objects. The tabular readers already tolerate variant column names (`simulation.py:410`). |
| Stale index after edits (the LLM fixes the model, then queries old results) | Stamp the index with the doc mutation counter and run id; responses say `stale: true`. |
| Ranking looks authoritative but is heuristic | Return evidence plus a verify call for every candidate; never an unexplained score. Measure with the Phase 0 eval. |
| Token blow-up on big models (sm_hotel: 564 warnings) | Deduplicate by kind; top-N; counts not lists; `coverage` summary. |
| No E+ in default CI | Pre-generated fixtures (Phase 0). The linker itself needs no E+. |

### Does it materially improve diagnosis?

- **Evidence for:** the join is 89–100% reliable on real outputs, so the LLM would get typed object handles instead of
  re-deriving joins from strings. The existing MCP already forces several hops (results → table → zone properties →
  references) that `get_object_results` and `diagnose` collapse. Honeybee had to hand-write exactly this matching
  (`honeybee_energy/result/match.py`), which shows practitioners need it.
- **Evidence missing:** no study measures LLM diagnosis accuracy with versus without result-to-object linking. The
  LLM-for-BEM work found (Zhang, Chen and Ford 2024; the agentic IDF generator/debugger in Energy and Buildings 2025;
  LLM-BEM-Engineer) uses ERR text and documentation for fatal-error repair, not performance root-causing. The honest
  claim is "fewer calls, fewer mis-joins, enables upstream walks", to be validated by the Phase 0 eval (success rate
  and tool calls per task, with versus without the new tools).

### Prior art

- honeybee-energy `result/match.py`: `match_rooms_to_data` and `match_faces_to_data`, with the conventions
  `' IDEAL LOADS AIR SYSTEM'`, `'..'` (SHW and triangulated surfaces), `'_SPACE'` and multiplier correction. These are
  directly reusable rules.
- OpenStudio `openstudio_results` measure (NREL/OpenStudio-resources): reporting tables by zone, air loop and plant
  loop, generated from model objects and SQL queries. It is human-facing, with no symptom → cause links. Its test
  outputs supplied the paired evidence above.
- EnergyPlus SQL `Errors` table (I/O "Output Details": eplusout.sql), with ERR messages, severity and count already
  structured.
- LLM + EnergyPlus: Zhang, Chen and Ford, "Advancing Building Energy Modeling with Large Language Models", Energy and
  Buildings 2024 (arXiv 2402.09579); an agentic IDF generation and debugging workflow (Energy and Buildings 2025,
  OSTI 2480816); LLM-BEM-Engineer (Hugging Face); a review of LLMs for HVAC operations (arXiv 2609.05314), which notes
  that debugging agents exist but are immature.

Sources: https://arxiv.org/abs/2402.09579v1 · https://www.osti.gov/biblio/2480816 ·
https://huggingface.co/GangJiang/LLM-BEM-Engineer/blob/main/README.md · https://arxiv.org/pdf/2609.05314 ·
https://bigladdersoftware.com/epx/docs/9-2/output-details-and-examples/eplusout-sql.html ·
https://github.com/ladybug-tools/honeybee-energy (`honeybee_energy/result/match.py`) ·
https://github.com/NREL/OpenStudio-resources (`measures/openstudio_results/tests/output/`)
