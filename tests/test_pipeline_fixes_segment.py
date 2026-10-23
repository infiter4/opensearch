"""Citation markers have to stay with the sentence they belong to, and a retraction must not
glue the next block of markdown onto the line before it."""
from backend.pipeline import segment


def _roundtrip(txt, ss):
    for s in ss:
        assert txt[s.start:s.end] == s.text, s.id


def test_marker_after_the_period_stays_with_its_sentence():
    # Observed writer output. Ending the sentence at the period handed [1] to the NEXT sentence,
    # which was then verified against a source it never cited.
    txt = "Tavily is free for 1,000 credits. [1] OpenAlex needs no key. [2]"
    ss = segment.segment(txt, prefix="a1.s")
    _roundtrip(txt, ss)
    assert [s.cited for s in ss] == [(1,), (2,)]
    assert ss[0].text == "Tavily is free for 1,000 credits. [1]"


def test_marker_glued_to_the_period_still_splits_the_sentences():
    # "B.[1] C.[2]" used to be one row citing both.
    txt = "Tavily is free.[1] OpenAlex needs no key.[2]"
    ss = segment.segment(txt, prefix="a1.s")
    _roundtrip(txt, ss)
    assert [s.cited for s in ss] == [(1,), (2,)]


def test_trailing_marker_run_is_not_a_row_of_its_own():
    txt = "Replication work disputes the method, not the core finding. [1][2]"
    ss = segment.segment(txt)
    assert len(ss) == 1 and ss[0].cited == (1, 2)


def test_a_reference_list_under_a_paragraph_is_not_swallowed():
    # Same line only: the marker opening the next paragraph belongs to that paragraph.
    txt = "It includes Microsoft's Math Solver [1].\n\n[1] https://example.org/solver"
    ss = segment.segment(txt)
    _roundtrip(txt, ss)
    assert [s.text for s in ss] == ["It includes Microsoft's Math Solver [1].",
                                    "[1] https://example.org/solver"]


def test_markers_inside_code_are_not_citations():
    txt = "Index with `items[0]` to get the first hit [2].\n\n```python\nx = results[1]\n```"
    ss = segment.segment(txt)
    assert [s.cited for s in ss] == [(2,), ()]


def test_retracting_the_last_sentence_keeps_the_heading_on_its_own_line():
    txt = ("Tavily gives 1,000 credits [1]. Its uptime is 99.99% [2].\n\n"
           "## What we could not establish\n\n- OpenAlex rate limits")
    s0 = segment.segment(txt, prefix="lead.s")
    out, s1 = segment.respan(txt, s0, {"lead.s2": ""})
    assert out == ("Tavily gives 1,000 credits [1].\n\n"
                   "## What we could not establish\n\n- OpenAlex rate limits")
    _roundtrip(out, s1)
    assert [s.id for s in s1] == [s.id for s in s0], "rows must not move"


def test_retracting_before_a_list_keeps_the_list_item_on_its_own_line():
    txt = "Intro A [1]. Intro B [2].\n- item one [3]\n- item two [4]"
    out, s1 = segment.respan(txt, segment.segment(txt, prefix="a1.s"), {"a1.s2": ""})
    assert out == "Intro A [1].\n- item one [3]\n- item two [4]"
    _roundtrip(out, s1)


def test_retraction_spacing_is_stable_across_rounds():
    txt = "A [1]. B [2].\n\n## H\n\nC [3]."
    out1, s1 = segment.respan(txt, segment.segment(txt, prefix="a1.s"), {"a1.s2": ""})
    out2, s2 = segment.respan(out1, s1, {"a1.s4": "C is capped [3]."})
    assert out2 == "A [1].\n\n## H\n\nC is capped [3]."
    _roundtrip(out2, s2)


def test_consecutive_retractions_do_not_merge_paragraphs():
    txt = "A [1]. B [2]. C [3].\n\nD [4]."
    out, s1 = segment.respan(txt, segment.segment(txt, prefix="a1.s"), {"a1.s2": "", "a1.s3": ""})
    assert out == "A [1].\n\nD [4]."
    _roundtrip(out, s1)
