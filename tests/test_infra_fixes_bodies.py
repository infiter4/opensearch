"""Page bodies enter the agent capped, and the process-wide body caches stay bounded and scoped:
a corpus passage stashed for one workspace is never served to a run bound to another."""
import asyncio

from backend import config
from backend.pipeline.sources import SourceRegistry
from backend.providers import lanes
from backend.runtime import corpus_tools, research_tools
from backend.runtime.tools import Ctx


def test_read_page_hands_the_agent_a_capped_body(monkeypatch):
    cap = config.SOURCE_BODY_CHARS

    async def huge(url):
        return {"title": "T", "content": "w" * (cap * 20)}

    monkeypatch.setattr(lanes, "_fetch_ollama", huge)
    reg = SourceRegistry()
    out = asyncio.run(research_tools.read_page({"url": "https://big.example"}, Ctx(agent="a", registry=reg)))
    assert out.count("w") == cap
    assert len(reg.body(1)) == cap                   # what the verifier will check against


def test_web_body_stash_is_bounded(monkeypatch):
    monkeypatch.setattr(research_tools, "_BODIES", {})
    monkeypatch.setattr(research_tools, "_BODIES_MAX", 3)
    for i in range(10):
        research_tools._stash(f"https://p{i}.example", "b" * (config.SOURCE_BODY_CHARS * 2))
    assert list(research_tools._BODIES) == [f"https://p{i}.example" for i in (7, 8, 9)]
    assert all(len(v) == config.SOURCE_BODY_CHARS for v in research_tools._BODIES.values())


def test_a_corpus_stash_is_scoped_to_its_workspace(monkeypatch):
    monkeypatch.setattr(corpus_tools, "_BODIES", {})
    url = "corpus://notes/abc123/0"

    async def retrieve(workspace_id, embed_model, query, k=10):
        return [{"url": url, "title": "Doc", "body": "secret plans", "locator": "p.1", "_lanes": ["dense"]}]

    async def by_url(workspace_id, u):
        return None                                  # the DB scopes by workspace: B has no such row

    monkeypatch.setattr(corpus_tools.retrieval, "retrieve", retrieve)
    monkeypatch.setattr(corpus_tools.chunks_store, "by_url", by_url)

    a = Ctx(agent="a", registry=SourceRegistry(), workspace_id="ws-A", embed_model="e")
    b = Ctx(agent="b", registry=SourceRegistry(), workspace_id="ws-B", embed_model="e")
    asyncio.run(corpus_tools.corpus_search({"query": "plans"}, a))
    assert "secret plans" in asyncio.run(corpus_tools.corpus_read({"url": url}, a))
    assert asyncio.run(corpus_tools.corpus_read({"url": url}, b)).startswith("ERROR: no such passage")
