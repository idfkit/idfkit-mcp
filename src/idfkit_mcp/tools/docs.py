"""Documentation tools — URLs, search, and full-text retrieval for EnergyPlus docs."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from idfkit_mcp.errors import safe_tool
from idfkit_mcp.models import (
    DocSearchHit,
    GetDocSectionResult,
    LookupDocumentationResult,
    SearchDocsResult,
)
from idfkit_mcp.state import DOCS_BASE_URL, get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

_MAX_SEARCH_TEXT = 500


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    """Minimal HTML tag stripper using stdlib."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(html: str) -> str:
    """Remove HTML tags, returning plain text."""
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_version(version: str | None) -> tuple[int, int, int] | None:
    """Parse a 'X.Y.Z' version string into a tuple, or return None."""
    if version is None:
        return None
    parts = version.split(".")
    if len(parts) != 3:
        msg = f"Version must be in 'X.Y.Z' format, got '{version}'"
        raise ValueError(msg)
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _build_doc_url(version: str, location: str) -> str:
    """Build a full docs.idfkit.com URL from version and location."""
    # version is like "25.2", location is like "engineering-reference/zone-heat-balance/"
    return f"{DOCS_BASE_URL}/v{version}/{location}"


def _tokenize(text: str, separator: str) -> list[str]:
    """Tokenize text using the index's separator regex, lowercased."""
    return [t for t in re.split(separator, text.lower()) if t]


def _score_item(item: dict[str, object], query_tokens: list[str], separator: str) -> float:
    """Score an item against query tokens. Title matches 3x, text matches 1x."""
    if not query_tokens:
        return 0.0

    title = str(item.get("title", "")).lower()
    text = _strip_html(str(item.get("text", ""))).lower()

    title_tokens = set(_tokenize(title, separator))
    text_tokens = set(_tokenize(text, separator))

    score = 0.0
    for token in query_tokens:
        if token in title_tokens:
            score += 3.0
        if token in text_tokens:
            score += 1.0

    return score / len(query_tokens)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@safe_tool
def lookup_documentation(object_type: str, version: str | None = None) -> LookupDocumentationResult:
    """Get documentation URLs for an EnergyPlus object type on docs.idfkit.com.

    Returns links to the I/O Reference page, Engineering Reference, and a
    search URL for the object type.

    Args:
        object_type: The object type name (e.g. "Zone", "Material").
        version: EnergyPlus version as "X.Y.Z" (default: latest or loaded model version).
    """
    from idfkit.docs import engineering_reference_url, io_reference_url, search_url
    from idfkit.versions import LATEST_VERSION

    state = get_state()
    ver_tuple = _parse_version(version)
    schema = state.get_or_load_schema(ver_tuple)
    effective_version = ver_tuple or LATEST_VERSION

    io_url = io_reference_url(object_type, effective_version, schema)
    eng_url = engineering_reference_url(effective_version)
    s_url = search_url(object_type, effective_version)

    ver_str = f"{effective_version[0]}.{effective_version[1]}.{effective_version[2]}"
    return LookupDocumentationResult(
        object_type=object_type,
        version=ver_str,
        io_reference_url=io_url.url if io_url else None,
        engineering_reference_url=eng_url.url if eng_url else None,
        search_url=s_url.url if s_url else None,
    )


@safe_tool
def search_docs(
    query: str,
    version: str | None = None,
    tags: str | None = None,
    limit: int = 5,
) -> SearchDocsResult:
    """Search EnergyPlus documentation by keyword.

    Full-text search across the documentation index. Returns ranked results
    with HTML-stripped text truncated to 500 characters. Use get_doc_section
    to read the full content of a specific result.

    Args:
        query: Search query (e.g. "zone heat balance", "material properties").
        version: EnergyPlus version as "X.Y" (default: latest).
        tags: Filter by documentation set (e.g. "Input Output Reference", "Engineering Reference").
        limit: Maximum number of results to return (default: 5).
    """
    state = get_state()
    items, separator, docs_version = state.get_or_load_docs_index(version)

    if not query.strip():
        return SearchDocsResult(query=query, version=docs_version, count=0, results=[])

    query_tokens = _tokenize(query, separator)
    if not query_tokens:
        return SearchDocsResult(query=query, version=docs_version, count=0, results=[])

    scored: list[tuple[float, dict[str, object]]] = []
    for item in items:
        # Filter by tags if specified
        if tags:
            item_tags: list[str] = item.get("tags", [])  # type: ignore[assignment]
            if tags not in item_tags:
                continue

        score = _score_item(item, query_tokens, separator)
        if score > 0:
            scored.append((score, item))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    results: list[DocSearchHit] = []
    for score, item in scored[:limit]:
        text = _strip_html(str(item.get("text", "")))
        if len(text) > _MAX_SEARCH_TEXT:
            text = text[:_MAX_SEARCH_TEXT] + "..."
        results.append(
            DocSearchHit(
                location=str(item.get("location", "")),
                title=str(item.get("title", "")),
                path=item.get("path", []),  # type: ignore[arg-type]
                tags=item.get("tags", []),  # type: ignore[arg-type]
                text=text,
                score=round(score, 4),
                doc_url=_build_doc_url(docs_version, str(item.get("location", ""))),
            )
        )

    logger.debug("search_docs: query=%r version=%s matched=%d", query, docs_version, len(results))
    return SearchDocsResult(
        query=query,
        version=docs_version,
        count=len(results),
        results=results,
    )


@safe_tool
def get_doc_section(location: str, version: str | None = None) -> GetDocSectionResult:
    """Retrieve the full content of a documentation section by location.

    Use after search_docs to read a specific section in depth. The location
    is the path fragment returned in search results (e.g.
    "input-output-reference/zone/#zone").

    Args:
        location: The section location key (from search_docs results).
        version: EnergyPlus version as "X.Y" (default: latest).
    """
    state = get_state()
    items, _separator, docs_version = state.get_or_load_docs_index(version)

    logger.debug("get_doc_section: location=%r version=%s", location, version)
    for item in items:
        if item.get("location") == location:
            return GetDocSectionResult(
                location=str(item.get("location", "")),
                title=str(item.get("title", "")),
                path=item.get("path", []),  # type: ignore[arg-type]
                tags=item.get("tags", []),  # type: ignore[arg-type]
                text=_strip_html(str(item.get("text", ""))),
                doc_url=_build_doc_url(docs_version, str(item.get("location", ""))),
                version=docs_version,
            )

    msg = f"Documentation section not found: '{location}'. Use search_docs to find valid locations."
    raise ToolError(msg)


_TOOL_REGISTRY = [
    (lookup_documentation, _READ_ONLY),
    (search_docs, _READ_ONLY),
    (get_doc_section, _READ_ONLY),
]


def register(mcp: FastMCP) -> None:
    """Register documentation tools on the MCP server."""
    for func, hints in _TOOL_REGISTRY:
        mcp.tool(annotations=hints, structured_output=True)(func)
