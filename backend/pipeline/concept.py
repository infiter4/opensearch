"""The ANSWER as a graph — entities and the relationships between them.

Not provenance. The provenance graph (report.graph) answers "how was this made": question -> agent
-> source. Useful once, to a judge. What a reader actually wants is the ANSWER rearranged: the
plans, the prices, the limits, and how they relate.

This is the only stage that reads the finished answer and nothing else. It runs ON DEMAND — nobody
pays a model call for a view they never opened — and the result is cached on the session, so
opening the graph twice costs one call.
"""
from __future__ import annotations

import re
from typing import Any

from ..providers import llm

PROMPT = """You turn a finished research answer into a knowledge graph.

Extract the ENTITIES the answer talks about and the RELATIONSHIPS it states between them.

Rules:
- Only what the answer actually says. Invent nothing, infer nothing.
- Entities are concrete things: products, plans, tiers, endpoints, limits, prices, organisations.
- A value (a price, a quota, a rate) IS an entity — that is what makes the graph informative.
- Prefer many small precise nodes over a few vague ones. Aim for 12-28 nodes.
- Every link must be a relationship the answer states, with a short verb label
  ("costs", "includes", "limited to", "requires", "part of").
- ids: short lowercase slugs, unique, no spaces.
- Every link's source and target MUST be an id present in nodes.

type is one of:
  "root"   the single central subject of the answer (exactly one)
  "entity" a thing: a plan, a product, an endpoint, an organisation
  "value"  a number or a limit: a price, a quota, a rate
  "concept" anything else worth a node

Return ONLY JSON:
{"nodes":[{"id":"tavily","label":"Tavily API","type":"root"},
          {"id":"free","label":"Free (Researcher)","type":"entity"},
          {"id":"c1000","label":"1,000 credits/mo","type":"value"}],
 "links":[{"source":"tavily","target":"free","label":"offers"},
          {"source":"free","target":"c1000","label":"includes"}]}
"""

_SLUG = re.compile(r"[^a-z0-9_]+")


def _slug(s: str) -> str:
    return _SLUG.sub("_", str(s).strip().lower())[:40] or "n"


def _clean(raw: Any, question: str) -> dict:
    """Keep only well-formed nodes, and only links whose BOTH ends exist.

    A dangling link is not cosmetic: 3d-force-graph throws on an edge pointing at a missing node
    and takes the whole view down with it. The model is asked for valid ids; it is never trusted
    for them.
    """
    nodes_in = raw.get("nodes") if isinstance(raw, dict) else None
    links_in = raw.get("links") if isinstance(raw, dict) else None
    if not isinstance(nodes_in, list):
        return {"nodes": [], "links": []}

    nodes: list[dict] = []
    seen: set[str] = set()
    for n in nodes_in:
        if not isinstance(n, dict):
            continue
        label = str(n.get("label") or "").strip()
        if not label:
            continue
        nid = _slug(n.get("id") or label)
        if nid in seen:
            continue
        seen.add(nid)
        kind = str(n.get("type") or "concept").lower()
        if kind not in ("root", "entity", "value", "concept"):
            kind = "concept"
        nodes.append({"id": nid, "label": label[:60], "type": kind})

    links: list[dict] = []
    pairs: set[tuple[str, str]] = set()
    for l in links_in if isinstance(links_in, list) else []:
        if not isinstance(l, dict):
            continue
        a, b = _slug(l.get("source") or ""), _slug(l.get("target") or "")
        if a not in seen or b not in seen or a == b or (a, b) in pairs:
            continue
        pairs.add((a, b))
        links.append({"source": a, "target": b, "label": str(l.get("label") or "")[:28]})

    # Exactly one root, and never zero — the layout hangs everything off it.
    roots = [n for n in nodes if n["type"] == "root"]
    if not roots and nodes:
        nodes[0]["type"] = "root"
    elif len(roots) > 1:
        for extra in roots[1:]:
            extra["type"] = "entity"

    # An orphan renders as a dot floating in space with no story. Hang it off the root.
    if nodes:
        root = next(n["id"] for n in nodes if n["type"] == "root")
        linked = {l["source"] for l in links} | {l["target"] for l in links}
        for n in nodes:
            if n["id"] != root and n["id"] not in linked:
                links.append({"source": root, "target": n["id"], "label": ""})

    return {"nodes": nodes, "links": links}


async def extract(question: str, answer_text: str) -> dict:
    """One call. Returns {nodes, links} — empty rather than raising, so a view never breaks a run."""
    if not (answer_text or "").strip():
        return {"nodes": [], "links": []}
    try:
        raw = await llm.complete_json(
            llm.model_for("claims"),
            [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": f"Question: {question}\n\nAnswer:\n{answer_text[:9000]}"},
            ],
            num_ctx=16384,
            temperature=0.1,
        )
    except Exception as e:
        # Still empty, still never raising — but SAID. A bare empty graph read as "nothing to
        # chart in this answer" when the truth was that the extraction call failed.
        return {"nodes": [], "links": [], "error": f"the extraction call failed ({type(e).__name__})"}
    return _clean(raw, question)
