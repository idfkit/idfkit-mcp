# HVAC Topology Tools

EnergyPlus joins HVAC objects through node names: a coil's air outlet node and the next fan's air inlet
node are the same string. Node names are not references, so `idfkit://model/references/{name}` does not
see them, and a mistyped node passes `validate_model`. These tools read the node graph that idfkit derives
from the model, and `rename_node` edits it.

| Tool or resource | Use it for |
|---|---|
| `get_hvac_topology` | Every loop, or one: its sides, zones served, setpoint nodes and findings |
| `trace_hvac` | One node or component: its ports, loops, flow up and downstream, controls and findings |
| `rename_node` | Renaming a node in every field and `NodeList` entry that uses it |
| `idfkit://model/hvac/{loop}` | One loop in flow order, without a tool call |

## `get_hvac_topology`

Summarises the model's air, plant and condenser loops: kind, fluid, supply and demand sides, zones served,
setpoint nodes and connection findings per code.

Parameters:

| Parameter | Default | Notes |
|---|---|---|
| `loop` | none | One `AirLoopHVAC`, `PlantLoop` or `CondenserLoop`, matched case-insensitively. Without it, every loop |
| `detail` | `"summary"` | `"summary"`: counts per side. `"chain"`: each side as one flow-order string |
| `limit` | `20` | 1–100. Most loops per response. Fewer whole loops are returned when the next would take the response past 8 KB; the rest are counted in `omitted` |

The response:

| Field | Content |
|---|---|
| `loops` | One entry per loop: air loops, then plant loops, then condenser loops, each in model order |
| `total` | Loops matched before `limit` |
| `omitted` | Loops matched but not returned |
| `coverage` | What the view could not see, as in `trace_hvac` |

Each loop:

| Field | Content |
|---|---|
| `loop` | `{object_type, name}` of the loop object |
| `kind` | `air`, `plant` or `condenser` |
| `fluid` | `Air` for an air loop; the loop's `fluid_type` otherwise, `Water` when unset |
| `supply`, `demand` | In `summary`: `"4 branches, 4 components"`; an air demand side counts paths. In `chain`: the side in flow order, described below |
| `zones_served` | Zones an air loop reaches; `0` for plant and condenser loops |
| `setpoint_nodes` | Nodes on the loop, of the loop's own fluid, that a setpoint manager writes |
| `finding_counts` | Connection findings touching the loop's objects, by code, such as `{"T010": 1}` |

### Chain mode

A side is one string. Components are `Type 'Name'`, joined by `→` in flow order, and parallel paths sit
between braces, separated by `|`:

- a plant or condenser side runs inlet branch → {parallel branches} → outlet branch;
- an air loop's supply side runs inlet branch → {decks} when it has more than one branch;
- an air loop's demand side lists its paths to the zones, then its return paths, separated by `;`.

Repeated paths collapse to a count, so a side stays short however many zones it serves:

- single-component paths of one type, such as parallel plant branches, collapse to `7× Coil:Heating:Water`;
- longer paths collapse only when they also start at the same component, whose name is kept:
  `5× AirLoopHVAC:ZoneSplitter 'Zone Supply Air Splitter 1' → AirTerminal:SingleDuct:VAV:Reheat → Coil:Heating:Water`.
  A dual-duct system's two decks have the same component types but different splitters, so they stay two
  entries;
- a path seen once keeps every name.

### Example: the loops of a VAV system

On EnergyPlus's `5ZoneAirCooled.idf` (`tests/fixtures/5ZoneAirCooled.idf.gz`), `get_hvac_topology()` returns the counts:

```json
{
  "loop": {"object_type": "PlantLoop", "name": "Hot Water Loop"},
  "kind": "plant",
  "fluid": "Water",
  "supply": "4 branches, 4 components",
  "demand": "10 branches, 10 components",
  "zones_served": 0,
  "setpoint_nodes": ["HW Supply Outlet Node", "Central Boiler Outlet Node"],
  "finding_counts": {}
}
```

and `get_hvac_topology(detail="chain")` the sides in flow order (one loop of three shown, `coverage` omitted):

```json
{
  "loops": [
    {
      "loop": {"object_type": "AirLoopHVAC", "name": "VAV Sys 1"},
      "kind": "air",
      "fluid": "Air",
      "supply": "AirLoopHVAC:OutdoorAirSystem 'OA Sys 1' → Coil:Cooling:Water 'Main Cooling Coil 1' → Coil:Heating:Water 'Main Heating Coil 1' → Fan:VariableVolume 'Supply Fan 1'",
      "demand": "5× AirLoopHVAC:ZoneSplitter 'Zone Supply Air Splitter 1' → AirTerminal:SingleDuct:VAV:Reheat → Coil:Heating:Water; AirLoopHVAC:ReturnPlenum 'Return-Plenum-1'",
      "zones_served": 5,
      "setpoint_nodes": [
        "VAV Sys 1 Outlet Node",
        "Mixed Air Node 1",
        "Main Cooling Coil 1 Outlet Node",
        "Main Heating Coil 1 Outlet Node"
      ],
      "finding_counts": {}
    }
  ],
  "total": 3,
  "omitted": 0
}
```

