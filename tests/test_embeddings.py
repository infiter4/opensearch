"""The embeddings seam: facade routes by model id and caches like chat (replay-safe)."""
import asyncio

from backend import config
from backend.providers import cache, llm


def _fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite")
    cache._conn = None                       # force reconnect to the temp db
    monkeypatch.setattr(config, "RESEARCH_MODE", "auto")


def test_embeddings_route_and_cache(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    calls = {"n": 0}

    async def fake(model, texts, **kw):
        calls["n"] += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(llm.ollama, "embeddings", fake)

    v1 = asyncio.run(llm.embeddings("embeddinggemma", ["a", "b"]))
    v2 = asyncio.run(llm.embeddings("embeddinggemma", ["a", "b"]))  # identical -> cache hit
    assert v1 == v2
    assert len(v1) == 2 and len(v1[0]) == 3
    assert calls["n"] == 1, "second identical batch must replay from cache, not re-embed"


def test_embeddings_routes_compat_models(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    seen = {"compat": 0, "ollama": 0}

    async def compat(model, texts, **kw):
        seen["compat"] += 1
        return [[1.0] for _ in texts]

    async def olm(model, texts, **kw):
        seen["ollama"] += 1
        return [[2.0] for _ in texts]

    monkeypatch.setattr(llm.openai_compat, "embeddings", compat)
    monkeypatch.setattr(llm.ollama, "embeddings", olm)

    asyncio.run(llm.embeddings("google/text-embedding-004", ["x"]))
    asyncio.run(llm.embeddings("embeddinggemma", ["y"]))
    assert seen == {"compat": 1, "ollama": 1}


def test_empty_input_short_circuits(monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    assert asyncio.run(llm.embeddings("embeddinggemma", [])) == []
