import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.segment import claim_candidates, segment


def _roundtrip(txt):
    """The invariant everything else rests on."""
    for s in segment(txt):
        assert txt[s.start : s.end] == s.text, f"offset drift at {s.id!r}: {s.text!r}"


def test_basic_offsets_roundtrip():
    _roundtrip("First one [1]. Second one [2]! Third one?")


def test_only_cited_sentences_are_claim_candidates():
    ss = segment("Ollama caps at ten [3]. This sentence cites nothing. Tavily is free [1].")
    assert len(ss) == 3
    assert [s.id for s in claim_candidates(ss)] == ["s1", "s3"]


def test_cited_ids_extracted_and_deduped():
    ss = segment("A claim citing two [1][4] sources. And one repeating [2][2].")
    assert ss[0].cited == (1, 4)
    assert ss[1].cited == (2,)


def test_does_not_split_decimals():
    ss = segment("Pi is 3.14159 and that is one sentence [1].")
    assert len(ss) == 1


def test_does_not_split_abbreviations():
    ss = segment("See Dr. Smith et al. for the details [2]. Then stop.")
    assert len(ss) == 2, [s.text for s in ss]


def test_does_not_split_inside_code_fence():
    """The fence becomes its own unit and is never split internally. It carries no citation,
    so it is not a claim candidate and never reaches the verifier."""
    txt = 'Run this [1]:\n\n```python\nx = 1. y = 2. z = 3.\n```\n\nThen done [2].'
    ss = segment(txt)
    assert len(ss) == 3, [s.text for s in ss]
    assert ss[1].text.startswith("```") and ss[1].cited == ()
    assert ss[1] not in claim_candidates(ss)
    assert [s.cited for s in ss] == [(1,), (), (2,)]
    _roundtrip(txt)


def test_markdown_structure_is_a_hard_boundary():
    """Blank lines, list items and headings split regardless of punctuation — otherwise a line
    ending in ':' swallows the rest and merges unrelated citation contexts into one row."""
    txt = "Intro [1]:\n\n- bullet one [3]\n- bullet two [4]\n\n## Heading\n\nFinal [5]."
    ss = segment(txt)
    _roundtrip(txt)
    assert [s.cited for s in ss] == [(1,), (3,), (4,), (), (5,)]


def test_markers_do_not_break_offsets():
    _roundtrip("Claim one [10]. Claim two [11]. Claim three [12].")


def test_empty_and_whitespace():
    assert segment("") == []
    assert segment("   \n  ") == []


def test_no_trailing_punctuation_still_emits():
    ss = segment("A dangling final clause with a cite [1]")
    assert len(ss) == 1 and ss[0].cited == (1,)


def test_realistic_multiline_answer_roundtrips():
    txt = (
        "Ollama's web search API caps at ten results per query [1]. The free tier's limits "
        "are not published anywhere [1][2].\n\n"
        "Tavily returns raw page content inline, which removes a fetch round-trip [3].\n"
        "It costs nothing for the first 1,000 credits per month [3]."
    )
    _roundtrip(txt)
    ss = segment(txt)
    assert len(claim_candidates(ss)) == 4
    assert ss[1].cited == (1, 2)
