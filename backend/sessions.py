"""Short-lived run sessions.

EventSource cannot set headers, so the flow is POST (question + optional BYOK keys) -> query_id,
then GET the stream by id. Keys live here in memory only: never logged, never written to disk,
never handed to cache.py (which redacts them anyway — belt and braces, because data/cache.sqlite
is committed to the repo).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

TTL_S = 1800


@dataclass
class Session:
    query_id: str
    question: str
    mode: str
    keys: dict[str, str] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    sources: dict[int, dict] = field(default_factory=dict)
    artifacts: dict[str, dict] = field(default_factory=dict)


_SESSIONS: dict[str, Session] = {}


def create(question: str, mode: str, keys: dict | None = None, models: dict | None = None) -> Session:
    _gc()
    qid = uuid.uuid4().hex[:12]
    s = Session(query_id=qid, question=question, mode=mode,
                keys=keys or {}, models=models or {})
    _SESSIONS[qid] = s
    return s


def get(qid: str) -> Session | None:
    _gc()
    return _SESSIONS.get(qid)


def _gc() -> None:
    now = time.time()
    for k in [k for k, v in _SESSIONS.items() if now - v.created > TTL_S]:
        _SESSIONS.pop(k, None)


def __repr_safe__() -> str:  # pragma: no cover - guard against accidental key logging
    return f"<{len(_SESSIONS)} sessions>"
