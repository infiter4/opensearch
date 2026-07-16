"""Pre-record the demo runs, then commit data/cache.sqlite.

    .venv/bin/python scripts/warm.py                 # warm the default demo set
    .venv/bin/python scripts/warm.py --mode deep     # warm deep mode
    .venv/bin/python scripts/warm.py --check         # verify every question replays offline

WHY THIS EXISTS: a live run costs ~100 external calls and several minutes, against a free tier
whose limits are unpublished and reset on a ~5h session. On stage you get one shot with a room
watching. Warm the cache, commit it, and rehearse in `replay` WITH THE WIFI PHYSICALLY OFF. If
that passes, the demo cannot fail live.

The demo question is a DELIVERABLE, not a detail. You need one that produces at least one red
cell the rewrite repairs — an all-green board proves nothing, because it is indistinguishable
from a board that isn't wired up. The red cell IS the product.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (question, mode) — the mode is part of the recording, not a detail. The cache is keyed on the
# exact calls a run makes, and lite/pro/deep make DIFFERENT calls. Warming everything in one mode
# and demoing another is a replay miss on stage, i.e. a hang in front of judges.
DEMO_SET: list[tuple[str, str]] = [
    # 1. The safe opener — well documented, should come back mostly green.
    ("What are the rate limits of Ollama's web search API?", "lite"),
    # 2. The money shot — pricing/limits are widely misreported by blogspam, so a sub-agent is
    #    likely to write something its source does not support. Watch red heal to green.
    ("How much does Tavily's search API cost and what does the free tier include?", "pro"),
    # 3. Contested — sources genuinely disagree. Exercises the red team, the contradiction flag,
    #    the provenance graph and the audit report. Also: it is this product's own subject matter.
    ("Do AI search engines cite sources accurately?", "deep"),
]


async def warm(pairs: list[tuple[str, str]]) -> int:
    from backend.pipeline import orchestrator
    from backend.providers import cache

    failures = 0
    for i, (q, mode) in enumerate(pairs, 1):
        print(f"\n\x1b[36m[{i}/{len(pairs)}]\x1b[0m \x1b[33m{mode}\x1b[0m · {q}")
        t0 = time.time()
        counts: dict[str, int] = {}
        try:
            # Progress must be visible: a warm run is minutes long, and "silent" and "wedged" look
            # identical from outside. One line per stage, rewritten in place.
            def tick(note: str = "") -> None:
                v = counts.get("verdict", 0)
                r = counts.get("rewrite_done", 0)
                s = counts.get("source", 0)
                el = time.time() - t0
                print(f"\r  \x1b[2m{el:5.0f}s\x1b[0m  {s} sources · {v} checked · {r} repaired"
                      f"   \x1b[2m{note[:42]:42s}\x1b[0m", end="", flush=True)

            async for event, data in orchestrator.run(q, mode):
                counts[event] = counts.get(event, 0) + 1
                if event == "agent_status":
                    tick(f"{data.get('agent_id')} {data.get('status')}")
                elif event in ("verdict", "source", "rewrite_done", "agent_answer"):
                    tick()
                elif event == "graph":
                    tick("provenance graph")
                elif event == "artifact":
                    tick(f"report: {data.get('name')}")
                elif event == "error":
                    print(f"\n  \x1b[31merror\x1b[0m {data.get('scope')}: {data.get('message', '')[:90]}")
            print()
        except Exception as e:
            print(f"  \x1b[31mFAILED\x1b[0m {type(e).__name__}: {e}")
            failures += 1
            continue

        v = counts.get("verdict", 0)
        ok = counts.get("answer_done", 0) > 0
        print(
            f"  {'\x1b[32mok\x1b[0m' if ok else '\x1b[31mincomplete\x1b[0m'} "
            f"{time.time() - t0:.0f}s · {v} verdicts · {counts.get('source', 0)} sources"
            f" · {counts.get('rewrite_done', 0)} repairs"
        )
        if not ok:
            failures += 1

    print(f"\ncache: {cache.stats()}")
    return failures


async def check(pairs: list[tuple[str, str]]) -> int:
    """Replay-only. Any miss here means the demo would hit the network on stage."""
    os.environ["RESEARCH_MODE"] = "replay"
    from backend import config

    config.RESEARCH_MODE = "replay"  # module already imported; override the captured value
    from backend.pipeline import orchestrator
    from backend.providers.cache import CacheMiss

    bad = 0
    for q, mode in pairs:
        t0 = time.time()
        try:
            got = 0
            async for event, data in orchestrator.run(q, mode):
                if event == "answer_done":
                    got = 1
                elif event == "error" and "replay miss" in str(data.get("message", "")):
                    got = 0
                    break
            status = "\x1b[32mreplays\x1b[0m" if got else "\x1b[31mno answer\x1b[0m"
            bad += 0 if got else 1
        except CacheMiss as e:
            status = f"\x1b[31mMISS\x1b[0m {str(e)[:60]}"
            bad += 1
        print(f"  {mode:5s} {status:34s} {time.time() - t0:5.1f}s  {q[:46]}")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", help="override the mode for every question (default: each question's demo mode)")
    ap.add_argument("--check", action="store_true", help="replay-only verification")
    ap.add_argument("--question", action="append", help="override the demo set")
    ap.add_argument("--only", type=int, help="warm/check just demo question N (1-based)")
    a = ap.parse_args()

    pairs = [(q, a.mode or "pro") for q in a.question] if a.question else list(DEMO_SET)
    if a.mode:
        pairs = [(q, a.mode) for q, _ in pairs]
    if a.only:
        pairs = pairs[a.only - 1 : a.only]

    if a.check:
        print("REPLAY CHECK — turn the wifi off and run this again before you go on stage.\n")
        n = asyncio.run(check(pairs))
        print(f"\n{'\x1b[32mall questions replay offline\x1b[0m' if not n else f'\x1b[31m{n} would hit the network\x1b[0m'}")
        sys.exit(1 if n else 0)

    n = asyncio.run(warm(pairs))
    print(
        "\nNow: git add -f data/cache.sqlite && commit.\n"
        "Then: python scripts/warm.py --check  (with the wifi OFF)"
    )
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
