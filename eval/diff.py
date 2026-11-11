"""Model diff, unwanted changes and control false fixes (contract "Rules" and "Recorded"; task T067).

**Snapshot.** A model is read as ``ObjectKey -> normalised field data`` through idfkit's public API
(``IDFDocument.all_objects``, ``IDFObject.obj_type``, ``.name`` and ``.data``). Keys compare case-insensitively
(``ObjectKey``). Field values are normalised so that a save and reload do not count as a change: strings are
stripped and case-folded, numbers and numeric strings become floats, empty values are dropped, and extensible
groups keep their order.

**Unnamed objects** (``Version``, ``Output:Variable``, ...) have no name to match on. They are compared per type as
multisets of their field data, and each one that appears on only one side is a change keyed
``ObjectKey(type, "")``; a changed unnamed object therefore counts once on each side.

**Unwanted changes** are the changed keys (added, removed or with different fields) outside the task's scope. A
scope entry with an empty name covers every unnamed object of its type.

**Control false fix** is any model change, or any fault the agent reported. A *reported fault* is decided from the
parsed transcript, deliberately simply:

1. the agent changed the in-memory model through a server tool (a successful ``update_object``, ``add_object``,
   ``remove_object``, ``rename_object`` and the like), even if it never saved it; or
2. a sentence of the agent's final message uses a fault-reporting word (``fixed``, ``corrected``, ``wrong``,
   ``incorrect``, ``misconfigured``, ``broken``, ``problem``, ``issue``, ``error``, ...) and no negation (``no``,
   ``not``, ``nothing``, ``none``, ``never``, ``without``, ``n't``, ``0``, ``zero``). "I corrected the outlet node"
   reports a fault; "No issues found" and "There is nothing to fix" do not.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from eval.model import ObjectKey
from eval.parsers import ParsedTranscript

if TYPE_CHECKING:
    from idfkit import IDFDocument

Fields = tuple[tuple[str, object], ...]

_REPORT = re.compile(
    r"\b(fix(ed|es)?|corrected|repair(ed|s)?|resolved?|wrong|incorrect(ly)?|misconfigured|broken|"
    r"errors?|problems?|issues?|mistakes?)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(no|not|nothing|none|never|without|zero|0)\b|n't\b", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Snapshot:
    """A model's objects: named ones by key, unnamed ones as per-type multisets of their fields."""

    named: dict[ObjectKey, Fields]
    unnamed: dict[str, Counter[Fields]]


@dataclass(frozen=True)
class ModelDiff:
    """What changed between two snapshots."""

    added: list[ObjectKey]
    removed: list[ObjectKey]
    modified: list[ObjectKey]

    @property
    def changed(self) -> list[ObjectKey]:
        return [*self.removed, *self.modified, *self.added]

    def outside(self, scope: Iterable[ObjectKey]) -> list[ObjectKey]:
        """Changed keys not covered by ``scope``."""
        keys = set(scope)
        whole_types = {k.object_type.casefold() for k in keys if not k.name}
        return [k for k in self.changed if k not in keys and k.object_type.casefold() not in whole_types]


def snapshot(doc: IDFDocument) -> Snapshot:
    """Read ``doc`` through idfkit's public API."""
    named: dict[ObjectKey, Fields] = {}
    unnamed: dict[str, Counter[Fields]] = {}
    for obj in doc.all_objects:
        fields = _fields(obj.data)
        name = obj.name
        if name:
            named[ObjectKey(obj.obj_type, name)] = fields
        else:
            unnamed.setdefault(obj.obj_type.casefold(), Counter())[fields] += 1
    return Snapshot(named=named, unnamed=unnamed)


def diff(start: Snapshot, final: Snapshot) -> ModelDiff:
    """Objects added, removed and modified from ``start`` to ``final``."""
    added = [k for k in final.named if k not in start.named]
    removed = [k for k in start.named if k not in final.named]
    modified = [k for k, fields in start.named.items() if k in final.named and final.named[k] != fields]
    for object_type in sorted(start.unnamed.keys() | final.unnamed.keys()):
        before = start.unnamed.get(object_type, Counter[Fields]())
        after = final.unnamed.get(object_type, Counter[Fields]())
        removed += [ObjectKey(object_type, "")] * sum((before - after).values())
        added += [ObjectKey(object_type, "")] * sum((after - before).values())
    return ModelDiff(added=added, removed=removed, modified=modified)


def unwanted_changes(changes: ModelDiff, scope: Iterable[ObjectKey]) -> int:
    """The number of changed objects outside ``scope``."""
    return len(changes.outside(scope))


def reported_fault(transcript: ParsedTranscript) -> bool:
    """Whether the agent changed the model through the server or reported a fault (see the module docstring)."""
    if transcript.mutating_calls():
        return True
    return any(_reports(sentence) for sentence in _SENTENCE.split(transcript.final_text or ""))


def false_fix(changes: ModelDiff | None, transcript: ParsedTranscript) -> bool:
    """A control task's false fix: any model change (``None`` when the final model did not load counts as one)
    or any reported fault."""
    return changes is None or bool(changes.changed) or reported_fault(transcript)


def first_edit_target(transcript: ParsedTranscript) -> ObjectKey | None:
    """The object the agent's first successful model-changing server call targeted, from its arguments:
    ``object_type`` with ``name`` or ``old_name``; for ``batch_add_objects``, the first object added."""
    for call in transcript.mutating_calls():
        key = _target(call.input)
        if key is None:
            objects = call.input.get("objects")
            if isinstance(objects, list) and objects and isinstance(objects[0], dict):
                key = _target(cast(dict[str, object], objects[0]))
        if key is not None:
            return key
    return None


def _target(arguments: Mapping[str, object]) -> ObjectKey | None:
    object_type = arguments.get("object_type")
    name = arguments.get("name", arguments.get("old_name"))
    if isinstance(object_type, str) and isinstance(name, str):
        return ObjectKey(object_type, name)
    return None


def _reports(sentence: str) -> bool:
    return bool(_REPORT.search(sentence)) and not _NEGATION.search(sentence)


def _fields(data: Mapping[str, object]) -> Fields:
    items = ((key.casefold(), _value(value)) for key, value in data.items())
    return tuple(sorted((k, v) for k, v in items if v is not None))


def _value(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return text.casefold()
    if isinstance(value, Mapping):
        return _fields(cast(Mapping[str, object], value))
    if isinstance(value, (list, tuple)):
        return tuple(_value(v) for v in cast(Iterable[object], value))
    return repr(value)
