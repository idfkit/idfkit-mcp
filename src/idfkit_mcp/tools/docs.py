"""Documentation tools — URLs, search, and full-text retrieval for EnergyPlus docs."""

from __future__ import annotations

import dataclasses
import logging
import re
from html.parser import HTMLParser
from typing import Annotated

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from idfkit_mcp.app import mcp
from idfkit_mcp.models import DocSearchHit, GetDocSectionResult, LookupDocumentationResult, SearchDocsResult
from idfkit_mcp.state import DOCS_BASE_URL, get_state

logger = logging.getLogger(__name__)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

_MAX_SEARCH_TEXT = 150


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
# Pre-computed search index (module-level cache, survives session resets)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _PrecomputedIndex:
    """Pre-computed token sets and stripped texts for fast searching."""

    version: str
    title_tokens: list[frozenset[str]]
    text_tokens: list[frozenset[str]]
    stripped_texts: list[str]


# Module-level cache — keyed by version string, survives session resets.
_index_cache: dict[str, _PrecomputedIndex] = {}


def _get_precomputed(items: list[dict[str, object]], separator: str, version: str) -> _PrecomputedIndex:
    """Return pre-computed index, building it on first call per version."""
    cached = _index_cache.get(version)
    if cached is not None:
        return cached

    compiled = re.compile(separator)
    title_tokens: list[frozenset[str]] = []
    text_tokens: list[frozenset[str]] = []
    stripped_texts: list[str] = []

    for item in items:
        title = str(item.get("title", "")).lower()
        title_tokens.append(frozenset(t for t in compiled.split(title) if t))

        raw_text = str(item.get("text", ""))
        stripped = _strip_html(raw_text)
        stripped_texts.append(stripped)
        text_tokens.append(frozenset(t for t in compiled.split(stripped.lower()) if t))

    pc = _PrecomputedIndex(
        version=version,
        title_tokens=title_tokens,
        text_tokens=text_tokens,
        stripped_texts=stripped_texts,
    )
    _index_cache[version] = pc
    return pc


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


def _rank_items(
    items: list[dict[str, object]],
    query_tokens: list[str],
    pc: _PrecomputedIndex,
    tags: str | None,
) -> list[tuple[float, int]]:
    """Score and rank all items against query tokens, returning (score, index) pairs."""
    n = len(query_tokens)
    scored: list[tuple[float, int]] = []
    for i, item in enumerate(items):
        if tags:
            item_tags: list[str] = item.get("tags", [])  # type: ignore[assignment]
            if tags not in item_tags:
                continue

        score = 0.0
        for token in query_tokens:
            if token in pc.title_tokens[i]:
                score += 3.0
            if token in pc.text_tokens[i]:
                score += 1.0
        score /= n

        if score > 0:
            scored.append((score, i))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _build_hits(
    scored: list[tuple[float, int]],
    items: list[dict[str, object]],
    pc: _PrecomputedIndex,
    docs_version: str,
) -> list[DocSearchHit]:
    """Convert scored (score, index) pairs into DocSearchHit results."""
    results: list[DocSearchHit] = []
    for score, idx in scored:
        item = items[idx]
        text = pc.stripped_texts[idx]
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
    return results


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def build_documentation_urls(object_type: str, version: str | None = None) -> LookupDocumentationResult:
    """Build documentation URLs for an object type."""
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


@mcp.tool(annotations=_READ_ONLY)
def search_docs(
    query: Annotated[str, Field(description='Search query (e.g. "zone heat balance").')],
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y".')] = None,
    tags: Annotated[str | None, Field(description='Filter by doc set (e.g. "Input Output Reference").')] = None,
    limit: Annotated[int, Field(description="Maximum results.")] = 5,
) -> SearchDocsResult:
    """Search EnergyPlus docs by keyword."""
    state = get_state()
    items, separator, docs_version = state.get_or_load_docs_index(version)

    limit = min(limit, 10)

    if not query.strip():
        return SearchDocsResult(query=query, version=docs_version, count=0, results=[])

    query_tokens = _tokenize(query, separator)
    if not query_tokens:
        return SearchDocsResult(query=query, version=docs_version, count=0, results=[])

    pc = _get_precomputed(items, separator, docs_version)
    scored = _rank_items(items, query_tokens, pc, tags)
    results = _build_hits(scored[:limit], items, pc, docs_version)

    logger.debug("search_docs: query=%r version=%s matched=%d", query, docs_version, len(results))
    return SearchDocsResult(
        query=query,
        version=docs_version,
        count=len(results),
        results=results,
    )


@mcp.tool(annotations=_READ_ONLY)
def get_doc_section(
    location: Annotated[str, Field(description="Section location key from search_docs results.")],
    version: Annotated[str | None, Field(description='EnergyPlus version as "X.Y".')] = None,
    max_length: Annotated[int, Field(description="Maximum characters of text to return.")] = 8000,
) -> GetDocSectionResult:
    """Read full content of a doc section from search_docs results."""
    state = get_state()
    items, separator, docs_version = state.get_or_load_docs_index(version)

    pc = _get_precomputed(items, separator, docs_version)

    logger.debug("get_doc_section: location=%r version=%s", location, version)
    for i, item in enumerate(items):
        if item.get("location") == location:
            text = pc.stripped_texts[i]
            truncated = len(text) > max_length
            if truncated:
                text = text[:max_length] + "..."
            return GetDocSectionResult(
                location=str(item.get("location", "")),
                title=str(item.get("title", "")),
                path=item.get("path", []),  # type: ignore[arg-type]
                tags=item.get("tags", []),  # type: ignore[arg-type]
                text=text,
                doc_url=_build_doc_url(docs_version, str(item.get("location", ""))),
                version=docs_version,
                truncated=truncated,
            )

    msg = f"Documentation section not found: '{location}'. Use search_docs to find valid locations."
    raise ToolError(msg)
