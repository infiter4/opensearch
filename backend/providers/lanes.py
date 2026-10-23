"""Search lanes + the fetch fallback chain. Every call goes through cache.cached_call.

Search is a fan-out (lanes are complementary, not alternatives — picking between two general web
engines throws away coverage for nothing). Fetch is a fallback CHAIN, not a choice: try, and on
failure or thin content, try the next. No routing decision, no model.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from .. import config
from . import cache
from .rrf import domain, normalize_url

_UA = {"User-Agent": "receipts/0.1 (research verifier; +https://github.com/local/receipts)"}


class LaneError(RuntimeError):
    """A lane or fetcher that could not answer — no key, a 429, a 5xx. RAISED, never returned as
    []/{}: cached_call records whatever call() returns, so an empty result here was recorded as
    the answer, and one Jina 429 blanked that URL for every later run, replay included.
    search_all and fetch already turn a raise into "this lane contributed nothing"."""


# ─────────────────────────── search lanes ───────────────────────────

async def search_ollama(query: str, max_results: int = 8) -> list[dict]:
    """max_results caps at 10 server-side — verified."""
    n = min(max_results, 10)
    req = {"query": query, "max_results": n}

    async def call() -> list[dict]:
        key = os.environ.get("OLLAMA_API_KEY")
        if not key:
            raise LaneError("ollama search: no OLLAMA_API_KEY")
        async with httpx.AsyncClient(timeout=45.0) as c:
            r = await c.post(
                f"{config.OLLAMA_CLOUD_URL}/api/web_search",
                json=req,
                headers={"Authorization": f"Bearer {key}", **_UA},
            )
            r.raise_for_status()
            # NOTE: `content` here is a search SNIPPET, not the page. It must never be used as a
            # source body — verifying against a snippet is exactly the failure this product exists
            # to catch. Hence no `body`: this lane always goes through the fetch chain.
            return [
                {"url": x.get("url", ""), "title": x.get("title") or "", "content": x.get("content") or ""}
                for x in (r.json().get("results") or [])
                if x.get("url")
            ]

    return await cache.cached_call("search:ollama", req, call)


async def search_tavily(query: str, max_results: int = 8) -> list[dict]:
    """include_raw_content=True returns full page text, which lets the fetch chain skip a
    round-trip entirely for Tavily-sourced URLs. Raises with no key; search_all turns that into
    [] for this lane — never blocks."""
    req = {"query": query, "max_results": max_results, "include_raw_content": True}

    async def call() -> list[dict]:
        key = config.api_key("TAVILY_API_KEY")
        if not key:
            raise LaneError("tavily search: no TAVILY_API_KEY")
        async with httpx.AsyncClient(timeout=45.0) as c:
            r = await c.post(
                "https://api.tavily.com/search",
                json=req,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            if r.status_code != 200:
                raise LaneError(f"tavily search: HTTP {r.status_code}")
            d = r.json()
            out = []
            for x in d.get("results") or []:
                if not x.get("url"):
                    continue
                out.append({
                    "url": x["url"],
                    "title": x.get("title") or "",
                    "content": x.get("content") or "",
                    # raw_content is the FULL page -> a legitimate body, skips the fetch chain
                    "body": x.get("raw_content") or "",
                    "score": x.get("score"),
                })
            return out

    return await cache.cached_call("search:tavily", req, call)


async def search_openalex(query: str, max_results: int = 6) -> list[dict]:
    """Keyless. Primary sources — 'prefer the paper over someone's summary of it' is doctrine
    from researcher.md, and this is what makes it true rather than aspirational."""
    req = {"search": query, "per-page": max_results}

    async def call() -> list[dict]:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as c:
            r = await c.get(
                "https://api.openalex.org/works",
                params={"search": query, "per-page": max_results, "mailto": "receipts@local"},
                headers=_UA,
            )
            if r.status_code != 200:
                raise LaneError(f"openalex search: HTTP {r.status_code}")
            out = []
            for w in r.json().get("results") or []:
                url = w.get("doi") or (w.get("primary_location") or {}).get("landing_page_url") or ""
                if not url:
                    continue
                inv = w.get("abstract_inverted_index")
                abstract = _deinvert(inv) if inv else ""
                out.append({
                    "url": url,
                    "title": w.get("title") or w.get("display_name") or "",
                    "content": abstract,
                    # The abstract IS the paper's own words — a legitimate primary-source body.
                    # Measured: fetching the DOI instead costs ~20s (doi.org -> publisher redirect)
                    # and usually lands on a paywall. We already have the text; don't pay for it twice.
                    "body": abstract,
                    "year": w.get("publication_year"),
                    "cited_by": w.get("cited_by_count"),
                })
            return out

    return await cache.cached_call("search:openalex", req, call)


def _deinvert(inv: dict[str, list[int]]) -> str:
    """OpenAlex ships abstracts as an inverted index for licensing reasons. Rebuild the text."""
    if not inv:
        return ""
    pos: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    pos.sort()
    return " ".join(w for _, w in pos)


_LANES = {"ollama": search_ollama, "tavily": search_tavily, "openalex": search_openalex}


async def search_all(query: str, lanes: tuple[str, ...], max_results: int = 8) -> dict[str, list[dict]]:
    """Fire every requested lane concurrently. A lane that errors contributes [] rather than
    killing the search — a dead Tavily key must not take down the run."""
    names = [n for n in lanes if n in _LANES]
    results = await asyncio.gather(
        *(_LANES[n](query, max_results) for n in names), return_exceptions=True
    )
    return {
        n: (r if isinstance(r, list) else [])
        for n, r in zip(names, results)
    }


# ─────────────────────────── fetch chain ───────────────────────────

async def _fetch_ollama(url: str) -> dict[str, Any]:
    async def call() -> dict[str, Any]:
        key = os.environ.get("OLLAMA_API_KEY")
        if not key:
            raise LaneError("ollama fetch: no OLLAMA_API_KEY")
        async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT) as c:
            r = await c.post(
                f"{config.OLLAMA_CLOUD_URL}/api/web_fetch",
                json={"url": url},
                headers={"Authorization": f"Bearer {key}", **_UA},
            )
            if r.status_code != 200:
                raise LaneError(f"ollama fetch: HTTP {r.status_code}")
            d = r.json()
            return {"title": d.get("title") or "", "content": d.get("content") or ""}

    return await cache.cached_call("fetch:ollama", {"url": url}, call)


async def _fetch_jina(url: str) -> dict[str, Any]:
    """Keyless, renders JS server-side, returns markdown. This is why Playwright is cut:
    it does the same job in ~1s with zero install and zero browser binaries."""
    async def call() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT, follow_redirects=True) as c:
            r = await c.get(f"https://r.jina.ai/{url}", headers=_UA)
            if r.status_code != 200:
                raise LaneError(f"jina fetch: HTTP {r.status_code}")
            text = r.text
            title = ""
            if text.startswith("Title:"):
                title = text.split("\n", 1)[0][6:].strip()
            return {"title": title, "content": text}

    return await cache.cached_call("fetch:jina", {"url": url}, call)


async def fetch(url: str, body: str = "") -> dict[str, Any]:
    """Ollama -> Jina -> give up. `body` short-circuits the chain when a lane already returned
    real page text (Tavily raw_content, OpenAlex abstract) — never a search snippet.

    Returns {} when every fetcher fails — the caller DROPS the source rather than verifying a
    claim against an empty body, which would produce a confident but meaningless 'unsupported'.

    Content is cut to SOURCE_BODY_CHARS HERE, where every page enters the agent and verify path.
    The cut used to live only in fetch_many, which nothing calls — so read_page handed agents and
    every verify prompt whole pages (Tavily raw_content, Jina markdown: 100k+ chars), far past
    num_ctx.
    """
    url = normalize_url(url)
    thin = config.THIN_CONTENT_CHARS
    cap = config.SOURCE_BODY_CHARS

    if body and len(body) >= thin:
        return {"url": url, "title": "", "content": body[:cap], "via": "lane:body"}

    for name, fn in (("ollama", _fetch_ollama), ("jina", _fetch_jina)):
        try:
            d = await fn(url)
        except Exception:
            continue
        if d and len(d.get("content") or "") >= thin:
            return {"url": url, "title": d.get("title") or "", "content": d["content"][:cap],
                    "via": name}

    if body:
        return {"url": url, "title": "", "content": body[:cap], "via": "lane:body(short)"}
    return {}


async def fetch_many(items: list[dict]) -> list[dict]:
    """items: [{url, title, raw_content?}]. Concurrent, bounded, failures dropped."""
    sem = asyncio.Semaphore(config.SEM_FETCH)

    async def one(it: dict) -> dict | None:
        async with sem:
            try:
                d = await fetch(it["url"], it.get("body") or "")
            except Exception:
                return None
        if not d:
            return None
        return {
            "url": d["url"],
            "title": d.get("title") or it.get("title") or d["url"],
            "domain": domain(d["url"]),
            "content": d["content"][: config.SOURCE_BODY_CHARS],
            "via": d.get("via", ""),
            "lanes": it.get("_lanes", []),
        }

    out = await asyncio.gather(*(one(i) for i in items), return_exceptions=True)
    return [o for o in out if isinstance(o, dict) and o]
