"""The id in `meta` must be the id the session is keyed by.

The frontend reads query_id out of `meta` (run.ts) and hangs every later lookup off it —
/api/source/{id}?query_id=… resolves against the session registry. When run() minted its own uuid
the client got an id no session had, so clicking a citation chip to read its quote 404'd. Nothing
else fails first: the stream is fine, the board fills, and only the click is dead.
"""
import asyncio

from backend.pipeline import orchestrator


def _first_event(**kw):
    async def go():
        gen = orchestrator.run("q", "lite", **kw)
        out = await gen.__anext__()  # meta is yielded before any network call
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
