"""Repair unsupported sentences, or retract them honestly.

THE CAP IS A range(), NOT A SENTENCE IN A PROMPT. jarvis's CODER_PROCEDURE asks the model nicely
to iterate at most N times and nothing counts rounds; the model is free to loop forever. Here the
caller cannot spin: even a model that returns "I'll fix it!" every time gets exactly N shots.

REWRITE IS A STATELESS NARROW CALL, NOT A CONTINUATION. The obvious design hands the sentence back
to the sub-agent with its full history — that replays ~10k tokens, costs a whole agent turn, and
re-exposes the model to the exact context that produced the hallucination. Same inputs, same bug.
Instead the rewriter sees ONLY the failing sentence, the verbatim evidence, and why it failed. The
only text in its window IS the source text, so a grounded rewrite is the path of least resistance.

RETRACT IS THE MECHANISM, NOT THE FALLBACK. A model with no legal way to say "I can't support
this" will invent something — you gave it one job and no exit, so it takes the exit that exists.
Making RETRACT a first-class, explicitly-praised output is what converts a hallucination generator
into an honest one.
"""
from __future__ import annotations

import asyncio
import re

from .. import config
from ..providers import llm
from . import claims as claims_mod
from . import renumber, segment, verify

RETRACT = "RETRACT"
# Decoration a model wraps the token in: "**RETRACT**", "`RETRACT`", "> RETRACT".
_LEAD_NOISE = re.compile(r"^[\W_]+")

# GLOBAL, and small on purpose. Every agent repairs concurrently, so without a shared bound the
# fan-out is (agents × failing sentences) — deep mode fired 29 rewrites at once. The rewriter is
# qwen3.5:397b, which Ollama SERIALIZES server-side: the extra callers do not get parallelism,
# they build a queue. Once that queue is deeper than the per-read stall budget, calls time out,
# retry with backoff, and the retries deepen the queue — a death spiral that wedged 14 of 29
# rewrites. Bounding the fan-out here is what keeps a slow model merely slow.
_SEM = asyncio.Semaphore(config.SEM_REWRITE)

_PROMPT = f"""You repair a single sentence that failed fact-checking.

You are given the sentence, and for each source it cites: what that source actually says, and why
the check failed. You cannot see the original question or the rest of the answer. Judge only what
is in front of you.

Do ONE of these:

1. REWRITE — if the evidence supports a weaker, narrower, or corrected version of the claim, write
   that version. Keep the same [n] citation markers, pointing at the same sources. Only state what
   the evidence in front of you actually says.

2. {RETRACT} — if the evidence does not support any version of this claim, reply with exactly the
   word {RETRACT} and nothing else.

{RETRACT} is a correct, valuable answer. An honest retraction is strictly better than a confident
sentence the sources do not support — that is the entire point of this system. Do not stretch the
evidence to save the sentence.

Reply with ONLY the replacement sentence, or ONLY the word {RETRACT}. No preamble, no explanation,
no quotes around it."""


def _evidence(sentence, cells_for_sentence: list[dict], reg) -> str:
    parts = []
    for c in cells_for_sentence:
        sid = c["source_id"]
        body = reg.body(sid)
        if c.get("quote"):
            says = f'says, verbatim: "{c["quote"]}"'
        else:
            says = f"does not appear to address this. Relevant excerpt:\n{body[:1200]}"
        parts.append(f"SOURCE [{sid}] {says}\nCHECK FAILED BECAUSE: {c.get('reason') or 'not supported'}")
    return "\n\n".join(parts)


async def _rewrite_one(sentence, cells_for_sentence: list[dict], reg) -> str:
    user = (
        f"SENTENCE THAT FAILED:\n{sentence.text}\n\n"
        f"{_evidence(sentence, cells_for_sentence, reg)}"
    )
    try:
        async with _SEM:
            out = await llm.complete(
                llm.model_for("rewriter"),
                [{"role": "system", "content": _PROMPT}, {"role": "user", "content": user}],
                num_ctx=8192,
                temperature=0,
            )
    except Exception:
        return RETRACT  # a rewriter that cannot answer must not leave the bad sentence standing
    out = (out or "").strip().strip('"').strip()
    if not out or _LEAD_NOISE.sub("", out).upper().startswith(RETRACT):
        return RETRACT
    out = renumber.expand(out.split("\n")[0].strip())
    # A "repair" that no longer cites any of the sentence's own sources is not a repair. With no
    # [n] it stops being a claim candidate, so it is never verified, its row leaves the board, and
    # it is not counted as retracted either — a failure laundered into unchecked prose. Retract.
    if not set(renumber.markers(out)) & set(sentence.cited):
        return RETRACT
    return out


