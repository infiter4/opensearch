"""The board's structure. A VIEW over verdicts — zero model calls, by design.

The temptation is to build this as a pipeline stage that "compares the answer to the sources",
which lands on embedding cosine. That would be a beautiful picture of noise: a claim and its
negation score ~0.95 cosine. "Aspirin prevents heart attacks" and "Aspirin does not prevent heart
attacks" are near-identical to an embedder and opposite to a reader.

verify_pair() detects. This renders. Nothing here calls a model.

ROWS ARE SENTENCES, not claims. Claims are the verification unit; sentences are the display unit.
A rewritten sentence keeps its sentence_id while its claims are regenerated with new ids — if rows
were claims, every rewrite would re-lay-out the grid and destroy the red->green transition.
Rows must not move.
"""
from __future__ import annotations

from .verify import SEVERITY, worst


def rows(reports: list[dict], lead: dict | None = None, retracted: list[dict] | None = None) -> list[dict]:
    """Banded by agent so the matrix is block-diagonal. Lead band on top when present.

    A retracted sentence keeps its row. segment.respan() leaves it as a zero-width span with no
    text, so it would otherwise fall through the uncited filter and vanish — and a row that
    disappears is how you lie with a UI: the grid would resolve clean by deleting its own failures.
    The row carries the ORIGINAL text and the reason so the board can strike it through and say why.
    """
    out: list[dict] = []
    order = 0
    gone = {r["sentence_id"]: r for r in (retracted or [])}

    def band(agent_id: str, sents, label: str):
        nonlocal order
        for s in sents:
            ret = gone.get(s.id)
            if not s.cited and not ret:
                continue  # uncited prose has nothing to verify — it is not a row
            out.append({
                "sentence_id": s.id, "agent_id": agent_id, "band": label,
                "text": ret["text"] if ret else s.text,
                "retracted": bool(ret),
                "reason": ret.get("reason") if ret else None,
                "order": order,
            })
            order += 1

    if lead and lead.get("sentences"):
        band("lead", lead["sentences"], "lead")
    for r in reports:
        if not r.get("failed"):
            band(r["agent_id"], r.get("sentences") or [], r.get("role", "research"))
    return out


def cells(reports: list[dict], lead: dict | None = None) -> list[dict]:
    """One cell per (sentence, source) actually cited. Sparse on purpose.

    Dense (every sentence x every source) would be ~30x18 = 540 verify calls, and it is
    semantically wrong besides: "source 7 does not support sentence 3" is not a defect if
    sentence 3 never cited source 7.

    The sparsity is the picture. Sub-agent A only cites A's sources, so ordering columns by
    first-interning agent makes the grid block-diagonal — and an off-block cell means two agents
    independently found and cited the same source. That is corroboration you can point at.
    """
    out: list[dict] = []
    for r in ([lead] if lead else []) + [x for x in reports if not x.get("failed")]:
        if not r:
            continue
        aid = r.get("agent_id", "lead")
        by_sent: dict[tuple[str, int], list[str]] = {}
        claim_ids: dict[tuple[str, int], list[str]] = {}
        by_claim = {c["id"]: c for c in (r.get("claims") or [])}
        best: dict[tuple[str, int], dict] = {}

        for (cid, sid), v in (r.get("verdicts") or {}).items():
            c = by_claim.get(cid)
            if not c:
                continue
            k = (c["sentence_id"], sid)
            by_sent.setdefault(k, []).append(v.verdict)
            claim_ids.setdefault(k, []).append(cid)
            # keep the evidence from the worst verdict in the group — that's what a reader wants
            cur = best.get(k)
            if cur is None or SEVERITY.get(v.verdict, 99) < SEVERITY.get(cur.verdict, 99):
                best[k] = v

        for (sent_id, src_id), verdicts in by_sent.items():
            v = best[(sent_id, src_id)]
            out.append({
                "sentence_id": sent_id, "agent_id": aid, "source_id": src_id,
                "verdict": worst(verdicts),  # worst-wins, same rule the chips use
                "confidence": v.confidence, "quote": v.quote,
                "quote_start": v.quote_start, "quote_end": v.quote_end,
                "reason": v.reason, "iteration": r.get("iteration", 0),
                "claim_ids": claim_ids[(sent_id, src_id)],
            })
    return out


def trust(cells_: list[dict], scope: str = "final") -> dict:
    """Score over SENTENCES, not cells — a sentence citing four sources must not count four times."""
    per_sent: dict[str, list[str]] = {}
    for c in cells_:
        per_sent.setdefault(c["sentence_id"], []).append(c["verdict"])

    counts = {"supported": 0, "weak": 0, "unsupported": 0, "contradicted": 0, "retracted": 0}
    for verdicts in per_sent.values():
        w = worst(verdicts)
        if w in counts:
            counts[w] += 1

    total = sum(counts.values())
    # weak is half credit: the source gestures at it. retracted scores zero but is still counted —
    # it stays visible rather than quietly improving the number by leaving.
    score = (counts["supported"] + 0.5 * counts["weak"]) / total if total else 0.0
    return {"scope": scope, **counts, "total": total, "score": round(score, 3)}


def contradictions(cells_: list[dict]) -> list[dict]:
    """Derived from the verdict matrix — zero model calls.

    A sentence whose cited sources disagree (one supports, another contradicts) IS a source
    conflict. It falls out of data we already have, which is what makes this genuinely free
    rather than another model's opinion.
    """
    per_sent: dict[str, list[dict]] = {}
    for c in cells_:
        per_sent.setdefault(c["sentence_id"], []).append(c)

    out = []
    for sent_id, cs in per_sent.items():
        sup = [c for c in cs if c["verdict"] == "supported"]
        con = [c for c in cs if c["verdict"] == "contradicted"]
        if sup and con:
            out.append({
                "sentence_id": sent_id,
                "source_ids": [sup[0]["source_id"], con[0]["source_id"]],
                "note": (
                    f"source [{sup[0]['source_id']}] supports this; "
                    f"source [{con[0]['source_id']}] contradicts it"
                ),
                "supporting_quote": sup[0].get("quote"),
                "contradicting_quote": con[0].get("quote"),
            })
    return out
