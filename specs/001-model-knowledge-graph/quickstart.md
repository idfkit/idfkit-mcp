# Quickstart: validating the model knowledge graph

These are runnable checks that prove each user story end to end. They exercise the interfaces in
[`contracts/`](contracts/) and the entities in [`data-model.md`](data-model.md). They are a validation guide, not
the test suite.

## Prerequisites

| Need | For |
|---|---|
| idfkit and idfkit-mcp checkouts on their feature branches, `uv sync` in each | everything |
| EnergyPlus 26.2 with `ENERGYPLUS_DIR` set | qualifying checks, User Stories 2, 3 and 6, building fixtures |
| EnergyPlus 9.6.0 and 23.2.0 ExampleFiles | measuring false findings on earlier versions (FR-013a) |
| An agent CLI configured as a runner (default: Claude Code) | User Story 2 |

Default test suites in both repositories need none of these. They run against the committed fixtures and add no
third-party dependency.

```bash
# idfkit
make check && make test
# idfkit-mcp
make check && make test
```

## Performance budgets (all stories)

```bash
# idfkit: the R-21 budgets on the vendored reference model; no EnergyPlus needed
uv run pytest -m perf tests/test_perf_budgets.py -v
uv run python benchmarks/bench_hvac_topology.py   # prints the before/after table for the PR
uv run python benchmarks/bench_result_index.py
uv run python benchmarks/bench_graph.py

# idfkit-mcp: per-call server time and response size through FastMCP
uv run pytest -m perf tests/test_perf_tools.py -v
```

