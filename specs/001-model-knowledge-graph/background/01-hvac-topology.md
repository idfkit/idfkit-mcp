# KG-1: A typed HVAC physical-topology graph for idfkit and idfkit-mcp

Research only. Nothing was changed in either repository. The throwaway prototype is kept beside this
report as [`prototype/hvac_topology_proto.py.txt`](prototype/hvac_topology_proto.py.txt). Its raw sweep logs and the helper
scripts it cites below (`c.py`, `d.py`, `e.py`) were scratch files and are not kept. The prototype is stored as
`.txt` so the repository linters skip it; rename it to `.py` to run it against an installed idfkit.

## TL;DR

- **The gap is real and wider than described.** idfkit indexes no node fields at all. Their epJSON schema entries carry no `object_list`, so `ReferenceGraph` never sees them. I injected a node-name typo into `5ZoneAirCooled.idf`. `validate_document` reported 10 errors before and 10 after, and `doc.get_referencing("Mixed Air Node 1")` returned `set()`. The shipped `hvac-loops.md` reference tells agents the opposite: that dangling node names surface as `E004`. That claim is wrong.
- **Feasibility is good.** Telling which fields are nodes can be derived from the schema. The 26.2 schema introduces `"data_type": "node"` on 817 fields; all 17 older bundled schemas have zero. Field-name regex plus that 26.2 table covers more than 97% of node fields in every bundled version. Knowing *what kind* of connection a field makes (inlet, outlet, sensor, setpoint, outdoor air, zone inlet, …) and how loops are assembled needs a curated per-type rule table. EnergyPlus keeps that semantics in C++ (`GetOnlySingleNode(... NodeConnectionType, FluidStream, ObjectIsParent)`), not in the schema.
- **The prototype worked on real models.** It used about 6 per-type overrides plus a Splitter/Mixer junction rule over 575 EnergyPlus 24.1 example files (58,027 nodes). It found **0 Branch-vs-component node mismatches** (no false positives) and **908 residual single-ended nodes** (1.6%). 358 of 575 files were fully clean. Almost all of the residual is legitimate boundary behaviour, such as exhaust fans and air-cooled condensers venting outdoors. A rule table of roughly 30–40 more entries should take that to near zero. The injected typo was caught both as a Branch/component mismatch and as a single-ended node.
- **Recommendation:** build `idfkit.hvac` with a NodeIndex, connection-typed ports and loop/side/branch membership (stdlib only). Run EnergyPlus's own `CheckNodeConnections` rules statically, plus a Branch/component consistency check. In MCP, expose three things:
  1. `trace_node` / `trace_component`, which are cheap and targeted.
  2. A compressed `get_hvac_topology` chain summary, which is token-bounded.
  3. A `hvac_topology` category in `check_model_integrity`.

  Add `rename_node` as a mutation, because nodes cannot be renamed safely today. Later, parse `eplusout.bnd` to cross-check the static graph and to generate the rule table.

---

## 1. Current state

### idfkit

| Item | Evidence |
|---|---|
| `ReferenceGraph` only indexes fields with `object_list` | `src/idfkit/schema.py:263-285` (`_build_reference_indexes`), `:496`, `:507` (parsing cache `ref_fields` built from `"object_list" in field_schema`); `src/idfkit/document.py:982-1005` (`_index_object_references`) |
| Node fields have no `object_list`, so they are invisible to the graph | Schema evidence: `Coil:Cooling:Water.air_inlet_node_name` is `{"type": "string"}` in V24-1-0. Only 19 of 860 node-ish fields in 24.1 carry an `object_list`, and those are RoomAir / OutdoorAirNodeNames / AFN, not HVAC flow. |
| Validation does not check node consistency | `src/idfkit/validation.py:1065-1067` checks only `get_dangling_references` from the ReferenceGraph. Verified empirically: the typo injection left the error count unchanged (10 → 10). |
| No topology code anywhere | `grep -rn -i "topolog\|BranchList\|NodeList"` over `src/idfkit` finds nothing HVAC-related, and there is no `hvac/` sub-package. `simulation/result.py:287-327` exposes sql/err/eso/mtr/csv/html/rdd/mdd paths but no `.bnd`, and `simulation/parsers/` has no bnd parser. |
| `rename` works only for named objects | `document.py:879-949`. A node is not an object, so there is no safe rename. The agent docs (`hvac-loops.py:mistake-node-good`) tell agents to "update both ends" by hand. |
| `introspection.py` ignores `data_type` | `grep data_type src/idfkit/*.py` returns nothing. The 26.2 `"data_type": "node"` marker is currently dropped on the floor. |

**Doc bugs in the agent reference (fix regardless of this proposal):**

