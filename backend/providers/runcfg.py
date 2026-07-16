"""Per-run BYOK state — a leaf module so both the façade and the transports can read it.

ContextVars, not globals: two browser tabs run two pipelines concurrently in one event loop, and
module-level state would bleed one user's model picks (or API keys) into the other's run. Keys
live here for the duration of a run only — they are never logged, never cached (cache.py redacts
before hashing), and never echoed back out in events.
"""
from __future__ import annotations

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
