"""Agent-readable reference docs shipped inside the idfkit wheel.

The idfkit package bundles topic-focused reference documents at
``idfkit/.agents/skills/developing-with-idfkit/``. This module exposes them
as MCP resources at ``idfkit://references/`` (index) and
``idfkit://references/{topic}`` (raw markdown).
"""

from __future__ import annotations

import dataclasses
import logging
import re
from functools import cache
from importlib.resources import files
from typing import Any

_VALID_TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]*$")

logger = logging.getLogger(__name__)

_SKILL_PATH = (".agents", "skills", "developing-with-idfkit")
_REFERENCES_SUBDIR = "references"


@dataclasses.dataclass(frozen=True)
class ReferenceEntry:
    """A single agent reference document."""

    slug: str
    title: str
    description: str
    path: str


def _skill_root() -> Any | None:
    """Locate the developing-with-idfkit skill root inside the installed idfkit package.

    Returns ``None`` when the installed idfkit doesn't bundle the references
    (e.g. an older release). Callers must handle that case gracefully.

    Returns ``importlib.resources.abc.Traversable`` at runtime; typed as
    ``Any`` to keep `importlib.resources.files()` callable across Python
    versions without pinning a particular Traversable protocol.
    """
    root = files("idfkit")
    for segment in _SKILL_PATH:
        root = root / segment
    if not root.is_dir():
        return None
    return root


def _parse_metadata(markdown: str) -> tuple[str, str]:
    """Extract (title, description) from the H1 and first prose paragraph."""
    title = ""
    description = ""
    paragraph: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        if not title:
            continue
        if line.startswith("#"):
            if paragraph:
                break
            continue
        if line:
            paragraph.append(line)
        elif paragraph:
            break
    if paragraph:
        description = " ".join(paragraph).strip()
    return title, description


@cache
def list_references() -> tuple[ReferenceEntry, ...]:
    """Return every reference shipped by the installed idfkit, sorted by slug.

    Returns an empty tuple when the installed idfkit doesn't bundle the
    references directory. Result is cached because the on-disk layout
    cannot change during the server's lifetime.
    """
    root = _skill_root()
    if root is None:
        logger.debug("idfkit does not bundle agent references (skill root missing)")
        return ()

    refs_dir = root / _REFERENCES_SUBDIR
    if not refs_dir.is_dir():
        return ()

    entries: list[ReferenceEntry] = []
    for child in refs_dir.iterdir():
        if not child.is_file() or not child.name.endswith(".md"):
            continue
        slug = child.name[:-3]
        text = child.read_text(encoding="utf-8")
        title, description = _parse_metadata(text)
        entries.append(
            ReferenceEntry(
                slug=slug,
                title=title or slug,
                description=description,
                path=str(child),
            )
        )
    entries.sort(key=lambda e: e.slug)
    return tuple(entries)


def get_reference_markdown(topic: str) -> str:
    """Return the raw markdown for ``topic``.

    Raises ``ValueError`` if the topic is unknown or the references aren't
    shipped by the installed idfkit.
    """
    if not _VALID_TOPIC.fullmatch(topic):
        msg = f"Invalid reference topic '{topic}'."
        raise ValueError(msg)

    root = _skill_root()
    if root is None:
        msg = (
            "The installed idfkit does not bundle agent references. "
            "Upgrade idfkit to a version that ships .agents/skills/developing-with-idfkit/."
        )
        raise ValueError(msg)

    refs_dir = root / _REFERENCES_SUBDIR
    target = refs_dir / f"{topic}.md"
    if not target.is_file():
        available = ", ".join(e.slug for e in list_references())
        msg = f"Reference '{topic}' not found. Available: {available}"
        raise ValueError(msg)
    return target.read_text(encoding="utf-8")


def build_reference_index() -> dict[str, object]:
    """Build the JSON payload for ``idfkit://references/``."""
    entries = list_references()
    skill_md: str | None = None
    root = _skill_root()
    if root is not None:
        skill_file = root / "SKILL.md"
        if skill_file.is_file():
            skill_md = skill_file.read_text(encoding="utf-8")

    return {
        "topics": [
            {
                "slug": entry.slug,
                "title": entry.title,
                "description": entry.description,
                "uri": f"idfkit://references/{entry.slug}",
            }
            for entry in entries
        ],
        "count": len(entries),
        "skill_md": skill_md,
    }
