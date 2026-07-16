"""Record/replay for every outbound call.

Two jobs, and the second one is a landmine:

1. Ollama's free-tier limits are unpublished and reset on a ~5h session. A deep run costs ~100
   external calls; ten dev iterations is 1000+. Without this you hit the wall at hour 20 while
   iterating fastest, and the stage demo is a coin flip. `replay` + a committed cache.sqlite means
   the demo runs with the wifi physically off.

2. data/cache.sqlite is COMMITTED. The request payload carries API keys. Redaction happens before
   hashing AND before storing — one function, both paths — or the repo leaks the user's keys.
   Redacting before hashing also means rotating a key doesn't bust the cache.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from typing import Any, Awaitable, Callable

from .. import config

_SECRET_KEYS = {
    "api_key", "apikey", "api-key", "authorization", "auth", "bearer",
    "key", "keys", "token", "access_token", "secret", "password",
}

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


class CacheMiss(RuntimeError):
    """Raised in replay mode when a call was never recorded."""


def _redact(obj: Any) -> Any:
    """Recursively strip secrets. Keys arrive nested ({"keys": {"ollama": "..."}}), so a flat
    scrub silently misses them — which is exactly how a key ends up committed."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in _SECRET_KEYS:
                out[k] = "<redacted>"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    if isinstance(obj, str) and (obj.startswith("Bearer ") or obj.startswith("tvly-")):
        return "<redacted>"
    return obj


def canonical(req: Any) -> str:
    return json.dumps(_redact(req), sort_keys=True, separators=(",", ":"), default=str)


def cache_key(kind: str, req: Any) -> str:
    return hashlib.sha256(f"{kind}\x00{canonical(req)}".encode()).hexdigest()


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.CACHE_DB, check_same_thread=False, timeout=15.0)
        _conn.execute("PRAGMA journal_mode=WAL")
        # The module _lock only serialises writers INSIDE this process, and asyncio is
        # single-threaded so it barely contends at all. The real contention is across PROCESSES:
        # a warm script, a second uvicorn worker, or two browser tabs all write this file.
        # Observed: "OperationalError: database is locked" killed a run at the lead stage.
        # busy_timeout makes a blocked writer WAIT rather than fail instantly.
        _conn.execute("PRAGMA busy_timeout=15000")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                   key        TEXT PRIMARY KEY,
                   kind       TEXT NOT NULL,
                   request    TEXT NOT NULL,
                   response   TEXT NOT NULL,
                   created_at REAL NOT NULL
               )"""
        )
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_kind ON cache(kind)")
        _conn.commit()
    return _conn


def get(kind: str, req: Any) -> Any | None:
    k = cache_key(kind, req)
    with _lock:
        row = _db().execute("SELECT response FROM cache WHERE key=?", (k,)).fetchone()
    return json.loads(row[0]) if row else None


def put(kind: str, req: Any, resp: Any) -> None:
    k = cache_key(kind, req)
    row = (k, kind, canonical(req), json.dumps(resp, default=str), time.time())
    with _lock:
        for attempt in range(4):
            try:
                _db().execute(
                    "INSERT OR REPLACE INTO cache(key,kind,request,response,created_at) "
                    "VALUES(?,?,?,?,?)",
                    row,
                )
                _db().commit()
                return
            except sqlite3.OperationalError as e:
                # A cache write must never kill a run — losing one recorded call costs a repeat
                # API call later; raising here throws away the whole in-flight investigation.
                if "locked" not in str(e).lower() or attempt == 3:
                    return
                time.sleep(0.25 * (attempt + 1))


async def cached_call(
    kind: str,
    req: Any,
    fn: Callable[[], Awaitable[Any]],
    mode: str | None = None,
) -> Any:
    """Wrap EVERY egress call. `fn` must be a zero-arg coroutine returning JSON-able data."""
    mode = mode or config.RESEARCH_MODE

    if mode in ("auto", "replay"):
        hit = get(kind, req)
        if hit is not None:
            return hit
        if mode == "replay":
            raise CacheMiss(
                f"replay miss: {kind} {canonical(req)[:160]}\n"
                f"Run once with RESEARCH_MODE=auto to record it."
            )

    resp = await fn()
    put(kind, req, resp)
    return resp


def stats() -> dict[str, int]:
    with _lock:
        rows = _db().execute("SELECT kind, COUNT(*) FROM cache GROUP BY kind").fetchall()
    return {k: n for k, n in rows}
