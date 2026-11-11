# Contract: idfkit public API added by this feature

This is the upstream surface idfkit-mcp calls (Constitution Principle I). Signatures are normative; bodies are not.
Every name here is typed for pyright strict and uses the standard library only, except `idfkit.standards` data
access, which reads PNNL's JSON files.

New capability units (`idfkit.hvac`, `idfkit.standards`, `idfkit.graph`) need parity-ledger and naming-register rows in
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

Three topics: envelope, lighting (90.1, space-by-space method) and ventilation (62.1). See research R-26 to R-29.

```python
class StandardsUnavailableError(IdfKitError): ...   # names the extra and the Python constraint

Topic = Literal["envelope", "lighting", "ventilation"]
RoleName = Literal["surface_class", "conditioned_status", "assembly_class",
                   "space_type", "lighting_space_type", "ventilation_space_type"]

def data_version() -> str: ...                       # raises StandardsUnavailableError
def editions(topic: Topic = "envelope") -> list[str]: ...
    # 90.1 editions for envelope and lighting ("2004" … "2025"); 62.1 editions for ventilation ("1999" … "2022")
def role_vocabulary(role: RoleName) -> list[str]: ...
    # Read from the data for the three space-type roles; raises StandardsUnavailableError without the extra

@dataclass(frozen=True, slots=True)
class StandardsContext: ...          # edition, ventilation_edition, climate_zone, building_category, *_source
@dataclass(frozen=True, slots=True)
class Requirement: ...
@dataclass(frozen=True, slots=True)
class ObjectRole: ...
@dataclass(frozen=True, slots=True)
class ZoneLighting: ...
@dataclass(frozen=True, slots=True)
class ZoneOutdoorAir: ...
@dataclass(frozen=True, slots=True)
class ScreeningVerdict: ...
@dataclass(frozen=True, slots=True)
class ScreeningReport: ...

def lookup_envelope(*, edition: str, climate_zone: str, surface_class: str,
                    building_category: str, assembly_class: str | None = None) -> list[Requirement]: ...
def lookup_lighting(*, edition: str, space_type: str) -> list[Requirement]: ...
    # space_type: a level-1 or a lighting space-type name; SS and CS rows only, never BA
def lookup_ventilation(*, edition: str, space_type: str) -> list[Requirement]: ...
    # space_type: a level-1 or a ventilation space-type name; edition is the 62.1 edition

# Model side: no extra needed (FR-006)
def compute_roles(doc: IDFDocument) -> list[ObjectRole]: ...         # computed + unconfirmed only
def zone_lighting(doc: IDFDocument) -> list[ZoneLighting]: ...
def zone_outdoor_air(doc: IDFDocument) -> list[ZoneOutdoorAir]: ...

def screen(doc: IDFDocument, context: StandardsContext, *,
           topics: Collection[Topic] | None = None,
           asserted: Mapping[tuple[str, str, str], str] | None = None) -> ScreeningReport: ...
    # `asserted` maps (object_type, NAME_UPPER, role) -> value; supplied by the caller (session state).
    # Raises ValueError naming each missing context item for a named topic, or when no topic can be evaluated.
```

`compute_roles`, `zone_lighting`, `zone_outdoor_air` and `StandardsContext` work without the extra. The lookups,
`screen`, `editions`, `role_vocabulary` and `data_version` need it.

`screen_envelope`, named in earlier drafts of this contract, is replaced by `screen` before any release (R-29).

## `idfkit.graph` (new unit; combined view over the layers)

