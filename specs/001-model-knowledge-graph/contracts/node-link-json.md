# Contract: node-link JSON export of the model graph

This is the file format written by `idfkit.graph.write_node_link` and `save_node_link` (spec FR-057, research
R-24). It is a public, versioned format. A change follows FR-053: removing or renaming a key, or changing the
meaning of a kind, needs a new `format_version` and a deprecation period. Adding an optional attribute, a node
kind, an edge kind or a layer does not: `format_version` stays `1`.

**Readers must ignore what they do not know.** A reader of format version 1 must skip node and edge kinds, layers
and attributes it does not recognise, rather than fail. That is what lets a later feature add, for example, a
`standards` layer with `verdict` kinds without a new version (spec FR-056).

The server never produces this format (FR-058).

## Top level

| Key | Type | Value |
|---|---|---|
| `directed` | `bool` | Always `true` |
| `multigraph` | `bool` | Always `true`. Edges are told apart by `key` |
| `graph` | object | Metadata, below |
| `nodes` | array | One object per graph node |
| `edges` | array | One object per graph edge. The key is `edges`, not `links` (research R-24) |

## `graph`

| Key | Type | Value |
|---|---|---|
| `format` | `str` | `"idfkit-model-graph"` |
| `format_version` | `int` | `1` |
| `idfkit_version` | `str` | `idfkit.__version__` |
| `energyplus_version` | `str` | The model's version, `X.Y.Z` |
| `layers` | `list[str]` | Layers included, today from `model`, `topology`, `results` |
| `unavailable` | `dict[str, str]` | Each layer asked for but absent, with the reason |
| `coverage` | object | The `Coverage` of the view: `partial`, and `uncovered` as a list of `{kind, count, examples, reason}` (research R-35) |
| `scope` | object | `start`, `hops`, `node_kinds`, `edge_kinds`, `categories` as given, `null` when unrestricted |
| `results_state` | `"fresh" \| "stale" \| null` | `null` when `results` is not included |

## Node object

Required keys: `id`, `kind`, `layer`, `label`. These are optional by kind:

| Kind | Further keys |
|---|---|
| `object` | `object_type`, `name` (model spelling), `category` (research R-36) |
| `node` | `name`, `fluid` |
| `result_fact` | `object_type`, `name` (owner), `metric`, `value`, `units`, `source`, `where`, `multiplier`, `stale` |
| `message` | `severity`, `message_kind`, `text`, `occurrences`, `first_seen`, `stale` |

`id` is unique within the file. It is formed from the kind and the upper-cased identity, so the same model gives the
same ids on every export.

## Edge object

Required keys: `source`, `target`, `key`, `kind`, `layer`. Both endpoints are node `id`s present in `nodes`. These
are optional by kind:

| Kind | Further keys |
|---|---|
| `reference` | `field` |
| `flow` | `field`, `connection_type`, `fluid`, `provenance` |
| `control` | `field`, `connection_type`, `provenance`; for EMS sensors and actuators, `rule: "ems_key"` and `confidence: "convention"` |
| `membership` | `side`, `branch`, `position`, `loop_kind` |
| `result_link` | `confidence`, `rule` |

## Compatibility guarantees, tested

- `json.loads` round-trips the file, and every value is a JSON scalar, array or object (default suite, standard
  library only).
- Every edge endpoint is a node `id`, and node `id`s are unique (default suite).
- `networkx.node_link_graph(data)` loads the file with no keyword arguments on networkx 3.6 or later, with the same
  numbers of nodes and edges (`nodelink` marker, run with `uv run --with "networkx>=3.6"`).
- On networkx 3.4 and 3.5, `node_link_graph(data, edges="edges")` loads it. This is documented, not tested.
