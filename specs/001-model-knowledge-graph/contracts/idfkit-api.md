# Contract: idfkit public API added by this feature

This is the upstream surface idfkit-mcp calls (Constitution Principle I). Signatures are normative; bodies are not.
Every name here is typed for pyright strict and uses the standard library only. Revision 2 (2026-11-11): the
standards layer is deferred ([deferred-standards.md](../deferred-standards.md)), and the review additions are in
(research R-34 to R-37).

New capability units (`idfkit.hvac`, `idfkit.graph`) need parity-ledger and naming-register rows in
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
class ComponentCategory(str, Enum): ...   # closed vocabulary from _categories.py (R-36); adding a member is minor

def category_of(object_type: str) -> ComponentCategory: ...   # from the type alone, never from names

@dataclass(frozen=True, slots=True)
class Coverage: ...          # partial, uncovered: list[UncoveredPart], resolved, unresolved (R-35)
@dataclass(frozen=True, slots=True)
class UncoveredPart: ...     # kind: hvac_template | ems_program | unclassified_type | unlinked_result

@dataclass(frozen=True, slots=True)
class NodeUse: ...
@dataclass(frozen=True, slots=True)
class LoopMembership: ...
@dataclass(frozen=True, slots=True)
class FlowEdge: ...
@dataclass(frozen=True, slots=True)
class TopologyFinding: ...   # severity is effective (after the version cap); capped_from, cap_reason (R-34)
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
    def upstream(self, start: IDFObject | str, *, hops: int = 2,
                 categories: Collection[ComponentCategory] | None = None) -> list[FlowEdge]: ...
    def downstream(self, start: IDFObject | str, *, hops: int = 2,
                   categories: Collection[ComponentCategory] | None = None) -> list[FlowEdge]: ...
        # `categories` keeps edges that reach a component of those categories; the walk still passes through others
    def loops(self) -> list[IDFObject]: ...
    def chain(self, loop: IDFObject, side: Literal["supply", "demand"]) -> list[list[IDFObject]]: ...
    def zones_served(self, air_loop: IDFObject) -> list[IDFObject]: ...
    def check(self) -> list[TopologyFinding]: ...
        # Severities are capped by the model's version through _version_caps.py (FR-013a)
    @property
    def coverage(self) -> Coverage: ...
        # Includes EMS programs as `ems_program`; EMS sensor and actuator uses are control NodeUses with rule "ems_key"

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
class CandidateCause: ...    # gains family and evidence_strength (R-16)
@dataclass(frozen=True, slots=True)
class Diagnosis: ...         # statement, no_strong_candidate, candidates, families_covered (R-16, R-37)

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
    # `statement` is set and `no_strong_candidate` is true when no candidate is strong

# parsers/err_catalog.py (new module)
MESSAGE_KINDS: tuple[MessageKind, ...]
def classify_message(text: str) -> tuple[MessageKind | None, list[tuple[str | None, str]]]: ...
```

## `idfkit.standards` (deferred)

Deferred to a future spec with surface-appropriate films in `idfkit.thermal`. See
[deferred-standards.md](../deferred-standards.md).

## `idfkit.graph` (new unit; combined view over the layers)

```python
NodeKind = Literal["object", "node", "result_fact", "message"]
EdgeKind = Literal["reference", "flow", "control", "membership", "result_link"]
Layer = Literal["model", "topology", "results"]
    # Closed within a release. Adding a member is a minor change (FR-053, FR-056); code that reads kinds
    # must ignore members it does not know.
JSONValue = Union[None, bool, int, float, str, list["JSONValue"], dict[str, "JSONValue"]]

@dataclass(frozen=True, slots=True)
class GraphNode: ...
@dataclass(frozen=True, slots=True)
class GraphEdge: ...
@dataclass(frozen=True, slots=True)
class Subgraph: ...

class ModelGraph:
    def __init__(self, doc: IDFDocument, *, results: ResultIndex | None = None) -> None: ...
        # Does no work (FR-056). `results` comes from the caller (FR-054).
    @property
    def layers(self) -> list[Layer]: ...
    @property
    def unavailable(self) -> dict[Layer, str]: ...
    @property
    def coverage(self) -> Coverage: ...
        # What the view cannot see: templates, EMS programs, unclassified types, unlinked results (R-35)
    def node_id(self, target: ObjectKey | str) -> str: ...
        # ObjectKey -> object id; str -> node id. Raises KeyError if absent from the model.
    def neighbourhood(self, start: ObjectKey | str, *, hops: int = 1,
                      node_kinds: Collection[NodeKind] | None = None,
                      edge_kinds: Collection[EdgeKind] | None = None,
                      categories: Collection[ComponentCategory] | None = None,
                      max_nodes: int = 200) -> Subgraph: ...
        # `categories` keeps object nodes of those categories, plus the start and non-object nodes on kept paths
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
- No public function reads session, server or global mutable state. Session concepts are arguments (`results`,
  `run_revision`, `run_model_hash`).
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
| `ModelGraph(...)` construction | ≤ 0.1 ms, with no layer built |
| `ModelGraph.neighbourhood`, 3 hops, up to 200 nodes, topology cached | ≤ 10 ms |
| `to_node_link()` of the `model` and `topology` layers on the reference model | ≤ 1 s, ≤ 50 MB peak extra memory |

Implementation obligations that keep these budgets:
- Per-type plans are computed once per schema version.
- Only node-bearing collections are visited.
- Internal records are tuples, and dataclasses are built only for returned items.
- Derived views are cached in `IDFDocument._derived` and stamped with the revision.

## Codegen and gates (idfkit)

- `python -m idfkit.codegen.generate_node_fields` writes `src/idfkit/hvac/_node_fields.py`. `make check` gains
  `check-node-fields`, which regenerates the file and diffs it.
- `src/idfkit/hvac/_categories.py` (R-36) and `_version_caps.py` (R-34) are committed tables. A coverage test lists
  node-bearing types without a category. `_version_caps.py` is rewritten only by the earlier-version corpus test
  (`pytest -m integration --corpus 9.6.0=PATH --corpus 23.2.0=PATH`).
- `agent_references/templates/hvac-topology.md` and `snippets/hvac-topology.py` are new, and so is `model-graph`
  with its snippet. `result-parsing`, `reference-tracking` and `hvac-loops` are updated. All of them are re-baked,
  and `SKILL.md`'s task table gains rows for the two new topics.
- idfkit-developers gains a reference page per new unit (`hvac`, `graph`) and an updated page for `simulation`.
  Each page embeds the snippets above rather than its own copies.
- `make check` keeps passing `check-parity-ledger` and `check-naming-register` with rows for `idfkit.hvac` and
  `idfkit.graph`, landed as a pair with idfkit-conformance.
- Every new public name is added to the CHANGELOG under `[Unreleased]`.
