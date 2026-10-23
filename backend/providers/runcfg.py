"""Per-run BYOK state — a leaf module so both the façade and the transports can read it.

ContextVars, not globals: two browser tabs run two pipelines concurrently in one event loop, and
module-level state would bleed one user's model picks (or API keys) into the other's run. Keys
live here for the duration of a run only — they are never logged, never cached (cache.py redacts
before hashing), and never echoed back out in events.
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from typing import Callable

from .. import config

_models: ContextVar[dict[str, str]] = ContextVar("run_models", default={})
_keys: ContextVar[dict[str, str]] = ContextVar("run_keys", default={})
# How a transport tells the run something went wrong WITHOUT failing it. The retry ladder used to
# swallow every transient error and simply go quiet for up to 32s at a time — from the outside a
# rate-limited provider and a wedged app look identical. A ContextVar (not a global) because two
# runs share the event loop, and tasks spawned by asyncio.gather inherit the context.
_reporter: ContextVar[Callable[[str, str], None] | None] = ContextVar("run_reporter", default=None)


def set_run_overrides(models: dict[str, str] | None, keys: dict[str, str] | None) -> None:
    _models.set({k: v for k, v in (models or {}).items() if v})
    _keys.set({k: v for k, v in (keys or {}).items() if v})


def set_reporter(fn: Callable[[str, str], None] | None) -> None:
    _reporter.set(fn)


def report(scope: str, message: str) -> None:
    """Best-effort note to the UI. Never raise: a run must not die because reporting failed."""
    fn = _reporter.get()
    if not fn:
        return
    try:
        fn(scope, message)
    except Exception:
        pass


def model_for(stage: str) -> str:
    """The model a stage runs on: the run's override if one was posted, else the measured default."""
    return _models.get().get(stage) or config.MODELS[stage]


def effective_models() -> dict[str, str]:
    return {stage: model_for(stage) for stage in config.MODELS}


def key_for(provider: str) -> str | None:
    """BYOK key for 'ollama' | 'groq' | 'openrouter' | 'google'. None -> caller falls back to env."""
    return _keys.get().get(provider)


# Env vars that hold a credential, by name. A DB URL is matched by its VALUE instead: it carries
# the password inline whatever the variable happens to be called.
_SECRET_ENV = re.compile(r"(_KEY|_TOKEN|_SECRET|_PASSWORD)$", re.I)
_URL_CREDS = re.compile(r"^[a-z][a-z0-9+.-]*://[^/\s:@]+:([^@\s]+)@", re.I)


def secret_values() -> set[str]:
    """Every credential value this process could leak right now: the run's BYOK keys, plus env
    vars that hold one. Redaction by key NAME misses a key that has left its dict — a tool's
    stdout after `env`, a page that echoes a header — so cache.py and tool output also scrub
    these by VALUE. Short values are skipped: scrubbing "1" would shred every number in a prompt."""
    vals = set(_keys.get().values())
    for name, v in os.environ.items():
        m = _URL_CREDS.match(v)
        if m:
            vals.update((v, m.group(1)))
        elif _SECRET_ENV.search(name):
            vals.add(v)
    out = {v.strip().strip("\"'") for v in vals if v}
    return {v for v in out if len(v) >= 8}
