"""Tool registry + dispatch. Lifted from jarvis/jarvis/tools/__init__.py.

Two deliberate changes from the original:
  * Ctx carries `emit` and `registry` instead of task_id/db handles. The 8 bus/db/policy call
    sites in jarvis's loop collapse into that one callback.
  * No side-effect import of tool modules at the bottom (jarvis line 76 dragged in desktop,
    shell, and claude_code just by importing the package). Callers import what they need.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from ..pipeline.sources import SourceRegistry


class Cancelled(RuntimeError):
    """User stopped the run. Must unwind the loop, never become a retryable tool error."""


class StepBudgetReached(RuntimeError):
    """Agent used its last step. run_agent finalizes into a verdict rather than swallowing it."""


Handler = Callable[[dict, "Ctx"], Awaitable[Any]]


@dataclass
class Ctx:
    agent: str
    emit: Callable[[str, dict], Any] = lambda _e, _d: None
    registry: "SourceRegistry | None" = None
    lanes: tuple[str, ...] = ("ollama",)
    max_sources: int = 6
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    workspace: str | None = None  # per-run artifact sandbox (report tools only)
    # Corpus binding (set when a run researches an ingested workspace instead of the web).
    workspace_id: str | None = None
    ws_slug: str | None = None
    embed_model: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    handler: Handler


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, params: dict) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        REGISTRY[name] = Tool(name, description, params, fn)
        return fn

    return deco


def schemas(names: list[str]) -> list[dict]:
    out = []
    for n in names:
        t = REGISTRY.get(n)
        if t:
            out.append({
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.params},
            })
    return out


async def dispatch(name: str, args: dict, ctx: Ctx) -> Any:
    t = REGISTRY.get(name)
    if not t:
        return f"ERROR: unknown tool '{name}'"
    try:
        return await t.handler(args or {}, ctx)
    except (Cancelled, StepBudgetReached, asyncio.CancelledError):
        raise
    except Exception as e:  # ordinary tool errors are information the model can act on, not crashes
        return f"ERROR: {type(e).__name__}: {e}"


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}
