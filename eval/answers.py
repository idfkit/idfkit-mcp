"""Comparing an agent's free-text answer with a question's answer key.

The normalisation is lenient about form and strict about content:

- **Text.** Case-folded; backticks, asterisks, quotes and curly quotes removed; whitespace collapsed. Underscores,
  hyphens and colons are kept, because EnergyPlus names use them.
- **Names.** A name counts as mentioned when it appears with no letter or digit directly before or after it (so
  ``SPACE1-1`` is not found inside ``SPACE1-10``); spaces inside a name match any run of whitespace. A mention lying
  inside the mention of a longer candidate (``Water Loop`` inside ``Hot Water Loop``) is not counted.
- **One name** (``single_name_matches``): the key is mentioned and no other candidate is, so listing every loop in
  the model is not a correct answer.
- **A set of names** (``name_set_matches``): exactly the key's names are mentioned among the candidates. An empty
  key matches an answer that mentions no candidate and says "none" or "no zone".
- **Numbers** (``first_number``): the first number in the answer after the candidate names are removed (so a
  digit inside a loop or zone name is never read as the answer). Thousands separators are accepted
  (``27,012``); the words "zero" to "twenty" count as numbers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_STRIP = str.maketrans(dict.fromkeys("`*\"'\u2018\u2019\u201c\u201d", " "))
_NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")
_WORDS = {
    w: float(i)
    for i, w in enumerate([
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
    ])
}
_NONE = re.compile(r"\b(none|no zones?|nothing|no such)\b")

KEY_SEPARATOR = "; "
"""How a set-valued key joins its names (sorted, case-folded order)."""


def normalise(answer: str) -> str:
    return " ".join(answer.translate(_STRIP).casefold().split())


def _pattern(name: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in normalise(name).split()]
    return re.compile(r"(?<![0-9a-z])" + r"\s+".join(words) + r"(?![0-9a-z])")


def _spans(text: str, names: Iterable[str]) -> dict[str, list[tuple[int, int]]]:
    found: dict[str, list[tuple[int, int]]] = {}
    for name in names:
        if not normalise(name):
            continue
        spans = [m.span() for m in _pattern(name).finditer(text)]
        if spans:
            found[name] = spans
    return found


def mentioned(answer: str, candidates: Iterable[str]) -> set[str]:
    """The candidates the answer mentions, ignoring mentions nested inside a longer candidate's mention."""
    text = normalise(answer)
    spans = _spans(text, set(candidates))
    every = [(span, name) for name, name_spans in spans.items() for span in name_spans]
    result: set[str] = set()
    for (start, end), name in every:
        nested = any((s <= start and end <= e) and (e - s) > (end - start) for (s, e), other in every if other != name)
        if not nested:
            result.add(name)
    return result


def single_name_matches(answer: str, key: str, candidates: Iterable[str]) -> bool:
    """The answer names ``key`` and no other candidate (names compared case-insensitively)."""
    pool = {c.casefold(): c for c in [*candidates, key]}
    hits = {m.casefold() for m in mentioned(answer, pool.values())}
    return hits == {key.casefold()}


def name_set_matches(answer: str, key: Iterable[str], candidates: Iterable[str]) -> bool:
    """The candidates the answer mentions are exactly ``key``; an empty key needs an explicit "none"."""
    wanted = {k.casefold() for k in key}
    pool = {c.casefold(): c for c in [*candidates, *key]}
    hits = {m.casefold() for m in mentioned(answer, pool.values())}
    if not wanted:
        return not hits and bool(_NONE.search(normalise(answer)))
    return hits == wanted


def first_number(answer: str, *, ignore: Iterable[str] = ()) -> float | None:
    """The first number in the answer once the names in ``ignore`` are blanked out."""
    text = normalise(answer)
    for name in sorted({n for n in ignore if normalise(n)}, key=len, reverse=True):
        text = _pattern(name).sub(" ", text)
    candidates: list[tuple[int, float]] = []
    match = _NUMBER.search(text)
    if match:
        candidates.append((match.start(), float(match.group(0).replace(",", ""))))
    for word, value in _WORDS.items():
        word_match = re.search(rf"\b{word}\b", text)
        if word_match:
            candidates.append((word_match.start(), value))
    if not candidates:
        return None
    return min(candidates)[1]


def split_key(key: str) -> list[str]:
    return [part for part in (p.strip() for p in key.split(KEY_SEPARATOR.strip())) if part]


def join_key(names: Iterable[str]) -> str:
    return KEY_SEPARATOR.join(sorted(names, key=str.casefold))
