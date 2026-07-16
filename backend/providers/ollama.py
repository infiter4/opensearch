"""Ollama chat. Lifted from jarvis/jarvis/runtime/llm.py, with caching bolted on at the turn level.

The retry logic here is not defensive padding — jarvis's comment names qwen3.5 as throwing
intermittent 5xx mid-stream, and qwen3.5 is our verifier at ~45 calls per deep run. Without this
the board fills with holes.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator

import httpx

from .. import config
from . import cache, runcfg


class LLMError(RuntimeError):
    pass


def _endpoint(model: str) -> tuple[str, dict[str, str]]:
    """Cloud tags go direct to ollama.com when a key is present, else through the local daemon
    (which proxies them after `ollama signin`). Local models always use the daemon."""
    key = runcfg.key_for("ollama") or os.environ.get("OLLAMA_API_KEY")
    if model.endswith(":cloud") and key:
        return config.OLLAMA_CLOUD_URL, {"Authorization": f"Bearer {key}"}
    return config.OLLAMA_LOCAL_URL, {}


_TRANSIENT = (
    "internal server error", "bad gateway", "service unavailable", "gateway timeout",
    "temporarily", "overloaded", "rate limit", "too many requests",
    "429", "500", "502", "503", "504",
)


def _is_transient(err: str) -> bool:
    e = err.lower()
    return any(t in e for t in _TRANSIENT)


async def _replay(final: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Re-chunk a cached turn. We store the final text, not the original deltas — visually
    identical on screen, a fraction of the code, and it survives a provider changing its chunking."""
    content = final.get("content") or ""
    for i in range(0, len(content), 6):
        yield {"type": "content", "delta": content[i : i + 6]}
        await asyncio.sleep(0.012)
    if final.get("calls"):
        yield {"type": "tool_calls", "calls": final["calls"]}
    yield {**final, "type": "done", "cached": True}


async def chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict] | None = None,
    num_ctx: int = 32768,
    temperature: float | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a turn. Yields {'type':'content'|'thinking'|'tool_calls'|'done', ...}.

    Cached at TURN granularity: key is (model, messages, tools, num_ctx, temperature). Because the
    verifier's messages are derived only from (claim, source_text), an identical claim/source pair
    anywhere in the run — including the lead re-stating a sub-agent's sentence verbatim — is a
    free cache hit. That is what makes verifying the lead nearly free.
    """
    req = {
        "model": model, "messages": messages, "tools": tools,
        "num_ctx": num_ctx, "temperature": temperature,
    }
    mode = config.RESEARCH_MODE

    if mode in ("auto", "replay"):
        hit = cache.get("chat", req)
        if hit is not None:
            async for ev in _replay(hit):
                yield ev
            return
        if mode == "replay":
            raise cache.CacheMiss(f"replay miss: chat {model} ({len(messages)} msgs)")

    final: dict[str, Any] | None = None
    async for ev in _chat_retry(model, messages, tools, num_ctx, temperature, timeout):
        if ev.get("type") == "done":
            final = ev
        yield ev
    if final is not None:
        cache.put("chat", req, final)


async def _chat_retry(model, messages, tools, num_ctx, temperature, timeout):
    """Retry a transient failure only while nothing has been emitted. Once real output has
    streamed we cannot restart safely, so the error propagates."""
    attempts = 6
    for attempt in range(attempts):
        emitted = False
        try:
            async for ev in _chat_once(model, messages, tools, num_ctx, temperature, timeout):
                emitted = True
                yield ev
            return
        except LLMError as e:
            if emitted or not _is_transient(str(e)) or attempt == attempts - 1:
                raise
            await asyncio.sleep(min(30.0, 2.0 * 2**attempt))
        except httpx.HTTPError as e:
            # Timeouts, connect failures and mid-stream drops arrive as httpx exceptions, NOT
            # LLMError — without this branch they skip the retry ladder entirely, which means
            # the flakiest failures were the only ones never retried.
            if emitted or attempt == attempts - 1:
                raise LLMError(f"{model}: {type(e).__name__}: {e}") from e
            await asyncio.sleep(min(30.0, 2.0 * 2**attempt))


async def _chat_once(model, messages, tools, num_ctx, temperature, timeout):
    base, headers = _endpoint(model)
    opts: dict[str, Any] = {"num_ctx": num_ctx}
    if temperature is not None:
        opts["temperature"] = temperature
    payload: dict[str, Any] = {
        "model": model, "messages": messages, "stream": True, "options": opts,
    }
    if tools:
        payload["tools"] = tools

    content, thinking = "", ""
    calls: list[dict] = []
    raw_calls: list[dict] = []
    tin = tout = 0

    # `timeout` is the per-read STALL budget, not a total-duration cap. Streaming resets it on
    # every chunk, so a long generation that keeps emitting never trips it — only a stalled
    # stream does. The old value (600s total, applied to reads) turned one server-side stall
    # into a 10-minute black hole per attempt; two runs "hung" at lead-verify paying exactly that.
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
        async with client.stream("POST", f"{base}/api/chat", json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:400]
                raise LLMError(f"{model}: HTTP {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in chunk:
                    raise LLMError(f"{model}: {chunk['error']}")
                msg = chunk.get("message") or {}
                if msg.get("thinking"):
                    thinking += msg["thinking"]
                    yield {"type": "thinking", "delta": msg["thinking"]}
                if msg.get("content"):
                    content += msg["content"]
                    yield {"type": "content", "delta": msg["content"]}
                for tc in msg.get("tool_calls") or []:
                    raw_calls.append(tc)
                    fn = tc.get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"_raw": args}
                    calls.append({"name": fn.get("name", ""), "arguments": args or {}})
                if chunk.get("done"):
                    tin = chunk.get("prompt_eval_count", 0) or 0
                    tout = chunk.get("eval_count", 0) or 0

    # Thinking models must see their own prior turn replayed verbatim — dropping the tool_call ids
    # or the thinking block makes them emit reasoning with no answer.
    assistant: dict[str, Any] = {"role": "assistant", "content": content}
    if thinking:
        assistant["thinking"] = thinking
    if raw_calls:
        assistant["tool_calls"] = raw_calls

    if calls:
        yield {"type": "tool_calls", "calls": calls}
    yield {
        "type": "done", "tokens_in": tin, "tokens_out": tout,
        "content": content, "thinking": thinking, "calls": calls, "message": assistant,
    }


async def complete(model: str, messages: list[dict], **kw) -> str:
    """Non-streaming convenience for the JSON stages (planner/claims/verify/rewrite)."""
    out = ""
    async for ev in chat(model, messages, **kw):
        if ev["type"] == "done":
            out = ev["content"]
    return out


async def complete_json(model: str, messages: list[dict], **kw) -> Any:
    """Parse a JSON object/array out of a completion, tolerating ``` fences and prose padding."""
    raw = (await complete(model, messages, **kw)).strip()
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