- `agent_references/templates/hvac-loops.md`:
  - "Pattern: lint before simulate" claims `validate_document` "reports every dangling node-name reference as an `E004` error". It does not. The same page later says the opposite ("Node names are strings, not references").
  - Item 1 under "Where idfkit helps" ("Schema validation catches node-name typos") is also false.
- `agent_references/snippets/hvac-loops.py:trace-referencing`: implies `get_referencing("AHU-1 Cooling Coil")` returns a `SetpointManager:Scheduled`. Setpoint managers reference nodes, not coils, so it will not.
- `hvac-loops.py:mistake-walk-good`:
  - It searches `getattr(o, "air_outlet_node_name")`, which misses Branch extensible components, OA mixer stream fields and NodeLists.
  - On `5ZoneAirCooled` it would assert-fail on correct models, for example a coil whose upstream is `OutdoorAir:Mixer.mixed_air_node_name`.

### idfkit-mcp

| Item | Evidence |
|---|---|
| 37 tools, none topological | Tool list from `@tool` defs: `search_docs … get_zone_properties`. The only HVAC check is `_check_hvac_zone_references` (`tools/integrity.py:190-212`), which verifies only that `ZoneHVAC:EquipmentConnections.zone_name` exists. |
| `check_model_integrity` structure | `tools/integrity.py:215-271`: a list of `(name, fn)` checks returning `IntegrityIssue(severity, category, object_type, object_name, message)` (`models.py:764-772`). A topology check slots straight in. |
| References resource | `tools/read.py:252-269` `build_references` → `doc.get_referencing(name)` / `get_references`. It returns empty for any node name. |
| Zone HVAC summary | `tools/zone_properties.py:102-115` lists `ZoneHVAC:EquipmentConnections` names only. It gives no equipment, no air loop and no plant. |
| Post-sim warning classification is keyword-based | `tools/simulation.py:363-368`. EnergyPlus's own "Node Connection Error" severes are lumped into "hvac" or "other". |
| `rename_object` | `tools/write.py:237-258`: names only, so nodes are not covered. |

---

## 2. Feasibility

### 2a. Identifying node fields: mostly schema-driven

Measured over the bundled schemas (scratch scripts, not kept):

| Version | Object types | Types with node fields | Node fields (regex `node(_or_nodelist)?_names?$`) | Inlet/outlet *pairs* by prefix | Fields also tagged `data_type: node` in 26.2 |
|---|---|---|---|---|---|
| 8.9.0 | 799 | 236 | 729 | 239 | 713 (97.8%) |
| 9.6.0 | — | — | 748 | — | 733 |
| 22.1.0 | 830 | 244 | 755 | 249 | 740 |
| 24.1.0 | 847 | 251 | 783 | 257 | 768 |
| 26.2.0 | 880 | 257 | 805 regex / **817 `data_type: node`** | 267 | — |

- **26.2 is the first schema that marks node fields** (`"data_type": "node"`, 819 occurrences). 8.9–26.1 have none. The IDD has always had `\type node` (1,541 occurrences in the 24.1 IDD), but the epJSON generator dropped it until 26.2.
- The 26.2 tag catches fields the regex misses: VRF `coil_air_inlet_node`, `PlantComponent:TemperatureSource.inlet_node`, `SwimmingPool:Indoor.pool_water_inlet_node`, `AirLoopHVAC.demand_side_inlet_node_names`, and so on (27 fields).
- The regex catches some the tag misses: `AirTerminal:DualDuct:VAV:OutdoorAir.air_outlet_node_name` is also untagged in the 24.1 IDD (an upstream gap), and there are some AFN/RoomAir/electric "nodes" that are not HVAC fluid nodes.
- **Approach:** generate a `(obj_type, field) → is_node` table at codegen time from the 26.2 tags. Union it with the regex for the older versions, keyed by field name, since field names are stable across versions (97–98% overlap above). Exclude non-fluid "nodes" (`electric_circuit_node_name`, AFN nodes, RoomAir nodes).

### 2b. Classifying connections: needs per-type rules

The schema says *that* a field is a node, never *how* it connects. EnergyPlus decides that in C++ per call site. The Module Developer guide (24.1 PDF, §7.4.6) documents the model I propose to mirror:

