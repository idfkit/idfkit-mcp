# Model Graph Tool

An EnergyPlus model is joined in two ways. Objects name other objects: a coil names its availability schedule,
a terminal names its reheat coil. HVAC objects also share node names: a coil's air outlet node is the next
component's air inlet node. `idfkit://model/references/{name}` sees the first kind only, and the HVAC topology
tools see the second. `get_object_neighbourhood` walks both at once, from one object or node, as one graph.

| Tool | Use it for |
|---|---|
| `get_object_neighbourhood` | What surrounds one object or node, across references, flow, controls and loop membership |

There is no export tool and no graph resource. A Python user can write the whole graph as node-link JSON with
`idfkit.graph.write_node_link(ModelGraph(doc))`, or save it to a file with `idfkit.graph.save_node_link`.

## `get_object_neighbourhood`

Walks the model graph breadth first, in both directions, from one object or node, and returns the nodes and
edges it reached.

Parameters:

| Parameter | Default | Notes |
|---|---|---|
| `object_type` | required | The start object's type, or `"Node"` to start from a fluid node |
| `name` | required | Object or node name, matched case-insensitively |
| `hops` | `1` | 1–3. Most edges walked from the start |
| `node_kinds` | none | Walk only through these node kinds: `object`, `node`, `result_fact`, `message` |
| `edge_kinds` | none | Walk only along these edge kinds: `reference`, `flow`, `control`, `membership`, `result_link` |
| `categories` | none | Keep only object nodes of these component categories, such as `heating_coil`, `boiler`, `terminal_unit`, plus the start and the fluid nodes on the paths to them |
| `max_nodes` | `20` | 1–100. Most nodes returned, the start included. Fewer are returned when the response would pass 8 KB |

The response:

| Field | Content |
|---|---|
| `start` | The graph id of the start, such as `object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL` or `node:SPACE1-1 IN NODE` |
| `nodes` | The nodes returned, breadth first from the start |
| `edges` | The edges between returned nodes, in the order the walk found them |
| `layers` | The layers present: `model` and `topology` |
| `unavailable` | Each missing layer, with the reason |
| `truncated` | `true` when the hop bound, the node bound or the 8 KB limit cut the walk |
| `omitted_nodes` | Nodes reached but not returned. A lower bound, since the walk stops at the cut |
| `frontier` | Returned node ids with neighbours that were not returned |
| `results_state` | `fresh` or `stale` when the results layer is present; none otherwise |
| `coverage` | What the view could not see, as in `trace_hvac` |

Each node:

| Field | Content |
|---|---|
| `id` | The graph id, used by `start`, `frontier` and the edges |
| `kind` | `object` or `node`. Ignore kinds you do not know |
| `object_type` | For an object: its type. Absent for a fluid node |
| `name` | The object's name or the node's name, in the model's spelling |
| `attrs` | For an object: its component `category` (`other` for a non-HVAC object). For a node: its `fluid` |

Each edge carries `source`, `target`, `kind`, `key` and `attrs`. For `reference`, `flow` and `control` edges
the key is `<kind>:<field>`, such as `reference:zone_name` or `flow:air_inlet_node_name`, so it names the field;
it is unique for the edge's two endpoints. A node's or edge's layer is fixed by its kind (table below), so the
response does not repeat it.

### Edge kinds

Edges are directed. The direction says which end names the other, or which way the fluid flows:

| Kind | Layer | Direction | `attrs` |
|---|---|---|---|
| `reference` | `model` | object → the object it names | none: the field is in the key |
| `flow` | `topology` | object → node for an outlet; node → object for an inlet | `connection_type`, `provenance`, `fluid` |
| `control` | `topology` | control object → the node it senses or sets | `connection_type` (`Sensor`, `Setpoint`, …), `provenance`, `rule` and `confidence` for an EMS sensor or actuator, and `via_nodelist` when the field names a `NodeList` |
| `membership` | `topology` | component → the loop it sits on | `loop_kind` (`air`, `plant`, `condenser`), `side`, `branch`, `position` |

