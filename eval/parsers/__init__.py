"""Transcript parsers: one per agent CLI, named by a runner configuration's ``parse`` key.

A parser turns the raw output of one agent invocation into a ``ParsedTranscript``: the tool calls in order (with
their results), the tokens consumed and the agent's final text. Adding an agent CLI means adding a module here and
an entry in ``PARSERS``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from eval.config import ConfigError

NEW_TOOLS: tuple[str, ...] = (
    "trace_hvac",
    "get_hvac_topology",
    "rename_node",
    "get_object_results",
    "diagnose_symptom",
    "get_object_neighbourhood",
)
"""The six tools this feature adds (research R-31): ``tools_used`` lists these only."""

MUTATING_TOOLS: frozenset[str] = frozenset({
    "add_object",
    "batch_add_objects",
    "update_object",
    "remove_object",
    "remove_objects",
    "rename_object",
    "duplicate_object",
    "migrate_model",
    "rename_node",
})
"""Server tools that change the in-memory model (``save_model`` writes it but does not change it)."""


@dataclass(frozen=True)
class ToolCall:
    """One tool call. ``name`` is normalised: an MCP tool ``mcp__<server>__<tool>`` becomes ``<tool>`` with
    ``server`` set; built-in agent tools (``Read``, ``Bash``) keep their name with ``server=None``."""

    id: str
    name: str
    server: str | None
    input: dict[str, object] = field(default_factory=dict[str, object])
    result: str | None = None
    is_error: bool = False

    @property
    def mutating(self) -> bool:
        return self.server is not None and self.name in MUTATING_TOOLS

    def result_json(self) -> object | None:
        """The result parsed as JSON, or ``None`` when there is no result or it is not JSON."""
        if self.result is None:
            return None
        try:
            return cast(object, json.loads(self.result))
        except ValueError:
            return None


@dataclass(frozen=True)
class ParsedTranscript:
    """What the harness reads from one agent invocation.

    Attributes:
        tool_calls: Every tool call, in the order the agent made them.
        response_tokens: Tokens consumed (see the parser for the definition it uses).
        final_text: The agent's final message, the answer of a question task; ``None`` when there was none.
        is_error: The agent CLI reported the session as failed (for example the turn limit was hit).
        num_turns: Turns the CLI reports, when it does.
        unknown_events: Lines of an event type the parser does not know (skipped, counted).
        malformed_lines: Lines that are not JSON objects (skipped, counted).
    """

    tool_calls: list[ToolCall]
    response_tokens: int
    final_text: str | None
    is_error: bool = False
    num_turns: int | None = None
    unknown_events: int = 0
    malformed_lines: int = 0

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]

    def new_tools_used(self, new_tools: Sequence[str] = NEW_TOOLS) -> list[str]:
        """The new tools called through MCP, each once, in the order of their first call."""
        wanted = set(new_tools)
        seen: dict[str, None] = {}
        for call in self.tool_calls:
            if call.server is not None and call.name in wanted:
                seen.setdefault(call.name, None)
        return list(seen)

    def mutating_calls(self) -> list[ToolCall]:
        """Server calls that changed the model, without the ones that failed."""
        return [call for call in self.tool_calls if call.mutating and not call.is_error]


Parser = Callable[[str], ParsedTranscript]


def get_parser(name: str) -> Parser:
    """The parser a runner configuration names; ``ConfigError`` for an unknown name."""
    from eval.parsers import claude_stream_json

    parsers: dict[str, Parser] = {"claude_stream_json": claude_stream_json.parse}
    try:
        return parsers[name]
    except KeyError:
        raise ConfigError(f"unknown transcript parser {name!r}; known: {sorted(parsers)}") from None
