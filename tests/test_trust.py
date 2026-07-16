"""A withdrawn sentence must never improve the score by leaving.

This is the product's own thesis pointed at its own scoreboard. A retracted sentence is repaired to
EMPTY text, so it yields no claims -> no verdicts -> no cells. Scored from cells alone it does not
merely miscount: it disappears, and the trust number goes UP because the sentences that failed
hardest quietly left the denominator. The UI showed `withdrawn, shown  0` next to a page full of
struck-through copy.
"""
from __future__ import annotations

from backend.pipeline.heatmap import trust


def cell(sid: str, src: int, verdict: str) -> dict:
    return {"sentence_id": sid, "source_id": src, "verdict": verdict}


def test_retracted_sentence_is_counted_not_dropped():
    # s3 was withdrawn: repaired to "" -> it has no cells at all.
    cells = [cell("a1.s1", 1, "supported"), cell("a1.s2", 1, "weak")]
    t = trust(cells, retracted=[{"sentence_id": "a1.s3", "text": "nope", "reason": "no support"}])
    assert t["retracted"] == 1
    assert t["total"] == 3, "the withdrawn sentence must stay in the denominator"


def test_retraction_lowers_the_score():
    cells = [cell("a1.s1", 1, "supported"), cell("a1.s2", 1, "supported")]
    clean = trust(cells)
    withheld = trust(cells, retracted=[{"sentence_id": "a1.s3", "text": "x", "reason": "y"}])
    assert clean["score"] == 1.0
    assert withheld["score"] < clean["score"], "withdrawing a claim must not flatter the number"


def test_retracted_wins_over_stale_iteration_zero_verdict():
    # s2 still carries its pre-repair 'unsupported' cell. It was withdrawn; it counts as withdrawn,
    # not as unsupported, and it must not be double-counted.
    cells = [cell("a1.s1", 1, "supported"), cell("a1.s2", 1, "unsupported")]
    t = trust(cells, retracted=[{"sentence_id": "a1.s2", "text": "x", "reason": "y"}])
    assert t["retracted"] == 1
    assert t["unsupported"] == 0
    assert t["total"] == 2


def test_no_retractions_is_unchanged():
    cells = [cell("a1.s1", 1, "supported"), cell("a1.s1", 2, "weak"), cell("a1.s2", 1, "contradicted")]
    t = trust(cells)
    # worst-wins per sentence: s1 is weak (cites two sources), s2 contradicted.
    assert t["retracted"] == 0
    assert t["weak"] == 1 and t["contradicted"] == 1
    assert t["total"] == 2
