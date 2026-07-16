"""Provider façade. Routes on the model id: "groq/x" -> openai_compat, bare -> ollama native.

Everything downstream imports THIS, never a concrete provider, so swapping a stage's model to a
different vendor is a config change and nothing else. That is also what makes the per-stage model
picker real rather than decorative.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from . import ollama, openai_compat
from .runcfg import effective_models, key_for, model_for, set_run_overrides  # noqa: F401 — re-exported


class LLMError(RuntimeError):
    pass


def chat(model: str, messages: list[dict], **kw) -> AsyncIterator[dict[str, Any]]:
    if openai_compat.is_compat(model):
        return openai_compat.chat(model, messages, **kw)
    return ollama.chat(model, messages, **kw)


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
        for opener, closer in (("[", "]"), ("{", "}")):
            i, j = raw.find(opener), raw.rfind(closer)
            if i != -1 and j > i:
                try:
                    return json.loads(raw[i : j + 1])
                except json.JSONDecodeError:
                    continue
        raise LLMError(f"{model}: non-JSON response: {raw[:200]}")