`connection_type` and `provenance` mean what they mean in `trace_hvac`. A water coil has a `membership` edge to
each of its loops, so from the coil one hop reaches both its air loop and its plant loop:

```text
node:SPACE1-1 ZONE COIL AIR IN NODE   → object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL   flow:air_inlet_node_name
object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL → node:SPACE1-1 IN NODE                   flow:air_outlet_node_name
node:SPACE1-1 ZONE COIL WATER IN NODE → object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL   flow:water_inlet_node_name
object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL → node:SPACE1-1 ZONE COIL WATER OUT NODE  flow:water_outlet_node_name
object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL → object:AIRLOOPHVAC:VAV SYS 1            membership:air
object:COIL:HEATING:WATER:SPACE1-1 ZONE COIL → object:PLANTLOOP:HOT WATER LOOP         membership:plant
```

That is `get_object_neighbourhood(object_type="Coil:Heating:Water", name="SPACE1-1 Zone Coil",
edge_kinds=["flow", "membership"])` on `5ZoneAirCooled.idf`. The plant membership carries
`{"side": "demand", "branch": "SPACE1-1 Reheat Branch", "position": 0, "loop_kind": "plant"}`.

The walk follows edges in both directions whatever their direction, so the start's referrers are reached as
well as what it names.

### The results layer

After a `run_simulation` in this session, the walk also reaches the run's results: `result_fact` nodes
(one reported value, with `metric`, `value`, `units`, `source`, `where` and, for zones, `multiplier`) and
`message` nodes (one warning, severe or fatal message, with `severity`, `message_kind`, `text`,
`occurrences` and `first_seen`), each joined to its object or node by a `result_link` edge carrying the
link's `confidence` and `rule`. An object can carry well over a hundred facts: pass
`node_kinds=["result_fact"]` or `["message"]` to walk only those. `results_state` is `fresh`, or `stale`
when the model changed since the run; stale results are still returned, with `stale: true` on each node.

Without results, `unavailable` says why: `"results": "no simulation run in this session"` before a run,
and `"results": "the session's run could not be linked to the model (no SQLite output)"` when the run
wrote no SQLite file. A missing layer is never an error.

### Size and continuation

A response stays within 8 KB. When the walk at `max_nodes` would serialise to more, the tool returns the
longest breadth-first part of it that fits, with the edges between the nodes it keeps, and sets `truncated`.
It never returns a partial node or edge. On the reference model (HospitalLowEnergy) about 12 to 20 nodes fit,
which is why the default is 20.

When `truncated` is `true`, `frontier` lists the returned nodes that have neighbours not returned. To continue
from one, call the tool again with that node's `object_type` and `name`, or, for a fluid node, with
`object_type="Node"` and its `name`. Narrowing the walk with `edge_kinds`, `node_kinds` or `categories` reaches further within the same
size.

## Example: what controls a node?

`get_object_neighbourhood(object_type="Node", name="Main Cooling Coil 1 Outlet Node", edge_kinds=["control"])`
on `5ZoneAirCooled.idf` (`coverage` omitted):

