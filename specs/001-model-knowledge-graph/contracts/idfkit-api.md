# Contract: idfkit public API added by this feature

This is the upstream surface idfkit-mcp calls (Constitution Principle I). Signatures are normative; bodies are not.
Every name here is typed for pyright strict and uses the standard library only, except `idfkit.standards` data
access, which reads PNNL's JSON files.

New capability units (`idfkit.hvac`, `idfkit.standards`) need parity-ledger and naming-register rows in
idfkit-conformance, landed as a pair with the code (research R-02).

## `idfkit.IDFDocument` (existing class)

```python
@property
def revision(self) -> int: ...
    # Monotonic; bumped by add, removeidfobject, field assignment, rename, rename_node.

def rename_node(self, old: str, new: str) -> NodeRenameResult: ...
    # Raises KeyError if `old` is unused; ValueError if `new` is empty, equal to `old`, or already a node.
```

## `idfkit.hvac` (new unit)

```python
class ConnectionType(str, Enum): ...
class Fluid(str, Enum): ...

@dataclass(frozen=True, slots=True)
class NodeUse: ...
@dataclass(frozen=True, slots=True)
class LoopMembership: ...
@dataclass(frozen=True, slots=True)
class FlowEdge: ...
@dataclass(frozen=True, slots=True)
class TopologyFinding: ...
@dataclass(frozen=True, slots=True)
class NodeRenameResult: ...

class HVACTopology:
    @classmethod
    def from_document(cls, doc: IDFDocument) -> HVACTopology: ...   # cached per (doc, doc.revision)
    def nodes(self) -> list[str]: ...
    def uses(self, node: str) -> list[NodeUse]: ...
    def producers(self, node: str) -> list[IDFObject]: ...
    def consumers(self, node: str) -> list[IDFObject]: ...
    def controls(self, node: str) -> list[NodeUse]: ...
    def ports(self, obj: IDFObject) -> list[NodeUse]: ...
    def memberships(self, obj: IDFObject) -> list[LoopMembership]: ...
    def upstream(self, start: IDFObject | str, *, hops: int = 2) -> list[FlowEdge]: ...
    def downstream(self, start: IDFObject | str, *, hops: int = 2) -> list[FlowEdge]: ...
    def loops(self) -> list[IDFObject]: ...
    def chain(self, loop: IDFObject, side: Literal["supply", "demand"]) -> list[list[IDFObject]]: ...
    def zones_served(self, air_loop: IDFObject) -> list[IDFObject]: ...
    def check(self) -> list[TopologyFinding]: ...
    @property
    def coverage(self) -> Coverage: ...

def check_topology(doc: IDFDocument) -> list[TopologyFinding]: ...   # convenience wrapper
```

## `idfkit.simulation` (existing unit)

```python
# parsers/sql.py: SQLResult gains
def component_sizes(self) -> list[ComponentSize]: ...        # ComponentSizes table
def errors(self) -> list[SQLErrorRow]: ...                   # Errors table (severity, message, count)
def zones(self) -> list[ZoneRow]: ...                        # Zones table incl. multipliers
def report_keys(self) -> list[VariableInfo]: ...             # ReportDataDictionary keys

# linking.py (new module)
@dataclass(frozen=True, slots=True)
class ObjectKey: ...
@dataclass(frozen=True, slots=True)
class Resolution: ...
@dataclass(frozen=True, slots=True)
class ResultFact: ...
@dataclass(frozen=True, slots=True)
class LinkedMessage: ...
@dataclass(frozen=True, slots=True)
class CandidateCause: ...

class ResultIndex:
    @classmethod
    def build(cls, doc: IDFDocument, result: SimulationResult, *,
              run_revision: int, run_model_hash: str) -> ResultIndex: ...
    def for_object(self, key: ObjectKey) -> ObjectResults: ...
    def objects_with(self, metric: str, *, top: int = 10) -> list[tuple[ObjectKey, ResultFact]]: ...
    def is_fresh(self, doc: IDFDocument, model_hash: str | None = None) -> bool: ...
    @property
    def coverage(self) -> Coverage: ...

def diagnose(index: ResultIndex, doc: IDFDocument, symptom: str,
             target: ObjectKey | None = None, *, limit: int = 5) -> Diagnosis: ...

# parsers/err_catalog.py (new module)
MESSAGE_KINDS: tuple[MessageKind, ...]
def classify_message(text: str) -> tuple[MessageKind | None, list[tuple[str | None, str]]]: ...
```

