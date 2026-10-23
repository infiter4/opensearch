"""The cache records answers, never failures — and never stalls the event loop to do it."""
import asyncio
import subprocess
import sys
import time

import httpx
import pytest

from backend import config
from backend.providers import cache, lanes, ollama, openai_compat

MSGS = [{"role": "user", "content": "q"}]


@pytest.fixture
def fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite")
    monkeypatch.setattr(cache, "_conn", None)
    monkeypatch.setattr(config, "RESEARCH_MODE", "auto")
    return tmp_path / "c.sqlite"


def _mock_http(monkeypatch, handler):
    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(lanes.httpx, "AsyncClient", Fake)


# ── lanes: a failure raises, so cached_call never records it ──────────────────────────────

def test_a_transient_lane_failure_is_not_replayed_after_recovery(monkeypatch, fresh_cache):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-not-a-real-key")
    status = {"code": 429}
    calls = []

    def handler(req):
        calls.append(req.url.host)
        if status["code"] != 200:
            return httpx.Response(status["code"], text="slow down")
        if "tavily" in req.url.host:
            return httpx.Response(200, json={"results": [
                {"url": "https://a.example/x", "title": "A", "content": "c", "raw_content": "B" * 900}]})
        return httpx.Response(200, text="Title: page\n" + "word " * 300)

    _mock_http(monkeypatch, handler)

    async def go():
        with pytest.raises(lanes.LaneError):
            await lanes.search_tavily("q", 8)
        with pytest.raises(lanes.LaneError):
            await lanes._fetch_jina("https://a.example/x")
        assert cache.stats() == {}, "a failure was recorded"
        status["code"] = 200
        hits = await lanes.search_tavily("q", 8)
        page = await lanes._fetch_jina("https://a.example/x")
        return hits, page

    hits, page = asyncio.run(go())
    assert hits and hits[0]["url"] == "https://a.example/x"
    assert page["content"].startswith("Title: page")
    assert len(calls) == 4


def test_a_missing_key_is_an_error_not_an_empty_recording(monkeypatch, fresh_cache):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    async def go():
        for fn in (lanes.search_tavily, lanes.search_ollama):
            with pytest.raises(lanes.LaneError):
                await fn("q", 8)

    asyncio.run(go())
    assert cache.stats() == {}


def test_search_all_and_fetch_still_degrade_gracefully(monkeypatch, fresh_cache):
    async def dead(*a, **kw):
        raise lanes.LaneError("tavily search: HTTP 429")

    async def alive(query, max_results=8):
        return [{"url": "https://ok.example", "title": "ok", "content": "c"}]

    monkeypatch.setitem(lanes._LANES, "tavily", dead)
    monkeypatch.setitem(lanes._LANES, "ollama", alive)
    got = asyncio.run(lanes.search_all("q", ("ollama", "tavily")))
    assert got == {"ollama": [{"url": "https://ok.example", "title": "ok", "content": "c"}], "tavily": []}

    async def boom(url):
        raise lanes.LaneError("ollama fetch: HTTP 500")

    async def jina(url):
        return {"title": "J", "content": "x" * 800}

    monkeypatch.setattr(lanes, "_fetch_ollama", boom)
    monkeypatch.setattr(lanes, "_fetch_jina", jina)
    assert asyncio.run(lanes.fetch("https://p.example"))["via"] == "jina"
    monkeypatch.setattr(lanes, "_fetch_jina", boom)
    assert asyncio.run(lanes.fetch("https://p.example")) == {}


# ── chat: only a turn that said something is recorded ───────────────────────────────────

def _collect(gen):
    async def go():
        return [ev async for ev in gen]
    return asyncio.run(go())


def test_an_empty_chat_turn_is_not_recorded(monkeypatch, fresh_cache):
    replies = iter(["", "a real answer"])
    called = []

    async def fake(model, messages, tools, num_ctx, temperature, timeout):
        called.append(model)
        yield {"type": "done", "content": next(replies), "calls": []}

    monkeypatch.setattr(ollama, "_chat_retry", fake)
    _collect(ollama.chat("m:cloud", MSGS))
    assert cache.stats() == {}
    _collect(ollama.chat("m:cloud", MSGS))                 # not served the empty turn: called again
    assert len(called) == 2 and cache.stats() == {"chat": 1}
    _collect(ollama.chat("m:cloud", MSGS))                 # the real answer replays
    assert len(called) == 2


def test_an_empty_compat_turn_is_not_recorded(monkeypatch, fresh_cache):
    async def fake(model, messages, tools, temperature, timeout):
        yield {"type": "done", "content": "", "calls": []}

    monkeypatch.setattr(openai_compat, "_retry", fake)
    _collect(openai_compat.chat("groq/x", MSGS))
    assert cache.stats() == {}

    async def with_calls(model, messages, tools, temperature, timeout):
        yield {"type": "done", "content": "", "calls": [{"name": "web_search", "arguments": {}}]}

    monkeypatch.setattr(openai_compat, "_retry", with_calls)
    _collect(openai_compat.chat("groq/x", MSGS))           # a tool-call turn IS an answer
    assert cache.stats() == {"chat": 1}


# ── sqlite off the loop ─────────────────────────────────────────────────────────────────

def test_a_locked_cache_does_not_freeze_the_event_loop(fresh_cache):
    cache.stats()                                           # create the schema
    holder = subprocess.Popen([sys.executable, "-c", (
        "import sqlite3, sys, time\n"
        f"c = sqlite3.connect({str(fresh_cache)!r}, isolation_level=None)\n"
        "c.execute('BEGIN IMMEDIATE'); print('locked', flush=True); time.sleep(1.5)\n")],
        stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "locked"

    async def go():
        gaps = []

        async def ticker():
            last = time.monotonic()
            while True:
                await asyncio.sleep(0.02)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        t = asyncio.create_task(ticker())

        async def fn():
            return {"ok": True}

        out = await cache.cached_call("search:test", {"query": "q"}, fn, mode="auto")
        t.cancel()
        return out, max(gaps)

    try:
        out, worst = asyncio.run(go())
    finally:
        holder.wait(timeout=10)
    assert out == {"ok": True}
    assert worst < 0.5, f"event loop stalled {worst:.2f}s behind a locked cache"
    assert cache.stats() == {"search:test": 1}             # the write still landed once unlocked


# ── page bodies are cut where they enter the agent/verify path ──────────────────────────

def test_fetch_caps_every_body_at_source_body_chars(monkeypatch):
    cap = config.SOURCE_BODY_CHARS

    async def long_page(url):
        return {"title": "T", "content": "y" * (cap * 10)}

    monkeypatch.setattr(lanes, "_fetch_ollama", long_page)
    assert len(asyncio.run(lanes.fetch("https://p.example"))["content"]) == cap
    lane_body = asyncio.run(lanes.fetch("https://p.example", body="z" * (cap * 10)))
    assert lane_body["via"] == "lane:body" and len(lane_body["content"]) == cap