```json
{
  "start": "node:MAIN COOLING COIL 1 OUTLET NODE",
  "nodes": [
    {"id": "node:MAIN COOLING COIL 1 OUTLET NODE", "kind": "node", "object_type": null,
     "name": "Main Cooling Coil 1 Outlet Node", "attrs": {"fluid": "Air"}},
    {"id": "object:CONTROLLER:WATERCOIL:CENTRAL COOLING COIL CONTROLLER 1", "kind": "object",
     "object_type": "Controller:WaterCoil", "name": "Central Cooling Coil Controller 1",
     "attrs": {"category": "controller"}},
    {"id": "object:SETPOINTMANAGER:MIXEDAIR:MIXED AIR TEMP MANAGER 1", "kind": "object",
     "object_type": "SetpointManager:MixedAir", "name": "Mixed Air Temp Manager 1",
     "attrs": {"category": "setpoint_manager"}}
  ],
  "edges": [
    {"source": "object:CONTROLLER:WATERCOIL:CENTRAL COOLING COIL CONTROLLER 1",
     "target": "node:MAIN COOLING COIL 1 OUTLET NODE", "kind": "control",
     "key": "control:sensor_node_name",
     "attrs": {"connection_type": "Sensor", "provenance": "eplus_examples"}},
    {"source": "object:SETPOINTMANAGER:MIXEDAIR:MIXED AIR TEMP MANAGER 1",
     "target": "node:MAIN COOLING COIL 1 OUTLET NODE", "kind": "control",
     "key": "control:setpoint_node_or_nodelist_name",
     "attrs": {"connection_type": "Setpoint", "provenance": "eplus_examples",
               "via_nodelist": "Main Branch SetPoint Node List"}}
  ],
  "layers": ["model", "topology"],
  "unavailable": {"results": "no simulation run in this session"},
  "truncated": true,
  "omitted_nodes": 4,
  "frontier": [
    "object:CONTROLLER:WATERCOIL:CENTRAL COOLING COIL CONTROLLER 1",
    "object:SETPOINTMANAGER:MIXEDAIR:MIXED AIR TEMP MANAGER 1"
  ],
  "results_state": null
}
```

The setpoint manager reaches the node through the `NodeList` its field names, so the edge carries
`via_nodelist`. The walk stopped at one hop, and both objects control other nodes, so both are on the frontier.

## Example: an object with no node fields

A construction has no HVAC connections, so `trace_hvac` refuses it and points here.
`get_object_neighbourhood(object_type="Construction", name="ROOF-1", hops=2)` on `5ZoneAirCooled.idf` returns
its four materials and the surface that uses it, all by `reference` edges, and one hop further the surface's
zone and another construction that shares a material:

```text
object:CONSTRUCTION:ROOF-1 → object:MATERIAL:RG01                 reference:outside_layer
object:BUILDINGSURFACE:DETAILED:TOP-1 → object:CONSTRUCTION:ROOF-1 reference:construction_name
object:BUILDINGSURFACE:DETAILED:TOP-1 → object:ZONE:PLENUM-1       reference:zone_name
object:CONSTRUCTION:WALL-1 → object:MATERIAL:WD01                  reference:outside_layer
```

The edges to its three other materials are left out above.

## Errors

Errors name the cause and never pick for you:

- no model loaded;
- an object that is not in the model, with the closest names:
  `No Coil:Heating:Water named 'SPACE1-1 Zone Coi'. Closest: 'SPACE1-1 Zone Coil', 'SPACE5-1 Zone Coil', …`;
- a node no object uses, with the closest node names:
  `No node named 'Main Coling Coil 1 Outlet Node' is used by any object. Closest: 'Main Cooling Coil 1 Outlet Node', …`;
- `hops` or `max_nodes` out of range: `hops must be between 1 and 3, got 4.`;
- an unknown node kind, edge kind or category, with the list of valid ones:
  `Unknown edge kinds ['flows']. Valid edge kinds: reference, flow, control, membership, result_link.`

The tool's output schema lists the top-level fields only, to keep the tool listing small; the tables above
give the full shape.

## Nearest neighbours

Each tool's description names the tool closest to it and when to use that one instead:

| Tool | Nearest neighbour | Use this one when |
|---|---|---|
| `trace_hvac` | `get_object_neighbourhood` | you need loop, side, branch, position and controls of one node or component |
| `get_hvac_topology` | `trace_hvac` | you need a whole loop, or every loop, in flow order |
| `rename_node` | `rename_object` | the name is a node name, not an object name |
| `get_object_results` | `get_object_neighbourhood` | you need every result and message for one object, with counts |
| `get_object_neighbourhood` | `trace_hvac` | you need to cross layers, or the object has no node fields |

`trace_hvac` interprets the topology for you; `get_object_neighbourhood` returns the raw graph, references
included, and leaves the reading to you.
