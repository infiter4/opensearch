"""One sub-agent: research a subquery, then put its own draft through verification.

Order matters and is not negotiable: RENUMBER -> SEGMENT -> CLAIMS -> VERIFY.
Renumbering rewrites [1]->[12], which changes string length; any offset computed before it is
wrong afterwards, and a wrong offset binds a citation chip to the wrong sentence, silently.
"""
from __future__ import annotations

from .. import config
from ..runtime import corpus_tools  # noqa: F401 — import registers corpus_search/corpus_read
from ..runtime import research_tools  # noqa: F401 — import registers the tools
from ..runtime.loop import run_agent
from ..runtime.registry import spec
from ..runtime.tools import Ctx
from . import claims as claims_mod
from . import renumber, segment, verify
from .sources import SourceRegistry

_RED_TEAM_EXTRA = """
You are the disconfirming researcher. Your job is NOT to answer the question — it is to find
credible evidence that the popular answer is wrong, stale, or contested.

Look for: corrections and retractions, superseded documentation, changed pricing or policy,
studies that failed to replicate, and named experts who disagree.

Report only what you can actually source and cite. If you look and the consensus genuinely holds,
say exactly that — a clean bill of health is a real finding. Do not manufacture doubt.
"""

_CORPUS_EXTRA = """
You are researching the PROJECT'S OWN ingested documents, not the open web. Use `corpus_search` to
find relevant passages and `corpus_read` to read one before you cite it. Cite only passages you have
actually read, with [n] at the end of the sentence. If the documents do not answer part of the
question, say so plainly — do not fill the gap from outside knowledge.
"""


async def run_subagent(
    subtask: dict,
    reg: SourceRegistry,
    preset: config.ModePreset,
    lanes: tuple[str, ...],
    emit,
    cancel,
    workspace: dict | None = None,
) -> dict:
    """Returns {agent_id, role, title, text, sentences, claims, verdicts, orphans, failed}.

    When `workspace` is set the agent searches the ingested corpus (corpus_search/corpus_read)
    instead of the web; everything after the draft is identical because corpus_read interns into
    the same SourceRegistry."""
    aid = subtask["agent_id"]
    emit("agent_status", {"agent_id": aid, "status": "spawned", "detail": subtask["title"]})

    if workspace:
        tools = ("corpus_search", "corpus_read")
        ctx = Ctx(
            agent=aid, emit=emit, registry=reg, max_sources=preset.max_sources, cancel=cancel,
            workspace_id=workspace["id"], ws_slug=workspace["slug"],
            embed_model=workspace["embed_model"],
        )
        source_word = "the project's documents"
    else:
        tools = ("web_search", "read_page")
        ctx = Ctx(
            agent=aid, emit=emit, registry=reg,
            lanes=lanes, max_sources=preset.max_sources, cancel=cancel,
        )
        source_word = "sources"

    s = spec("subagent", tools=tools, max_steps=preset.max_steps)
    prompt = (
        f"Research this and report what is true:\n\n{subtask['subquery']}\n\n"
        f"You have {preset.max_steps} actions. Search {source_word}, read what matters, then write."
    )
    extra = _CORPUS_EXTRA if workspace else ""
    if subtask.get("role") == "red_team":
        # ADDED to, never replacing, the corpus instructions: replaced, a deep-mode red team in a
        # workspace held only corpus tools while its prompt still talked about web_search.
        extra += _RED_TEAM_EXTRA

    emit("agent_status", {"agent_id": aid, "status": "drafting"})
    try:
        draft = await run_agent(s, ctx, prompt, system_extra=extra)
    except Exception as e:
        emit("agent_status", {"agent_id": aid, "status": "failed", "detail": str(e)[:120]})
        return _failed(subtask, f"{type(e).__name__}: {e}")

    if not draft or draft.startswith("(stopped") or draft.startswith("(no answer"):
        emit("agent_status", {"agent_id": aid, "status": "failed", "detail": draft[:120]})
        return _failed(subtask, draft or "no answer")

    # 1. local -> global, in code. Orphans dropped, never guessed.
    text, orphans = renumber.to_global(draft, aid, reg)
    # 2. offsets over the RENUMBERED text
    sents = segment.segment(text, prefix=f"{aid}.s")

    emit("agent_answer", {
        "agent_id": aid, "iteration": 0, "text": text,
        "sentences": segment.as_events(sents), "orphans": orphans,
    })
    if orphans:
        emit("error", {
            "scope": f"agent:{aid}",
            "message": f"{len(orphans)} invented citation marker(s) removed: {orphans}",
        })

    # 3. atomic claims from cited sentences only
    emit("agent_status", {"agent_id": aid, "status": "verifying"})
    cl = await claims_mod.extract(aid, segment.claim_candidates(sents))
    emit("claims", {"agent_id": aid, "claims": cl})

    # 4. verify each (claim, cited source)
    vs = await verify.verify_all(claims_mod.pairs(cl), reg)
    by_claim = {c["id"]: c for c in cl}
    for (cid, sid), v in vs.items():
        c = by_claim.get(cid)
        if not c:
            continue
        emit("verdict", {
            "agent_id": aid, "sentence_id": c["sentence_id"], "claim_id": cid,
            "source_id": sid, "iteration": 0, **v.dict(),
        })

    emit("agent_status", {"agent_id": aid, "status": "done"})
    return {
        "agent_id": aid, "role": subtask.get("role", "research"), "title": subtask["title"],
        "text": text, "sentences": sents, "claims": cl, "verdicts": vs,
        "orphans": orphans, "failed": False,
    }


def _failed(subtask: dict, why: str) -> dict:
    """A failed sub-agent is not a hole to paper over — it becomes a gap the lead must state.
    The failure path and the honesty feature are the same code."""
    return {
        "agent_id": subtask["agent_id"], "role": subtask.get("role", "research"),
        "title": subtask["title"], "text": "", "sentences": [], "claims": [], "verdicts": {},
        "orphans": [], "failed": True, "why": why,
        "subquery": subtask["subquery"],
    }
