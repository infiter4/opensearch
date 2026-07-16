import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.renumber import markers, to_global, validate
from backend.pipeline.sources import SourceRegistry


def _reg():
    r = SourceRegistry()
    # a reads ollama.com, docs.ollama.com ; b reads docs.ollama.com (SHARED), tavily.com
    assert r.intern("a", "https://ollama.com/blog/web-search", "Blog", "x" * 900) == 1
    assert r.intern("a", "https://docs.ollama.com/web-search", "Docs", "y" * 900) == 2
    assert r.intern("b", "https://docs.ollama.com/web-search", "Docs", "y" * 900) == 1
    assert r.intern("b", "https://tavily.com/pricing", "Tavily", "z" * 900) == 2
    return r


def test_shared_url_collapses_to_one_global_id():
    r = _reg()
    assert r.to_global("a", 2) == r.to_global("b", 1) == 2
    assert len(r.ids()) == 3  # not 4 — the shared docs URL is one source


def test_disjoint_agents_remap_independently():
    r = _reg()
    assert to_global("p [1] q [2]", "a", r) == ("p [1] q [2]", [])
    # b's local [1] is global 2, b's local [2] is global 3
    assert to_global("p [1] q [2]", "b", r) == ("p [2] q [3]", [])


def test_orphan_marker_dropped_not_guessed():
    r = _reg()
    out, orphans = to_global("real [1] invented [9]", "a", r)
    assert orphans == [9]
    assert "[9]" not in out
    assert "[1]" in out


def test_url_normalisation_dedups_across_agents():
    r = SourceRegistry()
    r.intern("a", "https://WWW.Example.com/p/?utm_source=x#frag", "T", "b" * 900)
    r.intern("b", "http://example.com/p", "T", "b" * 900)
    assert len(r.ids()) == 1


def test_same_agent_same_url_reuses_local_number():
    r = SourceRegistry()
    assert r.intern("a", "https://x.com/a", "A", "b" * 900) == 1
    assert r.intern("a", "https://x.com/a", "A", "b" * 900) == 1  # not 2


def test_lead_validate_drops_unknown_markers():
    out, orphans = validate("ok [1] bad [77]", {1, 2, 3})
    assert orphans == [77] and "[77]" not in out and "[1]" in out


def test_offsets_roundtrip_after_renumber():
    """The ordering rule: renumber THEN segment. Offsets taken on the renumbered text must
    index back into that exact string."""
    from backend.pipeline.segment import segment

    r = _reg()
    txt, _ = to_global("First claim [1]. Second claim [2]. Third has none.", "b", r)
    for s in segment(txt):
        assert txt[s.start : s.end] == s.text


def test_markers_helper():
    assert markers("a [1] b [23] c") == [1, 23]
