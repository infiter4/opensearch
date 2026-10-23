"""The ingestion run: bytes -> Doc -> chunks -> embeddings -> Supabase. Emits progress events (a
callback, so the HTTP layer can stream them). Synchronous per item; dedup skips re-ingests."""
from __future__ import annotations

from ..store import chunks as chunks_store
from ..store import documents as documents_store
from . import chunk as chunk_mod
from . import embed, loaders


async def ingest_items(workspace: dict, items: list[tuple[str, bytes]], emit=None) -> dict:
    """items: (filename, raw bytes). workspace: the row from workspaces.get_by_slug."""
    ws_id = workspace["id"]
    slug = workspace["slug"]
    model = workspace["embed_model"]
    dim = workspace["embed_dim"]

    def _emit(ev: str, data: dict) -> None:
        if emit:
            emit(ev, data)

    n_docs = n_chunks = skipped = 0
    results: list[dict] = []

    for filename, data in items:
        doc = loaders.load(filename, data)
        if not doc.text.strip():
            skipped += 1
            _emit("ingest_progress", {"doc": filename, "skipped": "empty"})
            results.append({"doc": filename, "skipped": "empty"})
            continue

        doc_id, created = await documents_store.upsert_document(
            ws_id, slug=slug, modality=doc.modality, title=doc.title,
            text=doc.text, source_uri=doc.source_uri, lang=doc.lang,
        )
        if not created:
            skipped += 1
            _emit("ingest_progress", {"doc": filename, "dedup": True})
            results.append({"doc": filename, "dedup": True})
            continue

        cks = chunk_mod.chunk_doc(doc)
        vecs = await embed.embed_texts([c.body for c in cks], model)
        if vecs and len(vecs[0]) != dim:
            raise ValueError(
                f"embedding dim {len(vecs[0])} != workspace dim {dim} "
                f"(model {model}); a workspace's embed model is frozen at creation"
            )
        inserted = await chunks_store.insert_chunks(ws_id, doc_id, cks, vecs)
        n_docs += 1
        n_chunks += inserted
        _emit("ingest_progress", {"doc": filename, "modality": doc.modality, "chunks": inserted})
        results.append({"doc": filename, "modality": doc.modality, "chunks": inserted})

    summary = {"documents": n_docs, "chunks": n_chunks, "skipped": skipped, "items": results}
    _emit("ingest_done", summary)
    return summary
