"""Agent specs. Prompts live in backend/agents/<name>.md as plain markdown.

Deliberately NOT frontmatter-parsed like jarvis's registry.py: that version swallows a malformed
agent file with `except Exception: continue`, so a typo makes an agent silently vanish and you
debug it for thirty minutes. Model comes from config.MODELS; a missing prompt file raises loudly.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .. import config
from ..providers import runcfg

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    model: str
    prompt: str
    tools: tuple[str, ...] = ()
    max_steps: int = 4
    num_ctx: int = 32768


@lru_cache(maxsize=None)
def _prompt(name: str) -> str:
    p = AGENTS_DIR / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"missing agent prompt: {p}")
    return p.read_text().strip()


def spec(name: str, *, tools: tuple[str, ...] = (), max_steps: int = 4, num_ctx: int = 32768) -> AgentSpec:
    return AgentSpec(
        name=name,
        model=runcfg.model_for(name) if name in config.MODELS else runcfg.model_for("subagent"),
        prompt=_prompt(name),
        tools=tools,
        max_steps=max_steps,
        num_ctx=num_ctx,
    )
