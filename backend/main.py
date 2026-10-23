from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .providers import cache
from .routers import research, workspace
from .store import db as store_db

app = FastAPI(title="receipts", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research.router)
app.include_router(workspace.router)


@app.on_event("startup")
async def _startup() -> None:
    # Apply the Graph-RAG schema iff a DB is configured. A failure here degrades to "store
    # disabled" — it must never take down the web-research path. The DSN (with password) is
    # scrubbed out of any error before it is logged.
    if store_db.is_enabled():
        try:
            await store_db.migrate()
            logging.getLogger("receipts").info("workspace store: schema ready")
        except Exception as e:
            logging.getLogger("receipts").warning(
                "workspace store unavailable, continuing web-only: %s",
                store_db.scrub(f"{type(e).__name__}: {e}"),
            )


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "mode": config.RESEARCH_MODE,
        "models": config.MODELS,
        "modes": {k: v.__dict__ for k, v in config.PRESETS.items()},
        "cache": cache.stats(),
        "store": {"enabled": store_db.is_enabled(), "embed_model": config.MODELS["embed"],
                  "embed_dim": config.EMBED_DIM},
        "lanes": {
            "ollama": bool(config.api_key("OLLAMA_API_KEY")),
            "tavily": bool(config.api_key("TAVILY_API_KEY")),
            "openalex": True,   # keyless
            "jina": True,       # keyless
        },
    }
