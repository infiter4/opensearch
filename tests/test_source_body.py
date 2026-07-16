"""/api/source/{id} must serve the page TEXT, not just its identity.

The drawer is the receipt gesture: click a chip, see the pinned quote highlighted inside the real
page. It locates the span by plain string search over `content`. The endpoint returned identity
only ({id,url,title,domain,n_chars,...}) — no `content` — so the drawer rendered an empty scroll
area under a confident "matched excerpt — located by string search ↓" header. Nothing 404s, nothing
errors, no console noise: the single most load-bearing interaction in the product just showed
blank. The body never left the SourceRegistry, which lived and died inside orchestrator.run().
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend import sessions
from backend.pipeline import orchestrator
from backend.pipeline.sources import SourceRegistry
from backend.routers.research import source


def test_orchestrator_hands_the_registry_to_its_caller():
    seen: list[SourceRegistry] = []

    async def go():
        gen = orchestrator.run("q", "lite", on_registry=seen.append)
        await gen.__anext__()  # meta
        await gen.aclose()

    asyncio.run(go())
    assert len(seen) == 1, "the caller must receive the live registry"
    assert isinstance(seen[0], SourceRegistry)


def test_source_endpoint_returns_the_body():
    s = sessions.create("q", "lite")
    reg = SourceRegistry()
    reg.intern("a1", "https://example.com/pricing", "Pricing", "The free tier includes 1,000 credits.")
    s.registry = reg
    s.sources[1] = {"id": 1, "url": "https://example.com/pricing", "title": "Pricing",
                    "domain": "example.com", "n_chars": 37, "first_agent": "a1"}

    got = asyncio.run(source(1, s.query_id))
    assert got["content"] == "The free tier includes 1,000 credits."
    assert got["id"] == 1 and got["url"] == "https://example.com/pricing"


def test_source_body_lets_a_quote_be_located():
    # This is exactly what the drawer does: str.find over the served content.
    s = sessions.create("q", "lite")
    reg = SourceRegistry()
    page = "Preamble. The free tier includes 1,000 credits per month. Trailing prose."
    reg.intern("a1", "https://example.com/p", "P", page)
    s.registry = reg
    s.sources[1] = {"id": 1, "url": "https://example.com/p", "title": "P"}

    content = asyncio.run(source(1, s.query_id))["content"]
    assert content.find("The free tier includes 1,000 credits per month.") >= 0


def test_missing_registry_degrades_to_empty_not_500():
    # A session whose run never started has no registry. Serve identity with empty text rather
    # than throwing at the user mid-click.
    s = sessions.create("q", "lite")
    s.sources[1] = {"id": 1, "url": "https://example.com/p", "title": "P"}
    got = asyncio.run(source(1, s.query_id))
    assert got["content"] == ""


def test_unknown_source_still_404s():
    s = sessions.create("q", "lite")
    s.registry = SourceRegistry()
    with pytest.raises(HTTPException) as e:
        asyncio.run(source(99, s.query_id))
    assert e.value.status_code == 404
