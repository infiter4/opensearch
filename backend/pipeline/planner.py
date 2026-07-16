"""Question -> N independently researchable subtasks, each tagged with a search lane.

Lane routing is free: the planner is already making a call, so tagging costs zero extra latency
and zero extra requests. The guardrail is that an unrecognised lane falls back to `web` and the
web lanes always fire regardless — a confused planner cannot starve the run of results.
"""
from __future__ import annotations

from .. import config
from ..providers import llm
from ..runtime.registry import spec

_VALID_LANES = {"web", "academic"}


async def plan(question: str, n: int, red_team: bool = False,
               history: list[dict] | None = None) -> list[dict]:
    s = spec("planner")
    # A follow-up is not self-contained: "what about the paid tier?" decomposes into nothing
    # useful without the exchange it hangs off. The planner is the only stage that needs this —
    # sub-agents get the resolved subquery, and the verifier must NEVER see conversation context
    # or its check stops being independent.
    prior = ""
    if history:
        turns = "\n\n".join(
            f"Earlier question: {h.get('question', '')}\nAnswer given: {h.get('answer', '')}"
            for h in history[-3:]
        )
        prior = (
            "This is a follow-up in an ongoing conversation. Earlier turns, for reference only:\n\n"
            f"{turns}\n\nResolve any pronouns or ellipsis in the new question against them, and "
            "make every part you produce self-contained.\n\n"
        )
    prompt = f"{prior}Question: {question}\n\nBreak this into exactly {n} parts."

    try:
        raw = await llm.complete_json(
            s.model,
            [{"role": "system", "content": s.prompt}, {"role": "user", "content": prompt}],
            num_ctx=8192,
            temperature=0.2,
        )
    except Exception:
        raw = []

    subtasks: list[dict] = []
    if isinstance(raw, list):
        for i, t in enumerate(raw[:n], 1):
            if not isinstance(t, dict):
                continue
            sub = str(t.get("subquery") or "").strip()
            if not sub:
                continue
            lane = str(t.get("lane") or "web").lower().strip()
            subtasks.append({
                "agent_id": f"a{i}",
                "title": str(t.get("title") or sub)[:60],
                "subquery": sub,
                "lane": lane if lane in _VALID_LANES else "web",
                "role": "research",
            })

    if not subtasks:
        # Planner failed. One agent on the raw question still produces a real answer — the run
        # degrades to Lite rather than dying.
        subtasks = [{
            "agent_id": "a1", "title": question[:60], "subquery": question,
            "lane": "web", "role": "research",
        }]

    if red_team:
        subtasks.append({
            "agent_id": f"a{len(subtasks) + 1}",
            "title": "Disconfirming evidence",
            "subquery": (
                f"Find credible evidence that the common answer to this is WRONG, outdated, or "
                f"disputed: {question}. Look specifically for corrections, retractions, "
                f"contradicting studies, changed pricing or policy, and dissenting expert views. "
                f"Report only what you can actually source; if the consensus looks solid, say so."
            ),
            "lane": "web",
            "role": "red_team",
        })

    return subtasks


def lanes_for(subtask: dict, preset: config.ModePreset) -> tuple[str, ...]:
    """Web lanes ALWAYS fire. `academic` adds OpenAlex on top — it never replaces the web lanes,
    because a planner mislabelling a product question as scholarly would otherwise return nothing."""
    base = tuple(l for l in preset.lanes if l != "openalex")
    if subtask.get("lane") == "academic" and "openalex" in preset.lanes:
        return base + ("openalex",)
    return base
