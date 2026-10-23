"""The single-agent perceive-act loop. Lifted from jarvis/jarvis/runtime/loop.py:30-242.

Three things here are hard-won and were kept verbatim in spirit:
  * forced-verdict finalization (jarvis :87-102) — models act until the last step and never
    volunteer a conclusion. A sub-agent returning "(stopped after 4 steps)" is a hole in the merge.
  * the 80% wrap-up nudge (:128-136) — at max_steps=4 this fires at step 3.
  * _race_cancel (:30-47) — with 4 concurrent sub-agents, a stop that only lands between steps
    leaves 4 in-flight calls burning free-tier budget.

Stripped: policy/bus/db (8 call sites -> ctx.emit), image handling, message trimming.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, Awaitable

from ..providers import llm
from . import tools
from .registry import AgentSpec
from .tools import Cancelled, Ctx


async def _race_cancel(coro: Awaitable[Any], cancel: asyncio.Event) -> Any:
    """Run coro but abandon it the moment the user hits stop. Without this a kill only lands
    between steps and the in-flight model call keeps burning."""
    task = asyncio.ensure_future(coro)
    waiter = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if waiter in done:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
            raise Cancelled("stopped by user")
        return task.result()
    finally:
        waiter.cancel()
        with contextlib.suppress(BaseException):
            await waiter
        # Stop, GC and the run deadline all set the event AND cancel the run's task, and the task
        # cancel lands first — in asyncio.wait above, which never cancels what it waits on. Without
        # this the in-flight turn was orphaned: it kept streaming, retrying and holding an
        # _INFLIGHT slot after the UI said "cancelled", starving the next run.
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task


async def run_agent(spec: AgentSpec, ctx: Ctx, prompt: str, system_extra: str = "") -> str:
    system = spec.prompt + (f"\n\n{system_extra}" if system_extra else "")
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    tool_schemas = tools.schemas(list(spec.tools)) if spec.tools else None

    final = await _run_steps(spec, ctx, messages, tool_schemas)
    if final is not None:
        return final

    # Fell out of the step loop with no final answer. Force one: models act right up to the
    # budget and never volunteer a conclusion, handing the caller a useless "(stopped after N)".
    # One last turn with NO tools, so the only legal move is to summarise what it actually saw.
    ctx.emit("agent_status", {"agent_id": ctx.agent, "status": "drafting", "detail": "forced verdict"})
    messages.append({
        "role": "user",
        "content": (
            "You are out of actions — do NOT call any tool. Write your final answer now from what "
            "you have already read, citing sources with [n] exactly as instructed. State plainly "
            "anything you could not verify. Do not claim you read something you did not."
        ),
    })
    content, _t, _c, _a = await _race_cancel(_one_call(spec, messages, None, ctx), ctx.cancel)
    if content.strip():
        return content.strip()
    return f"(stopped after {spec.max_steps} steps without a final answer)"


async def _run_steps(spec: AgentSpec, ctx: Ctx, messages: list[dict], tool_schemas) -> str | None:
    """Returns the final answer, or None if the step budget ran out (caller forces a verdict)."""
    final = ""
    warned = False

    for idx in range(spec.max_steps):
        if ctx.cancel.is_set():
            raise Cancelled("stopped by user")

        if not warned and idx >= int(spec.max_steps * 0.8):
            warned = True
            messages.append({
                "role": "user",
                "content": (
                    f"You have about {spec.max_steps - idx} actions left. Stop exploring now and "
                    "finish: do only what is essential, then write your final answer."
                ),
            })

        content, thinking, calls, assistant = await _race_cancel(
            _one_call(spec, messages, tool_schemas, ctx), ctx.cancel
        )

        if content.strip():
            final = content.strip()

        if not calls:
            return final or "(no answer)"

        messages.append(assistant)

        # Models emit several tool calls in ONE turn — observed: 3 web_search in step 0, then
        # 2 read_page in step 1. jarvis dispatched these serially, which turns 3 independent
        # 3s searches into 9s of dead wall-clock for no reason. Run them concurrently and append
        # the results IN CALL ORDER (models expect tool results positionally).
        async def _run(i: int, call: dict) -> tuple[int, str, str]:
            name, cargs = call["name"], call["arguments"]
            call_id = f"{ctx.agent}.{idx}.{i}.{name}"
            preview = json.dumps(cargs, default=str)[:180]
            ctx.emit("agent_tool", {
                "agent_id": ctx.agent, "call_id": call_id, "tool": name,
                "args_preview": preview, "status": "running",
            })
            t0 = asyncio.get_event_loop().time()
            result = await _race_cancel(tools.dispatch(name, cargs, ctx), ctx.cancel)
            text = result if isinstance(result, str) else json.dumps(result, default=str)
            ctx.emit("agent_tool", {
                "agent_id": ctx.agent, "call_id": call_id, "tool": name,
                "args_preview": preview, "status": "done", "result_preview": text[:220],
                "ms": int((asyncio.get_event_loop().time() - t0) * 1000),
            })
            return i, name, text

        results = await asyncio.gather(*(_run(i, c) for i, c in enumerate(calls)))
        for _i, name, text in sorted(results, key=lambda r: r[0]):
            # NOTE: no tool_call_id. Correct for Ollama native /api/chat; an OpenAI-compat
            # adapter MUST translate this or the request 400s.
            messages.append({"role": "tool", "tool_name": name, "content": text})

    return None  # budget exhausted; run_agent forces a verdict


async def _one_call(spec: AgentSpec, messages: list[dict], tool_schemas, ctx: Ctx):
    """Accumulate one streamed turn into (content, thinking, calls, assistant).

    Retry lives inside llm.chat(): 6 attempts, exponential backoff, only while nothing has been
    emitted. qwen3.5 throws intermittent mid-stream 5xx and it is our verifier at ~45 calls/run.
    """
    content = thinking = ""
    calls: list[dict] = []
    assistant: dict = {"role": "assistant", "content": ""}

    async for ev in llm.chat(spec.model, messages, tools=tool_schemas, num_ctx=spec.num_ctx):
        t = ev["type"]
        if t == "content":
            ctx.emit("agent_token", {"agent_id": ctx.agent, "text": ev["delta"]})
        elif t == "done":
            content, thinking = ev["content"], ev["thinking"]
            calls, assistant = ev["calls"], ev["message"]
    return content, thinking, calls, assistant
