"""The server uses only idfkit's public surface (FR-050, research R-22).

Every module under ``src/idfkit_mcp/`` is parsed, and the test fails on:

(a) an import from an ``idfkit`` module whose dotted path has an underscore-prefixed segment
    (``idfkit._compat``, ``idfkit.simulation._common``);
(b) an imported ``idfkit`` name that starts with an underscore (``from idfkit.hvac import _plan``);
(c) access to an underscore attribute of an idfkit object (``doc._derived``, ``idfkit._x``).

Rule (c) is a static heuristic. A name is treated as an idfkit object when it is

- bound by an ``idfkit`` import (a module, a module alias or an imported name), or
- annotated, as a parameter or in an annotated assignment, with an annotation that mentions such a name
  (``doc: IDFDocument``, ``result: SimulationResult | None``, string annotations included).

An underscore attribute anywhere in an attribute chain rooted at such a name is flagged
(``doc._derived``, ``doc.schema._cache``). Dunder attributes (``idfkit.__version__``) are public and allowed.

Limits of (c), stated so nobody reads more into a green run than it proves:

- Names are collected per module, not per scope. A name annotated with an idfkit type anywhere in a module is
  treated as an idfkit object everywhere in it. This can only over-report, and a rename fixes it.
- Values whose idfkit type is only inferred are not seen: ``doc = load_idf(path)`` with no annotation,
  ``state.document._x``, ``get_state().simulation_result._x``, values returned from calls, loop variables and
  ``getattr(doc, "_x")``. pyright strict's ``reportPrivateUsage`` covers most inferred cases at type-check time.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "idfkit_mcp"


@dataclass(frozen=True)
class Violation:
    """One use of a private idfkit name."""

    path: str
    line: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.detail}"


def _is_private(segment: str) -> bool:
    """Underscore-prefixed, but not a dunder such as ``__version__``."""
    return segment.startswith("_") and not (segment.startswith("__") and segment.endswith("__"))


def _is_idfkit_module(module: str) -> bool:
    return module == "idfkit" or module.startswith("idfkit.")


def _annotation_names(annotation: ast.expr) -> set[str]:
    """Return every bare name an annotation mentions, parsing string annotations too."""
    names: set[str] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode="eval")
            except SyntaxError:
                continue
            names |= _annotation_names(parsed.body)
    return names


def _attribute_chain(node: ast.Attribute) -> tuple[ast.expr, list[str]]:
    """Return the root expression and the attribute names of ``root.a.b.c``, outermost last."""
    attrs: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        attrs.append(current.attr)
        current = current.value
    attrs.reverse()
    return current, attrs


def _check_import(node: ast.Import, path: str, violations: list[Violation], bound: set[str]) -> None:
    for alias in node.names:
        if not _is_idfkit_module(alias.name):
            continue
        if any(_is_private(seg) for seg in alias.name.split(".")):
            violations.append(Violation(path, node.lineno, "a", f"import {alias.name}"))
        bound.add(alias.asname or alias.name.split(".")[0])


def _check_import_from(node: ast.ImportFrom, path: str, violations: list[Violation], bound: set[str]) -> None:
    module = node.module or ""
    if node.level or not _is_idfkit_module(module):
        return
    if any(_is_private(seg) for seg in module.split(".")):
        violations.append(Violation(path, node.lineno, "a", f"from {module} import ..."))
    for alias in node.names:
        if _is_private(alias.name):
            violations.append(Violation(path, node.lineno, "b", f"from {module} import {alias.name}"))
        if alias.name != "*":
            bound.add(alias.asname or alias.name)


def _check_imports(tree: ast.Module, path: str, violations: list[Violation]) -> set[str]:
    """Apply rules (a) and (b); return the names that ``idfkit`` imports bind."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _check_import(node, path, violations, bound)
        elif isinstance(node, ast.ImportFrom):
            _check_import_from(node, path, violations, bound)
    return bound


def _idfkit_objects(tree: ast.Module, bound: set[str]) -> set[str]:
    """Return ``bound`` plus every name annotated with an annotation that mentions a bound name."""
    objects = set(bound)
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None and _annotation_names(node.annotation) & bound:
            objects.add(node.arg)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _annotation_names(node.annotation) & bound
        ):
            objects.add(node.target.id)
    return objects


def _check_attributes(tree: ast.Module, objects: set[str], path: str, violations: list[Violation]) -> None:
    """Apply rule (c), reporting each attribute chain once, at its outermost node."""
    inner = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or id(node) in inner:
            continue
        root, attrs = _attribute_chain(node)
        if not isinstance(root, ast.Name) or root.id not in objects:
            continue
        private = [a for a in attrs if _is_private(a)]
        if private:
            chain = ".".join([root.id, *attrs])
            violations.append(Violation(path, node.lineno, "c", f"{chain} ({', '.join(private)})"))


def check_source(source: str, path: str = "<string>") -> list[Violation]:
    """Return every private-idfkit-API use in ``source``."""
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    bound = _check_imports(tree, path, violations)
    _check_attributes(tree, _idfkit_objects(tree, bound), path, violations)
    return violations


def _modules() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def test_source_tree_found() -> None:
    assert len(_modules()) > 10, f"expected the idfkit_mcp package under {SRC_ROOT}"


def test_server_uses_only_public_idfkit_api() -> None:
    violations: list[Violation] = []
    for module in _modules():
        rel = module.relative_to(SRC_ROOT.parent.parent).as_posix()
        violations.extend(check_source(module.read_text(encoding="utf-8"), rel))
    assert not violations, "private idfkit API used:\n" + "\n".join(str(v) for v in violations)


# ---------------------------------------------------------------------------
# The checker itself: each rule fires, and public use does not.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("import idfkit._compat", "a"),
        ("import idfkit.simulation._common as common", "a"),
        ("from idfkit._compat import EppyIDF", "a"),
        ("from idfkit.simulation._common import helper", "a"),
        ("from idfkit import _private_helper", "b"),
        ("from idfkit.hvac import plan as ok, _plan", "b"),
        ("import idfkit\nidfkit._internal()", "c"),
        ("import idfkit.simulation as sim\nsim._cache.clear()", "c"),
        ("from idfkit import IDFDocument\ndef f(doc: IDFDocument) -> None:\n    doc._derived.clear()", "c"),
        ("from idfkit import IDFDocument\ndef f(doc: 'IDFDocument | None') -> object:\n    return doc._derived", "c"),
        ("from idfkit import IDFDocument\ndoc: IDFDocument[bool] = make()\ndoc.schema._raw", "c"),
        ("from idfkit.objects import IDFObject as Obj\nObj._slots", "c"),
    ],
)
def test_checker_flags(source: str, rule: str) -> None:
    rules = [v.rule for v in check_source(source)]
    assert rule in rules, f"expected rule {rule} to fire on {source!r}, got {rules}"


@pytest.mark.parametrize(
    "source",
    [
        "import idfkit\nprint(idfkit.__version__)",
        "from idfkit import IDFDocument, load_idf\ndoc = load_idf('x')",
        "from idfkit.introspection import describe_object_type as _describe\n_describe(schema, 'Zone')",
        "from idfkit import IDFDocument\ndef f(doc: IDFDocument) -> object:\n    return doc.schema.version",
        "from . import _local\nfrom idfkit_mcp.tools._billing import BillingProbe",
        "class S:\n    def f(self) -> None:\n        self._restored = True",
    ],
)
def test_checker_allows_public_use(source: str) -> None:
    assert check_source(source) == []
