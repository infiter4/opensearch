"""Config + search-mode presets. No network, no imports from the rest of the app."""
from __future__ import annotations

import logging
import os
import re
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
        os.environ.setdefault(k.strip(), _env_value(v))


def _env_value(v: str) -> str:
    """`KEY=auto   # note` -> "auto", `KEY="a # b"` -> "a # b", `KEY=pa#ss` -> "pa#ss".

    The README's own config block carries inline comments. Kept verbatim they became the value:
    RESEARCH_MODE="auto   # live | auto | replay" matched no mode, so every call silently went
    LIVE (paid, cache never read), and `OLLAMA_API_KEY=   # required` sent the comment as a key.
    Only a `#` after whitespace starts a comment, so a `#` inside a password survives.
    """
    v = v.strip()
    if v[:1] in ("'", '"'):
        end = v.find(v[0], 1)
        if end != -1:
            return v[1:end]
    return re.sub(r"(?:^|\s)#.*$", "", v).strip()


_load_env()

OLLAMA_CLOUD_URL = "https://ollama.com"
OLLAMA_LOCAL_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

Mode = Literal["live", "auto", "replay"]


def _research_mode(raw: str) -> Mode:
    """An unknown mode used to fall through every `mode in ("auto", "replay")` check — i.e. run
    live, paying for every call, without a word. Say so, and take the dev default."""
    if raw in ("live", "auto", "replay"):
        return raw  # type: ignore[return-value]
    logging.getLogger("receipts").warning(
        "RESEARCH_MODE=%r is not one of live|auto|replay; using auto", raw)
    return "auto"


RESEARCH_MODE: Mode = _research_mode(os.environ.get("RESEARCH_MODE", "auto"))

# ── Graph-RAG / workspaces (all OPTIONAL; absent SUPABASE_DB_URL => feature disabled) ──
# The DSN is a server secret: .env only, never posted from the browser, never passed to cache.py.
# The pooler URL is used at runtime; the DIRECT url (port 5432) is preferred for migrations and
# `create extension` (the session pooler can reject DDL / breaks prepared statements).
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL") or None
SUPABASE_DB_DIRECT_URL = os.environ.get("SUPABASE_DB_DIRECT_URL") or None
# Embedding model + dimension. `embeddinggemma` runs on the LOCAL ollama daemon (bare name -> the
# daemon, per ollama._endpoint) at 768 dims — Ollama Cloud gates /api/embed on the free tier, and
# local means the corpus embeds offline. The dim is a ONE-WAY DOOR: it is baked into the pgvector
# column and validated per-workspace, so changing the model means re-embedding every chunk.
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))

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
    "subagent": os.environ.get("SUBAGENT_MODEL", "mistral-large-3:675b:cloud"),
    "claims": os.environ.get("CLAIMS_MODEL", "kimi-k2.6:cloud"),
    "verifier": os.environ.get("VERIFIER_MODEL", "kimi-k2.6:cloud"),
    "rewriter": os.environ.get("REWRITER_MODEL", "qwen3.5:397b:cloud"),
    "lead": os.environ.get("LEAD_MODEL", "mistral-large-3:675b:cloud"),
    "reporter": os.environ.get("REPORTER_MODEL", "kimi-k2.7-code:cloud"),
    # Intent router: one cheap JSON call, only for inputs the keyword fast-path can't resolve.
    "router": os.environ.get("ROUTER_MODEL", "kimi-k2.6:cloud"),
    # The "do-it" agent for CUA tasks — needs strong tool-use, so the code-tuned tag.
    "doer": os.environ.get("DOER_MODEL", "kimi-k2.7-code:cloud"),
    # Embedder for the workspace corpus. Bare name -> local ollama daemon (offline, free, 768-dim).
    "embed": os.environ.get("EMBED_MODEL", "embeddinggemma"),
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
#
# SEM_VERIFY was 6 on a measured throughput curve (see the table above). That measurement is now
# stale: Ollama Cloud returns `429 {"error":"too many concurrent requests"}` at 6, and a rejected
# call costs a full backoff — retry 5/6 waits 30s — so nominal concurrency of 6 delivered less
# real throughput than 4 that are actually accepted. Deep mode also runs FOUR agents whose verify
# fan-outs share this one global semaphore, which the original benchmark never exercised.
# ollama.py additionally parks every caller on a shared cooldown when a 429 lands, so a rate limit
# backs the whole process off once instead of each worker rediscovering it.
SEM_AGENTS = 4
SEM_VERIFY = int(os.environ.get("SEM_VERIFY", "4"))
SEM_FETCH = 6

# THE cap that actually matters: total simultaneous requests to Ollama, counted across every
# stage. The per-stage semaphores above bound their own fan-out and nothing else — deep mode adds
# them up to ~11 in flight, and the free tier refuses somewhere around three ("429: too many
# concurrent requests"). A refusal costs a full backoff, so more nominal concurrency bought less
# real throughput. Raise only against a paid tier that documents a higher limit.
OLLAMA_MAX_INFLIGHT = int(os.environ.get("OLLAMA_MAX_INFLIGHT", "3"))

# Replay pacing. A cached draft should still TYPE on screen rather than teleport — but only where
# a human watches the tokens. Anything shorter than REPLAY_PROSE_CHARS is machinery (verifier JSON,
# claim extraction) and replays instantly. Turn REPLAY_DELAY down to rehearse faster; 0 = no pacing.
REPLAY_DELAY = float(os.environ.get("REPLAY_DELAY", "0.012"))
REPLAY_PROSE_CHARS = int(os.environ.get("REPLAY_PROSE_CHARS", "400"))
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
