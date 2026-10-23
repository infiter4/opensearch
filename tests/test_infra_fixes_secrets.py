"""Secrets stay in the server: the sandbox child never sees them, tool output and the cache never
carry them — matched by VALUE, not just by a secret-looking dict key.

Every secret here is a fake. The real ones are stripped from os.environ first and assertions
compare booleans, so a regression can never print a real key into a test report.
"""
import asyncio
import importlib.util
import os
import sqlite3
import sys

import pytest

from backend import config
from backend.providers import cache, runcfg
from backend.runtime import report_tools  # noqa: F401 — registers the sandbox tools
from backend.runtime.tools import Ctx, dispatch

FAKE_ENV_KEY = "fake-env-secret-0123456789"
FAKE_DB_PASS = "fakepass-9876543210"
FAKE_BYOK = "byok-fake-key-abcdefgh"


@pytest.fixture
def fake_env(monkeypatch):
    """Drop every real credential from the env, then plant known fakes."""
    for name, v in list(os.environ.items()):
        if runcfg._SECRET_ENV.search(name) or runcfg._URL_CREDS.match(v):
            monkeypatch.delenv(name)
    monkeypatch.setenv("RCPT_TEST_API_KEY", FAKE_ENV_KEY)
    monkeypatch.setenv("RCPT_TEST_DB_URL", f"postgresql://postgres:{FAKE_DB_PASS}@db.example:5432/x")


def _ctx(tmp_path):
    return Ctx(agent="doer", workspace=str(tmp_path / "ws"))


def test_sandbox_child_gets_a_minimal_env(fake_env, tmp_path):
    out = asyncio.run(dispatch("run_shell", {"command": "env"}, _ctx(tmp_path)))
    names = {line.split("=", 1)[0] for line in out.splitlines()[1:] if "=" in line}
    leaked_name = "RCPT_TEST_API_KEY" in names or "RCPT_TEST_DB_URL" in names
    leaked_value = FAKE_ENV_KEY in out or FAKE_DB_PASS in out
    assert not leaked_name and not leaked_value
    assert {"PATH", "HOME", "LANG", "PYTHONIOENCODING"} <= names
    home = [line for line in out.splitlines() if line.startswith("HOME=")][0]
    assert home == f"HOME={(tmp_path / 'ws').resolve()}"


def test_a_shell_python_is_still_the_venv(fake_env, tmp_path):
    out = asyncio.run(dispatch("run_shell", {
        "command": "python3 -c 'import sys; print(sys.prefix)'"}, _ctx(tmp_path)))
    assert sys.prefix in out


@pytest.mark.skipif(importlib.util.find_spec("numpy") is None, reason="numpy not installed")
def test_run_python_still_imports_numpy(fake_env, tmp_path):
    out = asyncio.run(dispatch("run_python", {"code": "import numpy; print('np-ok')"}, _ctx(tmp_path)))
    assert "np-ok" in out and "exit=0" in out


def test_tool_output_is_scrubbed_of_env_and_byok_values(fake_env, tmp_path):
    async def go():
        runcfg.set_run_overrides(None, {"groq": FAKE_BYOK})
        code = f"print({FAKE_ENV_KEY!r}); print({FAKE_DB_PASS!r}); print({FAKE_BYOK!r})"
        return await dispatch("run_python", {"code": code}, _ctx(tmp_path))

    out = asyncio.run(go())
    leaked = any(s in out for s in (FAKE_ENV_KEY, FAKE_DB_PASS, FAKE_BYOK))
    assert not leaked
    assert out.count("<redacted>") == 3


def _fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "c.sqlite")
    monkeypatch.setattr(cache, "_conn", None)


def test_cache_scrubs_values_and_key_shapes_from_request_and_response(fake_env, monkeypatch, tmp_path):
    _fresh_cache(monkeypatch, tmp_path)
    shapes = ["gsk_" + "A1b2" * 6, "sk-proj-" + "x9" * 12, "AIza" + "Q7_-" * 9, "tvly-dev-" + "z8" * 6]
    text = f"tool said: {FAKE_ENV_KEY} / {FAKE_DB_PASS} / {FAKE_BYOK} / " + " ".join(shapes)

    async def go():
        runcfg.set_run_overrides(None, {"openrouter": FAKE_BYOK})
        req = {"model": "m:cloud", "messages": [{"role": "tool", "content": text}]}
        await asyncio.to_thread(cache.put, "chat", req, {"content": text, "message": {"content": text}})

    asyncio.run(go())
    conn = sqlite3.connect(tmp_path / "c.sqlite")
    request, response = conn.execute("select request, response from cache").fetchone()
    conn.close()
    for secret in (FAKE_ENV_KEY, FAKE_DB_PASS, FAKE_BYOK, *shapes):
        leaked = secret in request or secret in response
        assert not leaked, "a secret survived redaction"


def test_ordinary_prose_is_not_mistaken_for_a_key():
    s = "use sk-learn-style-pipelines and the task-1234567890abcdefghijk id"
    assert cache.scrub_text(s, set()) == s


def test_rotating_a_key_does_not_bust_the_cache_key(monkeypatch, fake_env):
    req = {"model": "m", "messages": [{"role": "user", "content": f"echo {FAKE_ENV_KEY}"}]}
    k1 = cache.cache_key("chat", req)
    monkeypatch.setenv("RCPT_TEST_API_KEY", "rotated-secret-abcdefghij")
    rotated = {"model": "m", "messages": [{"role": "user", "content": "echo rotated-secret-abcdefghij"}]}
    assert cache.cache_key("chat", rotated) == k1
