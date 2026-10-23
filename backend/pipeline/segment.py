"""Sentence segmentation with exact character offsets. Pure, no model.

Why not ask the model to mark sentences: it pollutes the token stream, models drop markers under
load, and it makes the most important prompt in the build do two jobs. Why not post-hoc string
matching: the claim extractor rewrites claims into standalone form ("Ollama's web_search caps at
ten results") which will never string-match the sentence it came from ("It caps at ten results
[3]"), forcing fuzzy matching onto the demo-critical path.

Segmenting here means offsets are computed from the same bytes the frontend renders, so they are
exact by construction rather than by luck.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .renumber import marker_spans, markers

# Abbreviations whose trailing period is not a sentence end.
_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "eg", "ie", "al",
    "fig", "no", "approx", "inc", "ltd", "co", "corp", "dept", "est", "min", "max",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}

_FENCE = re.compile(r"```.*?```", re.S)
# Group 1 is the punctuation run; group 2 is any [n] markers written AFTER it on the same line.
# Writers do this constantly ("…the core finding. [1][2]", "…queries.[5] Multiple…"). Ending the
# sentence at the period handed its markers to the NEXT sentence — the real claim went unchecked
# and its neighbour was verified against a source it never cited. The markers stay with the
# sentence they follow; same line only, so a reference list under a paragraph is not swallowed.
_BOUNDARY = re.compile(r"([.!?]+[\"')\]]*)((?:[ \t]*\[\d{1,3}\])*)(?=\s|$)")
# Blank line, or a markdown list/heading marker at line start — structural breaks.
_BLOCK = re.compile(r"\n\s*\n|\n(?=\s*(?:[-*+]\s|\d+\.\s|#{1,6}\s|\|))")


@dataclass(frozen=True)
class Sentence:
    id: str
    start: int
    end: int
    text: str
    cited: tuple[int, ...]

    @property
    def is_claim_candidate(self) -> bool:
        return bool(self.cited)


def _cited(text: str) -> tuple[int, ...]:
    return tuple(sorted(set(markers(text))))


def _masked(text: str) -> str:
    """Replace fenced code with same-length filler so offsets stay valid but no boundary is
    ever found inside a code block."""
    out = list(text)
    for m in _FENCE.finditer(text):
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = "\x00"
    return "".join(out)


def _is_real_boundary(masked: str, end: int) -> bool:
    """end = index just past the punctuation run."""
    dot = end - 1
    while dot > 0 and masked[dot] in "\"')]":
        dot -= 1
    if masked[dot] not in ".!?":
        return False

    # decimals / version numbers: 3.14, v1.2
    if masked[dot] == "." and dot > 0 and masked[dot - 1].isdigit():
        nxt = end
        while nxt < len(masked) and masked[nxt] == " ":
            nxt += 1
        if nxt < len(masked) and masked[nxt].isdigit():
            return False

    # abbreviations
    j = dot - 1
    word = ""
    while j >= 0 and (masked[j].isalpha() or masked[j] == "."):
        word = masked[j] + word
        j -= 1
    if word.replace(".", "").lower() in _ABBREV:
        return False

    # single initial: "J. Smith"
    if len(word) == 1 and word.isupper():
        return False

    return True


def segment(text: str, prefix: str = "s") -> list[Sentence]:
    """Split into sentences carrying exact (start, end) offsets into `text`.

    Only sentences containing a [n] marker are claim candidates — uncited prose has nothing to
    verify. That bounds the claim count and ties claims to sources for free.
    """
    if not text:
        return []

    masked = _masked(text)
    bounds: set[int] = set()

    # Markdown structure is a hard boundary regardless of punctuation. Without this, a line
    # ending in ':' followed by a fenced block swallows everything after it into one sentence —
    # merging two unrelated citation contexts into a single heatmap row.
    for m in _BLOCK.finditer(masked):
        bounds.add(m.end())
    for m in _FENCE.finditer(text):
        bounds.add(m.start())
        bounds.add(m.end())

    for m in _BOUNDARY.finditer(masked):
        if "\x00" in masked[m.start() : m.end()]:
            continue
        if _is_real_boundary(masked, m.end(1)):
            bounds.add(m.end())

    bounds.add(len(text))
    bounds = sorted(b for b in bounds if 0 < b <= len(text))  # type: ignore[assignment]

    # Citations are read off the WHOLE text, not each slice: a fence cut in two by a blank line
    # inside it no longer looks like code to the slice holding its tail.
    marks = marker_spans(text)
    out: list[Sentence] = []
    cursor = 0
    n = 0
    for b in bounds:
        raw = text[cursor:b]
        stripped = raw.strip()
        if not stripped:
            cursor = b
            continue
        start = cursor + (len(raw) - len(raw.lstrip()))
        end = start + len(stripped)
        n += 1
        out.append(Sentence(
            id=f"{prefix}{n}",
            start=start,
            end=end,
            text=text[start:end],
            cited=tuple(sorted({int(m.group(1)) for m in marks if start <= m.start() < end})),
        ))
        cursor = b
    return out


def respan(text: str, sentences: list[Sentence], edits: dict[str, str]) -> tuple[str, list[Sentence]]:
    """Apply {sentence_id: replacement} and recompute offsets WITHOUT re-segmenting.

    Never re-segment after a rewrite. segment() assigns ids by POSITION, so deleting a retracted
    sentence silently shifts every later id down by one: the sentence that was s3 becomes s2, and
    every iteration-0 verdict keyed to s2 now describes different prose. The heatmap keys cells on
    (sentence_id, source_id) and SHOW FIRST DRAFT diffs iteration 0 against iteration 1 by
    sentence_id — both would compare unrelated sentences, and the board would look perfect while
    lying. Row identity is established once, at iteration 0, and only ever carried forward.

    An empty replacement retracts: the row keeps its id and survives as a zero-width span, because
    a vanishing row is how you lie with a UI. A replacement holding two sentences stays ONE row —
    rows must not move.
    """
    pieces: list[str] = []
    out: list[Sentence] = []
    pos = 0
    cursor = 0
    drop_gap = False
    run_end = 0          # one past the run of consecutive retracted rows we are inside
    keep_after = False

    def _gone(j: int) -> bool:
        return not edits.get(sentences[j].id, sentences[j].text)

    for i, s in enumerate(sentences):
        gap = text[cursor:s.start]
        cursor = s.end
        if drop_gap:
            gap = ""
            drop_gap = False

        repl = edits.get(s.id, s.text)
        if not repl:
            # A run of retracted rows takes ONE separator with it — normally the one after the
            # run. But when that one is structural (a paragraph break, the newline before a
            # heading or a list item) and the one before is not, the one before goes instead:
            # retracting the last sentence of a paragraph otherwise glued "## What we could not
            # establish" onto the end of the previous line, where it no longer renders as a heading.
            if i >= run_end:
                run_end = i
                while run_end < len(sentences) and _gone(run_end):
                    run_end += 1
                last = sentences[run_end - 1]
                after = text[last.end:sentences[run_end].start] if run_end < len(sentences) \
                    else text[last.end:]
                keep_after = bool(pos) and "\n" in after and "\n" not in gap
                if keep_after:
                    gap = ""
            # separators inside the run always go; the one after it goes unless kept above
            drop_gap = not (keep_after and i == run_end - 1)
            pieces.append(gap)
            pos += len(gap)
            out.append(Sentence(id=s.id, start=pos, end=pos, text="", cited=()))
            continue

        pieces.append(gap)
        pos += len(gap)

        pieces.append(repl)
        out.append(Sentence(id=s.id, start=pos, end=pos + len(repl), text=repl, cited=_cited(repl)))
        pos += len(repl)

    if not drop_gap:
        pieces.append(text[cursor:])
    return "".join(pieces), out


def claim_candidates(sentences: list[Sentence]) -> list[Sentence]:
    return [s for s in sentences if s.is_claim_candidate]


def as_events(sentences: list[Sentence]) -> list[dict]:
    return [
        {"id": s.id, "start": s.start, "end": s.end, "cited": list(s.cited)}
        for s in sentences
    ]
