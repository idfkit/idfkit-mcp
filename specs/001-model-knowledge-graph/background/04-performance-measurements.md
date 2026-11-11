# Performance measurements

Measured on 2026-11-11 during planning, after the user stated that performance is critical. The scripts are kept
in [`benchmarks/`](benchmarks/), stored as `.txt` so the repository linters skip them.

**Machine:** cloud container, 4 vCPU x86-64, Python 3.12.3. idfkit at `main` (1.2.0), idfkit-mcp at `main`
(0.11.1).

**Inputs:**
- The EnergyPlus 24.1 ExampleFiles, using the 15 largest files that contain `Branch`.
- Two public paired runs from OpenStudio-resources (`test_example_model`, `sm_hotel`).
- PNNL `building-energy-standards-data` 0.3.3.

All timings are best of 5 unless stated otherwise. These are planning measurements of *prototype* code. The real
implementation adds rule tables and checks, so the budgets in research R-21 keep about 10× headroom over these
figures.

## 1. Building the node graph

[`bench_topology.py.txt`](benchmarks/bench_topology.py.txt) compares two ways of extracting every node use and
deriving producer-to-consumer flow edges.

- **Naive:** every field of every object, tested against the node-field pattern, with each use stored as a frozen
  slotted dataclass in a `dict[str, list]`.
- **Planned:**
  - Per-type node-field plans are computed once from the schema.
  - Only collections whose type has node fields are visited.
  - Node names are interned to integers.
  - Each use is stored as an `(object index, role code)` tuple.
  - Adjacency is held as forward and reverse `list[list[int]]`.

| Model | Objects | Node-bearing objects | Nodes | Load IDF | Naive build | Planned build | Speedup | 3-hop query |
|---|---|---|---|---|---|---|---|---|
| HospitalLowEnergy | 6,876 | 2,428 | 2,869 | 228 ms | 24.2 ms | **5.2 ms** | 4.7× | 1.5 µs |
| HospitalBaselineReheatReportEMS | 6,713 | 1,509 | 1,569 | 174 ms | 15.1 ms | 3.0 ms | 5.0× | 1.4 µs |
| ASHRAE901_ApartmentHighRise_STD2019 | 5,013 | 2,040 | 2,183 | 105 ms | 15.7 ms | 3.8 ms | 4.2× | 1.3 µs |
| ASHRAE901_OutPatientHealthCare_STD2019 | 3,836 | 844 | 956 | 75 ms | 9.0 ms | 1.8 ms | 5.1× | 1.0 µs |
| CmplxGlz_Daylighting (small HVAC) | 191 | 22 | 16 | 76 ms | 10.7 ms | 0.4 ms | 29.7× | 1.4 µs |

The median speedup over all 15 models is **4.6×**. Peak memory of the planned build is 1.5 MB on the largest
model.

**Findings:**
1. **The graph costs a few percent of loading the model.** The planned build takes 5.2 ms on the largest example,
   against 228 ms to parse it. Rebuilding after an edit is therefore cheap, and incremental maintenance is not
   worth its complexity at this scale (R-21, decision 4).
2. **Skipping objects with no node fields matters most.** About 65% of objects in large models have none, such as
   surfaces, schedules and materials. The naive variant pays for every field of every one of them. Even
   on a 191-object model, the naive scan costs 10 ms, against 0.4 ms for the planned build.
3. **Computing the plans is cheap**: 0.3–0.6 ms per model. A per-schema-version cache makes it free after the
   first model.
4. **Traversal is negligible.** About 1.5 µs per bounded 3-hop BFS over integer adjacency.

## 2. Record construction cost

100,000 records with five fields, built from varying values (not constants, which Python folds at compile time):

| Record type | Time per 100k | Relative |
|---|---|---|
| plain `tuple` | 5.0 ms | 1× |
| mutable `@dataclass(slots=True)` | 15.0 ms | 3× |
| `NamedTuple` | 19.1 ms | 3.8× |
| `@dataclass(frozen=True, slots=True)` | 47.4 ms | **9.5×** |

**Finding:** frozen dataclasses must not be built in inner loops. Internal records are tuples. Public dataclasses
are built only for the bounded set of items an API call returns (R-21, decision 2).

## 3. Results index

[`bench_linking.py.txt`](benchmarks/bench_linking.py.txt) runs the resolution steps that matter for cost:
- `ComponentSizes` (typed)
- distinct `ReportDataDictionary` keys
- distinct tabular row labels through the `Strings` join
- the `Errors` table

It builds an upper-case name index from idfkit's collections, connects with stdlib `sqlite3` in read-only mode, and
never reads `ReportData`.

| Run | SQL size | Timeseries values | Tabular cells | Load IDF | **Index build** | Sizing rows resolved |
|---|---|---|---|---|---|---|
| test_example_model | 32.5 MB | 653,274 | 5,920 | 239 ms | **1.8 ms** | 79 / 79 |
| sm_hotel | 4.6 MB | 167,671 | 0 | 79 ms | **3.1 ms** | 545 / 545 |

**Finding:** index cost does not depend on the timeseries volume, as long as the index never touches `ReportData`.
Summary statistics over timeseries (FR-024 "available variables" lists only keys) must use SQL aggregation on
request, never Python loops over rows (R-21, decision 8).

## 4. Standards data

| Step | Time |
|---|---|
| Locate the package with `importlib.util.find_spec` (no import) | 0.05 ms |
| `json.load` of `envelope_requirements_90_1.json` (11.3 MB, 6,315 rows) | **43 ms** |
| Build a dict index keyed `(edition, climate zone set, surface type, building category)` | 3.9 ms |
| One indexed lookup | 0.085 µs |
| All 139 tables together | 61.6 MB on disk |

**Finding:** loading tables one at a time, lazily, is mandatory. Loading everything would cost about 250 ms and
tens of MB per process for tables this feature never reads. The envelope table is loaded once per process, projected
to compact tuples, and shared read-only by every session (R-21, decision 9).

## 5. MCP call overhead and response size

[`bench_mcp.py.txt`](benchmarks/bench_mcp.py.txt) calls existing tools through the in-process FastMCP server on
HospitalLowEnergy.

| Call | Server time | Response size |
|---|---|---|
| `load_model` | 384 ms | — |
| `list_objects(Branch, limit=20)` | 0.7 ms | 1.4 KB |
| `check_model_integrity` | 1.8 ms | 1.7 KB |
| `get_zone_properties` (all zones) | **87 ms** | **110 KB (about 27k tokens)** |

**Finding:** framework overhead is about 1 ms. The dominant costs an agent sees are **response size**, which costs
tokens, context and latency, and per-item work that grows with the size of the response. Bounded responses
(R-12) are as much a performance requirement as fast algorithms. Every new tool's default response must stay
under 8 KB (R-21, decision 10).

## Not measured, still to do

- The full topology build with the curated rule table, memberships and checks. It is budgeted at 50 ms on
  HospitalLowEnergy and must be benchmarked in slice 1 before the budget is confirmed.
- Timeseries summary statistics on large SQL files (aggregation queries over `ReportData`, which has no index by
  key in EnergyPlus output). Measure them in slice 3.
- Behaviour under concurrent HTTP sessions in the hosted deployment.
- Python 3.10, the slowest supported interpreter. Budgets are stated for 3.12 and checked on 3.10 in CI.
