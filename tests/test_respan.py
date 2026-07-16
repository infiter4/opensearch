"""Row identity must survive repair.

segment() assigns ids by position, so re-segmenting after a retraction shifts every later id down
by one. The heatmap keys cells on (sentence_id, source_id) and SHOW FIRST DRAFT diffs iteration 0
against iteration 1 by sentence_id, so a shifted id makes both compare unrelated sentences — and
the board renders perfectly while lying. These tests are the tripwire.
"""
from backend.pipeline import heatmap, segment


def _seg(text):
    return segment.segment(text, prefix="a1.s")


TEXT = "Alpha costs five dollars [1]. Beta is free [2]. Gamma has limits [3]."


def test_retraction_does_not_shift_later_ids():
    s0 = _seg(TEXT)
    assert [s.id for s in s0] == ["a1.s1", "a1.s2", "a1.s3"]

    text, s1 = segment.respan(TEXT, s0, {"a1.s2": ""})

    # The bug: s3's prose silently becomes s2 after a re-segment.
    survivors = {s.id: s.text for s in s1 if s.text}
    assert survivors["a1.s1"] == "Alpha costs five dollars [1]."
    assert survivors["a1.s3"] == "Gamma has limits [3]."
    assert "a1.s2" not in survivors
    assert text == "Alpha costs five dollars [1]. Gamma has limits [3]."


def test_retracted_row_survives_as_zero_width():
    # A vanishing row is how you lie with a UI: the row stays, hatched grey.
    _, s1 = segment.respan(TEXT, _seg(TEXT), {"a1.s2": ""})
    row = next(s for s in s1 if s.id == "a1.s2")
    assert row.text == "" and row.start == row.end
    assert [s.id for s in s1] == ["a1.s1", "a1.s2", "a1.s3"]


def test_offsets_round_trip_after_every_edit():
    for edits in ({"a1.s1": ""}, {"a1.s3": ""}, {"a1.s2": "Beta costs money [2]."},
                  {"a1.s1": "", "a1.s3": ""}, {"a1.s1": "X [1].", "a1.s2": ""}):
        text, sents = segment.respan(TEXT, _seg(TEXT), edits)
        for s in sents:
            assert text[s.start:s.end] == s.text, (edits, s.id)


def test_rewrite_keeps_id_and_recomputes_citations():
    _, s1 = segment.respan(TEXT, _seg(TEXT), {"a1.s2": "Beta has a free tier [2][4]."})
    row = next(s for s in s1 if s.id == "a1.s2")
    assert row.text == "Beta has a free tier [2][4]."
    assert row.cited == (2, 4)


def test_multi_sentence_rewrite_stays_one_row():
    # Rows must not move: a replacement holding two sentences does not become two rows.
    _, s1 = segment.respan(TEXT, _seg(TEXT), {"a1.s2": "Beta is cheap [2]. It has a free tier [2]."})
    assert [s.id for s in s1] == ["a1.s1", "a1.s2", "a1.s3"]


def test_retraction_leaves_no_double_space():
    text, _ = segment.respan(TEXT, _seg(TEXT), {"a1.s2": ""})
    assert "  " not in text
    text, _ = segment.respan(TEXT, _seg(TEXT), {"a1.s1": ""})
    assert not text.startswith(" ")


def test_markdown_structure_survives_retraction():
    # The old tail rebuilt text as " ".join(sentences), collapsing every paragraph and list item.
    md = "Pricing works as follows [1].\n\n- Free tier is limited [2].\n- Paid tier scales [3]."
    s0 = _seg(md)
    victim = next(s for s in s0 if "Free tier" in s.text)
    text, _ = segment.respan(md, s0, {victim.id: ""})
    assert "Pricing works as follows [1]." in text
    assert "- Paid tier scales [3]." in text
    assert "\n" in text, "markdown structure was flattened"


def test_retracted_row_still_reaches_the_board():
    # A grid that resolves clean by deleting its own failures is a lie. The row stays, struck
    # through, carrying the original text and the reason it died.
    s0 = _seg(TEXT)
    _, s1 = segment.respan(TEXT, s0, {"a1.s2": ""})
    retracted = [{"sentence_id": "a1.s2", "text": "Beta is free [2].", "reason": "source says $30/mo"}]

    out = heatmap.rows([{"agent_id": "a1", "sentences": s1, "failed": False}], None, retracted)
    by_id = {r["sentence_id"]: r for r in out}

    assert "a1.s2" in by_id, "retracted row vanished from the board"
    assert by_id["a1.s2"]["retracted"] is True
    assert by_id["a1.s2"]["text"] == "Beta is free [2]."
    assert by_id["a1.s2"]["reason"] == "source says $30/mo"
    assert [r["sentence_id"] for r in out] == ["a1.s1", "a1.s2", "a1.s3"]


def test_uncited_prose_is_still_not_a_row():
    s0 = _seg("Here is some framing prose. Alpha costs five dollars [1].")
    out = heatmap.rows([{"agent_id": "a1", "sentences": s0, "failed": False}], None, [])
    assert [r["sentence_id"] for r in out] == ["a1.s2"]


def test_ids_stable_across_two_iterations():
    s0 = _seg(TEXT)
    text, s1 = segment.respan(TEXT, s0, {"a1.s1": ""})
    text, s2 = segment.respan(text, s1, {"a1.s3": "Gamma is capped at ten [3]."})
    final = {s.id: s.text for s in s2}
    assert final["a1.s1"] == ""
    assert final["a1.s2"] == "Beta is free [2]."
    assert final["a1.s3"] == "Gamma is capped at ten [3]."
    for s in s2:
        assert text[s.start:s.end] == s.text
