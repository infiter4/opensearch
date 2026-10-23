"""Record/replay for every outbound call.

Two jobs, and the second one is a landmine:

1. Ollama's free-tier limits are unpublished and reset on a ~5h session. A deep run costs ~100
   external calls; ten dev iterations is 1000+. Without this you hit the wall at hour 20 while
   iterating fastest, and the stage demo is a coin flip. `replay` + a committed cache.sqlite means
   the demo runs with the wifi physically off.

2. data/cache.sqlite is COMMITTED. The request payload carries API keys. Redaction happens before
   hashing AND before storing — one function, both paths — or the repo leaks the user's keys.
   Redacting before hashing also means rotating a key doesn't bust the cache. It runs on the
   stored RESPONSE too, and it matches secret VALUES, not just secret-looking dict keys: a key
   printed by a sandbox `env` rides into the next turn's messages as plain text.

3. Swapping a model must not strand a recording. The exact key includes the model, so `auto`
   really does call a newly configured model. `replay` falls back to the same request recorded
   under ANY model — change the writer in config and the recorded demo still plays.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import threading
import time
from typing import Any, Awaitable, Callable

from .. import config
from . import runcfg

_SECRET_KEYS = {
    "api_key", "apikey", "api-key", "authorization", "auth", "bearer",
    "key", "keys", "token", "access_token", "secret", "password",
}

# Provider key shapes, for a key this process was never told about (pasted into a question, read
# off a page). OpenAI-style `sk-` must contain a digit so "sk-learn-style-prose" survives.
_KEY_SHAPES = re.compile(
    r"\b(?:sk-(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{20,}"
    r"|AIza[0-9A-Za-z_-]{30,}|tvly-[A-Za-z0-9_-]{8,})"
)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


class CacheMiss(RuntimeError):
    """Raised in replay mode when a call was never recorded."""


def scrub_text(s: str, secrets: set[str] | None = None) -> str:
    """Strip known secret values and key-shaped tokens out of free text."""
    if secrets is None:
        secrets = runcfg.secret_values()
    for v in sorted(secrets, key=len, reverse=True):   # a DB URL before the password inside it
        if v in s:
            s = s.replace(v, "<redacted>")
    return _KEY_SHAPES.sub("<redacted>", s)


def _redact(obj: Any, secrets: set[str] | None = None) -> Any:
    """Recursively strip secrets. Keys arrive nested ({"keys": {"ollama": "..."}}), so a flat
    scrub silently misses them — which is exactly how a key ends up committed."""
    if secrets is None:
        secrets = runcfg.secret_values()
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in _SECRET_KEYS:
                out[k] = "<redacted>"
            else:
                out[k] = _redact(v, secrets)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact(v, secrets) for v in obj]
    if isinstance(obj, str):
        if obj.startswith("Bearer ") or obj.startswith("tvly-"):
            return "<redacted>"
        return scrub_text(obj, secrets)
    return obj


def canonical(req: Any) -> str:
    return json.dumps(_redact(req), sort_keys=True, separators=(",", ":"), default=str)


def cache_key(kind: str, req: Any) -> str:
    return hashlib.sha256(f"{kind}\x00{canonical(req)}".encode()).hexdigest()


def any_model_key(kind: str, req: Any) -> str:
    """The same request with the model left out — what replay falls back to after a model swap."""
    if isinstance(req, dict):
        req = {k: v for k, v in req.items() if k != "model"}
    return cache_key(f"{kind}:any-model", req)


def _restore_from_archive() -> None:
    """Unpack data/cache.sqlite.gz on first use.

    The warmed cache IS the demo insurance, so it ships with the repo — but at 117MB the raw file
    is over GitHub's 100MB hard limit, and it is mostly free pages and repetitive JSON (62MB of
    real rows, 27MB gzipped). So the archive is what is committed, and a fresh clone inflates it
    here: no build step to forget, and `git clone && run` still replays the demo offline.
    """
    db, gz = config.CACHE_DB, config.CACHE_DB.with_suffix(".sqlite.gz")
    if db.exists() or not gz.exists():
        return
    import gzip
    import shutil

    tmp = db.with_suffix(".sqlite.part")   # never leave a half-written db where a reader looks
    try:
        with gzip.open(gz, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        tmp.replace(db)
    except Exception:
        tmp.unlink(missing_ok=True)        # a bad archive must not stop the app; just run live


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _restore_from_archive()
        _conn = sqlite3.connect(config.CACHE_DB, check_same_thread=False, timeout=15.0)
        _conn.execute("PRAGMA journal_mode=WAL")
        # The module _lock only serialises access INSIDE this process (the async call sites run
        # get/put in worker threads, all sharing this one connection). The real contention is
        # across PROCESSES: a warm script, a second uvicorn worker, or two browser tabs all write
        # this file.
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
                   created_at REAL NOT NULL,
                   any_model_key TEXT
               )"""
        )
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(cache)")}
        if "any_model_key" not in cols:
            # A cache recorded before model-agnostic replay. Without the column every put() would
            # fail — and put() swallows errors, so nothing would be recorded, silently. Backfill it
            # from the stored request (already the redacted canonical form), once: measured at
            # ~2s for a full 2,400-row demo cache, and it lets old recordings survive a model
            # swap too.
            _conn.execute("ALTER TABLE cache ADD COLUMN any_model_key TEXT")
            rows = _conn.execute("SELECT key, kind, request FROM cache").fetchall()
            _conn.executemany(
                "UPDATE cache SET any_model_key=? WHERE key=?",
                [(any_model_key(kind, json.loads(req)), key) for key, kind, req in rows],
            )
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_kind ON cache(kind)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_any_model ON cache(any_model_key)")
        _conn.commit()
    return _conn


def get(kind: str, req: Any) -> Any | None:
    k = cache_key(kind, req)
    with _lock:
        row = _db().execute("SELECT response FROM cache WHERE key=?", (k,)).fetchone()
    return json.loads(row[0]) if row else None


def get_any_model(kind: str, req: Any) -> Any | None:
    """Replay's fallback: the same request recorded under any model, newest recording first."""
    k = any_model_key(kind, req)
    with _lock:
        row = _db().execute(
            "SELECT response FROM cache WHERE any_model_key=? ORDER BY created_at DESC LIMIT 1",
            (k,),
        ).fetchone()
    return json.loads(row[0]) if row else None


def put(kind: str, req: Any, resp: Any) -> None:
    k = cache_key(kind, req)
    row = (k, kind, canonical(req), json.dumps(_redact(resp), default=str), time.time(),
           any_model_key(kind, req))
    with _lock:
        for attempt in range(4):
            try:
                _db().execute(
                    "INSERT OR REPLACE INTO cache(key,kind,request,response,created_at,"
                    "any_model_key) VALUES(?,?,?,?,?,?)",
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

    # sqlite runs in a worker thread, never on the loop: while another process holds the write
    # lock a call WAITS (busy_timeout, up to ~60s across put's retries), and on the loop that wait
    # froze every run and every SSE stream at once — heartbeats included.
    if mode in ("auto", "replay"):
        hit = await asyncio.to_thread(get, kind, req)
        if hit is not None:
            return hit
        if mode == "replay":
            raise CacheMiss(
                f"replay miss: {kind} {canonical(req)[:160]}\n"
                f"Run once with RESEARCH_MODE=auto to record it."
            )

    resp = await fn()
    await asyncio.to_thread(put, kind, req, resp)
    return resp


def stats() -> dict[str, int]:
    with _lock:
        rows = _db().execute("SELECT kind, COUNT(*) FROM cache GROUP BY kind").fetchall()
    return {k: n for k, n in rows}
