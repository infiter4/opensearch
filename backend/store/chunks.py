"""Chunk writes + the three retrieval lanes (dense / keyword / graph).

The retriever SQL lives here; the retrieval package composes it. Each lane returns rows shaped for
rrf.fuse: a stable `corpus://slug/sha/ordinal` url (ordinal in the PATH so distinct chunks don't
collapse when normalize_url drops the fragment), plus title/body/locator and a lane score.
"""
from __future__ import annotations

from . import db


async def insert_chunks(workspace_id, document_id, chunks, embeddings) -> int:
    rows = [
        (workspace_id, document_id, ch.ordinal, ch.body, ch.locator,
         ch.char_start, ch.char_end, ch.token_count, emb)
        for ch, emb in zip(chunks, embeddings)
    ]
    if not rows:
        return 0
    p = await db.pool()
    async with p.acquire() as c:
        await c.executemany(
            "insert into chunks(workspace_id, document_id, ordinal, body, locator, char_start, "
            "                   char_end, token_count, embedding) "
            "values($1,$2,$3,$4,$5,$6,$7,$8,$9) "
            "on conflict (document_id, ordinal) do nothing",
            rows,
        )
    return len(rows)


# ── retrieval lanes ─────────────────────────────────────────────────────────
_SELECT = (
    "'corpus://' || w.slug || '/' || d.content_sha1 || '/' || c.ordinal as url, "
    "d.title as title, c.body as body, c.locator as locator, c.id as chunk_id, "
    "c.document_id as document_id"
)


async def dense(workspace_id, query_vec, k: int) -> list[dict]:
    p = await db.pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            f"select {_SELECT}, 1 - (c.embedding <=> $2::vector) as score "
            "from chunks c join documents d on d.id=c.document_id join workspaces w on w.id=c.workspace_id "
            "where c.workspace_id=$1 and c.embedding is not null "
            "order by c.embedding <=> $2::vector limit $3",
            workspace_id, query_vec, k,
        )
    return [dict(r) for r in rows]


async def keyword(workspace_id, query: str, k: int) -> list[dict]:
    p = await db.pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            f"select {_SELECT}, ts_rank_cd(c.tsv, plainto_tsquery('english', $2)) as score "
            "from chunks c join documents d on d.id=c.document_id join workspaces w on w.id=c.workspace_id "
            "where c.workspace_id=$1 and c.tsv @@ plainto_tsquery('english', $2) "
            "order by score desc limit $3",
            workspace_id, query, k,
        )
    return [dict(r) for r in rows]


async def by_url(workspace_id, url: str) -> dict | None:
    """Fetch one chunk body by its corpus:// url — for corpus_read. url = corpus://slug/sha/ordinal."""
    try:
        _, _, rest = url.partition("://")
        slug, sha, ordinal = rest.split("/", 2)
        ordinal = int(ordinal)
    except (ValueError, AttributeError):
        return None
    p = await db.pool()
    async with p.acquire() as c:
        row = await c.fetchrow(
            f"select {_SELECT} "
            "from chunks c join documents d on d.id=c.document_id join workspaces w on w.id=c.workspace_id "
            "where c.workspace_id=$1 and w.slug=$2 and d.content_sha1=$3 and c.ordinal=$4",
            workspace_id, slug, sha, ordinal,
        )
    return dict(row) if row else None
