# Quickstart: validating the model knowledge graph

These are runnable checks that prove each user story end to end. They exercise the interfaces in
[`contracts/`](contracts/) and the entities in [`data-model.md`](data-model.md). They are a validation guide, not
the test suite.

## Prerequisites

| Need | For |
|---|---|
| idfkit and idfkit-mcp checkouts on their feature branches, `uv sync` in each | everything |
| `uv sync --extra standards` in idfkit, Python 3.10–3.13 | User Story 5 |
| EnergyPlus 26.2 with `ENERGYPLUS_DIR` set | qualifying checks, User Stories 2, 3 and 6, building fixtures |
| An agent CLI configured as a runner (default: Claude Code) | User Story 2 |

Default test suites in both repositories need none of the starred items. They run against the committed
fixtures.

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
uv run python benchmarks/bench_standards.py       # needs the standards extra

# idfkit-mcp: per-call server time and response size through FastMCP
uv run pytest -m perf tests/test_perf_tools.py -v
```

Expect every budget in [contracts/idfkit-api.md](contracts/idfkit-api.md#performance-contract) and
[contracts/mcp-tools.md](contracts/mcp-tools.md#performance-budget) to be met, with the 2× CI allowance. Expect
topology build plus checks to stay at or under 25% of `load_idf` time on HospitalLowEnergy (SC-011).

## User Story 1: connection faults before simulating

```bash
cd idfkit
uv run pytest tests/test_hvac_topology.py -v              # unit + injected-typo tests, no EnergyPlus
ENERGYPLUS_DIR=/usr/local/EnergyPlus-26-2-0 \
  uv run pytest -m integration tests/test_hvac_corpus.py -v   # SC-001: zero error findings on 26.2 ExampleFiles
```

Through the server (MCP Inspector or any client):

1. `load_model` with `5ZoneAirCooled.idf`, then `check_model_integrity`. Expect no `hvac_topology` errors.
2. `update_object` to set `Coil:Cooling:Water "Main Cooling Coil 1"` `air_outlet_node_name` to `TYPO NODE`, then
   `check_model_integrity`. Expect `[T010]` naming the branch, coil, field, expected and actual node, plus a
   `T030` warning for `TYPO NODE`.
3. `trace_component("Coil:Cooling:Water", "Main Cooling Coil 1")`. Expect the same mismatch in `findings`.

## User Story 2: does it help agents?

```bash
cd idfkit-mcp
uv run python -m eval list-faults
uv run python -m eval run --faults all --repeat 2 \
  --baseline "uvx idfkit-mcp==0.11.1" --treatment "uv run idfkit-mcp" \
  --runner eval/runners/claude_code.toml --out eval/runs/$(date +%Y%m%d-%H%M)
uv run python -m eval compare eval/runs/<run>/
```

Expect `summary.md` with per-fault-type fix rate, tool calls, tokens and unwanted changes for both conditions, and
the SC-009 gate verdict. Without EnergyPlus, results-layer faults show as skipped, not failed.

## User Story 3: results tied to objects

1. `load_model` with `5ZoneAirCooled.idf`, then set one `AirTerminal:SingleDuct:VAV:Reheat` maximum reheat
   capacity far below the zone's need. Then `run_simulation`.
2. Read `idfkit://simulation/results`. Expect `qa_flags[*].affected_objects` to name the zone with unmet hours.
3. `get_object_results("AirTerminal:SingleDuct:VAV:Reheat", "<name>")`. Expect sizing facts with `where`, linked
   messages with `occurrences`, `results_state: "fresh"` and coverage.
4. `update_object` anything, then repeat step 3. Expect `results_state: "stale"`.

Offline equivalent, against the committed fixtures:
`uv run pytest tests/test_simulation_linking.py -v` (idfkit). This also asserts SC-004's 95% figure.

## User Story 4: understanding a system, renaming nodes

1. `get_hvac_topology(detail="chain")` on `5ZoneAirCooled.idf`. Expect one record per loop, about 200 tokens or
   fewer per loop, and terminals collapsed to `5×`.
2. `trace_node("SPACE3-1 In Node")`. Expect the producer terminal on the VAV air loop's demand side, and the
   reheat coil's hot water loop membership.
3. `rename_node("Mixed Air Node 1", "AHU-1 Mixed Air")`, then `check_model_integrity`. Expect the field count
   updated and no new topology findings. `get_change_log` should list `rename_node`.

## User Story 5: envelope screening

1. `load_model` with a model whose weather file is Chicago O'Hare (climate zone 5A), then
   `get_standards_context`. Expect `climate_zone: "5A"` with source `weather_station`, and `edition` missing.
2. `screen_envelope` before setting the edition. Expect an error naming `edition` and `building_category`.
3. `set_standards_context(edition="2019", building_category="Nonresidential")`, then `screen_envelope`. Expect:
   - the roof verdict cites "Table 5.5-5"
   - the limit is 0.032 Btu/h·ft²·°F, which is 0.18 W/m²·K
   - the value was computed with the roof film
   - every wall without asserted framing shows `cannot_tell` with a `resolve` hint
4. `assign_object_role("Construction", "<wall>", "assembly_class", "SteelFramed")`, then `screen_envelope` again.
   Expect a verdict whose assumptions say `assembly_class=SteelFramed (asserted)`.
5. Restart the server (stdio) and call `get_object_roles(unknown_only=False)`. The assertion survives (FR-037).

Hand-check sample (SC-006): `uv run pytest tests/test_standards_sample.py -v` (idfkit, needs the extra). It
compares 30 or more verdicts across all eight editions with hand-calculated values.

## User Story 6: symptom to cause

After step 1 of User Story 3, `diagnose_symptom("unmet_heating", object_type="Zone", name="<zone>")`. Expect the
undersized terminal in the top three, with its sizing fact as evidence and a `verify` call. Expect no weak-only
candidate at rank 1.

## User Story 7: building other applications on the graph

No MCP server is involved. In idfkit:

```bash
cd idfkit
# The documented standalone script (US7 independent test) runs and type-checks as written
uv run pytest tests/test_agent_references.py -v -k model-graph
uv run pyright agent_references/snippets/model-graph.py

# The public surface is declared and registered
make check            # includes check-parity-ledger and check-naming-register for hvac, standards, graph

# Node-link export: format checks with the standard library, then networkx loads it unchanged
uv run pytest tests/test_graph_view.py tests/test_graph_node_link.py -v
uv run --with "networkx>=3.6" pytest -m nodelink -v
```

Expect:
- `model-graph.py:standalone-script` loads the reference model, lists connection findings, traces a node and
  screens the envelope, using only names from the units' `__all__`
- `ModelGraph(doc).layers == ["model", "topology"]`, with `results` and `standards` in `unavailable` with reasons
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
   - `standards` in `unavailable` until a standards context is set
2. The same call with `max_nodes=5`. Expect `truncated: true`, a non-empty `frontier` and a response under 8 KB.
3. The same call with `hops=4`. Expect an error stating the 1–3 range.
