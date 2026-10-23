"""Workspace + corpus HTTP surface. Every route 503s cleanly when the store is disabled, so the
app runs identically with no SUPABASE_DB_URL."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import config
from ..ingest import pipeline as ingest_pipeline
from ..store import db
from ..store import workspaces as ws

router = APIRouter(prefix="/api")


def _require_store() -> None:
    if not db.is_enabled():
        raise HTTPException(503, "workspaces are disabled: set SUPABASE_DB_URL to enable them")


class WorkspaceIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.get("/workspaces")
async def list_workspaces() -> dict:
    _require_store()
    return {"workspaces": await ws.list_workspaces()}


@router.post("/workspaces")
async def create_workspace(body: WorkspaceIn) -> dict:
    _require_store()
    w = await ws.create_workspace(
        body.title, embed_model=config.MODELS["embed"], embed_dim=config.EMBED_DIM,
    )
    return {"workspace": w}


@router.get("/workspaces/{slug}")
async def get_workspace(slug: str) -> dict:
    _require_store()
    w = await ws.get_by_slug(slug)
    if not w:
        raise HTTPException(404, "unknown workspace")
    return {"workspace": w}


@router.delete("/workspaces/{slug}")
async def delete_workspace(slug: str) -> dict:
    _require_store()
    if not await ws.delete_workspace(slug):
        raise HTTPException(404, "unknown workspace")
    return {"deleted": slug}


@router.post("/workspaces/{slug}/ingest")
async def ingest(slug: str, files: list[UploadFile] = File(...)) -> dict:
    _require_store()
    w = await ws.get_by_slug(slug)
    if not w:
        raise HTTPException(404, "unknown workspace")
    items = [(f.filename or "file", await f.read()) for f in files]
    return await ingest_pipeline.ingest_items(w, items)