- **NodeConnectionType:** `Inlet, Outlet, Internal, ZoneNode, Sensor, Actuator, OutsideAir, ReliefAir, ZoneInlet, ZoneReturn, ZoneExhaust, Setpoint, Electric`. Newer EnergyPlus versions add a few more, such as `InducedAir` (from memory, unverified).
- **FluidStream** (1, 2, 3): pairs inlet and outlet per stream (air vs water on a water coil).
- **ObjectIsParent:** a parent such as `ZoneHVAC:FourPipeFanCoil` or `ZoneHVAC:AirDistributionUnit` duplicates its children's nodes. "Every fluid loop must be a continuous connection of non-parent objects and zones."
- **CheckNodeConnections rules (verbatim summary):**
  - An actuator node must also appear as a non-sensor/actuator/outsideair type.
  - A setpoint node must also appear as a non-setpoint/outsideair type.
  - Every ZoneInlet must be an Outlet of something.
  - Every ZoneExhaust must be an Inlet of something.
  - Every Inlet must match an Outlet, ZoneReturn, ZoneExhaust, ReliefAir or OutsideAir node, or be a loop inlet.

**How much is derivable by name heuristic?** I classified fields as follows: `*inlet*` → in, `*outlet*` → out, `*setpoint*` → setpoint, `sensor|reference|control_zone|actuator` → sensor, `outdoor_air_inlet|condenser_air_inlet|ambient` → outdoor boundary. Of the 805 node fields in 26.2, 267 inlet/outlet pairs (534 fields) pair cleanly by prefix, giving stream identity for free. 114 of 257 node-bearing types are *fully* paired. The remaining 143 types each have at least one field needing a rule. The bulk of those rules are mechanical:

- `setpoint_node_or_nodelist_name` appears in 28 setpoint managers.
- `outdoor_air_inlet_node_name` appears 12 times.
- `sensor_node_name` appears 8 times.

Genuinely hand-written structure is needed for about 20 types:

| Category | Types | Rule |
|---|---|---|
| Loop definitions | `AirLoopHVAC`, `PlantLoop`, `CondenserLoop` | The 4 endpoint nodes plus supply/demand `BranchList`/`ConnectorList` names define sides. |
| Branch | `Branch` | Each extensible `components[i]` asserts *(component_type, component_name, in, out)*. Membership edge plus consistency check against the component's own fields. Continuity: `out[i] == in[i+1]`. |
| Branch junctions (plant) | `Connector:Splitter`, `Connector:Mixer`, `ConnectorList` | These name **branches, not nodes**. Junction edges run from the last outlet of the inlet branch to the first inlet of each outlet branch. Without this rule the prototype reported 40 false "single-ended" nodes on `5ZoneAirCooled` and 1,065 on `HospitalLowEnergy`. With it, 1 and about 0. |
| Air-loop demand side | `AirLoopHVAC:SupplyPath`, `ZoneSplitter`, `SupplyPlenum`, `ReturnPath`, `ZoneMixer`, `ReturnPlenum` | Node-based (the generic rule works), but loop membership must be traced *through nodes* from `demand_side_inlet_node_names`, because there is no branch list. |
| OA system | `AirLoopHVAC:OutdoorAirSystem` → `AirLoopHVAC:OutdoorAirSystem:EquipmentList` → `OutdoorAir:Mixer` | The OA system has **no node fields**. Its Branch entry's in/out must be mapped to mixer `return_air_stream`/`mixed_air`. Mixer stream fields don't follow the inlet/outlet naming. `relief_air_stream` is a ReliefAir boundary. |
| Zone equipment | `ZoneHVAC:EquipmentConnections` (+ `SpaceHVAC:*` in 23.x+) | `zone_air_node_name` = ZoneNode, plus inlet/exhaust/return node-or-NodeLists = ZoneInlet/ZoneExhaust/ZoneReturn. Membership: `ZoneHVAC:EquipmentList` → equipment. |
| Lists and boundaries | `NodeList`, `OutdoorAir:NodeList`, `OutdoorAir:Node` | Expand node lists. Outdoor-air nodes are boundaries. |
| Parents | `ZoneHVAC:AirDistributionUnit`, `ZoneHVAC:*` units, `AirLoopHVAC:Unitary*`, `CoilSystem:*`, `WaterHeater:HeatPump:*` | Parent nodes duplicate children's nodes. Mark them `parent=True` so they add no flow edges. Parent→child containment comes from the existing ReferenceGraph (component_name/coil_name fields are `object_list`). |

**Value-dependent semantics** need small predicate rules:

- `Chiller:*.condenser_type = AirCooled` makes the condenser nodes OutsideAir.
- A blank `Coil:Cooling:DX*.condenser_inlet_node_name` means outdoor.
- `Fan:ZoneExhaust.air_outlet_node_name` exits the building.

In the sweep these were the top residuals:

| Residual | Nodes | Files |
|---|---|---|
| `Fan:ZoneExhaust` | 156 | 42 |
| `Chiller:Electric` condenser outlet | 44 | 42 |
| `Coil:Cooling:DX` condenser outlet | 52 | 18 |
| `HeatExchanger:AirToAir:SensibleAndLatent` exhaust outlet | 23 | 20 |
| Zone return node with no air loop (legitimate) | 331 | 64 |

