"""The intent router: research questions go to the pipeline, do-this tasks go to the doer.

The fast-path must be deterministic and offline (no model call) for the confident majority — that
is what keeps the replay demo from making a router call it has no cache entry for, and what fixes
the reported bug where "can you make this into a pdf" got web-searched.
"""
import asyncio

from backend.pipeline import router


def test_fast_path_sends_clear_questions_to_research():
    for q in [
        "What are the rate limits of Ollama's web search API?",
        "How much does Tavily's search API cost and what does the free tier include?",
        "Do AI search engines cite sources accurately?",
        "how do I convert markdown to pdf in python",   # asks HOW -> knowledge, not an action
        "which library should I use for charts",
    ]:
        assert router.fast_route(q) == "research", q


def test_fast_path_sends_clear_tasks_to_the_doer():
    for q in [
        "can you make this into a pdf",                  # reported case #1
        "can you compile this into a pdf?",              # reported case #2
        "could you establish these findings in a pdf form?",  # reported case #3 (polite request)
        "would you turn the report into a spreadsheet",
        "make this into a pdf",
        "turn the report into a pdf",
        "create a folder called reports",
        "mkdir output and move the csv there",
        "save this as an html file",
        "generate a csv of the verdict counts",
        # CAD / 3D model intent -> the doer builds it with trimesh
        "design a parametric L-bracket 40x40x3 mm with two mounting holes",
        "make me a 3D model of a phone stand",
        "generate an STL of a 20 mm gear",
        "export it as a glb",
        "build a mounting bracket and save it as stl",
    ]:
        assert router.fast_route(q) == "task", q


def test_cad_howto_questions_stay_research():
    # asking HOW is knowledge, not a build request
    for q in ["how does a planetary gear work", "what is an STL file", "which CAD tool should I use"]:
        assert router.fast_route(q) == "research", q


def test_fast_path_defers_when_unsure():
    assert router.fast_route("the quarterly numbers") is None
    assert router.fast_route("") is None


def test_classify_uses_the_fast_path_without_a_model():
    r = asyncio.run(router.classify("can you make this into a pdf"))
    assert r["kind"] == "task" and r["via"] == "fast"

    r = asyncio.run(router.classify("What are the rate limits of Ollama's web search API?"))
    assert r["kind"] == "research" and r["via"] == "fast"


def test_classify_consults_the_model_only_when_ambiguous(monkeypatch):
    called = {"n": 0}

    async def fake(model, messages, **kw):
        called["n"] += 1
        return {"kind": "task", "title": "make the file", "reason": "asks to produce a file"}

    monkeypatch.setattr(router.llm, "complete_json", fake)
    r = asyncio.run(router.classify("the quarterly numbers, please"))  # no fast-path match
    assert r["kind"] == "task" and r["via"] == "model" and called["n"] == 1


def test_classify_defaults_to_research_when_the_model_fails(monkeypatch):
    async def boom(model, messages, **kw):
        raise RuntimeError("replay miss / offline")

    monkeypatch.setattr(router.llm, "complete_json", boom)
    r = asyncio.run(router.classify("the quarterly numbers, please"))
    assert r["kind"] == "research" and r["via"] == "default"


def test_complexity_mode_scales_with_the_question():
    assert router.complexity_mode("what is the payload of the arm") == "lite"
    assert router.complexity_mode("compare the arm and the gantry on speed") == "pro"
    assert router.complexity_mode(
        "give a comprehensive, in-depth survey of every actuator option") == "deep"


def test_classify_carries_a_mode_and_corpus_nudges_lite_to_pro():
    r = asyncio.run(router.classify("what is the payload"))
    assert r["mode"] == "lite"
    r2 = asyncio.run(router.classify("what is the payload", corpus_available=True))
    assert r2["mode"] == "pro", "a real corpus should nudge a trivial question up to pro"
