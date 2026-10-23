"""Transports retry on what the provider SAID (the HTTP status), not on digits that happen to be
in the error text; complete_json takes the JSON value that opens first."""
import asyncio

import httpx
import pytest

from backend import config
from backend.providers import llm, ollama, openai_compat


@pytest.fixture
def transport(monkeypatch):
    """Route every httpx client to `respond`, record backoff instead of sleeping it."""
    state = {"attempts": 0, "slept": [], "held": [], "respond": None}

    def handler(req):
        state["attempts"] += 1
        return state["respond"](req)

    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    async def no_sleep(s):
        state["slept"].append(s)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    monkeypatch.setattr(ollama.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(ollama, "_hold_off", lambda s: state["held"].append(s))
    monkeypatch.setattr(ollama, "_cooldown_until", 0.0)
    monkeypatch.setattr(config, "RESEARCH_MODE", "live")      # no cache in the way
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-not-a-real-key")
    return state


def _run(mod, model):
    async def go():
        async for _ in mod.chat(model, [{"role": "user", "content": "hi"}]):
            pass
    asyncio.run(go())


def test_a_permanent_400_with_digits_in_its_body_is_not_retried(transport):
    transport["respond"] = lambda r: httpx.Response(
        400, json={"error": "prompt is 41500 tokens, exceeds the 32768 context window (429/503)"})
    with pytest.raises(ollama.LLMError) as e:
        _run(ollama, "kimi-k2.6:cloud")
    assert transport["attempts"] == 1 and transport["slept"] == [] and transport["held"] == []
    assert e.value.status == 400


def test_a_503_is_retried_and_a_429_parks_every_caller(transport):
    transport["respond"] = lambda r: httpx.Response(503, text="busy")
    with pytest.raises(ollama.LLMError):
        _run(ollama, "kimi-k2.6:cloud")
    assert transport["attempts"] == 6 and transport["held"] == []

    transport.update(attempts=0)
    replies = iter([httpx.Response(429, json={"error": "too many concurrent requests"})])
    ok = b'{"message":{"content":"hi"},"done":true}\n'
    transport["respond"] = lambda r: next(replies, httpx.Response(200, content=ok))
    _run(ollama, "kimi-k2.6:cloud")
    assert transport["attempts"] == 2 and len(transport["held"]) == 1


def test_an_in_stream_error_frame_is_judged_by_its_own_words(transport):
    frames = {"text": "server overloaded, try again"}
    transport["respond"] = lambda r: httpx.Response(200, content=f'{{"error":"{frames["text"]}"}}\n'.encode())
    with pytest.raises(ollama.LLMError):
        _run(ollama, "kimi-k2.6:cloud")
    assert transport["attempts"] == 6

    transport.update(attempts=0)
    frames["text"] = "model 'x500' not found"            # digits in the model name: permanent
    with pytest.raises(ollama.LLMError):
        _run(ollama, "x500:cloud")
    assert transport["attempts"] == 1


def test_compat_retries_on_status_only(transport):
    transport["respond"] = lambda r: httpx.Response(
        400, json={"error": {"message": "Please reduce the length: 9500 tokens requested"}})
    with pytest.raises(openai_compat.LLMError) as e:
        _run(openai_compat, "groq/llama-3.3-70b-versatile")
    assert transport["attempts"] == 1 and e.value.status == 400

    transport.update(attempts=0)
    transport["respond"] = lambda r: httpx.Response(502, text="bad gateway")
    with pytest.raises(openai_compat.LLMError):
        _run(openai_compat, "groq/llama-3.3-70b-versatile")
    assert transport["attempts"] == 5


@pytest.mark.parametrize("raw,want", [
    ('Here: {"claims": ["a", "b"]} done', {"claims": ["a", "b"]}),
    ('Sure! ["x", {"a": 1}] — hope that helps', ["x", {"a": 1}]),
    ('{"ok": true}', {"ok": True}),
])
def test_complete_json_takes_the_value_that_opens_first(monkeypatch, raw, want):
    async def fake_complete(model, messages, **kw):
        return raw

    monkeypatch.setattr(llm, "complete", fake_complete)
    assert asyncio.run(llm.complete_json("m", [])) == want
