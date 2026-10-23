"""Provider façade. Routes on the model id: "groq/x" -> openai_compat, bare -> ollama native.

Everything downstream imports THIS, never a concrete provider, so swapping a stage's model to a
different vendor is a config change and nothing else. That is also what makes the per-stage model
picker real rather than decorative.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from . import cache, ollama, openai_compat
from .runcfg import (  # noqa: F401 — re-exported
    effective_models, key_for, model_for, report, set_reporter, set_run_overrides,
)


class LLMError(RuntimeError):
    pass


def chat(model: str, messages: list[dict], **kw) -> AsyncIterator[dict[str, Any]]:
    if openai_compat.is_compat(model):
        return openai_compat.chat(model, messages, **kw)
    return ollama.chat(model, messages, **kw)


async def embeddings(model: str, texts: list[str]) -> list[list[float]]:
    """Embed a batch of strings -> one vector each. Routed by model id like chat(); cached at the
    facade so an identical batch is a free hit (and replays offline). Empty input short-circuits."""
    if not texts:
        return []

    async def _call() -> list[list[float]]:
        if openai_compat.is_compat(model):
            return await openai_compat.embeddings(model, texts)
        return await ollama.embeddings(model, texts)

    return await cache.cached_call("embed", {"model": model, "input": texts}, _call)


async def complete(model: str, messages: list[dict], **kw) -> str:
    out = ""
    async for ev in chat(model, messages, **kw):
        if ev["type"] == "done":
            out = ev["content"]
    return out


async def complete_json(model: str, messages: list[dict], **kw) -> Any:
    """Parse JSON out of a completion, tolerating ``` fences, prose padding, and <think> blocks."""
    raw = (await complete(model, messages, **kw)).strip()

    # Reasoning models on OpenAI-compat endpoints leak <think>…</think> into content.
    if "</think>" in raw:
        raw = raw.rsplit("</think>", 1)[1].strip()

    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try the bracket that OPENS first. A fixed "[" then "{" order turned
        # `Here: {"claims": ["a", "b"]} done` into the inner list ["a", "b"], not the object.
        pairs = sorted((("[", "]"), ("{", "}")),
                       key=lambda p: raw.find(p[0]) if p[0] in raw else len(raw))
        for opener, closer in pairs:
            i, j = raw.find(opener), raw.rfind(closer)
            if i != -1 and j > i:
                try:
                    return json.loads(raw[i : j + 1])
                except json.JSONDecodeError:
                    continue
        raise LLMError(f"{model}: non-JSON response: {raw[:200]}")