```python
NodeKind = Literal["object", "node", "result_fact", "message", "verdict"]
EdgeKind = Literal["reference", "flow", "control", "membership", "result_link", "verdict"]
Layer = Literal["model", "topology", "results", "standards"]
JSONValue = Union[None, bool, int, float, str, list["JSONValue"], dict[str, "JSONValue"]]

@dataclass(frozen=True, slots=True)
class GraphNode: ...
@dataclass(frozen=True, slots=True)
class GraphEdge: ...
@dataclass(frozen=True, slots=True)
class Subgraph: ...

class ModelGraph:
    def __init__(self, doc: IDFDocument, *, results: ResultIndex | None = None,
                 standards: StandardsContext | None = None,
                 asserted: Mapping[tuple[str, str, str], str] | None = None) -> None: ...
        # Does no work (FR-056). `standards` and `asserted` come from the caller (FR-054).
    @property
    def layers(self) -> list[Layer]: ...
    @property
    def unavailable(self) -> dict[Layer, str]: ...
    @property
    def partial(self) -> dict[Layer, str]: ...
        # Present layers covering only part of their scope, e.g. standards topics without a complete context
    def node_id(self, target: ObjectKey | str) -> str: ...
        # ObjectKey -> object id; str -> node id. Raises KeyError if absent from the model.
    def neighbourhood(self, start: ObjectKey | str, *, hops: int = 1,
                      node_kinds: Collection[NodeKind] | None = None,
                      edge_kinds: Collection[EdgeKind] | None = None,
                      max_nodes: int = 200) -> Subgraph: ...
        # ValueError if hops < 0 or max_nodes < 1. No upper bound here; the server applies its own (FR-058).
    def to_node_link(self, *, layers: Collection[Layer] | None = None,
                     node_kinds: Collection[NodeKind] | None = None,
                     edge_kinds: Collection[EdgeKind] | None = None,
                     start: ObjectKey | str | None = None, hops: int | None = None) -> dict[str, JSONValue]: ...
        # `start` and `hops` must be given together; ValueError otherwise.

def write_node_link(graph: ModelGraph, **scope: Any) -> str: ...       # same scope keywords as to_node_link
def save_node_link(graph: ModelGraph, path: str | os.PathLike[str], **scope: Any) -> None: ...
NODE_LINK_FORMAT_VERSION: Final = 1
```

In the implementation, `**scope` is spelled out as the five keyword-only parameters of `to_node_link`, so pyright
strict checks every call. It is abbreviated here only.

The export format is defined in [node-link-json.md](node-link-json.md).

## Rules for the whole public surface (FR-050 to FR-054)

- Public names are exactly the names in each unit's `__all__` and in the naming register. Everything else is
  private. idfkit-mcp's `tests/test_public_api_only.py` enforces this from the consumer side (research R-22).
- No public function reads session, server or global mutable state. Session concepts are arguments (`asserted`,
  `standards`, `run_revision`, `run_model_hash`).
- Every public name passes pyright strict with no suppression, and has at least one runnable snippet under
  `agent_references/snippets/` that runs in the test suite and is embedded in its idfkit-developers reference page
  (SC-014).
- Breaking changes follow idfkit's versioning. Deprecations warn for at least one minor release before removal
  (FR-053).

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
| First lookup or `screen` in a process, per topic | ≤ 150 ms |
| Later `screen` on a loaded model, all three topics | ≤ 20 ms |
| `zone_lighting`, `zone_outdoor_air` on the reference model | ≤ 20 ms each |
| `ModelGraph(...)` construction | ≤ 0.1 ms, with no layer built |
| `ModelGraph.neighbourhood`, 3 hops, up to 200 nodes, topology cached | ≤ 10 ms |
| `to_node_link()` of the `model` and `topology` layers on the reference model | ≤ 1 s, ≤ 50 MB peak extra memory |

Implementation obligations that keep these budgets:
- Per-type plans are computed once per schema version.
- Only node-bearing collections are visited.
- Internal records are tuples, and dataclasses are built only for returned items.
- Derived views are cached in `IDFDocument._derived` and stamped with the revision.
- Standards tables are loaded lazily, projected and shared process-wide.

## Codegen and gates (idfkit)

- `python -m idfkit.codegen.generate_node_fields` writes `src/idfkit/hvac/_node_fields.py`. `make check` gains
  `check-node-fields`, which regenerates the file and diffs it.
- `agent_references/templates/hvac-topology.md` and `snippets/hvac-topology.py` are new, and so are `standards`
  and `model-graph` with their snippets. `result-parsing`, `thermal-properties`, `reference-tracking` and
  `hvac-loops` are updated. All of them are re-baked, and `SKILL.md`'s task table gains rows for the three new
  topics.
- idfkit-developers gains a reference page per new unit (`hvac`, `standards`, `graph`) and updated pages for
  `simulation` and `thermal`. Each page embeds the snippets above rather than its own copies.
- `make check` keeps passing `check-parity-ledger` and `check-naming-register` with rows for `idfkit.hvac`,
  `idfkit.standards` and `idfkit.graph`, landed as a pair with idfkit-conformance.
- Every new public name is added to the CHANGELOG under `[Unreleased]`.