These are all boundary rules, not bugs.

### 2c. Prototype evidence

The prototype contains the 26.2 oracle, regex, 6 overrides, Branch consistency and the Splitter/Mixer junction rule.

| Run | Result |
|---|---|
| 575 example IDFs (24.1, every file containing `Branch`) | 58,027 nodes, **0 parse errors**, **0 Branch/component mismatches** |
| Same sweep, before junction and relief rules | 2,243 single-ended nodes |
| Same sweep, after | 908 single-ended nodes; 358/575 files clean |
| Fault injection (`Main Cooling Coil 1.air_outlet_node_name = "TYPO NODE"`) | `validate_document`: no change. Prototype: `branch/component node mismatch: VAV Sys 1 Main Branch / Main Cooling Coil 1: branch says Mixed Air Node 1 -> Main Cooling Coil 1 Outlet Node, component out=[…, 'TYPO NODE']` plus single-ended `TYPO NODE`. |
| Misclassification found | A name heuristic misfires: `AirTerminal:DualDuct:VAV:OutdoorAir.outdoor_air_inlet_node_name` is fed by a DOAS ZoneSplitter, not outdoors (11 nodes). This is why a curated table must beat heuristics. |

### 2d. Edge cases and version differences

- **Case:** EnergyPlus upper-cases node names. Key the index case-insensitively and keep the original spelling for display.
- **`node_or_nodelist` fields** (13 distinct field names in 24.1): resolve against `NodeList` first. A NodeList and a node may share a name, so prefer the NodeList as EnergyPlus does.
- **HVACTemplate:\*** objects have no nodes until ExpandObjects. Topology should run on `expand()` output (`simulation/expand.py`) or report "templates present, topology partial".
- **Version churn:**
  - 9.x adds `AirLoopHVAC:DedicatedOutdoorAirSystem`, `AirLoopHVAC:Mixer`/`Splitter` (extensible node fields).
  - 23.x adds `SpaceHVAC:EquipmentConnections`, `SpaceHVAC:ZoneEquipmentSplitter`/`Mixer`, `SpaceHVAC:ZoneReturnMixer`.
  - VRF coil fields drop the `_name` suffix.
  - The extensible-node-field count went from 9 (8.9) to 14 (26.2).

  Rules should be keyed `(type, field)` with a version-agnostic default and per-version overrides only where field names differ.
- **Plant demand vs supply:**
  - A component on a plant *demand* side (a water coil) is also on an *air* loop. These are two memberships via two fluid streams, so stream identity matters.
  - Supply-side components with two plant connections (chiller evaporator on CHW, condenser on CW; `HeatExchanger:FluidToFluid`; heat-pump plant EIR source side) bridge loops. That is exactly the "which loop is this on" question an LLM gets wrong.
- **Non-flow node uses** (sensor/setpoint/reference): `SetpointManager:*`, `Controller:WaterCoil` (sensor plus actuator on the water inlet), `Controller:OutdoorAir`, `AvailabilityManager:*`, `PlantEquipmentOperation:ComponentSetpoint`. These become *control edges*, not flow edges.

---

## 3. Proposed data model (idfkit core, stdlib only, pyright strict)

New sub-package `src/idfkit/hvac/`. It is computed on demand from an `IDFDocument`, like `geometry`, and is not live-maintained. It needs a revision counter or dirty flag on the document so callers can cache.

