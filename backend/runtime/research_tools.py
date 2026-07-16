"""The sub-agent's tools: search the web, read a page.

The important bit is in `read_page`: it interns the URL into the SourceRegistry and hands the
agent back a small LOCAL number to cite. The agent never sees or handles a global id. Models are
reliable at citing [1]..[6]; they are not reliable at citing [17] out of a shared 30-source pool,
and every slip there is a chip pointing at the wrong source.
"""
from __future__ import annotations

from ..providers import lanes, rrf
from .tools import Ctx, obj, tool


@tool(
    "web_search",
    "Search the web for a query. Returns ranked results with a URL, title and short snippet. "
    "A snippet is a LEAD, not a source — you must read_page before citing anything.",
    obj({"query": {"type": "string", "description": "the search query"}}, ["query"]),
)
async def web_search(args: dict, ctx: Ctx) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "ERROR: empty query"

    ctx.emit("agent_status", {"agent_id": ctx.agent, "status": "searching", "detail": query[:80]})
    got = await lanes.search_all(query, ctx.lanes, 10)
    fused = rrf.fuse(got)[: ctx.max_sources + 4]
    if not fused:
        return "No results. Try different words."

    # Stash bodies lanes already gave us so read_page can skip the fetch chain.
    for f in fused:
        if f.get("body"):
            _BODIES[rrf.normalize_url(f["url"])] = f["body"]

    out = []
    for i, f in enumerate(fused, 1):
        corro = f"  [found by {'+'.join(f['_lanes'])}]" if len(f["_lanes"]) > 1 else ""
        snippet = (f.get("content") or "")[:200].replace("\n", " ")
        out.append(f"{i}. {f['title'][:110]}\n   {f['url']}{corro}\n   {snippet}")
    return "\n".join(out)


_BODIES: dict[str, str] = {}


@tool(
    "read_page",
    "Read the full text of a page. Returns the text and the citation number you must use for it. "
    "Read a page before making any claim about what it says.",
    obj({"url": {"type": "string", "description": "the exact URL to read"}}, ["url"]),
)
async def read_page(args: dict, ctx: Ctx) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        return "ERROR: empty url"
    if ctx.registry is None:
        return "ERROR: no source registry"

    ctx.emit("agent_status", {"agent_id": ctx.agent, "status": "reading", "detail": url[:90]})
    norm = rrf.normalize_url(url)
    d = await lanes.fetch(norm, _BODIES.get(norm, ""))
    if not d or not d.get("content"):
        return f"ERROR: could not read {url}. It may be paywalled or unavailable. Try another source."

    local = ctx.registry.intern(
        ctx.agent, norm, d.get("title") or "", d["content"], via=d.get("via", "")
    )
    src = ctx.registry.get(ctx.registry.to_global(ctx.agent, local))
    if src:
        ctx.emit("source", {
            "id": src.id, "url": src.url, "title": src.title, "domain": src.domain,
            "n_chars": len(src.body), "first_agent": src.first_agent, "via": src.via,
        })

    body = d["content"]
    return (
        f"Read OK. Cite this page as [{local}].\n"
        f"TITLE: {d.get('title') or norm}\nURL: {norm}\n\n{body}"
    )
