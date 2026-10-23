"""Replay survives a model swap: a turn recorded under one model replays under another."""
import asyncio
import json
import sqlite3

import pytest

from backend import config
from backend.providers import cache, ollama, openai_compat

MSGS = [{"role": "user", "content": "rate limits?"}]


def _fresh_cache(monkeypatch, tmp_path, mode="auto"):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite")
    cache._conn = None                       # force reconnect to the temp db
    monkeypatch.setattr(config, "RESEARCH_MODE", mode)


def _fake_ollama(monkeypatch):
    """Answers with the model's own name, and counts who was actually called."""
    called = []

    async def fake(model, messages, tools, num_ctx, temperature, timeout):
        called.append(model)
        yield {"type": "done", "content": f"from {model}", "calls": []}

    monkeypatch.setattr(ollama, "_chat_retry", fake)
    return called


def _ask(model):
    return asyncio.run(ollama.complete(model, MSGS))


def test_replay_falls_back_to_another_models_recording(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    _fake_ollama(monkeypatch)
    _ask("minimax-m3:cloud")

    monkeypatch.setattr(config, "RESEARCH_MODE", "replay")
    assert _ask("mistral-large-3:675b:cloud") == "from minimax-m3:cloud"


def test_replay_prefers_the_exact_model(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    _fake_ollama(monkeypatch)
    _ask("a:cloud")
    _ask("b:cloud")

    monkeypatch.setattr(config, "RESEARCH_MODE", "replay")
    assert _ask("a:cloud") == "from a:cloud"


def test_auto_calls_a_swapped_model_instead_of_reusing_the_old_one(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    called = _fake_ollama(monkeypatch)
    _ask("old:cloud")
    assert _ask("new:cloud") == "from new:cloud"
    assert called == ["old:cloud", "new:cloud"]


def test_replay_still_misses_a_different_request(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    _fake_ollama(monkeypatch)
    _ask("a:cloud")

    monkeypatch.setattr(config, "RESEARCH_MODE", "replay")
    with pytest.raises(cache.CacheMiss):
        asyncio.run(ollama.complete("a:cloud", [{"role": "user", "content": "something else"}]))


def test_compat_models_fall_back_too(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)

    async def fake(model, messages, tools, temperature, timeout):
        yield {"type": "done", "content": f"from {model}", "calls": []}

    monkeypatch.setattr(openai_compat, "_retry", fake)

    async def ask(model):
        out = ""
        async for ev in openai_compat.chat(model, MSGS):
            if ev["type"] == "done":
                out = ev["content"]
        return out

    asyncio.run(ask("google/gemini-a"))
    monkeypatch.setattr(config, "RESEARCH_MODE", "replay")
    assert asyncio.run(ask("google/gemini-b")) == "from google/gemini-a"


def test_a_cache_from_before_the_column_is_migrated(monkeypatch, tmp_path):
    db = tmp_path / "c.sqlite"
    req = {"model": "old:cloud", "messages": MSGS}
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cache (key TEXT PRIMARY KEY, kind TEXT NOT NULL, request TEXT NOT "
                 "NULL, response TEXT NOT NULL, created_at REAL NOT NULL)")
    conn.execute("INSERT INTO cache VALUES (?,?,?,?,?)", (cache.cache_key("chat", req), "chat",
                 cache.canonical(req), json.dumps({"content": "old"}), 1.0))
    conn.commit()
    conn.close()

    _fresh_cache(monkeypatch, tmp_path)
    assert cache.get("chat", req) == {"content": "old"}            # old rows replay exactly
    new = {"model": "x:cloud", "messages": []}
    cache.put("chat", new, {"content": "new"})                    # writes still land...
    assert cache.get_any_model("chat", {**new, "model": "y:cloud"}) == {"content": "new"}
