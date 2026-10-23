"""Document upsert with content dedup — the SourceRegistry 'global dedup on first sight' idea, in
SQL. Returns (document_id, created); created=False means an identical document already existed."""
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
        existing = await c.fetchval(
            "select id from documents where workspace_id=$1 and content_sha1=$2", workspace_id, h,
        )
        return str(existing), False
