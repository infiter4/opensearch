"""The cap must be structural, not a polite request.

jarvis's CODER_PROCEDURE asks the model to iterate "at most N times" and nothing counts rounds —
a model that never converges loops forever. These tests pin that the caller cannot spin, using a
stub model that NEVER produces a fixable sentence.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config
from backend.pipeline import rewrite


class _Reg:
    def body(self, sid):
        return "The source says something entirely unrelated to the claim." * 20

    def to_global(self, a, l):
        return l

    def ids(self):
        return {1}


def _cells(sentence_id, verdict="unsupported"):
    return [{
        "sentence_id": sentence_id, "agent_id": "a1", "source_id": 1, "verdict": verdict,
        "confidence": 0.9, "quote": None, "quote_start": None, "quote_end": None,
        "reason": "source does not mention this", "iteration": 0, "claim_ids": ["a1.c1"],
    }]


def test_never_fixing_model_stops_at_cap_and_retracts(monkeypatch):
    """A rewriter that keeps emitting unsupported prose must burn exactly MAX iters, then retract."""
    calls = {"rewrite": 0, "verify": 0}

    async def fake_rewrite(sentence, cells, reg):
        calls["rewrite"] += 1
        return "Still an unsupported sentence [1]."

    async def fake_extract(agent_id, sents):
        return [{"id": "a1.c1", "sentence_id": s.id, "text": s.text, "source_ids": [1]}
                for s in sents]

    async def fake_verify_all(pairs, reg):
        calls["verify"] += 1
        from backend.pipeline.verify import Verdict
        return {(c, s): Verdict("unsupported", None, None, None, 0.9, "nope")
                for c, _sid, _t, s in pairs}

    monkeypatch.setattr(rewrite, "_rewrite_one", fake_rewrite)
    monkeypatch.setattr(rewrite.claims_mod, "extract", fake_extract)
    monkeypatch.setattr(rewrite.verify, "verify_all", fake_verify_all)

    text = "Still an unsupported sentence [1]."
    out, sents, cl, retracted = asyncio.run(
        rewrite.repair("a1", text, _Reg(), _cells("a1.s1"), max_iters=2, emit=lambda *_: None)
    )

    assert calls["rewrite"] == 2, f"expected exactly 2 attempts, got {calls['rewrite']}"
    assert retracted, "a claim that never passes must end up retracted, not shipped"


def test_retract_token_removes_sentence_immediately(monkeypatch):
    async def always_retract(sentence, cells, reg):
        return rewrite.RETRACT

    async def fake_extract(agent_id, sents):
        return []

    async def fake_verify_all(pairs, reg):
        return {}

    monkeypatch.setattr(rewrite, "_rewrite_one", always_retract)
    monkeypatch.setattr(rewrite.claims_mod, "extract", fake_extract)
    monkeypatch.setattr(rewrite.verify, "verify_all", fake_verify_all)

    events = []
    text = "Keep this one [1]. Drop this one [1]."
    from backend.pipeline import segment as seg
    ss = seg.segment(text, prefix="a1.s")
    bad = _cells(ss[1].id)

    out, _s, _c, retracted = asyncio.run(
        rewrite.repair("a1", text, _Reg(), bad, max_iters=2,
                       emit=lambda e, d: events.append((e, d)))
    )
    assert "Drop this one" not in out
    assert "Keep this one" in out
    assert any(e == "rewrite_done" and d["outcome"] == "retracted" for e, d in events)
    assert retracted and retracted[0]["sentence_id"] == ss[1].id


def test_global_cap_overrides_a_larger_request(monkeypatch):
    """A preset asking for more iterations than MAX_REWRITE_ITERS must be clamped in code."""
    calls = {"n": 0}

    async def fake_rewrite(sentence, cells, reg):
        calls["n"] += 1
        return "Nope [1]."

    async def fake_extract(agent_id, sents):
        return [{"id": "a1.c1", "sentence_id": s.id, "text": s.text, "source_ids": [1]} for s in sents]

    async def fake_verify_all(pairs, reg):
        from backend.pipeline.verify import Verdict
        return {(c, s): Verdict("unsupported", None, None, None, 0.9, "nope")
                for c, _sid, _t, s in pairs}

    monkeypatch.setattr(rewrite, "_rewrite_one", fake_rewrite)
    monkeypatch.setattr(rewrite.claims_mod, "extract", fake_extract)
    monkeypatch.setattr(rewrite.verify, "verify_all", fake_verify_all)

    asyncio.run(rewrite.repair("a1", "Nope [1].", _Reg(), _cells("a1.s1"),
                               max_iters=99, emit=lambda *_: None))
    assert calls["n"] == config.MAX_REWRITE_ITERS, \
        f"asked for 99 iters, cap is {config.MAX_REWRITE_ITERS}, ran {calls['n']}"


def test_no_failures_means_no_rewrite_calls(monkeypatch):
    calls = {"n": 0}

    async def fake_rewrite(sentence, cells, reg):
        calls["n"] += 1
        return "x"

    monkeypatch.setattr(rewrite, "_rewrite_one", fake_rewrite)
    out, _s, _c, retracted = asyncio.run(
        rewrite.repair("a1", "All good [1].", _Reg(), _cells("a1.s1", "supported"),
                       max_iters=2, emit=lambda *_: None)
    )
    assert calls["n"] == 0 and not retracted
    assert out == "All good [1]."
