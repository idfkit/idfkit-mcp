"""App resource metadata: each host is served the ui.domain it accepts."""

from __future__ import annotations

from typing import Any

import mcp.types as mt
import pytest
from fastmcp import Client

from idfkit_mcp.app_meta import PUBLIC_URL_ENV, claude_app_domain, claude_ui_meta, is_claude_client
from idfkit_mcp.server import mcp

UI_DOMAINS = {
    "ui://idfkit/geometry-viewer.html": "geometry-viewer.idfkit.com",
    "ui://idfkit/peak-loads-viewer.html": "peak-loads-viewer.idfkit.com",
    "ui://idfkit/schedule-viewer.html": "schedule-viewer.idfkit.com",
    "ui://idfkit/report-viewer.html": "report-viewer.idfkit.com",
    "ui://prefab/renderer.html": "file-manager.idfkit.com",
}
HOSTED_URL = "https://server.idfkit.com/mcp"


async def _ui_meta(client_name: str) -> dict[str, dict[str, Any]]:
    async with Client(mcp, client_info=mt.Implementation(name=client_name, version="1.0")) as client:
        out: dict[str, dict[str, Any]] = {}
        for uri in UI_DOMAINS:
            result = await client.read_resource_mcp(uri)
            meta = result.contents[0].meta
            assert meta is not None
            out[uri] = meta["ui"]
        return out


def test_claude_domain_matches_documented_example() -> None:
    # Example from Claude's MCP Apps documentation.
    assert claude_app_domain("https://example.com/mcp") == "c3d80a4ed901ee05b21755a88273b4a4.claudemcpcontent.com"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("claude-ai", True), ("Claude Code", True), ("openai-mcp", False), ("cursor", False), (None, False)],
)
def test_is_claude_client(name: str | None, expected: bool) -> None:
    assert is_claude_client(name) is expected


def test_claude_ui_meta_leaves_other_fields() -> None:
    meta = {"ui": {"domain": "x.idfkit.com", "csp": {"resourceDomains": ["https://unpkg.com"]}}, "other": 1}
    assert claude_ui_meta(meta, "h.claudemcpcontent.com") == {
        "ui": {"domain": "h.claudemcpcontent.com", "csp": {"resourceDomains": ["https://unpkg.com"]}},
        "other": 1,
    }
    assert claude_ui_meta(meta, None) == {"ui": {"csp": {"resourceDomains": ["https://unpkg.com"]}}, "other": 1}


async def test_other_hosts_keep_the_idfkit_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PUBLIC_URL_ENV, HOSTED_URL)
    served = await _ui_meta("openai-mcp")
    assert {uri: ui["domain"] for uri, ui in served.items()} == UI_DOMAINS


async def test_claude_gets_the_hashed_domain_when_public_url_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PUBLIC_URL_ENV, HOSTED_URL)
    served = await _ui_meta("claude-ai")
    assert {ui["domain"] for ui in served.values()} == {"f6a37022b2915e52f1fd1c707a0baa64.claudemcpcontent.com"}
    assert all("csp" in ui for ui in served.values())


async def test_claude_gets_no_domain_without_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PUBLIC_URL_ENV, raising=False)
    served = await _ui_meta("claude-ai")
    assert all("domain" not in ui for ui in served.values())
    # The served metadata is rewritten per read; the registered resources keep their domain.
    assert {uri: ui["domain"] for uri, ui in (await _ui_meta("openai-mcp")).items()} == UI_DOMAINS