The plant loops in the same response:

```text
Hot Water Loop
  supply: Pump:VariableSpeed 'HW Circ Pump' → {Boiler:HotWater 'Central Boiler' | Pipe:Adiabatic 'Heating Supply Side Bypass'} → Pipe:Adiabatic 'Heating Supply Outlet'
  demand: Pipe:Adiabatic 'Heating Demand Inlet Pipe' → {7× Coil:Heating:Water | Pipe:Adiabatic 'Heating Demand Bypass'} → Pipe:Adiabatic 'Heating Demand Outlet Pipe'
Chilled Water Loop
  supply: Pump:VariableSpeed 'CW Circ Pump' → {Chiller:Electric 'Central Chiller' | Pipe:Adiabatic 'Supply Side Bypass'} → Pipe:Adiabatic 'Supply Side Outlet Pipe'
  demand: Pipe:Adiabatic 'Cooling Demand Side Inlet Pipe' → {2× Coil:Cooling:Water | Pipe:Adiabatic 'Cooling Demand Side Bypass'} → Pipe:Adiabatic 'CW Demand Side Outlet Pipe'
```

On a dual-duct system the two decks appear on the supply side as two parallel paths, and on the demand side
as two entries, one per splitter:

```text
6× AirLoopHVAC:ZoneSplitter 'DUALDUCT_OTHER RC Supply Air Splitter' → AirTerminal:DualDuct:VAV:OutdoorAir; 6× AirLoopHVAC:ZoneSplitter 'DUALDUCT_OTHER Supply Air Splitter' → AirTerminal:DualDuct:VAV:OutdoorAir; AirLoopHVAC:ZoneMixer 'DUALDUCT_OTHER Return Air Mixer'
```

A loop name that is not in the model is an error listing the closest loop names:
`No AirLoopHVAC, PlantLoop or CondenserLoop named 'chilled water lop'. Closest: 'Chilled Water Loop', 'Hot Water Loop'.`

To go from a loop to one of its components, call `trace_hvac` on the component.

## `trace_hvac`

Traces one node or component: what connects to it, what flows up and downstream of it, what controls it,
and which connection findings touch it.

Parameters:

| Parameter | Default | Notes |
|---|---|---|
| `object_type` | required | `"Node"` for a node or a `NodeList`; `"Zone"` or `"Space"` for a zone; otherwise a component type |
| `name` | required | Matched case-insensitively |
| `hops` | `2` | 0–10. Flow edges walked upstream and downstream |
| `categories` | none | Keep only walk edges ending at components of these categories, such as `heating_coil`, `boiler`, `terminal_unit`. The walk still passes through other components |
| `fluid` | none | `Air`, `Water`, `Steam` or `Refrigerant`: keep the walks on edges of that fluid. Without it a walk follows every stream of each component, so from a coil it crosses from air to water |

The response:

| Field | Content |
|---|---|
| `start` | The node (`object_type: "Node"`), the `NodeList`, or the object with its component `category` |
| `fluid` | For a node: the fluid it carries |
| `ports` | For an object: every field naming a node, ordered by stream |
| `producers`, `consumers` | For a node: the components writing and reading it |
| `controls` | Setpoint managers, sensors, controllers and EMS uses on the start's nodes |
| `memberships` | The loops the start sits on, described below |
| `parent`, `children` | For a component: the equipment that contains it (a reheat coil's terminal, a terminal's air distribution unit), and what it contains |
| `upstream`, `downstream` | Flow edges `{source, target, node, fluid, kind}`, breadth first. A zone appears as `Zone` |
| `findings` | The connection findings touching the start, as in `check_model_integrity`, with `expected` and `actual` for a mismatch |
| `coverage` | What the view could not see: unexpanded `HVACTemplate` systems, EMS programs, object types without a rule |

Each node use in `ports` and `controls` carries `node`, `object`, `category`, `field`, `connection` (the
EnergyPlus role: `Inlet`, `Outlet`, `ZoneInlet`, `Sensor`, `Setpoint`, …), `stream`, `fluid`, `is_parent`,
and `provenance`: whether EnergyPlus reported the role (`eplus_examples`, `eplus_test_model`) or it was
written from the field's name (`hand_written`).

