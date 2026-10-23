"""retrieve(): embed the query, run the dense + keyword lanes concurrently, fuse with RRF.

Fusion reuses backend/providers/rrf.py unchanged — a chunk found by BOTH lanes floats up carrying
both in `_lanes`, the same cross-lane corroboration signal the web path gets for free. The graph
lane and reranking slot in here later (M4/M5) as extra lanes / a post-fuse step; nothing downstream
changes because the output shape is stable.
"""
from __future__ import annotations

import asyncio

from ..providers import llm, rrf
from ..store import chunks as chunks_store


async def retrieve(workspace_id, embed_model: str, query: str, k: int = 10) -> list[dict]:
    """Return up to k fused chunk hits: {url, title, body, locator, _rrf, _lanes, ...}."""
    query = (query or "").strip()
    if not query:
        return []

    # Keyword needs only the text; dense needs the query embedding. Embed + keyword run together.
    qvecs, kw_hits = await asyncio.gather(
        llm.embeddings(embed_model, [query]),
        chunks_store.keyword(workspace_id, query, k),
    )
    dense_hits = await chunks_store.dense(workspace_id, qvecs[0], k) if qvecs else []

    fused = rrf.fuse({"dense": dense_hits, "keyword": kw_hits})
    return fused[:k]
