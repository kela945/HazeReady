"""Chunking guard: a band table must never be split across chunks.

A fragment reading "101 - 200 | Unhealthy" without the row saying what to do
about it is worse than no retrieval, because it looks like an answer.

Note: on the shipped corpus every document fits in a single chunk, so this guard
is not exercised by production data. It is tested here with synthetic documents
long enough to force splitting, because a deployment ingesting full agency pages
would hit it immediately.
"""

from __future__ import annotations

from pathlib import Path

from app.rag.chunker import chunk_document
from app.rag.corpus import Document

TABLE = """| 24-hour PSI | Descriptor | Action |
|---|---|---|
| 0 - 50 | Good | Normal activities |
| 51 - 100 | Moderate | Normal activities |
| 101 - 200 | Unhealthy | Minimise outdoor activities |
| 201 - 300 | Very Unhealthy | Avoid outdoor exertion |
| above 300 | Hazardous | Remain indoors |"""

FILLER = ("Lorem ipsum dolor sit amet consectetur adipiscing elit sed do "
          "eiusmod tempor incididunt ut labore et dolore magna aliqua. ") * 12


def make_doc(body: str) -> Document:
    return Document(
        doc_id="test-doc", title="t", issuing_agency="NEA", source_url="http://x",
        retrieved_at="2026-08-08", licence="l", robots_txt_checked=True,
        robots_txt_permits=True, provenance="paraphrased_from_fetched",
        verified_against_source=True, applies_to_roles=["school"],
        authority_tier="primary", body=body, path=Path("test-doc.md"),
    )


def test_table_is_never_split_when_surrounded_by_long_prose() -> None:
    body = f"# Heading\n\n{FILLER}\n\n{TABLE}\n\n{FILLER}\n"
    chunks = chunk_document(make_doc(body), target_tokens=120, overlap_tokens=20)

    assert len(chunks) > 1, "test is vacuous unless the document actually splits"

    table_chunks = [c for c in chunks if "| 101 - 200 | Unhealthy" in c.text]
    assert len(table_chunks) == 1, "the band row appears in exactly one chunk"

    # Every row of the table must be present in that same chunk.
    chunk = table_chunks[0]
    for row in ("0 - 50", "51 - 100", "101 - 200", "201 - 300", "above 300"):
        assert row in chunk.text, f"row {row!r} was separated from its table"
    assert chunk.contains_table
    assert chunk.contains_numeric_threshold


def test_table_larger_than_target_is_still_emitted_whole() -> None:
    big_rows = "\n".join(f"| {i} | band{i} | action{i} |" for i in range(120))
    body = f"# H\n\n| a | b | c |\n|---|---|---|\n{big_rows}\n"
    chunks = chunk_document(make_doc(body), target_tokens=50, overlap_tokens=10)
    holding = [c for c in chunks if "| 119 | band119" in c.text]
    assert len(holding) == 1
    assert "| 0 | band0" in holding[0].text, "table split despite exceeding target"


def test_char_spans_are_exact_offsets_into_the_body() -> None:
    body = f"# Heading\n\n{FILLER}\n\n{TABLE}\n\n{FILLER}\n"
    doc = make_doc(body)
    for c in chunk_document(doc, target_tokens=120, overlap_tokens=20):
        start, end = c.char_span
        assert doc.body[start:end] == c.text


def test_heading_path_is_tracked() -> None:
    body = "# Top\n\ntext one\n\n## Sub\n\ntext two\n"
    chunks = chunk_document(make_doc(body), target_tokens=5, overlap_tokens=0)
    paths = {c.heading_path for c in chunks}
    assert any("Top" in p for p in paths)
    assert any("Sub" in p for p in paths)


def test_empty_body_yields_one_chunk() -> None:
    chunks = chunk_document(make_doc(""), target_tokens=100)
    assert len(chunks) == 1
