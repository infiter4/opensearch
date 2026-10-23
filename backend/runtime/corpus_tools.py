"""The corpus sub-agent's tools: search the workspace's ingested documents, read a passage.

Deliberately the SAME shape as research_tools.web_search/read_page. corpus_read interns the chunk
into the run's SourceRegistry and hands back a small LOCAL citation number — so renumber, segment,
claims, verify, rewrite, lead and the citation drawer all work byte-for-byte unchanged, now
fact-checking against the user's own documents. This is the whole integration seam.
"""
from __future__ import annotations

from .. import retrieval
from ..providers import rrf
from ..store import chunks as chunks_store
from .tools import Ctx, obj, tool

# url -> (title, body, locator), stashed by corpus_search so corpus_read skips a DB round-trip.
_BODIES: dict[str, tuple[str, str, str | None]] = {}


@tool(
    "corpus_search",
    "Search the project's ingested documents for a query. Returns ranked passages with an id, "
    "title and snippet. A snippet is a LEAD — you must corpus_read a passage before citing it.",
    obj({"query": {"type": "string", "description": "the search query"}}, ["query"]),
)
async def corpus_search(args: dict, ctx: Ctx) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "ERROR: empty query"
    if not ctx.workspace_id:
        return "ERROR: no workspace bound to this run"

    ctx.emit("agent_status", {"agent_id": ctx.agent, "status": "searching", "detail": query[:80]})
    hits = await retrieval.retrieve(ctx.workspace_id, ctx.embed_model or "", query,
                                    k=ctx.max_sources + 4)
    if not hits:
        return "No matching passages in this workspace. Try different words."

    out = []
    for i, h in enumerate(hits, 1):
        url = rrf.normalize_url(h["url"])
        _BODIES[url] = (h.get("title") or "", h.get("body") or "", h.get("locator"))
        corro = f"  [found by {'+'.join(h['_lanes'])}]" if len(h.get("_lanes", [])) > 1 else ""
        loc = f" ({h['locator']})" if h.get("locator") else ""
        snippet = (h.get("body") or "")[:200].replace("\n", " ")
        out.append(f"{i}. {(h.get('title') or 'passage')[:110]}{loc}\n   {url}{corro}\n   {snippet}")
    return "\n".join(out)


@tool(
    "corpus_read",
    "Read the full text of a passage by its id (the corpus:// url from corpus_search). Returns the "
    "text and the citation number you must use for it. Read before making any claim about it.",
    obj({"url": {"type": "string", "description": "the corpus:// id from corpus_search"}}, ["url"]),
)
async def corpus_read(args: dict, ctx: Ctx) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        return "ERROR: empty id"
    if ctx.registry is None:
        return "ERROR: no source registry"
    norm = rrf.normalize_url(url)

    hit = _BODIES.get(norm)
    if hit is not None:
        title, body, locator = hit
    else:
        row = await chunks_store.by_url(ctx.workspace_id, norm)
        if not row:
            return f"ERROR: no such passage: {url}"
        title, body, locator = row.get("title") or "", row["body"], row.get("locator")

    ctx.emit("agent_status", {"agent_id": ctx.agent, "status": "reading", "detail": (title or norm)[:90]})
    local = ctx.registry.intern(ctx.agent, norm, title or norm, body, via="corpus")
    src = ctx.registry.get(ctx.registry.to_global(ctx.agent, local))
    if src:
        ctx.emit("source", {
            "id": src.id, "url": src.url, "title": src.title, "domain": "corpus",
            "n_chars": len(src.body), "first_agent": src.first_agent, "lane": "corpus",
            "locator": locator,
        })

    where = f" ({locator})" if locator else ""
    return (
        f"Read OK. Cite this passage as [{local}].\n"
        f"TITLE: {title or 'passage'}{where}\nURL: {norm}\n\n{body}"
    )
