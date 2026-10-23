"""A repair has to stay checkable. A rewrite that drops its citations is never verified again —
it must count as a retraction, not slip through as uncited prose."""
import asyncio

import pytest

from backend.pipeline import claims as claims_mod
from backend.pipeline import heatmap, rewrite, segment, verify
from backend.pipeline.sources import SourceRegistry


def _reg():
    reg = SourceRegistry()
    reg.intern("a1", "https://a.org/1", "a", "Source one says nothing about B.")
    reg.intern("a1", "https://a.org/2", "b", "Source two says nothing about D.")
    return reg


def _one(monkeypatch, reply, sentence_text="C is D [2]."):
    async def fake(model, messages, **kw):
        return reply
    monkeypatch.setattr(rewrite.llm, "complete", fake)
    s = segment.segment(sentence_text, prefix="a1.s")[0]
    return asyncio.run(rewrite._rewrite_one(s, [], _reg()))


@pytest.mark.parametrize("reply", ["**RETRACT**", "`RETRACT`", "> RETRACT", "Retract.", "RETRACTED"])
def test_a_decorated_retract_token_is_still_a_retraction(monkeypatch, reply):
    assert _one(monkeypatch, reply) == rewrite.RETRACT


@pytest.mark.parametrize("reply", [
    "C is roughly D, according to most reports.",       # dropped the marker
    "C is roughly D [9].",                              # cites a source it was never shown
    "Here is the corrected sentence:\nC is D [2].",     # preamble line, marker only on line two
])
def test_a_rewrite_that_no_longer_cites_its_sources_is_retracted(monkeypatch, reply):
    assert _one(monkeypatch, reply) == rewrite.RETRACT


def test_a_grounded_rewrite_survives(monkeypatch):
    assert _one(monkeypatch, "C is close to D [2].") == "C is close to D [2]."
    # a grouped marker is read the same way the writers' are
    assert _one(monkeypatch, "C and E are D [1, 2].", "C and E are D [1][2].") == "C and E are D [1][2]."


def test_the_board_keeps_both_failures_visible(monkeypatch):
    """End to end over repair(): two failing sentences, one 'repaired' to unchecked prose and
    one bold-retracted. Both must end as visible retractions, never as unverified text."""
    reg = _reg()

    async def fake_complete(model, messages, **kw):
        return "**RETRACT**" if "A is B" in messages[1]["content"] else "C is roughly D."

    async def fake_json(model, messages, **kw):
        if "CLAIM:" in messages[1]["content"]:
            return {"verdict": "unsupported", "quote": "", "confidence": 0.9, "reason": "not addressed"}
        return []

    monkeypatch.setattr(rewrite.llm, "complete", fake_complete)
    monkeypatch.setattr(claims_mod.llm, "complete_json", fake_json)
    monkeypatch.setattr(verify.llm, "complete_json", fake_json)

    async def go():
        text = "A is B [1]. C is D [2]."
        sents = segment.segment(text, prefix="a1.s")
        cl = await claims_mod.extract("a1", segment.claim_candidates(sents))
        vs = await verify.verify_all(claims_mod.pairs(cl), reg)
        cells = heatmap.cells([{"agent_id": "a1", "claims": cl, "verdicts": vs, "failed": False}])
        return await rewrite.repair("a1", text, reg, cells, 2, lambda *_: None)

    out, sents, _cl, retracted = asyncio.run(go())
    assert "C is roughly D" not in out and "RETRACT" not in out
    assert sorted(x["sentence_id"] for x in retracted) == ["a1.s1", "a1.s2"]
    rows = heatmap.rows([{"agent_id": "a1", "sentences": sents, "failed": False}], None, retracted)
    assert [(r["sentence_id"], r["retracted"]) for r in rows] == [("a1.s1", True), ("a1.s2", True)]
