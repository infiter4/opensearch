"""The server-side quote check is the guarantee. A quote that is only partly in the source is not
support, and a verifier that crashes must still leave a verdict behind."""
import asyncio

from backend.pipeline import verify
from backend.pipeline.sources import SourceRegistry

SRC = "Pricing. Tavily's free Researcher plan includes 1,000 API credits per month. Paid plans start at $30."


def _answer(monkeypatch, d):
    async def fake(model, messages, **kw):
        return d
    monkeypatch.setattr(verify.llm, "complete_json", fake)


def test_a_real_opening_with_an_invented_tail_is_not_support(monkeypatch):
    _answer(monkeypatch, {
        "verdict": "supported", "confidence": 0.95, "reason": "stated",
        "quote": "Tavily's free Researcher plan includes 1,000 API credits per month and unlimited searches.",
    })
    v = asyncio.run(verify.verify_pair("Tavily's free plan includes unlimited searches.", SRC))
    assert v.verdict == "weak" and v.downgraded
    assert "partly" in v.reason
    # the highlight still points at real text, and the quote is only what is really there
    assert v.quote == SRC[v.quote_start:v.quote_end]
    assert SRC.find(v.quote) != -1


def test_a_whole_quote_still_supports(monkeypatch):
    _answer(monkeypatch, {"verdict": "supported", "confidence": 0.9, "reason": "ok",
                          "quote": "Tavily’s free Researcher plan includes 1,000 API credits per month."})
    src = SRC.replace("'", "’")      # typographic folding is still not "partial"
    v = asyncio.run(verify.verify_pair("Tavily's free plan includes 1,000 credits a month.", src))
    assert v.verdict == "supported" and not v.downgraded


def test_find_quote_keeps_its_two_tuple_api():
    assert verify.find_quote(SRC, "Paid plans start at $30.") == (SRC.index("Paid"), len(SRC))


def test_a_list_of_quotes_is_read_not_crashed_on(monkeypatch):
    _answer(monkeypatch, {"verdict": "contradicted", "confidence": 0.9, "reason": "says 1,000",
                          "quote": ["Tavily's free Researcher plan includes 1,000 API credits per month.",
                                    "Paid plans start at $30."]})
    v = asyncio.run(verify.verify_pair("The free plan includes 50,000 credits.", SRC))
    assert v.verdict == "contradicted" and v.quote_start is not None


def test_a_non_string_quote_cannot_pass_as_support(monkeypatch):
    _answer(monkeypatch, {"verdict": "supported", "confidence": 0.9, "reason": "x",
                          "quote": {"text": "Paid plans start at $30."}})
    v = asyncio.run(verify.verify_pair("Paid plans start at $30.", SRC))
    assert v.verdict == "weak" and v.downgraded


def test_a_verifier_crash_still_leaves_a_verdict(monkeypatch):
    reg = SourceRegistry()
    reg.intern("a1", "https://a.org/1", "a", SRC)

    async def crash(claim_text, source_text):
        raise AttributeError("'list' object has no attribute 'strip'")
    monkeypatch.setattr(verify, "verify_pair", crash)

    out = asyncio.run(verify.verify_all([("a1.c1", "a1.s1", "anything", 1)], reg))
    assert ("a1.c1", 1) in out, "the pair was dropped: no cell, no trust count, no repair"
    v = out[("a1.c1", 1)]
    assert v.verdict == "weak" and v.reason.startswith("verifier error")
