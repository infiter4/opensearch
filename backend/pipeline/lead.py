"""Merge the sub-reports into one answer — then verify THAT.

The lead is the second hallucination surface, and it is the one whose text the judge actually
reads. Verifying sub-agents and then merging unverified would make the product's own thesis false
at the last step. Two structural constraints (code, not prompts) make the merge safe:

  * The lead has NO search tools and never sees a source BODY — only {id, url, title, domain}.
    So it cannot cite something no sub-agent read, and any marker outside the registry is
    stripped by renumber.validate().
  * The lead is verified against text it never saw. A lead claim citing [4] is checked with
    verify_pair(claim, registry[4].body). That is a stronger independence property than the
    sub-agents get, and it costs almost nothing: llm.chat() is content-addressed, so any
    sentence the lead reuses verbatim is a cache hit. Only its NOVEL sentences — the cross-source
    synthesis, i.e. the highest-risk ones — cost live calls.
"""
from __future__ import annotations

from .. import config
from ..providers import llm
from ..runtime.registry import spec
from . import claims as claims_mod
from . import renumber, segment, verify


def _findings(reports: list[dict]) -> str:
    parts = []
    for r in reports:
        if r.get("failed"):
            continue
        role = " (disconfirming evidence)" if r.get("role") == "red_team" else ""
        parts.append(f"### Researcher {r['agent_id']}: {r['title']}{role}\n\n{r['text']}")
    return "\n\n".join(parts)


def gaps_from(reports: list[dict], retracted: list[dict]) -> list[str]:
    """Gaps are DERIVED from real failures — a dead sub-agent or a retracted sentence. Never
    invented, never a model's hedging instinct."""
    out: list[str] = []
    for r in reports:
        if r.get("failed"):
            out.append(f"{r['title']}: no usable findings ({r.get('why', 'agent failed')[:80]})")
    for x in retracted:
        out.append(f"{x['text'][:110]} — {x['reason'][:80]}")
    return out


async def merge(question: str, reports: list[dict], reg, gaps: list[str], emit) -> dict:
    s = spec("lead")

    manifest = "\n".join(
        f"[{m['id']}] {m['title'][:70]} — {m['domain']}" for m in reg.manifest()
    )
    gap_block = ""
    if gaps:
        gap_block = "\n\n## Gaps you MUST report\n" + "\n".join(f"- {g}" for g in gaps)

    user = (
        f"QUESTION:\n{question}\n\n"
        f"SOURCES (identity only — you have NOT read these):\n{manifest}\n\n"
        f"RESEARCHER FINDINGS:\n\n{_findings(reports)}{gap_block}\n\n"
        f"Write the combined answer now."
    )

    emit("agent_status", {"agent_id": "lead", "status": "drafting"})
    text = ""
    async for ev in llm.chat(
        s.model,
        [{"role": "system", "content": s.prompt}, {"role": "user", "content": user}],
        num_ctx=32768,
        temperature=0.3,
    ):
        if ev["type"] == "content":
            emit("lead_token", {"text": ev["delta"]})
        elif ev["type"] == "done":
            text = ev["content"]

    # The lead was told never to change a number. That instruction is not trusted.
    text, orphans = renumber.validate(text.strip(), reg.ids())
    if orphans:
        emit("error", {
            "scope": "lead",
            "message": f"lead invented {len(orphans)} citation marker(s), removed: {orphans}",
        })

    sents = segment.segment(text, prefix="lead.s")
    emit("agent_answer", {
        "agent_id": "lead", "iteration": 0, "text": text,
        "sentences": segment.as_events(sents), "orphans": orphans,
    })

    emit("agent_status", {"agent_id": "lead", "status": "verifying"})
    cl = await claims_mod.extract("lead", segment.claim_candidates(sents))
    emit("claims", {"agent_id": "lead", "claims": cl})

    vs = await verify.verify_all(claims_mod.pairs(cl), reg)
    by_claim = {c["id"]: c for c in cl}
    for (cid, sid), v in vs.items():
        c = by_claim.get(cid)
        if not c:
            continue
        emit("verdict", {
            "agent_id": "lead", "sentence_id": c["sentence_id"], "claim_id": cid,
            "source_id": sid, "iteration": 0, **v.dict(),
        })

    return {
        "agent_id": "lead", "role": "lead", "title": "Final answer",
        "text": text, "sentences": sents, "claims": cl, "verdicts": vs,
        "orphans": orphans, "failed": False, "iteration": 0,
    }
