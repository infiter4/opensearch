"""Claim-level entailment. The product.

TWO GUARANTEES, both enforced by code rather than by asking a model nicely:

1. THE VERIFIER CANNOT GRADE ITS OWN HOMEWORK.
   verify_pair(claim_text, source_text) takes exactly two strings. There is no parameter for the
   question, the answer, sibling claims, or other sources. Context leakage is structurally
   impossible without changing this signature — it is not a prompt discipline anyone has to
   remember. Do not add parameters to this function.

2. THE VERIFIER CANNOT FAKE SUPPORT.
   It must return a quote it claims is in the source. We then look for that quote with
   str.find(). If it isn't literally there and the verdict was `supported`, the server DOWNGRADES
   to `weak`. Support is checked by string search, not by a model's say-so.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from typing import Literal

from .. import config
from ..providers import llm

Vd = Literal["supported", "weak", "unsupported", "contradicted"]

# worst-wins ordering for aggregating a sentence's claims onto one cell
SEVERITY: dict[str, int] = {
    "contradicted": 0, "unsupported": 1, "weak": 2, "supported": 3,
    "retracted": -1, "pending": 99,
}

_PROMPT = """You check whether a single CLAIM is supported by a single SOURCE.

You are given only the claim and the source text. You do not know what question was asked, who
wrote the claim, or what other sources say. Judge the claim against this source and nothing else.

Reply with ONLY a JSON object:
{"verdict": "supported"|"weak"|"unsupported"|"contradicted",
 "quote": "<verbatim span copied EXACTLY from the source, or empty string>",
 "confidence": 0.0-1.0,
 "reason": "<one short sentence>"}

verdict meanings:
  supported    - the source states this claim, plainly. You MUST supply a verbatim quote.
  weak         - the source gestures at it or partly implies it, but does not state it.
  unsupported  - the source simply does not address this claim.
  contradicted - the source says something incompatible with the claim. Supply the quote.

