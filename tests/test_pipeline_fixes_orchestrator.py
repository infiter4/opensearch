"""A researcher that went through repair must end on `done`, not on `rewriting` forever.

Hermetic: every stage the orchestrator wires is faked, and llm.chat raises, so any path that
slips past the fakes fails loudly instead of calling a model.
"""
import asyncio

import pytest

from backend.pipeline import orchestrator, segment
from backend.pipeline.verify import Verdict
from backend.providers import llm

Q = "What are the rate limits of Ollama's web search API?"   # fast-path research: no router call


@pytest.fixture
def faked(monkeypatch):
    def no_live_calls(*a, **kw):
        raise AssertionError("a live model call escaped the fakes")
    monkeypatch.setattr(llm, "chat", no_live_calls)

    async def plan(question, n, red_team=False, history=None):
        return [{"agent_id": "a1", "title": "Limits", "subquery": Q, "lane": "web", "role": "research"}]

    async def run_subagent(st, reg, preset, lanes, emit, cancel, workspace=None):
        reg.intern("a1", "https://docs.ollama.com/x", "Docs", "The page does not state limits.")
        text = "It caps at 100 requests per minute [1]."
        sents = segment.segment(text, prefix="a1.s")
        cl = [{"id": "a1.c1", "sentence_id": "a1.s1", "text": "It caps at 100 rpm.", "source_ids": [1]}]
        emit("agent_status", {"agent_id": "a1", "status": "done"})
        return {"agent_id": "a1", "role": "research", "title": "Limits", "text": text,
                "sentences": sents, "claims": cl, "orphans": [], "failed": False,
                "verdicts": {("a1.c1", 1): Verdict("unsupported", None, None, None, 0.9, "no")}}

    async def reverify(cl, reg):
        return {}

    async def merge(question, reports, reg, gaps, emit):
        return {"agent_id": "lead", "role": "lead", "title": "Final answer", "text": "", "sentences": [],
                "claims": [], "verdicts": {}, "orphans": [], "failed": False, "iteration": 0}

    monkeypatch.setattr(orchestrator.planner, "plan", plan)
    monkeypatch.setattr(orchestrator.subagent, "run_subagent", run_subagent)
    monkeypatch.setattr(orchestrator, "_reverify", reverify)
    monkeypatch.setattr(orchestrator.lead_mod, "merge", merge)
    return monkeypatch


def _run():
    async def go():
        return [ev async for ev in orchestrator.run(Q, "pro")]
    return asyncio.run(go())


def _a1_statuses(events):
    return [d["status"] for e, d in events if e == "agent_status" and d["agent_id"] == "a1"]


def test_a_repaired_researcher_ends_done(faked):
    async def repair(agent_id, text, reg, cells, iters, emit):
        return "", segment.respan(text, segment.segment(text, prefix="a1.s"), {"a1.s1": ""})[1], [], []
    faked.setattr(orchestrator.rewrite, "repair", repair)

    events = _run()
    st = _a1_statuses(events)
    assert "rewriting" in st and st[-1] == "done", st
    assert events[-1][0] == "done"


def test_a_failed_repair_still_ends_done(faked):
    async def repair(agent_id, text, reg, cells, iters, emit):
        raise RuntimeError("rewriter exploded")
    faked.setattr(orchestrator.rewrite, "repair", repair)

    events = _run()
    assert _a1_statuses(events)[-1] == "done"
    assert any(e == "error" and "repair failed" in d["message"] for e, d in events)
    assert events[-1][0] == "done"
