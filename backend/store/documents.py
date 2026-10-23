"""Document upsert with content dedup — the SourceRegistry 'global dedup on first sight' idea, in
SQL. Returns (document_id, created); created=False means an identical document was already fully
ingested (a row left chunkless by a failed ingest comes back as created=True, to be re-chunked)."""
from __future__ import annotations

import hashlib

from . import db


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


async def upsert_document(workspace_id, *, slug: str, modality: str, title: str, text: str,
                          source_uri: str, lang: str | None) -> tuple[str, bool]:
    h = sha1(text)
    uri = f"corpus://{slug}/{h}"
    p = await db.pool()
    async with p.acquire() as c:
        row = await c.fetchrow(
            "insert into documents(workspace_id, uri, source_uri, modality, title, content_sha1, "
            "                      n_chars, lang) "
            "values($1,$2,$3,$4,$5,$6,$7,$8) "
            "on conflict (workspace_id, content_sha1) do nothing "
            "returning id",
            workspace_id, uri, source_uri, modality, title, h, len(text), lang,
        )
        if row:
            return str(row["id"]), True
        existing = await c.fetchrow(
            "select d.id, exists(select 1 from chunks ch where ch.document_id = d.id) as has_chunks "
            "from documents d where d.workspace_id=$1 and d.content_sha1=$2", workspace_id, h,
        )
        # The document row is written before chunking/embedding, so an ingest that died between
        # the two (embed daemon down, dim mismatch) leaves a row with no chunks. Calling that a
        # dedup made the file unsearchable forever — every re-upload was skipped. A chunkless row
        # is not ingested: hand it back as created, and insert_chunks' on-conflict makes a
        # concurrent retry harmless.
        return str(existing["id"]), not existing["has_chunks"]
