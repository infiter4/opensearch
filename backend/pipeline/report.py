"""Deep-mode closers, run AFTER the answer is on screen — they enrich, never block.

The graph is a pure projection of run data (like the heatmap): nodes are the question, the
agents, and the sources; edges are "researched", "cited" (carrying the worst verdict between that
sentence-owner and source), and "contradicted". Zero model calls. If graphify-style entity
extraction lands later it slots in as extra nodes behind the same event.

The reporter is a real agent with run_python / write_file / make_document — the "computer use"
that earns its keep by turning the verdict matrix into a keepable artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import config
from ..runtime import report_tools  # noqa: F401 — import registers the tools
from ..runtime.loop import run_agent
from ..runtime.registry import spec
from ..runtime.tools import Ctx
from .verify import SEVERITY


def graph(question: str, reports: list[dict], reg, cells_: list[dict]) -> dict:
    """{nodes, links} for the provenance graph. Pure code."""
    nodes = [{"id": "q", "kind": "question", "label": question[:120]}]
    links = []

    for r in reports:
        if r.get("failed"):
            continue
        aid = r["agent_id"]
        nodes.append({"id": aid, "kind": "agent", "label": r.get("title") or aid,
                      "role": r.get("role", "research")})
        links.append({"source": "q", "target": aid, "kind": "researched"})

    for s in reg.all():
        nodes.append({"id": f"s{s.id}", "kind": "source", "label": s.domain,
                      "title": s.title, "url": s.url, "n": s.id})

    # agent -> source edges wear the WORST verdict that agent's sentences earned on that source
    worst: dict[tuple[str, int], str] = {}
    for c in cells_:
        key = (c["agent_id"], c["source_id"])
        prev = worst.get(key)
        if prev is None or SEVERITY[c["verdict"]] < SEVERITY[prev]:
            worst[key] = c["verdict"]
    have_agents = {n["id"] for n in nodes if n["kind"] == "agent"}
    for (aid, sid), v in worst.items():
        if aid == "lead" and "lead" not in have_agents:
            nodes.append({"id": "lead", "kind": "agent", "label": "final answer", "role": "lead"})
            have_agents.add("lead")
        if aid in have_agents:
            links.append({"source": aid, "target": f"s{sid}", "kind": "cited", "verdict": v})

    return {"nodes": nodes, "links": links}


def _brief(question: str, ld: dict, trust: dict, cells_: list[dict],
           retracted: list[dict], reg) -> str:
    verdict_rows = [
        {"sentence": c["sentence_id"], "verdict": c["verdict"], "source": c["source_id"],
         "reason": (c.get("reason") or "")[:160]}
        for c in cells_
    ]
    sources = [{"n": s.id, "domain": s.domain, "title": s.title[:100]} for s in reg.all()]
    return (
        f"QUESTION:\n{question}\n\n"
        f"VERIFIED ANSWER:\n{ld['text']}\n\n"
        f"TRUST TALLY:\n{json.dumps(trust)}\n\n"
        f"CLAIM VERDICTS ({len(verdict_rows)}):\n{json.dumps(verdict_rows)}\n\n"
        f"WITHDRAWN ({len(retracted)}):\n{json.dumps(retracted)}\n\n"
        f"SOURCES:\n{json.dumps(sources)}\n\n"
        f"Produce the report now."
    )


async def run_reporter(query_id: str, question: str, ld: dict, trust: dict,
                       cells_: list[dict], retracted: list[dict], reg, emit, cancel) -> None:
    emit("agent_status", {"agent_id": "reporter", "status": "drafting",
                          "detail": "compiling the audit report"})
    ws = Path(config.DATA_DIR) / "artifacts" / query_id
    ctx = Ctx(agent="reporter", emit=emit, registry=reg, cancel=cancel, workspace=str(ws))
    sp = spec("reporter", tools=("run_python", "write_file", "make_document"),
              max_steps=6, num_ctx=32768)
    try:
        await run_agent(sp, ctx, _brief(question, ld, trust, cells_, retracted, reg))
        emit("agent_status", {"agent_id": "reporter", "status": "done"})
    except Exception as e:
        # The answer is already delivered — a failed report degrades, never breaks, the run.
        emit("agent_status", {"agent_id": "reporter", "status": "failed", "detail": str(e)[:200]})
        emit("error", {"scope": "reporter", "message": f"report failed: {type(e).__name__}: {e}"})
