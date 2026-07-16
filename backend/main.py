from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .providers import cache
from .routers import research

app = FastAPI(title="receipts", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research.router)


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "mode": config.RESEARCH_MODE,
        "models": config.MODELS,
        "modes": {k: v.__dict__ for k, v in config.PRESETS.items()},
        "cache": cache.stats(),
        "lanes": {
            "ollama": bool(config.api_key("OLLAMA_API_KEY")),
            "tavily": bool(config.api_key("TAVILY_API_KEY")),
            "openalex": True,   # keyless
            "jina": True,       # keyless
        },
    }
