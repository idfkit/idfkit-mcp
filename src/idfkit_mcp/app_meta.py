"""Resource metadata for the MCP Apps this server ships (the viewers and the file manager).

``_meta.ui.domain`` is host-specific, and two hosts disagree on it:

- ChatGPT requires a domain on a published app ("Widget domain is not set") and accepts an
  origin under ``idfkit.com``.
- claude.ai accepts only the first 32 hex characters of the SHA-256 of the server's public MCP
  URL followed by ``.claudemcpcontent.com``, and does not render an app that declares any
  other domain.

Each resource therefore declares its ``idfkit.com`` domain, and ``ClaudeAppDomainMiddleware``
rewrites it on ``resources/read`` for a session whose client identifies itself as Claude: to
the hashed domain when ``IDFKIT_MCP_PUBLIC_URL`` is set (the hosted server sets
``https://server.idfkit.com/mcp``), and to no domain otherwise, so the host assigns one.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import mcp.types as mt
from fastmcp.apps import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources.base import ResourceResult
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

PUBLIC_URL_ENV = "IDFKIT_MCP_PUBLIC_URL"
CLAUDE_DOMAIN_SUFFIX = ".claudemcpcontent.com"
UI_SCHEME = "ui://"


def claude_app_domain(public_url: str) -> str:
    """Return the app domain claude.ai expects for a server reachable at ``public_url``."""
    digest = hashlib.sha256(public_url.encode("utf-8")).hexdigest()
    return f"{digest[:32]}{CLAUDE_DOMAIN_SUFFIX}"


def configured_claude_domain() -> str | None:
    """Return the claude.ai app domain for ``IDFKIT_MCP_PUBLIC_URL``, or ``None`` when it is unset."""
    public_url = os.environ.get(PUBLIC_URL_ENV, "").strip()
    return claude_app_domain(public_url) if public_url else None


def default_app_domain(subdomain: str) -> str:
    """Return the domain an app declares to hosts other than Claude."""
    return f"{subdomain}.idfkit.com"


def app_resource_meta(*, resource_domains: list[str], subdomain: str) -> dict[str, Any]:
    """Return ``_meta`` for a viewer resource that loads scripts from ``resource_domains``."""
    config = AppConfig(
        csp=ResourceCSP(resourceDomains=resource_domains),
        domain=default_app_domain(subdomain),
        prefersBorder=False,
    )
    return {"ui": app_config_to_meta_dict(config)}


def is_claude_client(client_name: str | None) -> bool:
    """Return whether an ``initialize`` ``clientInfo.name`` identifies a Claude host."""
    return client_name is not None and "claude" in client_name.lower()


def claude_ui_meta(meta: dict[str, Any] | None, claude_domain: str | None) -> dict[str, Any] | None:
    """Return ``meta`` with ``ui.domain`` replaced by ``claude_domain``, or removed when it is ``None``."""
    if not meta or not isinstance(meta.get("ui"), dict) or "domain" not in meta["ui"]:
        return meta
    ui = {k: v for k, v in meta["ui"].items() if k != "domain"}
    if claude_domain is not None:
        ui["domain"] = claude_domain
    return {**meta, "ui": ui}


def _client_name(context: MiddlewareContext[Any]) -> str | None:
    ctx = context.fastmcp_context
    if ctx is None:
        return None
    try:
        params = ctx.session.client_params
    except (AttributeError, RuntimeError, ValueError):
        return None
    if params is None:
        return None
    return params.clientInfo.name


class ClaudeAppDomainMiddleware(Middleware):
    """Serve Claude clients the app domain claude.ai accepts (see the module docstring)."""

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        result = await call_next(context)
        if not str(context.message.uri).startswith(UI_SCHEME) or not is_claude_client(_client_name(context)):
            return result
        domain = configured_claude_domain()
        contents = [c.model_copy(update={"meta": claude_ui_meta(c.meta, domain)}) for c in result.contents]
        return result.model_copy(update={"contents": contents})
