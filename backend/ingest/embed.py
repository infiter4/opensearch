"""Batch embedding over the llm facade (cached + replayable). Batched so one ingest of many chunks
is a handful of requests, not one per chunk."""
from __future__ import annotations

from ..providers import llm

BATCH = 64


async def embed_texts(texts: list[str], model: str) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        out.extend(await llm.embeddings(model, texts[i : i + BATCH]))
    return out
