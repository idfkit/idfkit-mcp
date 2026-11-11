"""Parser for Claude Code's ``--output-format stream-json`` (one JSON event per line).

The events read:

- ``assistant``: ``message.content`` blocks. ``tool_use`` blocks are the tool calls, in order; ``text`` blocks are
  the agent's prose. ``message.usage`` is the usage of that API message. Claude Code repeats one message across
  several events (one per content block), so usage is taken once per ``message.id``, the last seen.
- ``user``: ``tool_result`` blocks, matched to their call by ``tool_use_id``; their text and ``is_error``.
- ``result``: the session's final event: ``result`` (the final text), ``is_error``, ``num_turns`` and ``usage``,
  which Claude Code totals over the session.

Every other event type (``system``, ``stream_event``, ``rate_limit_event``, ...) is skipped and counted, and lines
that are not JSON objects are skipped and counted, so a CLI that adds event types does not break a run.

**Tokens.** ``response_tokens`` is the tokens the session consumed: input tokens, cache-creation input tokens and
output tokens, from the ``result`` event's usage, or summed over the assistant messages when the session ended
without one (a timeout). Cache-read tokens are left out: they re-read context already counted when it was
created, so including them would count the conversation history once per turn. Large tool responses therefore
count once, when they enter the context, which is the cost the feature's tools are meant to cut.

**Tool names.** ``mcp__<server>__<tool>`` is split at the first two double underscores into the server and the
tool name; any other name is a built-in tool of the agent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from eval.parsers import ParsedTranscript, ToolCall

MCP_PREFIX = "mcp__"
_TOKEN_KEYS = ("input_tokens", "cache_creation_input_tokens", "output_tokens")


def split_tool_name(raw: str) -> tuple[str | None, str]:
    """``("idfkit", "load_model")`` for ``"mcp__idfkit__load_model"``; ``(None, raw)`` for a built-in tool."""
    if raw.startswith(MCP_PREFIX):
        server, sep, tool = raw[len(MCP_PREFIX) :].partition("__")
        if sep and server and tool:
            return server, tool
    return None, raw


@dataclass
class _Call:
    id: str
    raw_name: str
    input: dict[str, object]
    result: str | None = None
    is_error: bool = False


@dataclass
class _State:
    calls: list[_Call] = field(default_factory=list[_Call])
    by_id: dict[str, _Call] = field(default_factory=dict[str, _Call])
    usage_by_message: dict[str, Mapping[str, object]] = field(default_factory=dict[str, Mapping[str, object]])
    last_text: str | None = None
    result_text: str | None = None
    result_usage: Mapping[str, object] | None = None
    is_error: bool = False
    num_turns: int | None = None
    unknown: int = 0
    malformed: int = 0


def parse(text: str) -> ParsedTranscript:
    """Parse a whole stream-JSON transcript."""
    state = _State()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event: object = json.loads(line)
        except ValueError:
            state.malformed += 1
            continue
        if not isinstance(event, dict):
            state.malformed += 1
            continue
        _event(state, cast(dict[str, object], event))
    if state.result_usage is not None:
        tokens = _tokens(state.result_usage)
    else:
        tokens = sum(_tokens(usage) for usage in state.usage_by_message.values())
    calls = [
        ToolCall(
            id=c.id,
            name=split_tool_name(c.raw_name)[1],
            server=split_tool_name(c.raw_name)[0],
            input=c.input,
            result=c.result,
            is_error=c.is_error,
        )
        for c in state.calls
    ]
    return ParsedTranscript(
        tool_calls=calls,
        response_tokens=tokens,
        final_text=state.result_text if state.result_text is not None else state.last_text,
        is_error=state.is_error,
        num_turns=state.num_turns,
        unknown_events=state.unknown,
        malformed_lines=state.malformed,
    )


def _event(state: _State, event: dict[str, object]) -> None:
    kind = event.get("type")
    if kind == "assistant":
        _assistant(state, _mapping(event.get("message")))
    elif kind == "user":
        _user(state, _mapping(event.get("message")))
    elif kind == "result":
        result = event.get("result")
        if isinstance(result, str):
            state.result_text = result
        state.is_error = event.get("is_error") is True
        turns = event.get("num_turns")
        if isinstance(turns, int) and not isinstance(turns, bool):
            state.num_turns = turns
        usage = event.get("usage")
        if isinstance(usage, dict):
            state.result_usage = cast(dict[str, object], usage)
    else:
        state.unknown += 1


def _assistant(state: _State, message: Mapping[str, object]) -> None:
    usage = message.get("usage")
    if isinstance(usage, dict):
        message_id = message.get("id")
        key = message_id if isinstance(message_id, str) else f"_anonymous{len(state.usage_by_message)}"
        state.usage_by_message[key] = cast(dict[str, object], usage)
    texts: list[str] = []
    for block in _blocks(message.get("content")):
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        elif block_type == "tool_use":
            call_id, name = block.get("id"), block.get("name")
            if not isinstance(name, str):
                continue
            call = _Call(
                id=call_id if isinstance(call_id, str) else f"_call{len(state.calls)}",
                raw_name=name,
                input=dict(_mapping(block.get("input"))),
            )
            state.calls.append(call)
            state.by_id[call.id] = call
    if texts:
        state.last_text = "\n".join(texts)


def _user(state: _State, message: Mapping[str, object]) -> None:
    for block in _blocks(message.get("content")):
        if block.get("type") != "tool_result":
            continue
        call_id = block.get("tool_use_id")
        call = state.by_id.get(call_id) if isinstance(call_id, str) else None
        if call is None:
            continue
        call.result = _result_text(block.get("content"))
        call.is_error = block.get("is_error") is True


def _result_text(content: object) -> str | None:
    if isinstance(content, str):
        return content
    texts = [b["text"] for b in _blocks(content) if b.get("type") == "text" and isinstance(b.get("text"), str)]
    return "\n".join(cast(list[str], texts)) if texts else None


def _blocks(content: object) -> list[Mapping[str, object]]:
    if not isinstance(content, list):
        return []
    return [cast(dict[str, object], b) for b in cast(list[object], content) if isinstance(b, dict)]


def _mapping(value: object) -> Mapping[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _tokens(usage: Mapping[str, object]) -> int:
    total = 0
    for key in _TOKEN_KEYS:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
    return total
