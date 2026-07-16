from __future__ import annotations

import asyncio

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import config, sessions, sse
from ..pipeline import concept, orchestrator
from ..providers import cache

router = APIRouter(prefix="/api")


class Turn(BaseModel):
    question: str = ""
    answer: str = ""


class ResearchIn(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    mode: str = "pro"
    keys: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)
    # Prior turns in this thread. Only the planner sees them — enough to resolve a follow-up,
    # and nowhere near the verifier, whose independence depends on seeing nothing but the claim
    # and the source text.
    history: list[Turn] = Field(default_factory=list, max_length=3)


@router.post("/research")
async def start(body: ResearchIn) -> dict:
    if body.mode not in config.PRESETS:
        raise HTTPException(400, f"unknown mode {body.mode!r}")
    s = sessions.create(body.question, body.mode, body.keys, body.models)
    s.history = [t.model_dump() for t in body.history]
    return {"query_id": s.query_id}


async def _drive(s: sessions.Session) -> None:
    """Run the pipeline once, into the session's buffer. Owned by the session, not by a reader."""
    try:
        async for event, data in orchestrator.run(
            s.question, s.mode, cancel=s.cancel, query_id=s.query_id,
            models=s.models, keys=s.keys, history=s.history,
            on_registry=lambda r: setattr(s, "registry", r),
        ):
            if event == "source":
                s.sources[data["id"]] = data
            elif event == "artifact":
                s.artifacts[data["id"]] = data
            elif event == "answer_done":
                s.answer_text = data.get("text") or ""
            s.push(event, data)
    except cache.CacheMiss as e:
        s.push("error", {"scope": "run", "message": f"replay miss — this run was never recorded. {e}"})
        s.push("done", {})
    except asyncio.CancelledError:
        s.push("error", {"scope": "run", "message": "run cancelled"})
        s.push("done", {})
        raise
    except Exception as e:
        s.push("error", {"scope": "run", "message": f"{type(e).__name__}: {e}"})
        s.push("done", {})
    finally:
        s.close()


@router.get("/research/stream")
async def stream(query_id: str, request: Request) -> StreamingResponse:
    s = sessions.get(query_id)
    if not s:
        raise HTTPException(404, "unknown or expired query_id")

    # Start it at most once. A reconnecting EventSource or a reloaded page must ATTACH to the run
    # in flight, never launch a second one.
    if s.task is None:
        s.task = asyncio.create_task(_drive(s))

    # Resume point: the browser's own Last-Event-ID on an automatic reconnect, else ?from=,
    # else the beginning — a fresh page replays the buffer instantly and then follows live.
    try:
        start = int(request.headers.get("last-event-id") or request.query_params.get("from") or 0)
    except ValueError:
        start = 0

    async def gen():
        i = max(0, start)
        while True:
            while i < len(s.events):
                event, data = s.events[i]
                yield sse.frame(event, data, eid=i)
                i += 1
            if s.finished and i >= len(s.events):
                return
            s.bell.clear()
            try:
                await asyncio.wait_for(s.bell.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"   # keep proxies and the browser from dropping a quiet run

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx would otherwise buffer the stream into one blob
            "Connection": "keep-alive",
        },
    )


@router.post("/research/{query_id}/stop")
async def stop(query_id: str) -> dict:
    s = sessions.get(query_id)
    if not s:
        raise HTTPException(404, "unknown query_id")
    # The run outlives the HTTP connection now, so stopping has to reach the task itself —
    # otherwise "stop" only closed the reader while four agents kept spending the rate limit.
    s.cancel.set()
    if s.task and not s.task.done():
        s.task.cancel()
    s.close()
    return {"stopped": True}


@router.get("/source/{source_id}")
async def source(source_id: int, query_id: str) -> dict:
    s = sessions.get(query_id)
    if not s:
        raise HTTPException(404, "unknown query_id")
    src = s.sources.get(source_id)
    if not src:
        raise HTTPException(404, "unknown source")
    # `content` is the whole point of this endpoint: the drawer locates the pinned quote inside the
    # real page by string search. Returning identity only rendered an empty drawer under a
    # "matched excerpt ↓" header — the receipt gesture, pointing at nothing.
    body = s.registry.body(source_id) if s.registry else ""
    return {**src, "content": body}


@router.get("/concept")
async def concept_graph(query_id: str) -> dict:
    """The ANSWER as a knowledge graph — entities and the relations the answer states between them.

    On demand: it costs one model call, and nobody should pay for a view they never open. Cached
    on the session, so expanding it twice is free.
    """
    s = sessions.get(query_id)
    if not s:
        raise HTTPException(404, "unknown or expired query_id")
    if s.concept is None:
        if not s.answer_text:
            return {"nodes": [], "links": [], "pending": True}
        s.concept = await concept.extract(s.question, s.answer_text)
    return s.concept


@router.get("/artifact/{artifact_id}")
async def artifact(artifact_id: str, query_id: str) -> FileResponse:
    s = sessions.get(query_id)
    if not s:
        raise HTTPException(404, "unknown query_id")
    art = s.artifacts.get(artifact_id)
    if not art or not art.get("path"):
        raise HTTPException(404, "unknown artifact")
    p = Path(art["path"]).resolve()
    # Only serve what the reporter actually published into this run's workspace.
    ws = (Path(config.DATA_DIR) / "artifacts" / query_id).resolve()
    if not str(p).startswith(str(ws) + "/") or not p.exists():
        raise HTTPException(404, "artifact not on disk")
    return FileResponse(p, media_type="text/html")
