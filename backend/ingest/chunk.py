"""Doc -> Chunk[] with exact char offsets and a human locator.

Offsets matter: they are what lets the citation drawer highlight the supporting quote inside the
original document, exactly like the web path. Chunk sizing is the load-bearing risk (see plan): too
big dilutes retrieval and bloats the verifier's search; too small splits a claim's evidence across
chunks so the verifier can't find its quote. ~1600 chars (~400 tok) prose with overlap keeps a
claim's evidence contiguous.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from .loaders import Doc

PROSE_TARGET = 1600
PROSE_OVERLAP = 200
CODE_TARGET = 2000


@dataclass
class Chunk:
    ordinal: int
    body: str
    locator: str | None
    char_start: int
    char_end: int
    token_count: int


def chunk_doc(doc: Doc) -> list[Chunk]:
    if doc.modality == "code":
        spans = _line_windows(doc.text, CODE_TARGET)
        locate = lambda s, e: _line_locator(doc.text, s, e)
    else:
        spans = _prose_windows(doc.text, PROSE_TARGET, PROSE_OVERLAP)
        page_bounds = doc.meta.get("page_bounds") if doc.modality == "pdf" else None
        locate = (lambda s, e: _page_locator(page_bounds, s)) if page_bounds else (lambda s, e: None)

    chunks: list[Chunk] = []
    for i, (s, e) in enumerate(spans):
        body = doc.text[s:e].strip()
        if not body:
            continue
        chunks.append(Chunk(
            ordinal=len(chunks), body=body, locator=locate(s, e),
            char_start=s, char_end=e, token_count=max(1, len(body) // 4),
        ))
    return chunks


def _prose_windows(text: str, target: int, overlap: int) -> list[tuple[int, int]]:
    """Greedy character windows that break on a nearby sentence/paragraph boundary and overlap so a
    claim spanning a boundary still lands whole in at least one chunk."""
    n = len(text)
    if n <= target:
        return [(0, n)] if n else []
    spans: list[tuple[int, int]] = []
    start = 0
    while start < n:
        end = min(start + target, n)
        if end < n:
            end = _back_to_boundary(text, start + int(target * 0.6), end)
        spans.append((start, end))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return spans


def _back_to_boundary(text: str, lo: int, hi: int) -> int:
    """Prefer a paragraph break, then a sentence end, then a newline/space, within [lo, hi]."""
    para = text.rfind("\n\n", lo, hi)
    if para != -1:
        return para + 2
    for sep in (". ", ".\n", "! ", "? ", "\n"):
        p = text.rfind(sep, lo, hi)
        if p != -1:
            return p + len(sep)
    sp = text.rfind(" ", lo, hi)
    return sp + 1 if sp != -1 else hi


def _line_windows(text: str, target: int) -> list[tuple[int, int]]:
    """Chunk code on line boundaries so a chunk is always whole lines (clean 'lines A-B' locators)."""
    n = len(text)
    if n <= target:
        return [(0, n)] if n else []
    line_starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]
    spans: list[tuple[int, int]] = []
    start = 0
    while start < n:
        target_end = min(start + target, n)
        # snap end up to the end of the line containing target_end
        j = bisect.bisect_right(line_starts, target_end)
        end = line_starts[j] if j < len(line_starts) else n
        end = min(end, n)
        if end <= start:
            end = n
        spans.append((start, end))
        start = end
    return spans


def _line_locator(text: str, s: int, e: int) -> str:
    a = text.count("\n", 0, s) + 1
    b = text.count("\n", 0, max(s, e - 1)) + 1
    return f"lines {a}-{b}" if b > a else f"line {a}"


def _page_locator(page_bounds: list[int], s: int) -> str:
    p = bisect.bisect_right(page_bounds, s) + 1
    return f"p.{min(p, len(page_bounds))}"
