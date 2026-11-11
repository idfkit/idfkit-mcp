"""The ``tools/list`` response stays within 15% of the pre-feature base (SC-010, research R-12).

The cost is counted exactly as ``scripts/token_audit.py --listing-json`` counts it (the function is loaded from
the script, so the two cannot drift): the whole listing, output schemas included, at 4 characters per token. The
base was measured at ``81d3cd6``, before the model knowledge graph feature, and lives in
``tests/fixtures/tool_listing_base.json``.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_FILE = REPO_ROOT / "tests" / "fixtures" / "tool_listing_base.json"
TOKEN_AUDIT = REPO_ROOT / "scripts" / "token_audit.py"
ALLOWED_GROWTH = 1.15


def _tool_listing_cost() -> Callable[[Sequence[Any]], dict[str, int]]:
    """Load ``tool_listing_cost`` from ``scripts/token_audit.py`` (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("_token_audit", TOKEN_AUDIT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("Callable[[Sequence[Any]], dict[str, int]]", module.tool_listing_cost)


async def test_tool_listing_within_budget(client: Client[FastMCPTransport]) -> None:
    base = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    current = _tool_listing_cost()(await client.list_tools())

    budget = int(base["tokens"] * ALLOWED_GROWTH)
    assert current["tokens"] <= budget, (
        f"tools/list is {current['tokens']} tokens for {current['tools']} tools; the budget is {budget} "
        f"(base {base['tokens']} tokens / {base['tools']} tools at {base['commit']}, x{ALLOWED_GROWTH}). "
        "Shrink descriptions or output schemas, or reuse shared sub-models (research R-12)."
    )


def test_base_fixture_shape() -> None:
    base = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    assert set(base) == {"commit", "tools", "tokens"}
    assert base["commit"] == "81d3cd6"
    assert base["tools"] == 39
    assert 14_000 <= base["tokens"] <= 16_500
