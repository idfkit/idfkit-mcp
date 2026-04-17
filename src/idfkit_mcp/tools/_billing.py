"""Emit ``_meta.billing`` on billable tool responses.

A hosted deployment in front of idfkit-mcp (see `idfkit-mcp-deployment`)
meters simulation runtime and retained artifact bytes. That deployment can
synthesize billing from wall-clock timing, but the authoritative source is
the MCP server itself — it knows the real CPU time and the artifacts the
simulation produced.

This module provides the tiny helper that collects those metrics and
attaches them to a FastMCP ``ToolResult``. Call sites are expected to use
``BillingProbe`` as a context manager around the work being measured.

The data shape is stable and versioned via ``schema_version``:

    {
      "schema_version": "1",
      "tool": "run_simulation",
      "runtime_ms": 42718,
      "cpu_seconds": 38.5,
      "artifacts": [
        {"name": "eplusout.sql", "bytes": 284731},
        ...
      ]
    }

Hosted deployments can trust this block; gateway-synthesised fallbacks
carry ``"source": "gateway_fallback"`` instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any


@dataclass
class BillingProbe:
    """Context manager that captures runtime + CPU across a block of work."""

    _t0: float = 0.0
    _cpu0: os.times_result | None = None
    runtime_ms: int = field(default=0, init=False)
    cpu_seconds: float = field(default=0.0, init=False)

    def __enter__(self) -> BillingProbe:
        self._t0 = perf_counter()
        self._cpu0 = os.times()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._cpu0 is None:
            raise RuntimeError("BillingProbe exited without entering")
        cpu1 = os.times()
        self.runtime_ms = int((perf_counter() - self._t0) * 1000)
        # Include child-process CPU (EnergyPlus runs as a subprocess).
        self.cpu_seconds = round(
            (cpu1.user - self._cpu0.user)
            + (cpu1.system - self._cpu0.system)
            + (cpu1.children_user - self._cpu0.children_user)
            + (cpu1.children_system - self._cpu0.children_system),
            3,
        )


def _sum_artifacts(run_dir: Path | None) -> list[dict[str, int | str]]:
    """Return ``[{"name": str, "bytes": int}, ...]`` for files in run_dir."""
    if run_dir is None or not run_dir.exists() or not run_dir.is_dir():
        return []
    out: list[dict[str, int | str]] = []
    for child in sorted(run_dir.iterdir()):
        if child.is_file():
            try:
                size = child.stat().st_size
            except OSError:
                continue
            out.append({"name": child.name, "bytes": size})
    return out


def build_billing_meta(
    *,
    tool: str,
    probe: BillingProbe,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Assemble the ``_meta.billing`` payload for a billable tool response."""
    return {
        "schema_version": "1",
        "tool": tool,
        "runtime_ms": probe.runtime_ms,
        "cpu_seconds": probe.cpu_seconds,
        "artifacts": _sum_artifacts(run_dir),
    }