def _failing(cells_: list[dict]) -> dict[str, list[dict]]:
    bad: dict[str, list[dict]] = {}
    for c in cells_:
        if c["verdict"] in ("unsupported", "contradicted"):
            bad.setdefault(c["sentence_id"], []).append(c)
    return bad


async def repair(
    agent_id: str,
    text: str,
    reg,
    cells_: list[dict],
    max_iters: int,
    emit,
) -> tuple[str, list[dict], list[dict], list[dict]]:
    """Returns (text, sentences, claims, retracted).

    Re-segments after every splice because the replacement changes string length — offsets from
    before the splice are wrong after it, and a wrong offset binds a chip to the wrong sentence.
    """
    iters = min(max_iters, config.MAX_REWRITE_ITERS)
    sents = segment.segment(text, prefix=f"{agent_id}.s")
    cl: list[dict] = []
    retracted: list[dict] = []

    for iteration in range(1, iters + 1):
        bad = _failing(cells_)
        if not bad:
            break

        by_id = {s.id: s for s in sents}
        targets = [(by_id[sid], cs) for sid, cs in bad.items() if by_id.get(sid) and by_id[sid].text]
        if not targets:
            break

        for s, cs in targets:
            emit("rewrite_start", {
                "agent_id": agent_id, "sentence_id": s.id, "iteration": iteration,
                "failing_claims": [c["claim_ids"][0] for c in cs if c.get("claim_ids")],
                "reason": cs[0].get("reason", ""),
            })

        results = await asyncio.gather(*(_rewrite_one(s, cs, reg) for s, cs in targets))

        edits: dict[str, str] = {}
        for (s, cs), new in zip(targets, results):
            if new == RETRACT:
                edits[s.id] = ""
                retracted.append({
                    "sentence_id": s.id, "text": s.text,
                    "reason": cs[0].get("reason", "not supported by the cited source"),
                })
                emit("rewrite_done", {
                    "agent_id": agent_id, "sentence_id": s.id, "iteration": iteration,
                    "text": "", "outcome": "retracted",
                })
            else:
                edits[s.id] = new
                emit("rewrite_done", {
                    "agent_id": agent_id, "sentence_id": s.id, "iteration": iteration,
                    "text": new, "outcome": "rewritten",
                })

        text, sents = segment.respan(text, sents, edits)
        emit("agent_answer", {
            "agent_id": agent_id, "iteration": iteration, "text": text,
            "sentences": segment.as_events(sents), "orphans": [],
        })

        cl = await claims_mod.extract(agent_id, segment.claim_candidates(sents))
        vs = await verify.verify_all(claims_mod.pairs(cl), reg)
        by_claim = {c["id"]: c for c in cl}
        for (cid, sid), v in vs.items():
            c = by_claim.get(cid)
            if not c:
                continue
            emit("verdict", {
                "agent_id": agent_id, "sentence_id": c["sentence_id"], "claim_id": cid,
                "source_id": sid, "iteration": iteration, **v.dict(),
            })

        from .heatmap import cells as build_cells
        cells_ = build_cells([{
            "agent_id": agent_id, "claims": cl, "verdicts": vs,
            "sentences": sents, "iteration": iteration, "failed": False,
        }])

    # Cap reached with failures still standing: retract them rather than shipping them.
    by_id = {s.id: s for s in sents}
    edits = {}
    for sid, cs in _failing(cells_).items():
        s = by_id.get(sid)
        if not s or not s.text:
            continue
        retracted.append({"sentence_id": sid, "text": s.text,
                          "reason": cs[0].get("reason", "not supported after repair attempts")})
        edits[sid] = ""
        emit("rewrite_done", {
            "agent_id": agent_id, "sentence_id": sid, "iteration": iters,
            "text": "", "outcome": "retracted",
        })
    if edits:
        text, sents = segment.respan(text, sents, edits)
        emit("agent_answer", {
            "agent_id": agent_id, "iteration": iters, "text": text,
            "sentences": segment.as_events(sents), "orphans": [],
        })
        cl = await claims_mod.extract(agent_id, segment.claim_candidates(sents))

    return text, sents, cl, retracted
