"""An ingest that died between the document row and its chunks must not be called a dedup.

The DB is faked at the connection level, so the real ingest pipeline, upsert_document and
insert_chunks all run; only the SQL engine is stood in for (same `on conflict do nothing` and
"has chunks?" semantics as migrations/0001_init.sql).
"""
import asyncio
import contextlib

import pytest

from backend.ingest import pipeline as ingest
from backend.store import db


class FakeConn:
    def __init__(self):
        self.docs: dict[tuple, str] = {}       # (workspace_id, sha1) -> id   (unique constraint)
        self.chunks: dict[str, int] = {}       # document_id -> n chunks

    async def fetchrow(self, sql, *args):
        if sql.startswith("insert into documents"):
            key = (args[0], args[5])
            if key in self.docs:
                return None                      # on conflict do nothing
            self.docs[key] = f"doc{len(self.docs)}"
            return {"id": self.docs[key]}
        assert "has_chunks" in sql, sql
        did = self.docs[(args[0], args[1])]
        return {"id": did, "has_chunks": self.chunks.get(did, 0) > 0}

    async def executemany(self, sql, rows):
        for r in rows:
            self.chunks[r[1]] = self.chunks.get(r[1], 0) + 1


@pytest.fixture
def store(monkeypatch):
    conn = FakeConn()

    class Pool:
        @contextlib.asynccontextmanager
        async def acquire(self):
            yield conn

    async def pool():
        return Pool()

    monkeypatch.setattr(db, "pool", pool)
    return conn


WS = {"id": "w1", "slug": "notes", "embed_model": "embeddinggemma", "embed_dim": 4}
FILE = [("paper.md", b"hello world. " * 300)]


def test_a_failed_embed_does_not_poison_the_dedup(monkeypatch, store):
    fail = {"on": True}

    async def embed_texts(texts, model):
        if fail["on"]:
            raise RuntimeError("embeddinggemma: ConnectError")
        return [[0.0] * 4 for _ in texts]

    monkeypatch.setattr(ingest.embed, "embed_texts", embed_texts)

    with pytest.raises(RuntimeError):
        asyncio.run(ingest.ingest_items(WS, FILE))
    assert list(store.chunks) == []              # the row exists, chunkless

    fail["on"] = False                           # daemon up; the user re-uploads the same file
    again = asyncio.run(ingest.ingest_items(WS, FILE))
    assert again["documents"] == 1 and again["chunks"] > 0 and again["skipped"] == 0

    third = asyncio.run(ingest.ingest_items(WS, FILE))   # now it IS a dedup
    assert third["skipped"] == 1 and third["items"] == [{"doc": "paper.md", "dedup": True}]