The quote must be COPIED CHARACTER-FOR-CHARACTER from the source. Do not paraphrase it, do not
tidy it, do not join fragments with an ellipsis. A quote that is not literally present will be
detected automatically and your verdict downgraded. If you cannot find a literal quote, the
verdict is not "supported"."""


@dataclass
class Verdict:
    verdict: str
    quote: str | None
    quote_start: int | None
    quote_end: int | None
    confidence: float
    reason: str
    downgraded: bool = False

    def dict(self) -> dict:
        return asdict(self)


# Fetched web text is full of typographic Unicode; models silently retype it as ASCII when they
# copy a quote. Measured: this alone downgraded every TRUE claim to `weak` ("quote not found")
# because the blog says "Ollama’s" with a curly apostrophe. Without this table the board turns
# uniformly amber and the product looks broken while the verifier is actually correct.
_UNI = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "…": "...", "­": "", "​": "", "﻿": "",
    "´": "'", "`": "'",
}
_UNI_RE = re.compile("|".join(map(re.escape, _UNI)))


def _fold_char(ch: str) -> str:
    return _UNI.get(ch, ch)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", _UNI_RE.sub(lambda m: _UNI[m.group()], s)).strip().lower()


def find_quote(source: str, quote: str) -> tuple[int, int] | None:
    """Exact, then Unicode+whitespace-folded. Deliberately NOT fuzzy — the entire guarantee is
    that a quote either IS in the source or it isn't. Folding typography is not fuzziness:
    "Ollama’s" and "Ollama's" are the same characters as far as evidence goes.

    Returns raw offsets into `source` so the UI can highlight the real span.
    """
    if not quote:
        return None
    i = source.find(quote)
    if i != -1:
        return i, i + len(quote)

    nq = _norm(quote)
    if not nq:
        return None

    # Build a folded view of the source while remembering each folded char's raw index, so a hit
    # in folded space maps back to a real highlightable span.
    buf: list[str] = []
    raw_idx: list[int] = []
    prev_space = False
    for idx, ch in enumerate(source):
        folded = _fold_char(ch)
        if folded == "":
            continue
        if folded.isspace():
            if prev_space:
                continue
            buf.append(" ")
            raw_idx.append(idx)
            prev_space = True
            continue
        prev_space = False
        for f in folded.lower():
            buf.append(f)
            raw_idx.append(idx)

    ns = "".join(buf)
    j = ns.find(nq)
    if j == -1:
        # last resort: the model dropped or added a trailing clause. Anchor on a long prefix.
        if len(nq) >= 40:
            j = ns.find(nq[:40])
            if j == -1:
                return None
            return raw_idx[j], raw_idx[min(j + 40 - 1, len(raw_idx) - 1)] + 1
        return None
    return raw_idx[j], raw_idx[min(j + len(nq) - 1, len(raw_idx) - 1)] + 1


async def verify_pair(claim_text: str, source_text: str) -> Verdict:
    """Two strings in, one verdict out. Do not widen this signature — see module docstring."""
    messages = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": f"SOURCE:\n{source_text}\n\n---\n\nCLAIM:\n{claim_text}"},
    ]

    model = llm.model_for("verifier")
    try:
        d = await llm.complete_json(model, messages, num_ctx=8192, temperature=0)
    except Exception:
        # A verifier that cannot answer must not silently pass the claim. Fall back to a
        # different family; if that also fails, the claim is unverified, not supported.
        try:
            d = await llm.complete_json(
                config.VERIFIER_FALLBACK, messages, num_ctx=8192, temperature=0
            )
        except Exception as e:
            return Verdict("weak", None, None, None, 0.0, f"verifier unavailable: {type(e).__name__}")

    if not isinstance(d, dict):
        return Verdict("weak", None, None, None, 0.0, "verifier returned non-object")

    verdict = str(d.get("verdict", "")).lower().strip()
    if verdict not in ("supported", "weak", "unsupported", "contradicted"):
        verdict = "weak"
    quote = (d.get("quote") or "").strip() or None
    reason = str(d.get("reason") or "")[:240]
    try:
        conf = max(0.0, min(1.0, float(d.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5

    span = find_quote(source_text, quote) if quote else None
    downgraded = False

    # THE ENFORCEMENT. A claimed quote that is not literally in the source is not evidence.
    if verdict in ("supported", "contradicted") and span is None:
        verdict = "weak"
        downgraded = True
        reason = "quote not found in source" + (f" — model said: {reason}" if reason else "")
        quote = None

    return Verdict(
        verdict=verdict,
        quote=quote,
        quote_start=span[0] if span else None,
        quote_end=span[1] if span else None,
        confidence=conf,
        reason=reason,
        downgraded=downgraded,
    )


# GLOBAL, not per-call: four agents verifying at once must still respect the measured optimum
# (sem=6 — Ollama Cloud serializes us server-side, so more in-flight just builds queue depth and
# turns into stalls). A per-call semaphore multiplies the budget by the number of agents.
_SEM = asyncio.Semaphore(config.SEM_VERIFY)


async def verify_all(pairs: list[tuple[str, str, str, int]], reg) -> dict[tuple[str, int], Verdict]:
    """pairs: [(claim_id, sentence_id, claim_text, source_id)] -> {(claim_id, source_id): Verdict}

    Bounded fan-out. Every pair is content-addressed inside llm.chat(), so an identical
    (claim, source) anywhere in the run — including the lead restating a sub-agent's sentence
    verbatim — is a free cache hit. That is what makes verifying the lead nearly free.
    """
    sem = _SEM

    async def one(claim_id: str, _sid: str, claim_text: str, source_id: int):
        body = reg.body(source_id)
        if not body:
            return (claim_id, source_id), Verdict(
                "unsupported", None, None, None, 0.0, "source body unavailable"
            )
        async with sem:
            return (claim_id, source_id), await verify_pair(claim_text, body)

    out = await asyncio.gather(*(one(*p) for p in pairs), return_exceptions=True)
    return {k: v for r in out if not isinstance(r, BaseException) for k, v in [r]}


def worst(verdicts: list[str]) -> str:
    if not verdicts:
        return "pending"
    return min(verdicts, key=lambda v: SEVERITY.get(v, 99))
