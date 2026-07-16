"""Answer -> atomic claims, each tagged with the sentence it came from and the sources it cites.

Claims are the VERIFICATION unit (atomic statements make for clean entailment). Sentences remain
the DISPLAY unit — see heatmap.py. Keeping those separate is what lets a rewritten sentence hold
its row on the board while its claims are regenerated underneath.
"""
from __future__ import annotations

import re

from .. import config
from ..providers import llm
from .segment import Sentence

_PROMPT = """You split cited sentences into atomic factual claims.

You are given numbered sentences, each carrying citation markers like [3].

For each sentence, emit one or more atomic claims. An atomic claim is a single checkable
statement: one subject, one assertion. Split "X caps at 10 and costs nothing" into two claims.

Rewrite each claim to stand alone — resolve pronouns and implied subjects so it can be understood
with no surrounding text. Drop the [n] markers from the claim text itself.

Do NOT invent claims. Do NOT include opinions, hedges, or questions. If a sentence makes no
checkable factual assertion, omit it entirely.

Reply with ONLY a JSON array:
[{"sentence_id": "s3", "text": "<standalone atomic claim>", "source_ids": [3]}]

source_ids MUST be a subset of the markers actually present in that sentence. Never add a source
the sentence did not cite."""


def _payload(sentences: list[Sentence]) -> str:
    return "\n".join(f"[{s.id}] (cites {list(s.cited)}) {s.text}" for s in sentences)


async def extract(agent_id: str, sentences: list[Sentence]) -> list[dict]:
    """sentences: cited candidates only. Returns [{id, sentence_id, text, source_ids}].

    Every returned source_id is validated against the markers actually present in that sentence.
    A model that invents a citation here would silently point a heatmap cell at a source the
    sentence never cited — so hallucinated ids are dropped, not trusted.
    """
    cands = [s for s in sentences if s.cited]
    if not cands:
        return []

    by_id = {s.id: s for s in cands}
    try:
        raw = await llm.complete_json(
            llm.model_for("claims"),
            [{"role": "system", "content": _PROMPT},
             {"role": "user", "content": _payload(cands)}],
            num_ctx=16384,
            temperature=0,
        )
    except Exception:
        raw = []

    if not isinstance(raw, list):
        raw = []

    out: list[dict] = []
    n = 0
    for c in raw:
        if not isinstance(c, dict):
            continue
        sid = str(c.get("sentence_id") or "").strip()
        s = by_id.get(sid)
        text = str(c.get("text") or "").strip()
        if not s or not text:
            continue
        ids = c.get("source_ids") or []
        if not isinstance(ids, list):
            ids = [ids]
        # subset check: never let a claim cite what its sentence didn't
        valid = sorted({int(i) for i in ids if _int(i) and int(i) in s.cited})
        if not valid:
            valid = list(s.cited)  # model dropped them; the sentence's own markers are authoritative
        n += 1
        out.append({
            "id": f"{agent_id}.c{n}",
            "sentence_id": sid,
            "text": re.sub(r"\s*\[\d{1,3}\]", "", text).strip(),
            "source_ids": valid,
        })

    if not out:
        # Extractor failed entirely. Falling back to whole sentences keeps the board populated —
        # coarser claims verify worse, but an empty board looks like the feature is broken.
        for i, s in enumerate(cands, 1):
            out.append({
                "id": f"{agent_id}.c{i}",
                "sentence_id": s.id,
                "text": re.sub(r"\s*\[\d{1,3}\]", "", s.text).strip(),
                "source_ids": list(s.cited),
                "fallback": True,
            })
    return out


def _int(x) -> bool:
    try:
        int(x)
        return True
    except (TypeError, ValueError):
        return False


def pairs(claims: list[dict]) -> list[tuple[str, str, str, int]]:
    """Flatten to (claim_id, sentence_id, claim_text, source_id) — the verifier's work list."""
    return [
        (c["id"], c["sentence_id"], c["text"], sid)
        for c in claims
        for sid in c["source_ids"]
    ]
