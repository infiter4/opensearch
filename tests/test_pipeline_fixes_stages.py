"""Stage wiring: claim ids the extractor really returns, planner agent ids, and the red team's
instructions in a workspace run. Every model call is faked."""
import asyncio

from backend import config
from backend.pipeline import claims as claims_mod
from backend.pipeline import planner, segment, subagent
from backend.pipeline.sources import SourceRegistry


def test_bare_sentence_ids_from_the_extractor_still_map(monkeypatch):
    # Recorded kimi output answered "s1" for "a2.s1" in ~1 of 12 calls; every claim was dropped.
    async def fake(model, messages, **kw):
        return [{"sentence_id": "s1", "text": "Tavily is free.", "source_ids": [3]},
                {"sentence_id": "[a2.s2]", "text": "OpenAlex needs no key.", "source_ids": [4]}]
    monkeypatch.setattr(claims_mod.llm, "complete_json", fake)

    sents = segment.segment("Tavily is free [3]. OpenAlex needs no key [4].", prefix="a2.s")
    cl = asyncio.run(claims_mod.extract("a2", sents))
    assert [(c["sentence_id"], c["source_ids"]) for c in cl] == [("a2.s1", [3]), ("a2.s2", [4])]
    assert not any(c.get("fallback") for c in cl), "fell back to whole sentences"


def test_the_prompt_example_shows_a_prefixed_id():
    assert '"sentence_id": "a1.s3"' in claims_mod._PROMPT


def test_a_skipped_plan_entry_cannot_duplicate_the_red_team_id(monkeypatch):
    async def fake(model, messages, **kw):
        return [
            {"title": "Pricing", "subquery": "What does Tavily cost?"},
            {"title": "Limits", "query": "wrong key, skipped"},
            {"title": "Alternatives", "subquery": "What are the alternatives?"},
            {"title": "Reliability", "subquery": "How reliable is it?"},
        ]
    monkeypatch.setattr(planner.llm, "complete_json", fake)

    st = asyncio.run(planner.plan("Tavily: cost, limits, alternatives, reliability?", 4, red_team=True))
    ids = [s["agent_id"] for s in st]
    assert ids == ["a1", "a2", "a3", "a4"]
    assert st[-1]["role"] == "red_team"


def test_the_red_team_keeps_the_corpus_instructions(monkeypatch):
    seen = {}

    async def fake_run_agent(spec, ctx, prompt, system_extra=""):
        seen["tools"], seen["extra"] = spec.tools, system_extra
        return "(no answer)"
    monkeypatch.setattr(subagent, "run_agent", fake_run_agent)

    st = {"agent_id": "a5", "title": "Disconfirming evidence", "subquery": "q", "role": "red_team"}
    ws = {"id": "w1", "slug": "proj", "embed_model": "embeddinggemma"}
    asyncio.run(subagent.run_subagent(st, SourceRegistry(), config.PRESETS["deep"], (),
                                      lambda *_: None, asyncio.Event(), workspace=ws))
    assert seen["tools"] == ("corpus_search", "corpus_read")
    assert "corpus_search" in seen["extra"], "corpus instructions were replaced"
    assert "disconfirming researcher" in seen["extra"]
