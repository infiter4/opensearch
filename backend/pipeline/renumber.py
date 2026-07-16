"""local [n] -> global [n]. Pure. No model. Unit-tested before anything depends on it.

Ordering rule, and it is not optional: RENUMBER *THEN* SEGMENT. [1] -> [12] changes string length,
so any offset computed before renumbering is wrong afterwards — and a wrong offset binds a citation
chip to the wrong sentence, silently. Same after every rewrite iteration.
"""
from __future__ import annotations

import re

MARKER = re.compile(r"\[(\d{1,3})\]")


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

    return MARKER.sub(sub, text), orphans


def markers(text: str) -> list[int]:
    return [int(m.group(1)) for m in MARKER.finditer(text)]


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

    return MARKER.sub(sub, text), orphans
