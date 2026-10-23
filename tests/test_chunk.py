"""Chunker invariants (offline). Offsets must round-trip so the drawer can highlight the quote in
the original, and locators must be correct so a citation reads 'p.4' / 'lines 30-58'."""
from backend.ingest.chunk import chunk_doc
from backend.ingest.loaders import Doc, load


def test_offsets_round_trip():
    text = ("Sentence one about robotics. " * 60) + "\n\n" + ("Sentence two about payloads. " * 60)
    doc = Doc("text", "t.md", text, source_uri="t.md")
    chunks = chunk_doc(doc)
    assert len(chunks) >= 2, "long text must split into multiple chunks"
    for c in chunks:
        assert text[c.char_start:c.char_end].strip() == c.body, "offset must map back to the body"


def test_prose_chunks_overlap_and_cover():
    text = "".join(f"Para {i} has some content here. " for i in range(200))
    chunks = chunk_doc(Doc("text", "t.txt", text, source_uri="t.txt"))
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text), "chunks must cover to the end of the document"
    # consecutive chunks overlap (start of next < end of prev)
    assert any(chunks[i + 1].char_start < chunks[i].char_end for i in range(len(chunks) - 1))


def test_code_locator_is_line_range():
    src = "\n".join(f"line{i} = {i}" for i in range(400))
    chunks = chunk_doc(load("m.py", src.encode()))
    assert len(chunks) >= 2
    assert chunks[0].locator.startswith("line"), chunks[0].locator
    assert "-" in chunks[0].locator


def test_pdf_locator_uses_page_map():
    # two synthetic pages, boundary at offset 20
    doc = Doc("pdf", "d.pdf", "A" * 20 + "B" * 20, source_uri="d.pdf", meta={"page_bounds": [20, 40]})
    chunks = chunk_doc(doc)
    assert chunks and chunks[0].locator == "p.1"


def test_short_text_is_one_chunk():
    chunks = chunk_doc(Doc("text", "s.md", "just a short note", source_uri="s.md"))
    assert len(chunks) == 1 and chunks[0].ordinal == 0