Each membership carries `loop` (`{object_type, name}`), `kind` (`air`, `plant`, `condenser` or
`zone_equipment`), `side` (`supply`, `demand`, or none), `branch` (the `Branch` that lists the component, or
none), `position` (0-based on that branch) and `stream` (the component's port stream on that loop). A water
coil sits on two loops, so it reports both:

```json
[
  {"loop": {"object_type": "AirLoopHVAC", "name": "VAV Sys 1"}, "kind": "air",
   "side": "demand", "branch": null, "position": null, "stream": 1},
  {"loop": {"object_type": "PlantLoop", "name": "Hot Water Loop"}, "kind": "plant",
   "side": "demand", "branch": {"object_type": "Branch", "name": "SPACE1-1 Reheat Branch"},
   "position": 0, "stream": 2}
]
```

That is `trace_hvac(object_type="Coil:Heating:Water", name="SPACE1-1 Zone Coil")` on
`5ZoneAirCooled.idf`. A component on an air loop's path but on no branch (an outdoor-air mixer, a terminal
unit, the reheat coil inside it, a zone splitter) reports its side with no branch. Equipment in a zone's
equipment list reports a `zone_equipment` membership keyed by its `ZoneHVAC:EquipmentConnections`. For a
node, `memberships` holds those of its producers and consumers, each loop and side once per stream. A zone
is on no loop, so its `memberships` is empty.

Errors name the cause and never pick for you:

- no model loaded;
- a name or type that is not in the model, with the closest names;
- a node or `NodeList` no object uses, with the closest node names;
- an object with no node fields, pointing at `idfkit://model/references/{name}`;
- an unknown category or fluid, with the list of valid ones.

The tool's output schema lists the top-level fields only, to keep the tool listing small; the tables above
give the full shape.

## Example: which plant serves a coil?

```
trace_hvac(object_type="Coil:Heating:Water", name="SPACE1-1 Zone Coil",
           hops=10, categories=["boiler", "chiller"], fluid="Water")
```

`upstream` holds the boiler only. Without `fluid`, the walk would also cross the coil's air stream and could
reach another coil's plant.

## Example: a mistyped node

After setting a cooling coil's `air_outlet_node_name` to a node nothing else uses,
`trace_hvac(object_type="Coil:Cooling:Water", name="Main Cooling Coil 1")` reports a `T010` finding naming
the branch, the field, the node the branch expects and the node the coil now names, and the downstream walk
no longer reaches the heating coil.

## `rename_node`

Renames a node in every field and `NodeList` entry that uses it, in one step. Node names are not references,
so `rename_object` never reaches them; renaming a node by hand with `update_object` means finding every field
that spells it, and missing one breaks the connection.

Parameters:

| Parameter | Notes |
|---|---|
| `old` | Current node name, matched case-insensitively |
| `new` | New name. Must not be empty, equal to `old`, or already a node of the model |

The response:

| Field | Content |
|---|---|
| `old`, `new` | The node's name before and after, in the model's spelling |
| `fields_updated` | Node fields and `NodeList` entries rewritten |
| `objects` | Each changed object once, as `{object_type, name}` |

`rename_node(old="Main Cooling Coil 1 Outlet Node", new="Cooling Coil Leaving Air")` on `5ZoneAirCooled.idf`:

```json
{
  "old": "Main Cooling Coil 1 Outlet Node",
  "new": "Cooling Coil Leaving Air",
  "fields_updated": 6,
  "objects": [
    {"object_type": "Branch", "name": "VAV Sys 1 Main Branch"},
    {"object_type": "Coil:Cooling:Water", "name": "Main Cooling Coil 1"},
    {"object_type": "Coil:Heating:Water", "name": "Main Heating Coil 1"},
    {"object_type": "Controller:WaterCoil", "name": "Central Cooling Coil Controller 1"},
    {"object_type": "NodeList", "name": "Main Branch SetPoint Node List"}
  ]
}
```

A field that names a `NodeList` keeps naming the list. Output variable keys and other free-text fields that
happen to spell the node are not node fields and are left alone. If one write fails, the writes already made
are undone.

Errors:

- no model loaded;
- no field uses `old`, with the closest node names:
  `No field uses a node named 'Main Coling Coil 1 Outlet Node'. Closest: 'Main Cooling Coil 1 Water Outlet Node', …`;
- `new` is already a node: `'Main Heating Coil 1 Outlet Node' is already a node in the model; rename_node never
  merges two nodes. Choose another name.`;
- `new` is empty or equal to `old`.

A successful rename is recorded in the change log, so `get_change_log` shows it with the node names and the
field count:

```json
{"tool": "rename_node", "summary": "rename_node: Main Cooling Coil 1 Outlet Node -> Cooling Coil Leaving Air (6 fields)"}
```

Nearest neighbour: `rename_object`, for object names, which cascades through references.

## Resource: `idfkit://model/hvac/{loop}`

One loop in chain mode, as JSON: the same content as `get_hvac_topology(loop=..., detail="chain")`, with
`loops` holding that loop alone. Use it when a client reads resources without a tool call. The loop name is
matched case-insensitively and URL-encoded in the URI (`idfkit://model/hvac/Chilled%20Water%20Loop`). An
unknown loop is an error listing the closest loop names, as in the tool.