```python
# idfkit/hvac/types.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class ConnectionType(str, Enum):      # mirrors EnergyPlus DataLoopNode::ConnectionType
    INLET = "Inlet"; OUTLET = "Outlet"; INTERNAL = "Internal"; ZONE_NODE = "ZoneNode"
    SENSOR = "Sensor"; ACTUATOR = "Actuator"; OUTSIDE_AIR = "OutsideAir"; RELIEF_AIR = "ReliefAir"
    ZONE_INLET = "ZoneInlet"; ZONE_RETURN = "ZoneReturn"; ZONE_EXHAUST = "ZoneExhaust"; SETPOINT = "Setpoint"

class Fluid(str, Enum):
    AIR = "Air"; WATER = "Water"; STEAM = "Steam"; REFRIGERANT = "Refrigerant"; UNKNOWN = "Unknown"

class LoopKind(str, Enum):
    AIR = "AirLoopHVAC"; PLANT = "PlantLoop"; CONDENSER = "CondenserLoop"; ZONE_EQUIPMENT = "ZoneEquipment"

class Side(str, Enum):
    SUPPLY = "supply"; DEMAND = "demand"

@dataclass(frozen=True, slots=True)
class PortRule:                       # one row of the generated/curated table
    obj_type: str
    field: str                        # python field name; extensible sub-field allowed
    connection: ConnectionType
    stream: int = 1                   # pairs inlet/outlet of the same fluid stream
    fluid: Fluid = Fluid.UNKNOWN
    is_parent: bool = False
    nodelist_ok: bool = False
    when: tuple[str, str] | None = None   # (field, value) predicate, e.g. ("condenser_type","AirCooled")

@dataclass(frozen=True, slots=True)
class NodeUse:                        # an edge endpoint: object --(connection, stream)--> node
    node: str                         # display spelling
    obj: IDFObject
    field: str
    connection: ConnectionType
    stream: int
    is_parent: bool
    via_nodelist: str | None = None

@dataclass(slots=True)
class FlowEdge:                       # derived component->component edge through a node
    src: IDFObject; dst: IDFObject; node: str; fluid: Fluid
    kind: Literal["component", "branch_junction", "zone"]

@dataclass(slots=True)
class LoopMembership:
    loop: IDFObject; kind: LoopKind; side: Side
    branch: IDFObject | None; position: int | None   # index on branch, for chain rendering

@dataclass(slots=True)
class TopologyIssue:                  # mirrors validation.ValidationError shape
    code: str                         # e.g. "T001"
    severity: Literal["error", "warning", "info"]
    node: str | None; obj: IDFObject | None; message: str
```

```python
# idfkit/hvac/topology.py
class HVACTopology:
    @classmethod
    def from_document(cls, doc: IDFDocument) -> HVACTopology: ...
    # node level
    def nodes(self) -> Iterable[str]
    def uses(self, node: str) -> Sequence[NodeUse]              # all object/field uses
    def producers(self, node: str) -> list[IDFObject]           # non-parent Outlet/ZoneReturn/...
    def consumers(self, node: str) -> list[IDFObject]
    def controls(self, node: str) -> list[NodeUse]              # Sensor/Setpoint/Actuator
    # component level
    def ports(self, obj: IDFObject) -> list[NodeUse]
    def downstream(self, obj_or_node, *, stream: int | None = None, max_hops: int = 50) -> list[FlowEdge]
    def upstream(...) -> list[FlowEdge]
    def memberships(self, obj: IDFObject) -> list[LoopMembership]
    # loop level
    def loops(self) -> list[IDFObject]
    def chain(self, loop: IDFObject, side: Side) -> list[list[IDFObject]]   # parallel branches
    def zones_served(self, air_loop: IDFObject) -> list[IDFObject]
    # QA
    def check(self) -> list[TopologyIssue]
```

Rule-table sourcing (codegen, like `codegen/generate_stubs.py`):

1. **is-node:** generated from the 26.2 `data_type: node`, unioned with the regex for older versions. The output is a frozen dict in a generated `_node_fields.py`.
2. **Connection type, stream and parent:** default to the name heuristic. Override from a checked-in, curated `_port_rules.py` of about 150–250 rows.
   - **Preferred generator:** harvest the `Non-Parent Node Connection` and `Parent Node Connection` rows that EnergyPlus writes to `eplusout.bnd` for every ExampleFile. That gives *(ObjectType, ObjectName, Node, ConnectionType, FluidStream)*. Map back to a field by matching the node value in the IDF.
   - This is an offline step that needs an EnergyPlus install, not a runtime dependency. I could not run EnergyPlus in this sandbox (the execution was refused), so the harvest is **unvalidated**. The BND header layout I confirmed from the 24.1 `OutputDetailsAndExamples.pdf`, §2.3.

The design deliberately does **not** add node edges to `ReferenceGraph`. Node names are not object names, so mixing them would corrupt `get_referencing` and rename semantics. A separate lightweight `node → [(obj, field)]` index is enough. It also enables `doc.rename_node(old, new)`, which updates every node field and NodeList entry atomically and reuses `notify_reference_change`-style plumbing. That is the one live-maintained piece worth adding to `IDFDocument`.

### Static checks (codes illustrative)

