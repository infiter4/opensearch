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
    # Prior turns of this conversation thread, for the planner only.
    history: list[dict] = field(default_factory=list)
    # The run's live SourceRegistry. The `source` event carries identity only, so this is the only
    # place the actual page text survives — /api/source/{id} serves the body out of it so the
    # drawer can locate the pinned quote in the real page.
    registry: object | None = None

    # ——— the run, owned by the SESSION and not by any one HTTP connection ———
    # EventSource reconnects on its own whenever a stream drops, and it reconnects to the same URL.
    # While the stream endpoint *started* a run, every reconnect — and every page reload — kicked
    # off another full research run against the same question: duplicate agents, duplicate spend,
    # "429 too many concurrent requests" from our own stacked runs, and enough churn to crash the
    # tab. A run now happens once per query_id; the buffer below lets any number of readers attach,
    # replay what they missed, and follow along live.
    events: list[tuple[str, dict]] = field(default_factory=list)
    task: asyncio.Task | None = None
    finished: bool = False
    _bell: asyncio.Event | None = None

    @property
    def bell(self) -> asyncio.Event:
        """Rings whenever an event lands. Created lazily so Session() is safe off-loop."""
        if self._bell is None:
            self._bell = asyncio.Event()
        return self._bell

    def push(self, event: str, data: dict) -> None:
        self.events.append((event, data))
        self.bell.set()

    def close(self) -> None:
        self.finished = True
        self.bell.set()


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
        s = _SESSIONS.pop(k, None)
        # A session's run outlives its readers by design; expiring the session must therefore kill
        # the task too, or an abandoned run keeps four agents and the rate limit busy forever.
        if s and s.task and not s.task.done():
            s.task.cancel()


def __repr_safe__() -> str:  # pragma: no cover - guard against accidental key logging
    return f"<{len(_SESSIONS)} sessions>"
