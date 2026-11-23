from __future__ import annotations

import asyncio
import ipaddress
import logging
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from . import config
from .providers import cache
from .routers import research, workspace
from .store import db as store_db

app = FastAPI(title="opensearch", version="0.1")

ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class SameOriginWrites:
    """Refuse a state-changing request whose Origin is present and not ours.

    CORS does not stop a request, it only hides the response. A multipart POST is a "simple"
    request with no preflight, so any page the user visited could ingest documents into a
    workspace (or stop a run) and simply not read the answer. Browsers always send Origin on a
    POST, the vite proxy forwards it unchanged (http://localhost:5173 passes), and a request with
    no Origin — the CLI, curl, tests — is not a browser being steered, so it stays allowed.
    """

    _WRITES = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app, allowed: list[str]):
        self.app = app
        self.allowed = set(allowed)

    def _trusted(self, origin: str) -> bool:
        # vite binds 0.0.0.0 on purpose (see web/vite.config.ts), so the app is also opened as
        # http://127.0.0.1:5173, http://[::1]:5173 or from a phone at http://192.168.x.y:5173.
        # Those are this machine or its own network; the attack is a PUBLIC page steering the
        # browser, and that is still refused.
        if origin in self.allowed:
            return True
        host = urlsplit(origin).hostname or ""
        if host == "localhost":
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return ip.is_loopback or ip.is_private

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in self._WRITES:
            origin = dict(scope["headers"]).get(b"origin")
            if origin is not None and not self._trusted(origin.decode("latin-1")):
                refuse = PlainTextResponse("cross-origin request refused", status_code=403)
                return await refuse(scope, receive, send)
        await self.app(scope, receive, send)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SameOriginWrites, allowed=ALLOWED_ORIGINS)

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
        "cache": await asyncio.to_thread(cache.stats),   # sqlite off the loop, as in cache.py
        "store": {"enabled": store_db.is_enabled(), "embed_model": config.MODELS["embed"],
                  "embed_dim": config.EMBED_DIM},
        "lanes": {
            "ollama": bool(config.api_key("OLLAMA_API_KEY")),
            "tavily": bool(config.api_key("TAVILY_API_KEY")),
            "openalex": True,   # keyless
            "jina": True,       # keyless
        },
    }
