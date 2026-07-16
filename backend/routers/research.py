from __future__ import annotations

import asyncio

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import config, sessions, sse
from ..pipeline import orchestrator
from ..providers import cache

router = APIRouter(prefix="/api")


class ResearchIn(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    mode: str = "pro"
    keys: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)


@router.post("/research")
async def start(body: ResearchIn) -> dict:
    if body.mode not in config.PRESETS:
        raise HTTPException(400, f"unknown mode {body.mode!r}")
    s = sessions.create(body.question, body.mode, body.keys, body.models)
    return {"query_id": s.query_id}


@router.get("/research/stream")
async def stream(query_id: str) -> StreamingResponse:
    s = sessions.get(query_id)
    if not s:
        raise HTTPException(404, "unknown or expired query_id")

    async def gen():
        try:
            async for event, data in orchestrator.run(
                s.question, s.mode, cancel=s.cancel, query_id=s.query_id,
                models=s.models, keys=s.keys,
            ):
                if event == "source":
                    s.sources[data["id"]] = data
                elif event == "artifact":
                    s.artifacts[data["id"]] = data
                yield sse.frame(event, data)
        except cache.CacheMiss as e:
            yield sse.frame("error", {
                "scope": "run",
                "message": f"replay miss — this run was never recorded. {e}",
            })
            yield sse.frame("done", {})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield sse.frame("error", {"scope": "run", "message": f"{type(e).__name__}: {e}"})
            yield sse.frame("done", {})

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
    s.cancel.set()
    return {"stopped": True}


@router.get("/source/{source_id}")
async def source(source_id: int, query_id: str) -> dict:
    s = sessions.get(query_id)
    if not s:
        raise HTTPException(404, "unknown query_id")
    src = s.sources.get(source_id)
    if not src:
        raise HTTPException(404, "unknown source")
    return src


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
