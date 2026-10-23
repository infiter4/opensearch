"""local [n] -> global [n]. Pure. No model. Unit-tested before anything depends on it.

Ordering rule, and it is not optional: RENUMBER *THEN* SEGMENT. [1] -> [12] changes string length,
so any offset computed before renumbering is wrong afterwards — and a wrong offset binds a citation
chip to the wrong sentence, silently. Same after every rewrite iteration.
"""
from __future__ import annotations

import re

MARKER = re.compile(r"\[(\d{1,3})\]")

# Code is not prose. `results[0]` and a fenced `first = results[1]` are subscripts, not citations —
# treated as markers, the [0] was deleted as an "invented citation", the [1] was renumbered into
# `results[12]`, and the code block became a claim checked against two unrelated sources. Every
# marker scan in the pipeline skips these spans.
_CODE = re.compile(r"```.*?```|`[^`\n]+`", re.S)

# A grouped or ranged citation: "[1, 2]", "[2-4]". MARKER never matched these, so they slipped past
# renumbering with their LOCAL numbers intact (naming some other agent's sources once merged) and
# the sentence carried no citation the verifier could see. They are expanded to "[1][2]" first.
_GROUP = re.compile(r"\[(\d{1,3}(?:\s*[,\-–—]\s*\d{1,3})+)\]")
_MAX_RANGE = 10


def _code_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _CODE.finditer(text)]


def _outside_code(text: str, fn) -> str:
    """Apply `fn` to every stretch of `text` that is not code; code spans stay byte-identical."""
    out: list[str] = []
    pos = 0
    for a, b in _code_spans(text):
        out += [fn(text[pos:a]), text[a:b]]
        pos = b
    out.append(fn(text[pos:]))
    return "".join(out)


def _expand(prose: str) -> str:
    def sub(m: re.Match) -> str:
        nums: list[int] = []
        for part in m.group(1).split(","):
            lo, _, hi = re.sub(r"[–—]", "-", part).partition("-")
            a, b = int(lo), int(hi or lo)
            # Local numbers start at 1 and runs are short. "[0, 1]" or "[1-50]" is an interval in
            # prose, not a citation, and is left exactly as written.
            if a < 1 or b < a or b - a > _MAX_RANGE:
                return m.group()
            nums += range(a, b + 1)
        return "".join(f"[{n}]" for n in nums)

    return _GROUP.sub(sub, prose)


def marker_spans(text: str) -> list[re.Match]:
    """Every [n] in `text` that is a citation — i.e. not inside code."""
    code = _code_spans(text)
    return [m for m in MARKER.finditer(text) if not any(a <= m.start() < b for a, b in code)]


def strip(text: str) -> str:
    """Remove every citation marker (and the space before it), leaving code alone."""
    return _outside_code(text, lambda p: re.sub(r"[ \t]*" + MARKER.pattern, "", _expand(p)))


def to_global(text: str, agent_id: str, reg) -> tuple[str, list[int]]:
    """Rewrite [local] -> [global] for one agent's draft.

    A marker with no mapping is DROPPED — never guessed, never remapped to a neighbour. Guessing
    would produce a confident citation to a source the agent never read, which is the exact
    failure mode this product exists to catch. Orphans are returned so the UI can say so out loud.
    """
    orphans: list[int] = []

    def sub(m: re.Match) -> str:
        local = int(m.group(1))
        gid = reg.to_global(agent_id, local)
        if gid is None:
            orphans.append(local)
            return ""
        return f"[{gid}]"

    return _outside_code(text, lambda p: MARKER.sub(sub, _expand(p))), orphans


def markers(text: str) -> list[int]:
    return [int(m.group(1)) for m in marker_spans(_outside_code(text, _expand))]


def validate(text: str, allowed: set[int]) -> tuple[str, list[int]]:
    """Drop any marker not in `allowed`. Used on the LEAD's output: it is instructed never to
    change a number, and that instruction is not trusted."""
    orphans: list[int] = []

    def sub(m: re.Match) -> str:
        n = int(m.group(1))
        if n not in allowed:
            orphans.append(n)
            return ""
        return f"[{n}]"

    return _outside_code(text, lambda p: MARKER.sub(sub, _expand(p))), orphans


def expand(text: str) -> str:
    """Grouped/ranged markers -> one [n] each, outside code. For text that skips to_global and
    validate (the rewriter's output) but must still be read the same way."""
    return _outside_code(text, _expand)
