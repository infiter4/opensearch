"""The HTTP surface: artifacts can't run script on the app's origin, the stream resumes one past
the last event the browser saw, the concept graph runs on the run's own models, and a page on
another origin cannot drive a state-changing route."""
import asyncio

import httpx
import pytest

from backend import config, sessions
from backend.main import app
from backend.providers import llm, runcfg
from backend.routers import research


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000")


def _session_without_a_run(question="q?"):
    s = sessions.create(question, "lite")
    fut = asyncio.get_running_loop().create_future()
    fut.set_result(None)
    s.task = fut                                         # the stream must not start a real run
    return s


# ── #5 artifacts ────────────────────────────────────────────────────────────────────────

def test_artifact_path_stays_server_side_and_html_is_sandboxed(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    async def go():
        s = sessions.create("make a report", "lite")
        f = tmp_path / "artifacts" / s.query_id / "r.html"
        f.parent.mkdir(parents=True)
        f.write_text("<script>steal()</script>")

        async def fake_run(*a, **kw):
            yield "artifact", {"id": "a1", "name": "r.html", "kind": "report",
                               "url": "/api/artifact/a1", "path": str(f)}
            yield "done", {}

        monkeypatch.setattr(research.orchestrator, "run", fake_run)
        await research._drive(s)
        streamed = [d for e, d in s.events if e == "artifact"]
        async with _client() as c:
            r = await c.get(f"/api/artifact/a1?query_id={s.query_id}")
        return s, streamed, r

    s, streamed, r = asyncio.run(go())
    assert streamed and "path" not in streamed[0]
    assert set(streamed[0]) == {"id", "name", "kind", "url"}
    assert s.artifacts["a1"]["path"]                     # still known to the server
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"


# ── #8 resume ───────────────────────────────────────────────────────────────────────────

def _ids(text):
    return [int(line[4:]) for line in text.splitlines() if line.startswith("id: ")]


def test_last_event_id_resumes_one_past_it_and_from_keeps_its_meaning():
    async def go():
        s = _session_without_a_run()
        for tok in ("The ", "sky ", "is ", "blue."):
            s.push("lead_token", {"text": tok})
        s.push("done", {})
        s.close()
        url = f"/api/research/stream?query_id={s.query_id}"
        async with _client() as c:
            resumed = await c.get(url, headers={"Last-Event-ID": "1"})
            from_ = await c.get(url + "&from=1")
            fresh = await c.get(url)
        return resumed.text, from_.text, fresh.text

    resumed, from_, fresh = asyncio.run(go())
    assert _ids(resumed) == [2, 3, 4]                    # event 1 was already applied
    assert _ids(from_) == [1, 2, 3, 4]
    assert _ids(fresh) == [0, 1, 2, 3, 4]


# ── #9 concept ──────────────────────────────────────────────────────────────────────────

def test_concept_runs_on_the_sessions_byok_and_retries_a_failure(monkeypatch):
    seen = []
    replies = iter([llm.LLMError("claims: HTTP 503"), {"nodes": [{"id": "paris", "label": "Paris"}], "links": []}])

    async def fake_complete_json(model, messages, **kw):
        seen.append((model, runcfg.key_for("groq")))
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)

    async def go():
        s = _session_without_a_run()
        s.models, s.keys = {"claims": "groq/llama-3.3-70b"}, {"groq": "gsk-test-not-a-real-key"}
        s.answer_text = "Paris is the capital of France."
        async with _client() as c:
            first = (await c.get(f"/api/concept?query_id={s.query_id}")).json()
            second = (await c.get(f"/api/concept?query_id={s.query_id}")).json()
        # the overrides lived in their own task: this context never saw them
        return first, second, s.concept, runcfg.key_for("groq")

    first, second, stored, leaked_key = asyncio.run(go())
    assert seen == [("groq/llama-3.3-70b", "gsk-test-not-a-real-key")] * 2
    assert first["nodes"] == [] and second["nodes"]      # the failure was not pinned
    assert stored == second
    assert leaked_key is None


# ── #11 same-origin writes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("POST", "/api/research/nope/stop"),
    ("DELETE", "/api/workspaces/notes"),
    ("POST", "/api/workspaces/notes/ingest"),
])
def test_a_foreign_origin_cannot_drive_a_state_changing_route(method, path):
    async def go():
        async with _client() as c:
            evil = await c.request(method, path, headers={"Origin": "https://evil.example"})
            ours = await c.request(method, path, headers={"Origin": "http://localhost:5173"})
            bare = await c.request(method, path)
        return evil.status_code, ours.status_code, bare.status_code

    evil, ours, bare = asyncio.run(go())
    assert evil == 403
    assert ours != 403 and bare != 403                   # the vite proxy and the CLI pass through


@pytest.mark.parametrize("origin,ok", [
    ("http://127.0.0.1:5173", True), ("http://[::1]:5173", True),
    ("http://192.168.0.50:5173", True), ("http://10.0.0.4:5173", True),   # a phone on the LAN
    ("http://8.8.8.8", False), ("https://receipts.example", False),
])
def test_this_machine_and_its_network_may_write_the_public_web_may_not(origin, ok):
    async def go():
        async with _client() as c:
            return (await c.post("/api/research/nope/stop", headers={"Origin": origin})).status_code

    assert (asyncio.run(go()) != 403) is ok


def test_reads_and_preflights_are_untouched():
    async def go():
        async with _client() as c:
            get = await c.get("/api/research/stream?query_id=nope", headers={"Origin": "https://evil.example"})
            pre = await c.options("/api/research", headers={
                "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
        return get.status_code, pre.status_code, pre.headers.get("access-control-allow-origin")

    get, pre, acao = asyncio.run(go())
    assert get == 404
    assert pre == 200 and acao == "http://localhost:5173"
