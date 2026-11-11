"""The agent runner (contract "Runner configuration"; task T064).

One invocation runs the agent CLI of a ``RunnerConfig`` on one rendered prompt, against one condition's server:

1. ``write_mcp_config`` writes the condition's MCP configuration: one stdio server named ``SERVER_NAME``, its
   command, and an environment that points the server's output directory at the task's working directory.
2. ``build_argv`` substitutes ``{prompt}`` and ``{mcp_config}`` in the configured command (plain substitution, so
   braces in a prompt are kept), then appends ``max_turns_flag max_turns`` and ``model_flag model`` when configured,
   and ``disallowed_flag`` with the disallowed tools for an ablation condition.
3. ``run_agent`` runs it with an argument list (no shell), in the task's working directory, with a wall-clock
   timeout. Standard output, the transcript, goes to ``transcripts/<name>.jsonl``; standard error and the
   invocation's facts (argument list, exit code, timeout, duration) go beside it.

The turn limit is enforced by the agent CLI through ``max_turns_flag``. A runner without such an option is bounded
only by ``timeout_seconds``. On timeout the agent's whole process group is killed, the server it started included.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.config import RunnerConfig

SERVER_NAME = "idfkit"
"""The server's name in the generated MCP configuration; Claude Code names its tools ``mcp__idfkit__<tool>``."""

_BARE_TOOL = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class ServerCommand:
    """How to start one condition's MCP server (stdio)."""

    argv: list[str]
    env: dict[str, str]

    def display(self) -> str:
        return " ".join(self.argv)


@dataclass(frozen=True)
class AgentRun:
    """One finished agent invocation."""

    argv: list[str]
    returncode: int | None
    timed_out: bool
    duration_seconds: float
    transcript: Path
    stderr: Path

    def read_transcript(self) -> str:
        return self.transcript.read_text(encoding="utf-8", errors="replace")


def write_mcp_config(path: Path, server: ServerCommand, *, workdir: Path) -> Path:
    """Write the MCP configuration of one invocation. ``IDFKIT_MCP_OUTPUT_DIRS`` lets ``save_model`` write into
    ``workdir`` whatever the server's working directory; ``server.env`` is added on top."""
    env = {"IDFKIT_MCP_OUTPUT_DIRS": str(workdir), **server.env}
    config = {
        "mcpServers": {
            SERVER_NAME: {"type": "stdio", "command": server.argv[0], "args": server.argv[1:], "env": env},
        }
    }
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def agent_tool_name(tool: str) -> str:
    """The agent-side name of a server tool: ``trace_hvac`` becomes ``mcp__idfkit__trace_hvac``. Names that are
    already qualified, or are not bare snake-case server tool names (``Bash``), pass through unchanged."""
    return f"mcp__{SERVER_NAME}__{tool}" if _BARE_TOOL.match(tool) else tool


def build_argv(
    runner: RunnerConfig, *, prompt: str, mcp_config: Path, disallowed_tools: Sequence[str] = ()
) -> list[str]:
    """The agent command line of one invocation."""
    argv = [part.replace("{mcp_config}", str(mcp_config)).replace("{prompt}", prompt) for part in runner.command]
    if runner.max_turns_flag:
        argv += [runner.max_turns_flag, str(runner.max_turns)]
    if runner.model_flag and runner.model != "unset":
        argv += [runner.model_flag, runner.model]
    if disallowed_tools:
        argv += [runner.disallowed_flag, *(agent_tool_name(t) for t in disallowed_tools)]
    return argv


def run_agent(
    argv: Sequence[str],
    *,
    cwd: Path,
    transcript: Path,
    timeout_seconds: float,
    env: Mapping[str, str] | None = None,
) -> AgentRun:
    """Run the agent; its standard output becomes ``transcript``. Never raises for the agent's own failure: a
    non-zero exit or a timeout is recorded in the returned ``AgentRun`` (and in ``<transcript>.meta.json``)."""
    transcript.parent.mkdir(parents=True, exist_ok=True)
    stderr = transcript.with_suffix(".stderr.txt")
    started = time.monotonic()
    timed_out = False
    with transcript.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(  # noqa: S603 - an argument list from the maintainer's runner configuration
            list(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env=dict(env) if env is not None else None,
            start_new_session=os.name == "posix",
        )
        try:
            returncode: int | None = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(process)
            returncode = process.wait()
    run = AgentRun(
        argv=list(argv),
        returncode=returncode,
        timed_out=timed_out,
        duration_seconds=round(time.monotonic() - started, 3),
        transcript=transcript,
        stderr=stderr,
    )
    meta = {
        "argv": run.argv,
        "cwd": str(cwd),
        "returncode": run.returncode,
        "timed_out": run.timed_out,
        "duration_seconds": run.duration_seconds,
    }
    transcript.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return run


def _kill(process: subprocess.Popen[bytes]) -> None:
    """Kill the agent and everything it started (its session's process group on POSIX)."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        process.kill()