## `idfkit.thermal` (existing unit)

```python
SurfaceClass = Literal["wall", "roof", "floor"]

def calculate_r_value(construction: IDFObject, include_films: bool = True,
                      *, surface_class: SurfaceClass = "wall") -> float: ...
def calculate_u_value(construction: IDFObject, include_films: bool = True,
                      *, surface_class: SurfaceClass = "wall") -> float: ...
def heat_capacity_per_area(construction: IDFObject) -> float: ...   # J/m²·K
```

Defaults preserve today's results exactly.

## `idfkit.standards` (new unit; data needs extra `idfkit[standards]`)

```python
class StandardsUnavailableError(IdfKitError): ...   # names the extra and the Python constraint

def data_version() -> str: ...                       # raises StandardsUnavailableError
def editions() -> list[str]: ...                     # e.g. ["2004", ..., "2025"]

@dataclass(frozen=True, slots=True)
class Requirement: ...
@dataclass(frozen=True, slots=True)
class ObjectRole: ...
@dataclass(frozen=True, slots=True)
class ScreeningVerdict: ...
@dataclass(frozen=True, slots=True)
class ScreeningReport: ...

def lookup_envelope(*, edition: str, climate_zone: str, surface_class: str,
                    building_category: str, assembly_class: str | None = None) -> list[Requirement]: ...

def compute_roles(doc: IDFDocument) -> list[ObjectRole]: ...         # computed + unconfirmed only
def screen_envelope(doc: IDFDocument, *, edition: str, climate_zone: str, building_category: str,
                    asserted: Mapping[tuple[str, str, str], str] | None = None) -> ScreeningReport: ...
    # `asserted` maps (object_type, NAME_UPPER, role) -> value; supplied by the caller (session state).
```

`compute_roles` and every model-side computation work without the extra. Only `lookup_envelope`,
`screen_envelope`, `editions` and `data_version` need it.

## Performance contract

These are part of the API's guarantees (spec FR-009, research R-21). They are checked by the `perf` benchmark gate
on the reference model (HospitalLowEnergy), with a 2× CI allowance.

| Call | Budget |
|---|---|
| First `HVACTopology.from_document(doc)` after load or an edit, including `check()` | ≤ 50 ms, and ≤ 25% of `load_idf` time |
| Repeated `from_document(doc)` with no edit in between | Returns the cached view (≤ 0.1 ms) |
| Any single `HVACTopology` query (`uses`, `trace`, `upstream`, `downstream`, `memberships`, `chain`) | ≤ 5 ms |
| `ResultIndex.build` | ≤ 50 ms, independent of timeseries volume. Never reads `ReportData` |
| `ResultIndex.for_object`, `diagnose` | ≤ 10 ms |
| First `lookup_envelope` / `screen_envelope` in a process | ≤ 150 ms |
| Later `screen_envelope` on a loaded model | ≤ 20 ms |

Implementation obligations that keep these budgets:
- Per-type plans are computed once per schema version.
- Only node-bearing collections are visited.
- Internal records are tuples, and dataclasses are built only for returned items.
- Derived views are cached in `IDFDocument._derived` and stamped with the revision.
- Standards tables are loaded lazily, projected and shared process-wide.

## Codegen and gates (idfkit)

- `python -m idfkit.codegen.generate_node_fields` writes `src/idfkit/hvac/_node_fields.py`. `make check` gains
  `check-node-fields`, which regenerates the file and diffs it.
- `agent_references/templates/hvac-topology.md` and `snippets/hvac-topology.py` are new. `result-parsing` and
  `thermal` are updated, and `standards.md` and its snippet are new. All of them are re-baked.
- Every new public name is added to the CHANGELOG under `[Unreleased]`.
