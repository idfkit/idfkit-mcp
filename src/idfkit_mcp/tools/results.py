"""Simulation results attached to the model objects they concern (idfkit.simulation.linking)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from idfkit import IDFDocument
from idfkit.hvac import HVACTopology
from idfkit.simulation import LinkedMessage, ObjectKey, ObjectResults, Resolution, ResultFact, ResultIndex
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp import models as m
from idfkit_mcp.compact_schema import compact_output_schema
from idfkit_mcp.state import ResultsState, get_state
from idfkit_mcp.tools.topology import RESPONSE_BYTES, closest, coverage_model, find_object

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

MAX_LIMIT = 100
DEFAULT_LIMIT = 20
_ENVELOPE_BYTES = 64
_PSEUDO_TYPES = frozenset({"AGGREGATE", "UNRESOLVED"})
"""Keys that name no model object or node: report totals and unlinked raw keys."""


# ----------------------------------------------------------------------------------------------- #
# Mirrors: idfkit records to the response models
# ----------------------------------------------------------------------------------------------- #


def key_model(key: ObjectKey) -> m.ObjectKey:
    """Mirror an idfkit ``ObjectKey``."""
    return m.ObjectKey(object_type=key.object_type, name=key.name)


def affected(keys: Iterable[ObjectKey | None]) -> list[m.ObjectKey]:
    """Model objects and nodes among *keys*, each once, in first-seen order; aggregates are left out."""
    seen: dict[ObjectKey, None] = {}
    for key in keys:
        if key is not None and key.object_type.upper() not in _PSEUDO_TYPES:
            seen.setdefault(key, None)
    return [key_model(k) for k in seen]


def message_objects(messages: Iterable[LinkedMessage]) -> list[m.ObjectKey]:
    """The objects the given messages name, each once."""
    return affected(link.key for message in messages for link in message.objects)


def _resolution(link: Resolution) -> m.Resolution:
    return m.Resolution(
        key=key_model(link.key) if link.key is not None else None,
        rule=link.rule,
        confidence=link.confidence,
        via=[key_model(k) for k in link.via],
    )


def _fact(fact: ResultFact) -> m.ResultFact:
    return m.ResultFact(
        source=fact.source,
        metric=fact.metric,
        value=fact.value,
        units=fact.units,
        where=fact.where,
        multiplier=fact.multiplier,
    )


def _message(message: LinkedMessage) -> m.LinkedMessage:
    return m.LinkedMessage(
        severity=message.severity,
        kind=message.kind,
        text=message.text,
        objects=[_resolution(link) for link in message.objects],
        occurrences=message.occurrences,
        first_seen=message.first_seen,
    )


def _bounded(items: Sequence[Any], limit: int) -> tuple[list[Any], int, int]:
    kept = list(items[:limit])
    return kept, len(items), len(items) - len(kept)


def _mirror(found: ObjectResults, limit: int, results_state: ResultsState) -> m.ObjectResults:
    facts, facts_total, facts_omitted = _bounded(found.facts, limit)
    messages, messages_total, messages_omitted = _bounded(found.messages, limit)
    variables, variables_total, variables_omitted = _bounded(found.available_variables, limit)
    neighbours, neighbours_total, neighbours_omitted = _bounded(found.neighbours, limit)
    return m.ObjectResults(
        object=key_model(found.object),
        facts=m.FactPage(items=[_fact(f) for f in facts], total=facts_total, omitted=facts_omitted),
        messages=m.MessagePage(items=[_message(x) for x in messages], total=messages_total, omitted=messages_omitted),
        available_variables=m.VariablePage(items=variables, total=variables_total, omitted=variables_omitted),
        neighbours=m.NeighbourPage(
            items=[
                m.ObjectNeighbour(object=key_model(n.object), top_fact=_fact(n.top_fact) if n.top_fact else None)
                for n in neighbours
            ],
            total=neighbours_total,
            omitted=neighbours_omitted,
        ),
        coverage=coverage_model(found.coverage),
        results_state=results_state,
    )


def _size(result: m.ObjectResults) -> int:
    return len(result.model_dump_json()) + _ENVELOPE_BYTES


def _fit(found: ObjectResults, limit: int, results_state: ResultsState) -> m.ObjectResults:
    """The answer at *limit*, or at the largest lower limit whose response fits the 8 KB budget.

    The same limit applies to every list, and each list's ``omitted`` counts what the cut left out.
    """
    full = _mirror(found, limit, results_state)
    if _size(full) <= RESPONSE_BYTES:
        return full
    low, high = 0, limit - 1  # with every list empty the answer always fits
    while low < high:
        mid = (low + high + 1) // 2
        if _size(_mirror(found, mid, results_state)) <= RESPONSE_BYTES:
            low = mid
        else:
            high = mid - 1
    return _mirror(found, low, results_state)


# ----------------------------------------------------------------------------------------------- #
# The answer
# ----------------------------------------------------------------------------------------------- #


def _target(doc: IDFDocument[Any], object_type: str, name: str) -> ObjectKey:
    """The object or node asked about, in the model's spelling, or a ToolError naming the closest names."""
    if object_type.strip().lower() == "node":
        topo = HVACTopology.from_document(doc)
        for node in topo.nodes():
            if node.upper() == name.upper():
                return ObjectKey("Node", node)
        msg = (
            f"No node named {name!r} is used by any object.{closest(name, topo.nodes())} Use search_objects to find it."
        )
        raise ToolError(msg)
    try:
        obj = find_object(doc, object_type, name)
    except ToolError as exc:
        msg = f"{exc} Use search_objects to find it."
        raise ToolError(msg) from None
    return ObjectKey(obj.obj_type, obj.name)


def linked_results(index: ResultIndex, key: ObjectKey, limit: int, results_state: ResultsState) -> m.ObjectResults:
    """Everything the run reported about *key*, bounded by *limit* per list and by the 8 KB budget."""
    return _fit(index.for_object(key), limit, results_state)


def build_object_results(object_type: str, name: str, limit: int = DEFAULT_LIMIT) -> m.ObjectResults:
    """Shared by ``get_object_results`` and the ``idfkit://simulation/objects/{type}/{name}`` resource."""
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}, got {limit}."
        raise ToolError(msg)
    state = get_state()
    index, results_state = state.require_results()
    key = _target(state.require_model(), object_type, name)
    return linked_results(index, key, limit, results_state)


@tool(annotations=_READ_ONLY, output_schema=compact_output_schema(m.ObjectResults))
def get_object_results(
    object_type: Annotated[str, Field(description='The object\'s type, or "Node" for a fluid node.')],
    name: Annotated[str, Field(description="Object or node name, matched case-insensitively.")],
    limit: Annotated[int, Field(description="Most items per list, 1-100.")] = DEFAULT_LIMIT,
) -> m.ObjectResults:
    """Every result the last run reported for one object or node: sizing and tabular facts with
    where each was read, its warnings deduplicated by kind with occurrence counts, the output
    variables recorded for it, and its neighbours with their first fact.

    Nearest neighbour: get_object_neighbourhood, to walk the model around the object across layers.
    Use this one for every result and message of one object, with counts. Zone facts carry the zone
    multiplier: values are per instance. results_state is "stale" once the model changed after the run.

    Preconditions: a simulation run by run_simulation in this session.
    Side effects: none.
    """
    return build_object_results(object_type, name, limit)
