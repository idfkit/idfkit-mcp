# Results Tool

After `run_simulation`, EnergyPlus has reported many values about each object: sizing rows, tabular report
cells, recorded output variables and warnings. Each names its object in its own way, often upper-cased, sometimes
by a naming convention. `get_object_results` gathers them for one object or node, linked by idfkit's
`ResultIndex`, so you do not have to search the report tables for it.

| Tool | Use it for |
|---|---|
| `get_object_results` | Every result and message the last run reported for one object or node, with counts |

The same content is available as the resource `idfkit://simulation/objects/{object_type}/{name}`.

Results are linked only for a simulation this server ran in this session (`run_simulation`). Output produced
elsewhere is not linked. The run survives a server restart through the session file, but its results then read
`stale` unless the restored model is the one simulated (see [Freshness](#freshness)).

## `get_object_results`

Parameters:

| Parameter | Default | Notes |
|---|---|---|
| `object_type` | required | The object's type, or `"Node"` for a fluid node |
| `name` | required | Object or node name, matched case-insensitively |
| `limit` | `20` | 1–100. Most items returned in each list |

The response:

| Field | Content |
|---|---|
| `object` | The object or node, `{object_type, name}`, in the model's spelling |
| `facts` | `{items, total, omitted}`: the values reported for it, sizing first, then tabular cells in table order |
| `messages` | `{items, total, omitted}`: the warnings and errors naming it, one per kind, most severe first |
| `available_variables` | `{items, total, omitted}`: the output variables recorded for it, by name. Fetch values with `query_timeseries` |
| `neighbours` | `{items, total, omitted}`: objects and nodes one hop away, over HVAC connections or references, each with its first fact |
| `coverage` | What the run's linking could not resolve, for the whole run (below) |
| `results_state` | `fresh`, or `stale` when the model changed after the run |

Each list keeps at most `limit` items; `total` counts them all and `omitted` is `total` minus those returned.
A response stays within 8 KB: when the lists at `limit` would serialise to more, every list is cut to the
largest common length that fits, and `omitted` says how many each lost.

Each fact:

| Field | Content |
|---|---|
| `source` | `sizing` (`ComponentSizes`), `tabular` (a tabular report cell) or `timeseries_stat` |
| `metric` | Snake-case name with units, such as `design_size_rated_capacity_w` |
| `value` | A number when the cell holds one, otherwise its text |
| `units` | The units EnergyPlus gave, or `null` |
| `where` | Where it was read: `Report/Table/Row/Column`, or `ComponentSizes#<row>` |
| `multiplier` | For a zone: the zone multiplier times its zone-list multiplier. `null` for other objects |

**Zone values are per instance.** EnergyPlus reports zone rows without the multiplier. Multiply by
`multiplier` before adding zone values into a building total.

Each message:

| Field | Content |
|---|---|
| `severity` | `warning`, `severe` or `fatal` |
| `kind` | The message catalogue id, such as `dxcoil.low_outlet_temp`, or `other` |
| `text` | The first line of the message; the rest is in the run's ERR file |
| `objects` | Each object it names: `{key, rule, confidence, via}`. `key` is `null` when no object matched |
| `occurrences` | How many times EnergyPlus reported messages of this kind for the object, summed |
| `first_seen` | `"<environment> MM/DD HH:MM"` when EnergyPlus reported when it first occurred |

`confidence` is `exact` (type and name), `typed` (name, with the type taken from the context), `convention` (a
naming convention, such as a zone's implicit space) or `weak` (a substring match).

## Coverage

`coverage` has the shape every graph answer uses. Here `resolved` and `unresolved` count result items of the
whole run: sizing rows, output keys, tabular rows and named objects in messages. Items that no rule links are
never dropped. They are counted in an `uncovered` entry of kind `unlinked_result`, with up to three raw keys as
examples (`{"object_type": "Unresolved", "name": "<raw key>"}`). An `hvac_template` entry says the model has
`HVACTemplate:*` objects, whose expanded objects link only by naming convention, if at all.

## Freshness

`results_state` is `stale` once the model has changed since the run (FR-026). A stale answer is still given:
the values describe the model as it was simulated, not as it is.

`run_simulation` records three things about each run: the document revision it simulated, the SHA-256 of the
IDF text it wrote for EnergyPlus (`simulation_model_hash`) and the run directory. A later edit changes the
revision, so the results read stale. When the session's document is replaced, by `migrate_model` or by a
restart that restores the model from its file, the revision says nothing, and the results read fresh only if
the model's text hashes the same as the text that was simulated.

`load_model`, `new_model` and `convert_osm_to_idf` forget the run.

## Example: an air loop with a sizing warning

`get_object_results(object_type="AirLoopHVAC", name="vav sys 1", limit=2)` after a run of `5ZoneAirCooled`
(`coverage` and `neighbours` items shortened):

```json
{
  "object": {"object_type": "AirLoopHVAC", "name": "VAV Sys 1"},
  "facts": {
    "items": [
      {"source": "sizing", "metric": "sum_of_air_terminal_maximum_heating_flow_rates_m3_s",
       "value": 0.31508568153742983, "units": "m3/s", "where": "ComponentSizes#66", "multiplier": null},
      {"source": "sizing", "metric": "sum_of_air_terminal_minimum_heating_flow_rates_m3_s",
       "value": 0.31508568153742983, "units": "m3/s", "where": "ComponentSizes#67", "multiplier": null}
    ],
    "total": 104,
    "omitted": 102
  },
  "messages": {
    "items": [
      {"severity": "warning", "kind": "sizing.system_flow_ratio",
       "text": "FinalSystemSizing: AirLoop=\"VAV SYS 1\", Sizing:System Central Heating Maximum System Air Flow Ratio = 0.300000,",
       "objects": [{"key": {"object_type": "AirLoopHVAC", "name": "VAV Sys 1"}, "rule": "typed",
                    "confidence": "typed", "via": []}],
       "occurrences": 1, "first_seen": null}
    ],
    "total": 1,
    "omitted": 0
  },
  "available_variables": {"items": [], "total": 0, "omitted": 0},
  "neighbours": {"items": [ … ], "total": 20, "omitted": 18},
  "coverage": {"partial": false, "uncovered": [], "resolved": 678, "unresolved": 0},
  "results_state": "fresh"
}
```

## Errors

Errors name the cause and never pick for you:

- no simulation run in this session: `No simulation run in this session; run `run_simulation` first.`;
- a run with no SQLite output (`run_simulation` always adds `Output:SQLite`);
- no model loaded;
- an object that is not in the model, with the closest names:
  `No AirLoopHVAC named 'VAV Sys 2'. Closest: 'VAV Sys 1'. Use search_objects to find it.`;
- a node no object uses, with the closest node names;
- `limit` out of range: `limit must be between 1 and 100, got 0.`

An object the run reported nothing about is not an error: its lists are empty.

The tool's output schema lists the top-level fields only, to keep the tool listing small; the tables above give
the full shape.

## Nearest neighbour

| Tool | Nearest neighbour | Use this one when |
|---|---|---|
| `get_object_results` | `get_object_neighbourhood` | you need every result and message for one object, with counts |

`get_object_neighbourhood` walks the model around an object across layers, and after a run its results
layer returns the same facts and messages as graph nodes. Use this tool for one object's results in full:
messages deduplicated by kind with counts, the output variables recorded for it, and coverage.

## Results in the other simulation answers

The same linking adds fields to two existing answers, documented in [Simulation Tools](simulation.md):
`affected_objects` and `kind` in `idfkit://simulation/results`, and the zone `object` and `flag_details` in
`analyze_peak_loads`.
