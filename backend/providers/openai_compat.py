"""OpenAI-shaped /v1/chat/completions adapter (Groq, OpenRouter, Google, local endpoints).

This exists for two reasons, and the second one turned out to matter more than the first:

  1. BYOK — bring any provider.
  2. SPEED. Measured, same 6k-char source, same verify prompt:
        Ollama Cloud kimi-k2.6          ~8.0s/call   (and it SERIALIZES: sem=12 was slower than sem=6)
        Groq llama-3.3-70b-versatile     0.71s/call   -> 0.14s/call at 6 concurrent
     45 verdicts: ~66s on Ollama vs ~6s on Groq. Ollama Cloud is fine for the writer (one long
     stream) and hopeless for the verifier (dozens of short parallel calls). This adapter is what
     makes a live run possible at all.

MODEL IDS ARE NAMESPACED: "groq/llama-3.3-70b-versatile". A bare id means Ollama native.

THE TOOL-CALL GOTCHA: Ollama native appends tool results as {"role":"tool","tool_name":..} with NO
tool_call_id. OpenAI-compat REQUIRES tool_call_id and will 400 without it. _translate() repairs
that on the way out, so runtime/loop.py can stay Ollama-shaped.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from .. import config
from . import cache, runcfg

ENDPOINTS: dict[str, tuple[str, str]] = {
    # prefix -> (base_url, env var holding the key)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
}


class LLMError(RuntimeError):
    pass


def is_compat(model: str) -> bool:
    return model.split("/", 1)[0] in ENDPOINTS


def _split(model: str) -> tuple[str, str]:
    prefix, _, rest = model.partition("/")
    return prefix, rest


_ENV_TO_PROVIDER = {"GROQ_API_KEY": "groq", "OPENROUTER_API_KEY": "openrouter", "GEMINI_API_KEY": "google"}


def _key(env: str) -> str | None:
    byok = runcfg.key_for(_ENV_TO_PROVIDER.get(env, ""))
    if byok:
        return byok.strip()
    k = os.environ.get(env)
    if k:
        return k.strip().strip('"').strip("'")
    # Fall back to the user's other projects. NOTE: scholardesk's GROQ key is REVOKED (401);
    # continuity's works. Order matters — verified 2026-07-16.
    for p in ("/home/demo/projects/continuity/.env", "/home/demo/projects/scholardesk/.env.local"):
        f = Path(p)
        if not f.exists():
            continue
        m = re.search(rf'^\s*{env}\s*=\s*["\']?([^"\'\n]+)', f.read_text(), re.M)
        if m:
            return m.group(1).strip()
    return None


def _translate(messages: list[dict]) -> list[dict]:
    """Ollama-shaped -> OpenAI-shaped. The tool_call_id repair is the whole point."""
    out: list[dict] = []
    pending: list[str] = []  # tool_call_ids emitted by the last assistant turn, in order
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            a: dict[str, Any] = {"role": "assistant", "content": m.get("content") or ""}
            tcs = m.get("tool_calls") or []
            if tcs:
                a["tool_calls"] = []
                pending = []
                for i, tc in enumerate(tcs):
                    fn = tc.get("function") or {}
                    tid = tc.get("id") or f"call_{len(out)}_{i}"
                    pending.append(tid)
                    args = fn.get("arguments")
                    a["tool_calls"].append({
                        "id": tid, "type": "function",
                        "function": {
                            "name": fn.get("name", ""),
                            "arguments": args if isinstance(args, str) else json.dumps(args or {}),
                        },
                    })
            out.append(a)
        elif role == "tool":
            # Ollama gives us no id; pair positionally with the assistant turn's calls.
            tid = pending.pop(0) if pending else f"call_orphan_{len(out)}"
            out.append({"role": "tool", "tool_call_id": tid, "content": m.get("content") or ""})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


async def chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict] | None = None,
    num_ctx: int = 32768,
    temperature: float | None = None,
    timeout: float = 180.0,
) -> AsyncIterator[dict[str, Any]]:
    req = {"model": model, "messages": messages, "tools": tools,
           "num_ctx": num_ctx, "temperature": temperature}
    mode = config.RESEARCH_MODE
    if mode in ("auto", "replay"):
        hit = cache.get("chat", req)
        if hit is None and mode == "replay":
            hit = cache.get_any_model("chat", req)
        if hit is not None:
            from .ollama import _replay
            async for ev in _replay(hit):
                yield ev
            return
        if mode == "replay":
            raise cache.CacheMiss(f"replay miss: chat {model}")

    final = None
    async for ev in _retry(model, messages, tools, temperature, timeout):
        if ev.get("type") == "done":
            final = ev
        yield ev
    if final:
        cache.put("chat", req, final)


async def _retry(model, messages, tools, temperature, timeout):
    for attempt in range(5):
        emitted = False
        try:
            async for ev in _once(model, messages, tools, temperature, timeout):
                emitted = True
                yield ev
            return
        except LLMError as e:
            s = str(e).lower()
            transient = any(t in s for t in ("429", "500", "502", "503", "504", "overload", "timeout"))
            if emitted or not transient or attempt == 4:
                runcfg.report("provider", f"{model}: {str(e)[:160]}")
                raise
            delay = min(20.0, 1.5 * 2**attempt)
            runcfg.report("provider", f"{model}: {str(e)[:110]} — retry {attempt + 1}/5 in {delay:.0f}s")
            await asyncio.sleep(delay)
        except httpx.HTTPError as e:
            # Stalls and connection drops are httpx exceptions, not LLMError — see ollama.py.
            if emitted or attempt == 4:
                runcfg.report("provider", f"{model}: {type(e).__name__}: {str(e)[:140]}")
                raise LLMError(f"{model}: {type(e).__name__}: {e}") from e
            delay = min(20.0, 1.5 * 2**attempt)
            runcfg.report("provider", f"{model}: {type(e).__name__} — retry {attempt + 1}/5 in {delay:.0f}s")
            await asyncio.sleep(delay)


async def embeddings(model: str, texts: list[str], timeout: float = 120.0) -> list[list[float]]:
    """Embed a batch via an OpenAI-shaped /embeddings endpoint (Google/OpenAI-compat). Caching
    lives in the llm facade. Order is preserved by `index` per the OpenAI spec."""
    prefix, real = _split(model)
    base, env = ENDPOINTS[prefix]
    key = _key(env)
    if not key:
        raise LLMError(f"{model}: no {env} configured")
    payload = {"model": real, "input": texts}
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
        resp = await client.post(
            f"{base}/embeddings", json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            raise LLMError(f"{model}: HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
    rows = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in rows]


async def _once(model, messages, tools, temperature, timeout):
    prefix, real = _split(model)
    base, env = ENDPOINTS[prefix]
    key = _key(env)
    if not key:
        raise LLMError(f"{model}: no {env} configured")

    payload: dict[str, Any] = {
        "model": real,
        "messages": _translate(messages),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools

    content = ""
    calls_acc: dict[int, dict] = {}
    tin = tout = 0

    # Per-read stall budget, not a total cap — a healthy stream resets it every chunk.
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode(errors="replace")[:300]
                raise LLMError(f"{model}: HTTP {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if u := chunk.get("usage"):
                    tin = u.get("prompt_tokens", tin) or tin
                    tout = u.get("completion_tokens", tout) or tout
                for ch in chunk.get("choices") or []:
                    d = ch.get("delta") or {}
                    if d.get("content"):
                        content += d["content"]
                        yield {"type": "content", "delta": d["content"]}
                    # tool_calls stream in fragments indexed by position; accumulate then parse once
                    for tc in d.get("tool_calls") or []:
                        i = tc.get("index", 0)
                        e = calls_acc.setdefault(i, {"id": None, "name": "", "args": ""})
                        if tc.get("id"):
                            e["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            e["name"] += fn["name"]
                        if fn.get("arguments"):
                            e["args"] += fn["arguments"]

    calls, raw = [], []
    for i in sorted(calls_acc):
        e = calls_acc[i]
        try:
            args = json.loads(e["args"]) if e["args"] else {}
        except json.JSONDecodeError:
            args = {"_raw": e["args"]}
        calls.append({"name": e["name"], "arguments": args})
        raw.append({"id": e["id"] or f"call_{i}", "type": "function",
                    "function": {"name": e["name"], "arguments": e["args"] or "{}"}})

    assistant: dict[str, Any] = {"role": "assistant", "content": content}
    if raw:
        assistant["tool_calls"] = raw
    if calls:
        yield {"type": "tool_calls", "calls": calls}
    yield {"type": "done", "tokens_in": tin, "tokens_out": tout, "content": content,
           "thinking": "", "calls": calls, "message": assistant}
