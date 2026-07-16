"""Ollama chat. Lifted from jarvis/jarvis/runtime/llm.py, with caching bolted on at the turn level.

The retry logic here is not defensive padding — jarvis's comment names qwen3.5 as throwing
intermittent 5xx mid-stream, and qwen3.5 is our verifier at ~45 calls per deep run. Without this
the board fills with holes.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
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


def _tidy(msg: str) -> str:
    """One line, no JSON envelope. `{"error":"too many concurrent requests"}` reads as noise."""
    m = re.sub(r'\{"error":\s*"([^"]+)"\}', r"\1", msg)
    return " ".join(m.split())[:150]


# ——— one gate for the whole provider ————————————————————————————————
# THE 429 FIX. Per-stage semaphores cannot bound what a provider actually sees: SEM_VERIFY=4 caps
# verifies, but deep mode also runs SEM_AGENTS=4 agent turns and SEM_REWRITE=3 rewrites through
# this same endpoint — up to ELEVEN concurrent requests, against a free tier that starts refusing
# around three. Every stage was individually well-behaved and collectively over the limit, which
# is why tuning SEM_VERIFY alone never stopped "too many concurrent requests".
#
# So the cap lives where the constraint lives: one semaphore in front of the transport, counting
# every call regardless of which stage made it.
_INFLIGHT = asyncio.Semaphore(config.OLLAMA_MAX_INFLIGHT)

# "too many concurrent requests" is a statement about the whole PROCESS, not about the one call
# that happened to receive it. Each call retrying on its own schedule means the others in flight
# walk straight back into the same wall, which is how a single 429 becomes "retry 5/6 in 30s" on
# every worker at once. One 429 parks every caller for the same window.
_cooldown_until = 0.0


def _hold_off(seconds: float) -> None:
    global _cooldown_until
    _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


async def _await_cooldown() -> None:
    while True:
        left = _cooldown_until - time.monotonic()
        if left <= 0:
            return
        await asyncio.sleep(min(0.5, left))


async def _replay(final: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Re-chunk a cached turn. We store the final text, not the original deltas — visually
    identical on screen, a fraction of the code, and it survives a provider changing its chunking.

    The pacing exists so a replayed draft still TYPES on screen instead of teleporting. It is only
    worth paying where a human is watching the tokens: the researchers' drafts and the lead's
    answer. A verifier turn is ~120 chars of JSON nobody ever sees, and there are hundreds of them
    — pacing those spent ~90s of a 118s replay on invisible sleeps. Long content is prose; short
    content is machinery.
    """
    content = final.get("content") or ""
    if len(content) >= config.REPLAY_PROSE_CHARS and config.REPLAY_DELAY > 0:
        for i in range(0, len(content), 6):
            yield {"type": "content", "delta": content[i : i + 6]}
            await asyncio.sleep(config.REPLAY_DELAY)
    elif content:
        yield {"type": "content", "delta": content}
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
            # LLMError is already raised as "{model}: ...", so never prefix the model again here —
            # that produced "kimi-k2.6:cloud: kimi-k2.6:cloud: HTTP 429: ...".
            if emitted or not _is_transient(str(e)) or attempt == attempts - 1:
                runcfg.report("provider", _tidy(str(e)))
                raise
            delay = min(30.0, 2.0 * 2**attempt)
            # A 429 is about the whole process, not this one call: back every caller off together,
            # or five more calls immediately retry into the same wall.
            if "429" in str(e) or "concurrent" in str(e).lower():
                _hold_off(delay)
            # Say it out loud. Silently sleeping 32s is why the run looked wedged.
            runcfg.report("provider", f"{_tidy(str(e))} — retry {attempt + 1}/{attempts} in {delay:.0f}s")
            await asyncio.sleep(delay)
        except httpx.HTTPError as e:
            # Timeouts, connect failures and mid-stream drops arrive as httpx exceptions, NOT
            # LLMError — without this branch they skip the retry ladder entirely, which means
            # the flakiest failures were the only ones never retried.
            if emitted or attempt == attempts - 1:
                runcfg.report("provider", f"{model}: {type(e).__name__}")
                raise LLMError(f"{model}: {type(e).__name__}: {e}") from e
            delay = min(30.0, 2.0 * 2**attempt)
            runcfg.report(
                "provider",
                f"{model}: {type(e).__name__} — retry {attempt + 1}/{attempts} in {delay:.0f}s",
            )
            await asyncio.sleep(delay)


async def _chat_once(model, messages, tools, num_ctx, temperature, timeout):
    # Another caller's 429 parks this one too — that is the whole point of a shared cooldown.
    await _await_cooldown()
    async with _INFLIGHT:          # the provider counts requests, not stages
        async for ev in _chat_stream(model, messages, tools, num_ctx, temperature, timeout):
            yield ev


async def _chat_stream(model, messages, tools, num_ctx, temperature, timeout):
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