| Code | Check | Source of rule |
|---|---|---|
| T001 | Inlet node with no matching Outlet/ZoneReturn/ZoneExhaust/ReliefAir/OutsideAir, and not a loop inlet | EnergyPlus `CheckNodeConnections` |
| T002 | ZoneInlet not an outlet of anything (terminal not tied to zone, or zone not served) | EnergyPlus |
| T003 | ZoneExhaust not an inlet of anything | EnergyPlus |
| T004 | Setpoint/actuator node with no flow use (setpoint manager on a nonexistent or typo'd node) | EnergyPlus |
| T010 | Branch component in/out ≠ component's own stream ports | EnergyPlus `TestCompSet` (prototype: works) |
| T011 | Branch discontinuity: `out[i] != in[i+1]` | EnergyPlus branch validation (BND) |
| T012 | Loop endpoint ≠ first/last branch node of that side | EnergyPlus |
| T013 | Splitter/Mixer branch not in the side's BranchList, or a BranchList branch not reached | eppy/OpenStudio-style |
| T020 | Plant/condenser supply outlet node has no setpoint (no SetpointManager covers it, directly or via NodeList) | Common EnergyPlus severe (domain knowledge; verify message text) |
| T021 | Air-loop supply outlet / `Controller:WaterCoil` sensor node has no setpoint manager | Same |
| T022 | Same water component on both supply and demand of one loop, or on two loops via one stream | Domain |
| T030 | Single-ended node not explained by any boundary rule (catch-all, warning) | Prototype |

---

## 4. Proposed MCP surface

Token discipline is the main design constraint. HospitalLowEnergy has 2,607 nodes and 6,876 objects. A full edge dump is about 100k tokens and useless, so every surface is targeted or aggregated.

### Tools and resources

| Name | Kind | Input | Output (shape) |
|---|---|---|---|
| `get_hvac_topology` | tool (read-only) | `loop: str \| None`, `detail: "summary" \| "chain"` (default summary) | One record per loop: `{name, kind, fluid, supply:{chain}, demand:{chain}, zones_served:n, setpoints:[node→SPM], issues:n}`. Chains are rendered as compact strings, and repeated parallel branches are collapsed. |
| `trace_node` | tool | `node: str` | `{node, fluid, loop, side, branch, producers:[type:name.field], consumers:[…], controls:[SPM/controller], upstream_component, downstream_component}`. The ideal answer to "what is this node". |
| `trace_component` | tool | `object_type, name, hops=3` | Ports by stream (`air: in→out`, `water: in→out`), memberships (`AirLoop VAV Sys 1/supply/branch 'Main Branch' pos 2`; `PlantLoop CHW/demand/branch 'Coil Br'`), up/downstream N hops, parent/children. |
| `check_model_integrity` | existing | — | Add `hvac_topology` checks (T0xx) as `IntegrityIssue(category="hvac_topology")`. Cap at 50 issues and group them by code with counts. |
| `rename_node` | tool (mutating) | `old, new` | `{fields_updated:n, objects:[…]}` |
| `idfkit://model/hvac/{loop}` | resource | — | Same as `get_hvac_topology(loop, "chain")`, for clients that prefer resources. |
| (phase 3) `compare_topology_with_bnd` | tool | uses last run dir | Static vs EnergyPlus node connections: missing or extra connections and EnergyPlus "Suspicious Node" list. |

Example `chain` rendering, hand-derived from the prototype data for `5ZoneAirCooled`:

```text
AirLoopHVAC "VAV Sys 1" (Air)
 supply: [VAV Sys 1 Inlet Node] OA Sys 1{OutdoorAir:Mixer, OA in: Outside Air Inlet Node 1, relief out}
   → [Mixed Air Node 1] Coil:Cooling:Water Main Cooling Coil 1 {water: CHW Loop/demand}
   → [Main Cooling Coil 1 Outlet Node] Coil:Heating:Water Main Heating Coil 1 {water: HW Loop/demand}
   → [Main Heating Coil 1 Outlet Node] Fan:VariableVolume Supply Fan 1
   → [VAV Sys 1 Outlet Node] SPM: Supply Air Temp Manager 1
 demand: [Zone Eq In Node] ZoneSplitter → 5× AirTerminal:SingleDuct:VAV:Reheat (reheat water: HW Loop/demand)
   → zones SPACE1-1..SPACE5-1 → ReturnPlenum Return-Plenum-1 → [PLENUM-1 Out Node]
```

That is roughly 150 tokens per air loop. Repeated terminals collapse to `N× type`.

### Concrete LLM use cases

The answers below are what the tools *would* return. They are illustrative, not run.

1. **"Simulation fails with 'Node Connection Error … Coil:Cooling:Water'. Fix it."**
   - Today: read the .err, then `search_objects` for the node string across types, by trial and error.
   - With the tools: `trace_component("Coil:Cooling:Water","Main Cooling Coil 1")` returns `T010: branch 'VAV Sys 1 Main Branch' expects outlet 'Main Cooling Coil 1 Outlet Node'; component air outlet is 'TYPO NODE' (no consumer)`. The fix is one `update_object` call.
2. **"Is zone SPACE3-1 served by an air loop, and by which plant?"** `trace_node("SPACE3-1 In Node")` returns producer `AirTerminal:SingleDuct:VAV:Reheat SPACE3-1 VAV Reheat` ∈ `AirLoop VAV Sys 1/demand`, with reheat coil water stream on `HW Loop/demand`.
3. **"Add a second chiller in parallel."** `get_hvac_topology("CHW Loop","chain")` shows the supply side's splitter/mixer and branch list. The LLM then knows it must touch `Branch`, `BranchList`, `Connector:Splitter` and `Connector:Mixer`. Re-running T011–T013 confirms the change.
4. **"Why is the CHW loop not meeting setpoint / severe 'missing setpoint'?"** `T020: PlantLoop 'CHW Loop' supply outlet node 'CHW Supply Outlet' has no SetpointManager`.
5. **"Rename all 'AHU-1' nodes to 'AHU-A'."** `rename_node` per node, instead of `sed`-style edits across dozens of objects.
6. **"Draw / explain the HVAC system."** A chain summary is a compact description an LLM can narrate or turn into a diagram.

### Does it materially help? Evidence and caveats

- **Evidence for:**
  - Today the MCP gives an LLM *no* way to learn node connectivity except reading every object. Both `get_referencing` and the `references/{name}` resource return empty for nodes (demonstrated).
  - Node errors otherwise appear only after a full simulation, deep in the .err file.
  - The prototype detects the most common authoring fault class with zero false positives on Branch consistency across 575 real models.
- **Caveat (speculative):** I have no measured LLM success-rate data. I propose a cheap eval before investing beyond phase 1:
  - Inject about 10 fault types into about 20 example files: node typo, swapped inlet/outlet, missing branch-list entry, missing SPM, terminal outlet ≠ zone inlet, component on the wrong loop side, and others.
  - Compare an agent's fix rate, tool calls and tokens with and without `trace_*` and the T-checks.
  - The fault injector doubles as an idfkit test fixture.

---

## 5. Prior art

Verified items come from local docs. The rest are from memory and marked so.

| Prior art | What it does | Borrow |
|---|---|---|
| **EnergyPlus NodeInputManager / BranchNodeConnections** (ModuleDeveloper.pdf §7.4, verified locally) | Every node use is registered as *(object, node, ConnectionType, FluidStream, IsParent)*. `CheckNodeConnections` rules. `TestCompSet` cross-checks parent vs Branch component sets. | **Mirror its data model exactly**, so idfkit's issues map one-to-one to EnergyPlus severes and the BND file is a ground-truth oracle. |
| **`eplusout.bnd`** (OutputDetailsAndExamples.pdf §2.3, verified) | CSV-like file containing: `Node` (with ref counts), `Suspicious Node` (0 refs), `Branch List`/`Branch` (loop, type, in/out), `Supply/Return Air Path` component nodes, `Outdoor Air Node`, `Component Set` (parent type/name, component, in/out, description), plus parent/non-parent node connections (used by the HVAC Diagram utility). | (a) Cross-check after `run_simulation`: the MCP can diff static vs BND. (b) Offline codegen of the port-rule table. (c) An integration-test oracle over ExampleFiles. A stdlib parser is about 150 LOC. |
| **EnergyPlus HVAC Diagram utility** (bnd → SVG) | Draws loops from the BND. | Proof that BND has enough data to reconstruct topology. `idfkit.visualization` could do a static SVG later. |
| **OpenStudio SDK** (from memory) | `Loop`/`AirLoopHVAC`/`PlantLoop`, `Node` as a first-class ModelObject, `HVACComponent`/`StraightComponent`/`WaterToAirComponent` with `inletModelObject()`/`outletModelObject()`, `supplyComponents()`/`demandComponents()`, connections stored as `OS:Connection` (source/target object and port). | Typed ports per stream and supply/demand component queries as the API shape. Do **not** copy "nodes as objects": IDF nodes are strings, and inventing objects breaks round-tripping. |
| **eppy** (from memory) | `hvacbuilder` (`makeairloop`, `makeplantloop`, `replacebranch`, `getnodefieldname` using IDD `\type node` and Inlet/Outlet substrings) and `useful_scripts/loopdiagram.py` (Branch + Splitter/Mixer → graphviz). | Confirms that the name heuristic plus Branch/Connector rules is the community baseline. idfkit can beat it with stream pairing, parent handling and checks. `idfkit/_compat.py` is the eppy shim, so a later `hvacbuilder`-like builder could sit on top of the topology. |
| **Ladybug/Honeybee-energy** (from memory) | HVAC as templates mapped through OpenStudio Standards. No node-level graph exposed. | Little to borrow. Shows the template-first design that idfkit already supports with `hvac-templates`. |
| **Brick / ASHRAE 223P** (223P draft status confirmed via search; ontology details from memory) | Brick: `brick:feeds`/`isFedBy`, `hasPart`, `isPointOf`. 223P: `Equipment`/`DomainSpace`/`Junction` with typed `InletConnectionPoint`/`OutletConnectionPoint` carrying a `Medium`, joined by `Connection`s. | 223P's ConnectionPoint/Medium model is isomorphic to *(ConnectionType, FluidStream, Fluid)*. Name edge types to be exportable later (an N-Triples writer is stdlib-only). Speculative and low priority. |
| **LLM on HVAC graphs** (from memory, unverified: e.g. Eplus-LLM for NL→IDF; LLM-assisted Brick model generation) | Generation-focused. I'm not aware of work that gives an LLM a queryable EnergyPlus node graph. | The eval proposed above would be a novel, publishable result. |

---

## 6. Effort, risks, phased plan

### Phase 0: fix the docs (½ day, do now)

- Correct the false `E004`-for-nodes claims in `agent_references/templates/hvac-loops.md`, along with the `trace-referencing` and `mistake-walk-good` snippets. Re-bake.
- Mention in the idfkit-mcp server instructions that node names are not covered by `references/{name}`.

### Phase 1: node index and static checks (smallest valuable step, about 4–6 dev-days)

**idfkit:**

- Add `hvac/` with the generated `_node_fields.py` (26.2 tag plus regex) and the `NodeIndex`.
- Handle NodeList expansion and case-folding.
- Add a curated `PortRule` table for about 40 types: loops, Branch, Connector, OA mixer/system, ZoneHVAC:EquipmentConnections, setpoint managers, controllers, top boundary emitters.
- Implement checks T001–T004, T010, T011 and T030.
- Tests:
  - Unit tests on `simple_doc`-style fixtures.
  - A fault-injection test.
  - An *opt-in* sweep over EnergyPlus ExampleFiles, marked integration, that asserts no T010 or T011 issues.

**idfkit-mcp:**

- `trace_node`.
- A `hvac_topology` check group in `check_model_integrity`.

**Exit criterion:** T010/T011 report zero issues on all ExampleFiles, and T001-class false positives are under 0.5% of nodes.

### Phase 2: loop membership and summaries (about 4–5 days)

- Supply/demand membership (BranchList, Splitter/Mixer, air demand via SupplyPath/ReturnPath, zone equipment lists).
- `chain()` with parallel-branch collapse.
- `trace_component`, `get_hvac_topology` and the `idfkit://model/hvac/{loop}` resource.
- Checks T012, T013 and T020–T022.
- `rename_node` in core and MCP.
- New agent reference topic `hvac-topology.md` plus snippet, and CHANGELOG entries.

### Phase 3: EnergyPlus as oracle (about 3–4 days)

- A stdlib `simulation/parsers/bnd.py` and `SimulationResult.bnd_path`.
- MCP `compare_topology_with_bnd`.
- Classify the `Node Connection Error` severes in `_classify_warnings`.
- A codegen script to harvest the port-rule table from ExampleFile BNDs (requires an EnergyPlus install offline).

### Phase 4 (optional)

- A static SVG schematic in `visualization`.
- A 223P/Brick-flavoured export.
- An eppy-style loop *builder* on top of the topology.

**Total:** about 2–3 weeks for phases 0–3. Phase 1 alone delivers most of the debugging value.

### Risks

1. **Rule-table maintenance.** About 260 node-bearing types, growing about 3 per release. Mitigations: the 26.2 tag, BND harvesting, and a generic fallback that degrades to "unclassified" rather than raising false errors. Unknown types should yield `info`, never `error`.
2. **False positives erode trust.** An LLM told "error" will "fix" correct models. Gate everything except T010/T011 (which have zero false positives in the sweep) as `warning` until BND-validated.
3. **Value-dependent semantics** (condenser type, blank-means-outdoor, unitary-system parent/child modes) need predicates. Some are irreducibly EnergyPlus-internal.
4. **HVACTemplate models** have no nodes before expansion, so the topology must say so explicitly.
5. **Caching and staleness:** topology is derived. Recompute per call. That is cheap: the prototype parsed and analysed 575 models in under 10 minutes total, including IDF parsing, which dominates. For heavy MCP sessions, cache by document revision.
6. **Scope creep into an HVAC builder.** Keep phases 1–3 read-only plus `rename_node`.

### What I could not verify

- I could not run EnergyPlus here (execution was refused), so there is no live BND cross-check.
- bigladdersoftware.com is not reachable from this session. BND and node-connection details come from the PDFs bundled with the local EnergyPlus 24.1 install.
- OpenStudio, eppy, Honeybee and LLM-literature statements are from memory.
