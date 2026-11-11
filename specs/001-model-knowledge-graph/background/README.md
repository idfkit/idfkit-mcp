# Background research for 001-model-knowledge-graph

This folder holds the evidence the specification rests on. The spec ([`../spec.md`](../spec.md)) says *what*
agents and users need and *why*. These documents record what was found, measured, prototyped and proposed. They
include design sketches (class names, tool names, phase estimates) that are deliberately **not** in the spec, so
that `/speckit-plan` can take them as input rather than as decisions already made.

| File | Contents |
|---|---|
| [`00-literature-scan.md`](00-literature-scan.md) | Published work on knowledge graphs, LLMs and MCP in EnergyPlus modelling, and the gap this feature fills. |
| [`01-hvac-topology.md`](01-hvac-topology.md) | Layer 1: a typed HVAC topology graph. Current state, schema feasibility measured over all bundled versions, a prototype swept over 575 EnergyPlus example models, proposed checks, MCP surface, prior art and phases. |
| [`02-standards-and-ontologies.md`](02-standards-and-ontologies.md) | Layer 3: links to standards knowledge and ontologies. What the agent supplies from memory today, the Brick, 223P, Haystack, ASHRAE 229 and PNNL BESD landscape with licences, ranked options and phases. |
| [`03-results-on-graph.md`](03-results-on-graph.md) | Layer 2: simulation results attached to model objects. Name-mapping rates measured on real paired runs, failure categories over 735 example models, data model, MCP scenarios and phases. |
| [`prototype/hvac_topology_proto.py.txt`](prototype/hvac_topology_proto.py.txt) | The throwaway topology prototype behind report 01. It is stored as `.txt` so repository linters skip it. |

Reports 01 to 03 were produced by three research agents working in parallel on 2026-11-10 against `idfkit` and
`idfkit-mcp` at that day's `main`. Neither repository was modified during the research. File and line references
in the reports point at that snapshot and will drift.

## How the three layers fit together

```
           standards knowledge (layer 3)   "what should this value be?"
                    │  object roles: roof or wall, conditioned or not, space type
   ┌────────────────┴──────────────────┐
   │  model graph                      │
   │  object references (exists today) │
   │  + nodes and air/water flow (L1)  │   "what is connected to what?"
   └────────────────┬──────────────────┘
                    │  results keyed by (object type, name) and by node
           simulation results (layer 2)    "what went wrong, and where?"
```

- **Layer 1 is the structural prerequisite.** It makes nodes part of the graph. Layer 2 needs nodes for node
  outputs (requested by 38% of example models) and for following flow upstream to a cause.
- **Layer 3 is independent of the other two.** It mostly reuses calculations idfkit already performs, and it
  replaces guidance that agents currently carry in prompts and that is demonstrably wrong.
- **Layer 2 works without layer 1** at the zone and component level. Diagnosis becomes strong only once flow
  edges exist.
- **All three reports reach the same open question:** no study shows that any of this improves an agent's
  diagnosis. All three recommend the same fault-injection evaluation, which this spec makes a first-class story.

## Findings checked independently

The coordinating session re-checked these claims against the repositories rather than relying on the reports:

| Claim | Check | Result |
|---|---|---|
| The 26.2 schema is the first to tag node fields | Counted `"data_type": "node"` in the bundled schemas | 819 in V26-2-0, 0 in V24-1-0 and older |
| idfkit's agent docs wrongly promise node typos surface as `E004` | `agent_references/templates/hvac-loops.md` lines 27, 65, 124 | Confirmed |
| The idfkit plugin gives roof U-value targets in IP units labelled as SI | `agents/envelope-analyst.md:27` in the installed plugin | Confirmed: "0.027-0.063 W/m2·K" |
| PNNL `building-energy-standards-data` 0.3.3 exists and is installable | Downloaded the wheel | Confirmed |
| idfkit's SQL reader ignores the `ComponentSizes` and `Errors` tables | Searched `simulation/parsers/sql.py` | Confirmed: neither table is read |
| idfkit-mcp's only result-to-model join is a zone-name lookup | Read `tools/peak_loads.py` | Confirmed |

## Corrections that do not wait for this feature

Two of the defects above mislead agents today and are cheap to fix. They belong in other repositories and are
tracked outside this spec:

1. **idfkit:** `agent_references/templates/hvac-loops.md` and two snippets (`trace-referencing`,
   `mistake-walk-good`) claim node-name typos surface as `E004` validation errors. They do not.
2. **idfkit-plugin:** `agents/envelope-analyst.md:27` gives roof U-factor targets of 0.027–0.063 labelled W/m²·K.
   Those are Btu/h·ft²·°F values, so the targets are about 5.7 times too strict. The SI range is roughly
   0.15–0.36 W/m²·K.

## What was not possible during the research

- EnergyPlus could not be run in the research sandbox. No branch-node details file (`eplusout.bnd`) cross-check
  was done, and no new paired input/output runs were generated. The results-linking rates come from public
  paired runs (OpenStudio-resources test outputs, honeybee-energy test results).
- Some sites were unreachable (bigladdersoftware.com, nist.gov, open223.info). Statements about OpenStudio,
  eppy, Honeybee and parts of the LLM literature come from memory and are marked as such in the reports.
- No measurement of agent performance was made. Every claim that an agent would do better is a hypothesis,
  which is why the spec includes the evaluation.
