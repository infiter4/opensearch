"""URL normalisation + Reciprocal Rank Fusion.

RRF is the standard way to merge ranked lists from heterogeneous retrievers, and it buys one thing
for free that matters here: a URL surfaced by BOTH Ollama and Tavily gets both lanes' contributions
summed, so cross-engine agreement floats to the top without a reranker (which would cost ~15 more
LLM calls against the same unpublished rate limit).
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

RRF_K = 60

_JUNK_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "spm", "_hsenc", "_hsmi",
}


def normalize_url(url: str) -> str:
    """Collapse the same page reached different ways. Runs BEFORE global-id allocation, so
    dedup across sub-agents is automatic."""
    try:
        s = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = "https" if s.scheme in ("http", "https", "") else s.scheme
    host = s.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":443"):
        host = host[:-4]
    if host.endswith(":80"):
        host = host[:-3]
    path = s.path.rstrip("/") or "/"
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if k.lower() not in _JUNK_PARAMS]
    return urlunsplit((scheme, host, path, urlencode(sorted(q)), ""))  # fragment always dropped


def domain(url: str) -> str:
    try:
        h = urlsplit(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except ValueError:
        return ""


def fuse(lanes: dict[str, list[dict]], k: int = RRF_K) -> list[dict]:
    """lanes: {lane_name: [result, ...]} already in that lane's rank order.

    Returns results sorted by fused score, each annotated with `_rrf` and `_lanes`. A result found
    by two lanes carries both — that is the corroboration signal, and it's free.
    """
    scored: dict[str, dict] = {}
    for lane, results in lanes.items():
        for rank, r in enumerate(results):
            url = normalize_url(r.get("url", ""))
            if not url:
                continue
            e = scored.get(url)
            if e is None:
                e = {**r, "url": url, "_rrf": 0.0, "_lanes": []}
                scored[url] = e
            e["_rrf"] += 1.0 / (k + rank + 1)
            if lane not in e["_lanes"]:
                e["_lanes"].append(lane)
            # Keep the best text each lane offered for this url. `body` is real page text and
            # skips the fetch chain; `content` may be a mere snippet. Never conflate them.
            if len(r.get("body") or "") > len(e.get("body") or ""):
                e["body"] = r.get("body")
            if len(r.get("content") or "") > len(e.get("content") or ""):
                e["content"] = r.get("content")
    return sorted(scored.values(), key=lambda e: -e["_rrf"])
