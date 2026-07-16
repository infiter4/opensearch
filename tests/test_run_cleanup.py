"""Abandoning a run must not leak the global semaphores.

THE BUG THIS PINS: `run()` is an async generator. When the browser goes away — a reload, a closed
tab, a stop — FastAPI closes it, GeneratorExit fires at the yield, and the drain loop just ends.
The pipeline task was never cancelled, so it ran on with nobody reading it, still holding slots in
verify._SEM — which is module-GLOBAL and has six slots for the entire process.

Three reloads leaked all six. From then on every new run hung at exactly the same point: the first
`async with _SEM` in verification, forever. It looked like "deep research always gets stuck around
activity 72" — 72 being wherever checking happened to begin. Nothing errored, nothing logged, and
restarting the server "fixed" it, which is what made it look like a provider problem.
"""
from __future__ import annotations

import asyncio

from backend.pipeline import orchestrator, rewrite, verify


async def _abandon_mid_run() -> None:
    """Exactly what the server does when the client disconnects: consume, then aclose()."""
    gen = orchestrator.run("What are the rate limits of Ollama's web search API?", "lite")
    async for event, _ in gen:
        if event == "plan":       # far enough in that the pipeline is really working
            break
    await gen.aclose()


def test_abandoned_runs_do_not_leak_verify_slots():
    async def go():
        before = verify._SEM._value
        for _ in range(3):
            await _abandon_mid_run()
            await asyncio.sleep(0.6)
        await asyncio.sleep(1.0)
        return before, verify._SEM._value

    before, after = asyncio.run(go())
    assert after == before, (
        f"verify semaphore leaked: {before} -> {after}. Every abandoned run strands slots, and "
        f"once they are gone every later run blocks forever at the start of verification."
    )


def test_abandoned_runs_do_not_leak_rewrite_slots():
    async def go():
        before = rewrite._SEM._value
        await _abandon_mid_run()
        await asyncio.sleep(0.8)
        return before, rewrite._SEM._value

    before, after = asyncio.run(go())
    assert after == before, f"rewrite semaphore leaked: {before} -> {after}"


def test_closing_the_generator_early_is_clean():
    """Close before a single event is read — the cancel path must not raise."""
    async def go():
        gen = orchestrator.run("anything", "lite")
        await gen.__anext__()      # meta
        await gen.aclose()
        await asyncio.sleep(0.3)
        return verify._SEM._value

    assert asyncio.run(go()) == verify._SEM._value
