""""What we could not establish" reports verification failures. It must never itself become a
set of claims that get verified, fail, and are retracted out of the answer."""
import asyncio
import re

from backend.pipeline import claims as claims_mod
from backend.pipeline import lead as lead_mod
from backend.pipeline import verify
from backend.pipeline.sources import SourceRegistry


def test_gap_lines_carry_no_citation_markers():
    gaps = lead_mod.gaps_from([], [{"sentence_id": "a1.s2", "reason": "not supported",
                                    "text": "Tavily guarantees 99.99% uptime [2][3]."}])
    assert gaps == ["Tavily guarantees 99.99% uptime. — not supported"]


def test_the_gap_section_is_not_claim_extracted(monkeypatch):
    reg = SourceRegistry()
    reg.intern("a1", "https://a.org/1", "a", "Tavily offers 1,000 free credits per month.")
    reg.intern("a1", "https://a.org/2", "b", "Credits page.")

    async def fake_chat(model, messages, **kw):
        # The lead attaches markers inside the section on its own, as recorded leads did.
        yield {"type": "done", "content": (
            "Tavily offers 1,000 free credits per month [1].\n\n"
            "## What we could not establish\n\n"
            "- Tavily's uptime guarantee [2].\n"
            "- Per-request costs — the credits page did not render in the fetch [2]."
        )}

    seen = []

    async def fake_extract(agent_id, sentences):
        seen.extend(s.text for s in sentences)
        return []

    async def fake_verify_all(pairs, reg):
        return {}

    monkeypatch.setattr(lead_mod.llm, "chat", fake_chat)
    monkeypatch.setattr(claims_mod, "extract", fake_extract)
    monkeypatch.setattr(verify, "verify_all", fake_verify_all)

    ld = asyncio.run(lead_mod.merge("q", [], reg, ["Tavily's uptime guarantee. — not supported"],
                                    lambda *_: None))
    assert seen == ["Tavily offers 1,000 free credits per month [1]."]
    gap_section = ld["text"].split("## What we could not establish", 1)[1]
    assert not re.search(r"\[\d+\]", gap_section)
    assert "- Tavily's uptime guarantee." in gap_section, "the gap itself must stay in the answer"
    assert [s.cited for s in ld["sentences"] if s.cited] == [(1,)]
