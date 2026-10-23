"""The concept graph says when its extraction failed, instead of passing the failure off as an
answer with nothing in it."""
import asyncio

from backend.pipeline import concept


def test_a_failed_extraction_is_reported_not_shown_as_empty(monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(concept.llm, "complete_json", boom)
    out = asyncio.run(concept.extract("q?", "Some answer [1]."))
    assert out["nodes"] == [] and "failed" in out["error"]


def test_no_answer_yet_is_just_empty():
    assert asyncio.run(concept.extract("q?", "  ")) == {"nodes": [], "links": []}
