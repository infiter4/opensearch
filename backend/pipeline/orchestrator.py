"""The run. An async generator of SSE events, debuggable from the CLI with no browser.

    python -m backend.pipeline.orchestrator "your question" --mode pro
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator, Callable

from .. import config
from ..providers import llm
from ..store import db as store_db
from ..store import workspaces as ws_store
from . import doer, heatmap, lead as lead_mod, planner, report as report_mod, rewrite, router, subagent
from .sources import SourceRegistry


async def run(question: str, mode: str = "pro", cancel: asyncio.Event | None = None,
              query_id: str | None = None, models: dict[str, str] | None = None,
              keys: dict[str, str] | None = None,
              on_registry: Callable[[SourceRegistry], None] | None = None,
              history: list[dict] | None = None, workspace: str | None = None,
              ) -> AsyncIterator[tuple[str, dict]]:
    """`query_id` MUST be the caller's session id when there is one. The frontend reads it out of
    the `meta` event and hangs every later lookup off it — /api/source/{id}?query_id=… resolves
    against the session registry. Minting a fresh uuid here instead handed the client an id no
    session was keyed by, so clicking a citation chip 404'd.

    `on_registry` hands the caller the live registry. The `source` EVENT carries identity only
    (n_chars, never the body) — streaming six thousand chars per source down the wire to a client
    that may never open one is waste. But the drawer needs the real page text to locate the quote
    in, so the server has to keep it: this is the seam that lets a session serve it on demand.
    """
    cancel = cancel or asyncio.Event()
    reg = SourceRegistry()
    if on_registry:
        on_registry(reg)
    query_id = query_id or uuid.uuid4().hex[:12]
    t0 = time.time()
    # BYOK: per-run model picks and keys, ContextVar-scoped so concurrent runs can't cross.
    llm.set_run_overrides(models, keys)

    # Sub-agents run concurrently, so they cannot yield into this generator directly. They push
    # onto a queue; the generator drains it. That is what makes the board fill live instead of
    # in per-agent batches.
    q: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    def emit(event: str, data: dict) -> None:
        q.put_nowait((event, data))

    # Let the transports narrate their own trouble. Without this a rate-limited provider backs off
    # for up to 32s per attempt in total silence, and the only honest thing the UI could say was
    # nothing at all.
    llm.set_reporter(lambda scope, message: emit("provider", {"scope": scope, "message": message}))

    # Optional corpus: when a workspace is bound (and the store is enabled) the sub-agents research
    # the ingested documents instead of the web. A missing/unknown workspace degrades to the web.
    ws_row = None
    if workspace and store_db.is_enabled():
        try:
            ws_row = await ws_store.get_by_slug(workspace)
        except Exception as e:
            emit("provider", {"scope": "store", "message": store_db.scrub(f"workspace lookup failed: {e}")})
        if ws_row is None:
            emit("error", {"scope": "workspace",
                           "message": f"workspace {workspace!r} not found — researching the web instead"})

    # Intent + auto-selected depth. Corpus availability nudges the depth up (retrieval pays off).
    route = await router.classify(question, history=history, corpus_available=ws_row is not None)
    if mode == "auto":
        mode = route.get("mode", "pro")
    preset = config.PRESETS.get(mode, config.PRESETS["pro"])

    yield "meta", {
        "query_id": query_id, "mode": config.RESEARCH_MODE, "search_mode": mode,
        "models": llm.effective_models(), "workspace": (ws_row["slug"] if ws_row else None),
        "preset": {
            "n_agents": preset.n_agents, "lanes": (["corpus"] if ws_row else list(preset.lanes)),
            "max_sources": preset.max_sources, "rewrite_iters": preset.rewrite_iters,
            "red_team": preset.red_team,
        },
    }
    yield "route", route

    async def do_task() -> dict:
        text = await doer.run_task(question, query_id, emit, cancel, history=history)
        emit("answer_done", {
            "text": text, "sentences": [], "gaps": [], "conflicts": [],
            "elapsed_s": round(time.time() - t0, 1),
        })
        return {"text": text}

    async def pipeline() -> dict:
        subtasks = await planner.plan(
            question, preset.n_agents, red_team=preset.red_team, history=history,
        )
        emit("plan", {"subtasks": subtasks})

        # Board columns/rows are declared as things are interned; the grid must exist on screen
        # before any prose does — that is what makes this not look like a chat app at second 1.
        sem = asyncio.Semaphore(config.SEM_AGENTS)

        async def one(st: dict) -> dict:
            async with sem:
                return await subagent.run_subagent(
                    st, reg, preset, planner.lanes_for(st, preset), emit, cancel, workspace=ws_row
                )

        reports = list(await asyncio.gather(*(one(st) for st in subtasks), return_exceptions=True))
        reports = [
            r if isinstance(r, dict) else subagent._failed(st, str(r))
            for st, r in zip(subtasks, reports)
        ]

        # Per-agent repair, then the merge. Agents repair CONCURRENTLY: each owns its own text,
        # sentences and claims, and only reads the registry — so serialising them here would just
        # stack three independent rewrite+reverify rounds end to end on the critical path.
        async def _repair(r: dict) -> list[dict]:
            if r.get("failed") or not preset.rewrite_iters:
                return []
            cells_ = heatmap.cells([r])
            if not any(c["verdict"] in ("unsupported", "contradicted") for c in cells_):
                return []
            emit("agent_status", {"agent_id": r["agent_id"], "status": "rewriting"})
            text, sents, cl, retr = await rewrite.repair(
                r["agent_id"], r["text"], reg, cells_, preset.rewrite_iters, emit
            )
            r.update(text=text, sentences=sents, claims=cl, iteration=1)
            r["verdicts"] = await _reverify(cl, reg)
            return retr

        repaired = await asyncio.gather(*(_repair(r) for r in reports), return_exceptions=True)
        all_retracted: list[dict] = []
        for r, out in zip(reports, repaired):
            if isinstance(out, BaseException):
                emit("error", {"scope": f"agent:{r['agent_id']}", "message": f"repair failed: {out}"})
                continue
            all_retracted += out

        for r in reports:
            if not r.get("failed"):
                emit("agent_report", {
                    "agent_id": r["agent_id"], "text": r["text"],
                    "trust": heatmap.trust(
                        heatmap.cells([r]), scope=f"agent:{r['agent_id']}",
                        retracted=[x for x in all_retracted if x["sentence_id"].startswith(r["agent_id"])],
                    ),
                    "retracted": [x for x in all_retracted if x["sentence_id"].startswith(r["agent_id"])],
                })

        gaps = lead_mod.gaps_from(reports, all_retracted)
        ld = await lead_mod.merge(question, reports, reg, gaps, emit)

        # The lead gets the SAME repair pipeline as the researchers. Its dict is shaped like a
        # sub-report on purpose — the merge is a second hallucination surface, and a final answer
        # wearing failures it could have healed (or honestly dropped) is a worse product than a
        # shorter, verified one.
        if preset.rewrite_iters:
            lead_cells = heatmap.cells([ld])
            if any(c["verdict"] in ("unsupported", "contradicted") for c in lead_cells):
                emit("agent_status", {"agent_id": "lead", "status": "rewriting"})
                try:
                    text, sents, cl, retr = await rewrite.repair(
                        "lead", ld["text"], reg, lead_cells, preset.rewrite_iters, emit
                    )
                    ld.update(text=text, sentences=sents, claims=cl, iteration=1)
                    ld["verdicts"] = await _reverify(cl, reg)
                    all_retracted += retr
                    gaps += [f"{x['text'][:110]} — {x['reason'][:80]}" for x in retr]
                except Exception as e:
                    emit("error", {"scope": "lead", "message": f"lead repair failed: {e}"})
        emit("agent_status", {"agent_id": "lead", "status": "done"})

        cells = heatmap.cells(reports, ld)
        emit("heatmap", {"rows": heatmap.rows(reports, ld, all_retracted), "cols": reg.columns()})
        emit("trust", heatmap.trust(cells, scope="final", retracted=all_retracted))
        for c in heatmap.contradictions(cells):
            emit("contradiction", c)

        emit("answer_done", {
            "text": ld["text"],
            "sentences": [
                {"id": s.id, "start": s.start, "end": s.end, "cited": list(s.cited)}
                for s in ld["sentences"]
            ],
            "gaps": gaps,
            "conflicts": heatmap.contradictions(cells),
            "elapsed_s": round(time.time() - t0, 1),
        })

        # Deep-mode closers, strictly AFTER the answer is on screen: they enrich the run,
        # they never delay it.
        # Always. graph() is pure code over verdicts the run already produced — no model call, no
        # network, microseconds. Gating it behind deep mode only denied lite and pro a free view
        # of their own provenance; the client decides whether to draw it.
        try:
            emit("graph", report_mod.graph(question, reports, reg, cells))
        except Exception as e:
            emit("error", {"scope": "graph", "message": f"{type(e).__name__}: {e}"})
        if preset.report:
            await report_mod.run_reporter(
                query_id, question, ld, heatmap.trust(cells, scope="final", retracted=all_retracted),
                cells, all_retracted, reg, emit, cancel,
            )
        return ld

    task = asyncio.create_task(do_task() if route["kind"] == "task" else pipeline())

    # A hard wall-clock ceiling so a run can NEVER hang forever. Provider stalls, a serialized
    # rewriter queue, or a question the corpus can't answer (endless failing-claim churn) could
    # otherwise leave the tab spinning for 15+ minutes. On the deadline we cancel, flush what's
    # queued, and finalize with a clear message — partial results stay on screen.
    budget = {"lite": 240.0, "pro": 480.0, "deep": 900.0}.get(mode, 480.0)
    deadline = t0 + budget

    # The finally is load-bearing, not hygiene. When the browser goes away — a reload, a closed
    # tab, a stop — FastAPI closes this async generator, GeneratorExit is raised at the yield, and
    # the loop below simply stops. Without cancelling `task`, the pipeline runs on forever with
    # nobody reading it, leaking module-global semaphore slots and spending rate limit it no
    # longer owns.
    try:
        timed_out = False
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                timed_out = True
                break
            drain = asyncio.create_task(q.get())
            done, _ = await asyncio.wait(
                {drain, task}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if drain in done:
                yield drain.result()
                continue
            drain.cancel()
            if task in done:                  # pipeline finished
                while not q.empty():          # flush anything queued as it wrapped up
                    yield q.get_nowait()
                break
            timed_out = True                  # nothing completed in the window -> deadline hit
            break

        if timed_out:
            cancel.set()
            if not task.done():
                task.cancel()
                try:
                    await task                # propagates into the gathers, freeing _SEM
                except (asyncio.CancelledError, Exception):
                    pass
            while not q.empty():
                yield q.get_nowait()
            yield "error", {"scope": "run", "message": (
                f"this run passed its {int(budget // 60)}-minute limit and was stopped — showing "
                "what completed. Try a narrower question, or Lite mode."
            )}
        elif task.exception():
            e = task.exception()
            yield "error", {"scope": "run", "message": f"{type(e).__name__}: {e}"}
        yield "done", {"elapsed_s": round(time.time() - t0, 1)}
    finally:
        cancel.set()                      # tell the agent loops to stop between steps
        if not task.done():
            task.cancel()
            try:
                await task                # cancellation propagates into the gathers, freeing _SEM
            except (asyncio.CancelledError, Exception):
                pass
        llm.set_reporter(None)


async def _reverify(claims_: list[dict], reg) -> dict:
    from . import claims as cm
    from . import verify
    return await verify.verify_all(cm.pairs(claims_), reg)


async def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--mode", default="pro", choices=list(config.PRESETS))
    ap.add_argument("--quiet", action="store_true", help="suppress token spam")
    ap.add_argument("--jsonl", action="store_true",
                    help="emit full untruncated {event, data} per line, no colour — pipeable")
    a = ap.parse_args()

    counts: dict[str, int] = {}
    async for event, data in run(a.question, a.mode):
        counts[event] = counts.get(event, 0) + 1
        if a.quiet and event in ("agent_token", "lead_token"):
            continue
        if a.jsonl:
            # The pretty view truncates to stay readable, which makes it unparseable — the quote
            # field alone blows the limit. Anything inspecting a run needs the whole event.
            print(json.dumps({"event": event, "data": data}, default=str))
        else:
            print(f"\x1b[36m{event}\x1b[0m {json.dumps(data, default=str)[:220]}")
    if a.jsonl:
        print(json.dumps({"event": "_counts", "data": counts}))
    else:
        print(f"\n\x1b[33mevent counts:\x1b[0m {counts}")


if __name__ == "__main__":
    asyncio.run(_cli())
