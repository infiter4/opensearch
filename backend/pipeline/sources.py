"""Global source identity.

The trap this exists to defuse: each sub-agent numbers its own citations [1],[2],[3]. Three
sub-agents each have a different [1]. Merging those namespaces is mechanical index remapping across
N documents — precisely what models botch silently, and every botch is a chip pointing at the wrong
source. In a product whose entire pitch is citation fidelity, that failure is invisible AND fatal.

So: global ids are allocated in CODE, at retrieval time, before any model sees anything.
Sub-agents cite small dense LOCAL numbers (the regime models are reliable in); renumber.py maps
local -> global afterwards, also in code.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..providers.rrf import domain, normalize_url


@dataclass
class Source:
    id: int
    url: str
    title: str
    body: str
    domain: str = ""
    first_agent: str = ""
    lanes: tuple[str, ...] = ()
    via: str = ""


@dataclass
class SourceRegistry:
    _by_url: dict[str, int] = field(default_factory=dict)
    _sources: dict[int, Source] = field(default_factory=dict)
    _local: dict[tuple[str, int], int] = field(default_factory=dict)
    _next_local: dict[str, int] = field(default_factory=dict)

    def intern(
        self,
        agent_id: str,
        url: str,
        title: str,
        body: str,
        lanes: tuple[str, ...] = (),
        via: str = "",
    ) -> int:
        """Register a source this agent just read. Returns the LOCAL number it should cite.

        The global id is allocated on first sight of this URL by ANY agent, so cross-agent URL
        dedup is automatic and free — and two agents independently citing the same URL is exactly
        the corroboration signal the board draws as a string crossing the whole width.
        """
        u = normalize_url(url)
        gid = self._by_url.get(u)
        if gid is None:
            gid = len(self._by_url) + 1
            self._by_url[u] = gid
            self._sources[gid] = Source(
                id=gid, url=u, title=title or u, body=body,
                domain=domain(u), first_agent=agent_id, lanes=tuple(lanes), via=via,
            )

        # If this agent already cited this URL, reuse its existing local number rather than
        # burning a new one — otherwise [2] and [5] silently mean the same page.
        for (a, ln), g in self._local.items():
            if a == agent_id and g == gid:
                return ln

        ln = self._next_local.get(agent_id, 0) + 1
        self._next_local[agent_id] = ln
        self._local[(agent_id, ln)] = gid
        return ln

    def to_global(self, agent_id: str, local: int) -> int | None:
        return self._local.get((agent_id, local))

    def get(self, gid: int) -> Source | None:
        return self._sources.get(gid)

    def body(self, gid: int) -> str:
        s = self._sources.get(gid)
        return s.body if s else ""

    def ids(self) -> set[int]:
        return set(self._sources)

    def all(self) -> list[Source]:
        return [self._sources[i] for i in sorted(self._sources)]

    def manifest(self) -> list[dict]:
        """What the LEAD is allowed to see: identity only, never bodies. The lead having no
        source text is what makes verifying it a genuinely independent check."""
        return [
            {"id": s.id, "url": s.url, "title": s.title, "domain": s.domain}
            for s in self.all()
        ]

    def columns(self) -> list[dict]:
        """Heatmap columns, ordered by first-interning agent so the matrix is block-diagonal."""
        srcs = sorted(self.all(), key=lambda s: (s.first_agent, s.id))
        # "id", matching the `source` event — the frontend keys cells and clicks on it.
        return [
            {"id": s.id, "url": s.url, "title": s.title,
             "domain": s.domain, "first_agent": s.first_agent}
            for s in srcs
        ]
