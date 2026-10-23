"""Renumbering must touch citations and nothing else: not code, and not a grouped citation it
used to let through with its LOCAL numbers still in it."""
from backend.pipeline import renumber, segment
from backend.pipeline.sources import SourceRegistry


def _reg():
    r = SourceRegistry()
    r.intern("a0", "https://z.org/1", "z", "body")      # globals 1 and 2 belong to another agent
    r.intern("a0", "https://z.org/2", "z", "body")
    r.intern("a1", "https://a.org/1", "a", "body")      # a1 local 1 -> global 3
    r.intern("a1", "https://a.org/2", "b", "body")      # a1 local 2 -> global 4
    return r


def test_inline_and_fenced_code_survive_renumbering_untouched():
    draft = ("The top hit is `response['results'][0]` [1].\n\n"
             "```python\nfirst = results[1]\nsecond = results[2]\n```\n\nNo pagination [2].")
    out, orphans = renumber.to_global(draft, "a1", _reg())
    assert orphans == [], "a subscript was reported as an invented citation"
    assert "`response['results'][0]` [3]." in out
    assert "first = results[1]\nsecond = results[2]" in out
    assert out.endswith("No pagination [4].")
    assert [s.cited for s in segment.segment(out)] == [(3,), (), (4,)]


def test_validate_and_markers_ignore_code():
    out, orphans = renumber.validate("Use `a[77]` here [1].", {1})
    assert out == "Use `a[77]` here [1]." and orphans == []
    assert renumber.markers("call `f[9]` then cite [2]") == [2]


def test_grouped_and_ranged_citations_are_expanded_then_renumbered():
    out, orphans = renumber.to_global("Both return JSON [1, 2]. Fused with RRF [1-2].", "a1", _reg())
    assert out == "Both return JSON [3][4]. Fused with RRF [3][4]."
    assert orphans == []
    assert [s.cited for s in segment.segment(out)] == [(3, 4), (3, 4)]


def test_an_invented_number_inside_a_group_is_dropped_alone():
    out, orphans = renumber.to_global("Both caps are ten [1, 7].", "a1", _reg())
    assert out == "Both caps are ten [3]." and orphans == [7]
    out, orphans = renumber.validate("Merged claim [2, 99].", {1, 2})
    assert out == "Merged claim [2]." and orphans == [99]


def test_intervals_are_not_citations():
    # A probability in [0, 1] or a span [1-50] is prose, and stays exactly as written.
    out, orphans = renumber.to_global("Scores lie in [0, 1] and ids in [1-50] [1].", "a1", _reg())
    assert out == "Scores lie in [0, 1] and ids in [1-50] [3]." and orphans == []


def test_strip_removes_markers_but_not_code():
    assert renumber.strip("X is Y [2][3]. See `a[1]`.") == "X is Y. See `a[1]`."
