# HVAC Topology Tools

EnergyPlus joins HVAC objects through node names: a coil's air outlet node and the next fan's air inlet
node are the same string. Node names are not references, so `idfkit://model/references/{name}` does not
see them, and a mistyped node passes `validate_model`. These tools read the node graph that idfkit derives
from the model.

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
| `memberships` | Empty for now: loop, side, branch and position arrive with `get_hvac_topology` |
| `parent`, `children` | For a component: the equipment that contains it (a reheat coil's terminal, a terminal's air distribution unit), and what it contains |
| `upstream`, `downstream` | Flow edges `{source, target, node, fluid, kind}`, breadth first. A zone appears as `Zone` |
| `findings` | The connection findings touching the start, as in `check_model_integrity`, with `expected` and `actual` for a mismatch |
| `coverage` | What the view could not see: unexpanded `HVACTemplate` systems, EMS programs, object types without a rule |

Each node use in `ports` and `controls` carries `node`, `object`, `category`, `field`, `connection` (the
EnergyPlus role: `Inlet`, `Outlet`, `ZoneInlet`, `Sensor`, `Setpoint`, …), `stream`, `fluid`, `is_parent`,
and `provenance`: whether EnergyPlus reported the role (`eplus_examples`, `eplus_test_model`) or it was
written from the field's name (`hand_written`).

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
