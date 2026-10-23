"""The id in `meta` must be the id the session is keyed by.

The frontend reads query_id out of `meta` (run.ts) and hangs every later lookup off it —
/api/source/{id}?query_id=… resolves against the session registry. When run() minted its own uuid
the client got an id no session had, so clicking a citation chip to read its quote 404'd. Nothing
else fails first: the stream is fine, the board fills, and only the click is dead.
"""
import asyncio

import pytest

from backend.pipeline import orchestrator


@pytest.fixture(autouse=True)
def _offline_router(monkeypatch):
    # "q" matches no fast-path pattern, so the router consults its model before `meta`. Fail
    # that call (-> the research default) rather than let the test reach a live endpoint.
    async def offline(model, messages, **kw):
        raise RuntimeError("no live model calls in tests")
    monkeypatch.setattr(orchestrator.router.llm, "complete_json", offline)


def _first_event(**kw):
    async def go():
        gen = orchestrator.run("q", "lite", **kw)
        out = await gen.__anext__()  # meta: only the (faked) router call runs before it
        await gen.aclose()
        return out
    return asyncio.run(go())


def test_meta_reports_the_callers_session_id():
    event, data = _first_event(query_id="deadbeef1234")
    assert event == "meta"
    assert data["query_id"] == "deadbeef1234"


def test_meta_still_has_an_id_when_called_bare():
    # The CLI has no session; it must still get a usable id rather than None.
    event, data = _first_event()
    assert event == "meta"
    assert data["query_id"]