Expect every budget in [contracts/idfkit-api.md](contracts/idfkit-api.md#performance-contract) and
[contracts/mcp-tools.md](contracts/mcp-tools.md#performance-budget) to be met, with the 2× CI allowance. Expect
topology build plus checks to stay at or under 25% of `load_idf` time on HospitalLowEnergy (SC-011).

## Tool-listing budget (all slices)

```bash
cd idfkit-mcp
uv run python scripts/token_audit.py   # listing tokens, schemas included
```

Expect the listing to grow by no more than 15% over the base of 39 tools and about 15,300 tokens measured at
`81d3cd6`, that is about 2,300 tokens for all new tools together (SC-010, research R-12 and R-31). Each slice's pull
request states the figure before and after.

## User Story 1: connection faults before simulating

```bash
cd idfkit
uv run pytest tests/test_hvac_topology.py -v              # unit + injected-typo tests, no EnergyPlus
ENERGYPLUS_DIR=/usr/local/EnergyPlus-26-2-0 \
  uv run pytest -m integration tests/test_hvac_corpus.py -v   # SC-001: zero error findings on 26.2 ExampleFiles

# FR-013a, SC-001a: measure false findings on earlier versions (research R-34)
uv run pytest -m integration tests/test_hvac_corpus.py -v \
  --corpus 9.6.0=/path/to/EnergyPlus-9-6-0/ExampleFiles \
  --corpus 23.2.0=/path/to/EnergyPlus-23-2-0/ExampleFiles
```

Expect the earlier-version run to print false findings per version and check, and to report zero error-severity
findings once the caps in `idfkit/hvac/_version_caps.py` are applied. A regenerated caps table shows in
`git diff`.

Through the server (MCP Inspector or any client):

1. `load_model` with `5ZoneAirCooled.idf`, then `check_model_integrity`. Expect no `hvac_topology` errors.
2. `update_object` to set `Coil:Cooling:Water "Main Cooling Coil 1"` `air_outlet_node_name` to `TYPO NODE`, then
   `check_model_integrity`. Expect `[T010]` naming the branch, coil, field, expected and actual node, plus a
   `T030` warning for `TYPO NODE`.
3. `trace_hvac("Coil:Cooling:Water", "Main Cooling Coil 1")`. Expect the same mismatch in `findings`.
4. Load a model with an `EnergyManagementSystem:Program`. Expect `coverage.partial: true` and an `uncovered` entry
   of kind `ems_program` (FR-004a).

## User Story 2: does it help agents?

```bash
cd idfkit-mcp
uv run python -m eval list-faults --check-held-out   # held-out faults predate the checks (R-33)
uv run python -m eval run --faults all --repeat 3 \
  --baseline-config eval/baseline.toml --treatment "uv run idfkit-mcp" \
  --runner eval/runners/claude_code.toml --out eval/runs/$(date +%Y%m%d-%H%M)
uv run python -m eval compare eval/runs/<run>/
```

Expect:
- every task kind present: fault, control, authoring and question (FR-040b)
- the prompt lint passing, so no prompt names the injected object, field or fault (FR-042b)
- `summary.md` with the paired difference per task and its 95% bootstrap interval, overall, per layer and per
  fault type, and per-type rows whose interval includes zero marked descriptive (FR-042a)
- a separate held-out table, and the SC-009 verdict listing each clause: effect size, interval excludes zero,
  direction on held-out types, unwanted changes, false fixes on controls
- the SC-008 spread across the three repeat passes, and SC-010a tool-use shares per new tool
- `baseline_kind: "pre_feature"`. A run against a release is labelled `other` and its gate verdict is not valid
- without EnergyPlus, results-layer faults shown as skipped, not failed

## User Story 3: results tied to objects

1. `load_model` with `5ZoneAirCooled.idf`, then set one `AirTerminal:SingleDuct:VAV:Reheat` maximum reheat
   capacity far below the zone's need. Then `run_simulation`.
2. Read `idfkit://simulation/results`. Expect `qa_flags[*].affected_objects` to name the zone with unmet hours.
3. `get_object_results("AirTerminal:SingleDuct:VAV:Reheat", "<name>")`. Expect sizing facts with `where`, linked
   messages with `occurrences`, `results_state: "fresh"` and coverage in the shared shape.
4. `update_object` anything, then repeat step 3. Expect `results_state: "stale"`.

Offline equivalent, against the committed fixtures:
`uv run pytest tests/test_simulation_linking.py -v` (idfkit). This also asserts SC-004's 95% figure.

## User Story 4: understanding a system, renaming nodes

1. `get_hvac_topology(detail="chain")` on `5ZoneAirCooled.idf`. Expect one record per loop, about 200 tokens or
   fewer per loop, and terminals collapsed to `5×`.
2. `trace_hvac("Node", "SPACE3-1 In Node")`. Expect the producer terminal on the VAV air loop's demand side, and the
   reheat coil's hot water loop membership.
3. `trace_hvac("Node", "SPACE3-1 In Node", hops=4, categories=["heating_coil"])`. Expect only heating coils in the
   upstream walk, each with its `category` (FR-016a).
4. `rename_node("Mixed Air Node 1", "AHU-1 Mixed Air")`, then `check_model_integrity`. Expect the field count
   updated and no new topology findings. `get_change_log` should list `rename_node`.

## User Story 5: screening against a standard

Deferred to a future spec. See [deferred-standards.md](deferred-standards.md).

## User Story 6: symptom to cause

After step 1 of User Story 3, `diagnose_symptom("unmet_heating", object_type="Zone", name="<zone>")`. Expect:
- the undersized terminal in the top three, with its sizing fact as `strong` evidence and a `verify` call
- no weak-only candidate at rank 1
- `families_covered` listing the rule families examined for unmet heating

Then set the terminal back to autosize, add an EMS actuator that overrides the zone's heating setpoint, simulate,
and diagnose again. Expect `no_strong_candidate: true`, with its statement first, and no family that covers EMS.

SC-009a is read from the evaluation's `summary.md` (User Story 2): the rate of edits to a wrong top-ranked candidate
is no higher than the baseline's rate of wrong first edits.

## User Story 7: building other applications on the graph

No MCP server is involved. In idfkit:

```bash
cd idfkit
# The documented standalone script (US7 independent test) runs and type-checks as written
uv run pytest tests/test_agent_references.py -v -k model-graph
uv run pyright agent_references/snippets/model-graph.py

# The public surface is declared and registered
make check            # includes check-parity-ledger and check-naming-register for hvac and graph

# Node-link export: format checks with the standard library, then networkx loads it unchanged
uv run pytest tests/test_graph_view.py tests/test_graph_node_link.py -v
uv run --with "networkx>=3.6" pytest -m nodelink -v
```

Expect:
- `model-graph.py:standalone-script` loads the reference model, lists connection findings, traces a node and
  walks one component's neighbourhood, using only names from the units' `__all__`
- `ModelGraph(doc).layers == ["model", "topology"]`, with `results` in `unavailable` with its reason
- the export's `graph.format_version == 1`, every edge endpoint present in `nodes`, and networkx reporting the
  same node and edge counts

From the consumer side, in idfkit-mcp:

```bash
cd idfkit-mcp
uv run pytest tests/test_public_api_only.py -v   # no private idfkit imports or attributes (FR-050)
```

Through the server, after step 1 of User Story 3:

1. `get_object_neighbourhood("AirTerminal:SingleDuct:VAV:Reheat", "<name>", hops=2)`. Expect:
   - its zone and its reheat coil as `object` nodes, the coil linked by `flow` edges through `node` nodes
   - the coil's `membership` edge to the hot-water loop
   - the terminal's `result_fact` nodes, with `results_state: "fresh"`
   - `layers` of `model`, `topology` and `results`, and no `unavailable` entry
2. The same call with `categories=["heating_coil"]`. Expect only the start and heating-coil object nodes.
3. The same call with `max_nodes=5`. Expect `truncated: true`, a non-empty `frontier` and a response under 8 KB.
4. The same call with `hops=4`. Expect an error stating the 1–3 range.
