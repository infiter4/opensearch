"""Config + search-mode presets. No network, no imports from the rest of the app."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
CACHE_DB = DATA_DIR / "cache.sqlite"


def _load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader. os.environ always wins so `RESEARCH_MODE=replay python -m ...` works."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_env()

OLLAMA_CLOUD_URL = "https://ollama.com"
OLLAMA_LOCAL_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

Mode = Literal["live", "auto", "replay"]
RESEARCH_MODE: Mode = os.environ.get("RESEARCH_MODE", "auto")  # type: ignore[assignment]

# Stage -> model. Three distinct families across write / verify / repair is the whole point: the
# verifier must not share a lineage with the writer, or "independent check" is a lie. All tags
# verified HTTP 200.
#
# MEASURED, not guessed (see git history for the benchmark):
#   throughput @ sem=6, uncached, 6k-char source, ~80 tok out
#     qwen3.5:397b  0.15/s  -> 45 verdicts ~300s   accuracy 7/7
#     kimi-k2.6     0.68/s  -> 45 verdicts  ~66s   accuracy 7/7
#     minimax-m3    1.05/s  -> 45 verdicts  ~43s   accuracy 7/7
#   Ollama Cloud SERIALIZES qwen3.5:397b server-side: sem=12 was 2x SLOWER in wall clock than
#   sem=6 (151s vs 79s for 12). Raising concurrency does not help it — it queues.
#
# So: kimi verifies (all ~45 calls, fast, matches qwen's accuracy on a clean battery).
# qwen rewrites (only FAILING sentences, ~4 calls ~26s) — its cost is irrelevant at that volume
# and it is a third family, so the repair is judged by neither the writer nor the verifier.
# minimax is NOT eligible to verify at any speed: it writes.
MODELS: dict[str, str] = {
    "planner": os.environ.get("PLANNER_MODEL", "kimi-k2.6:cloud"),
    "subagent": os.environ.get("SUBAGENT_MODEL", "minimax-m3:cloud"),
    "claims": os.environ.get("CLAIMS_MODEL", "kimi-k2.6:cloud"),
    "verifier": os.environ.get("VERIFIER_MODEL", "kimi-k2.6:cloud"),
    "rewriter": os.environ.get("REWRITER_MODEL", "qwen3.5:397b:cloud"),
    "lead": os.environ.get("LEAD_MODEL", "minimax-m3:cloud"),
    "reporter": os.environ.get("REPORTER_MODEL", "kimi-k2.7-code:cloud"),
}

# Fallback when the verifier sustains 429/5xx. Slow, but a slow verdict beats no verdict — and it
# must never fall back to minimax-m3, which wrote the text being checked.
VERIFIER_FALLBACK = "qwen3.5:397b:cloud"


@dataclass(frozen=True)
class ModePreset:
    n_agents: int
    lanes: tuple[str, ...]
    max_sources: int
    max_steps: int
    rewrite_iters: int
    red_team: bool
    knowledge_graph: bool
    report: bool


# One knob on everything. Lite exists so the LIVE demo is fast and real;
# Deep is the showpiece and runs from cache on stage.
# max_steps is an ACTION budget, and the floor is not arbitrary: search(1) + read(1) + write(1) = 3
# is the bare minimum to produce a single citation, which leaves zero slack — observed: an agent
# that searches twice then burns its last step on the forced verdict reads NOTHING and cites
# NOTHING. 4 is the real floor; 5 lets it read two sources and cross-check.
PRESETS: dict[str, ModePreset] = {
    "lite": ModePreset(
        n_agents=1, lanes=("ollama",), max_sources=3, max_steps=5,
        rewrite_iters=0, red_team=False, knowledge_graph=False, report=False,
    ),
    "pro": ModePreset(
        n_agents=3, lanes=("ollama", "tavily"), max_sources=6, max_steps=6,
        rewrite_iters=1, red_team=False, knowledge_graph=False, report=False,
    ),
    "deep": ModePreset(
        n_agents=4, lanes=("ollama", "tavily", "openalex"), max_sources=10, max_steps=7,
        rewrite_iters=2, red_team=True, knowledge_graph=True, report=True,
    ),
}

# Concurrency. Sub-agents are expensive turns; verifier calls are cheap and numerous.
SEM_AGENTS = 4
SEM_VERIFY = 6
SEM_FETCH = 6
# The rewriter is qwen3.5:397b, which Ollama serializes server-side — extra concurrency buys
# queue depth, not throughput, and a queue deeper than the stall timeout turns into retries.
# Repairs are few (only failing sentences) so a small bound costs nothing.
SEM_REWRITE = 3

MAX_REWRITE_ITERS = 2          # hard ceiling regardless of preset. Enforced by range(), not a prompt.
SOURCE_BODY_CHARS = 6000       # per-source truncation fed to the verifier
THIN_CONTENT_CHARS = 500       # below this a fetch is considered failed -> next in the chain

# Measured: ollama fetch ~1.7s, jina ~2.4s. The long tail was doi.org redirects (~20s, usually
# into a paywall). 15s keeps a slow-but-real page while cutting the tail that dominated wall clock.
FETCH_TIMEOUT = 15.0
SEARCH_RESULTS_PER_LANE = 10   # ollama caps here; also where ollama/tavily overlap starts to fire


def api_key(name: str) -> str | None:
    return os.environ.get(name) or None
