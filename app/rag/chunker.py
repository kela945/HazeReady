"""Structure-aware chunking.

The hard requirement: a chunk containing a numeric threshold must retain its
full governing table. Band tables are the entire substance of this corpus, and a
table split across two chunks produces a retrievable fragment that says
"101 - 200 | Unhealthy" without the row that says what to do about it. That
fragment is worse than no retrieval, because it looks like an answer.

The guard is explicit (`_table_blocks`) and unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.corpus import Document

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
NUMERIC_RE = re.compile(r"\b\d{1,4}\b")


def estimate_tokens(text: str) -> int:
    """Word-count proxy. The system never needs exact token counts for
    chunking, and using a real tokeniser here would pull the embedding model
    into a module that otherwise has no ML dependency."""
    return max(1, len(text.split()))


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    char_span: tuple[int, int]
    heading_path: str
    contains_table: bool
    contains_numeric_threshold: bool


@dataclass
class _Block:
    """A unit that must never be split: either a paragraph or a whole table."""

    text: str
    start: int
    end: int
    is_table: bool


def _table_blocks(body: str) -> list[_Block]:
    """Split a document body into atomic blocks, treating a contiguous run of
    table rows (plus the line immediately above it, which is the caption or
    lead-in) as a single indivisible block."""
    lines = body.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    blocks: list[_Block] = []
    i = 0
    buf_start_line: int | None = None

    def flush_paragraph(upto: int) -> None:
        nonlocal buf_start_line
        if buf_start_line is None:
            return
        start = offsets[buf_start_line]
        end = offsets[upto - 1] + len(lines[upto - 1]) if upto > 0 else start
        text = body[start:end]
        if text.strip():
            blocks.append(_Block(text=text, start=start, end=end, is_table=False))
        buf_start_line = None

    while i < len(lines):
        if TABLE_ROW_RE.match(lines[i]):
            # A table starts here. Absorb the preceding non-blank line as the
            # lead-in so the table is never separated from what introduces it.
            table_start_line = i
            if (
                buf_start_line is not None
                and i - 1 >= buf_start_line
                and lines[i - 1].strip()
            ):
                flush_paragraph(i - 1)
                table_start_line = i - 1
            else:
                flush_paragraph(i)

            j = i
            while j < len(lines) and (
                TABLE_ROW_RE.match(lines[j]) or lines[j].strip() == ""
            ):
                if lines[j].strip() == "":
                    # A blank line ends the table unless the next line resumes it.
                    if j + 1 < len(lines) and TABLE_ROW_RE.match(lines[j + 1]):
                        j += 1
                        continue
                    break
                j += 1

            start = offsets[table_start_line]
            end = offsets[j - 1] + len(lines[j - 1])
            blocks.append(
                _Block(text=body[start:end], start=start, end=end, is_table=True)
            )
            i = j
            continue

        if lines[i].strip() == "":
            flush_paragraph(i)
            i += 1
            continue

        if buf_start_line is None:
            buf_start_line = i
        i += 1

    flush_paragraph(len(lines))
    return blocks


def _heading_path_at(body: str, offset: int) -> str:
    stack: list[tuple[int, str]] = []
    pos = 0
    for line in body.split("\n"):
        if pos > offset:
            break
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
        pos += len(line) + 1
    return " > ".join(t for _, t in stack)


def chunk_document(
    doc: Document, target_tokens: int = 400, overlap_tokens: int = 80
) -> list[Chunk]:
    blocks = _table_blocks(doc.body)
    chunks: list[Chunk] = []
    current: list[_Block] = []
    current_tokens = 0
    seq = 0

    def emit() -> None:
        nonlocal current, current_tokens, seq
        if not current:
            return
        start = current[0].start
        end = current[-1].end
        text = doc.body[start:end]
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}::{seq:03d}",
                doc_id=doc.doc_id,
                text=text,
                char_span=(start, end),
                heading_path=_heading_path_at(doc.body, start),
                contains_table=any(b.is_table for b in current),
                contains_numeric_threshold=bool(NUMERIC_RE.search(text)),
            )
        )
        seq += 1
        current = []
        current_tokens = 0

    for block in blocks:
        block_tokens = estimate_tokens(block.text)

        # A table that exceeds the target on its own is still emitted whole.
        # Splitting it is the failure this module exists to prevent.
        if block.is_table and block_tokens > target_tokens:
            emit()
            current = [block]
            current_tokens = block_tokens
            emit()
            continue

        if current and current_tokens + block_tokens > target_tokens:
            tail = current[-1] if not current[-1].is_table else None
            emit()
            # Overlap: carry the previous paragraph forward for context, but
            # never carry a table forward, which would duplicate it across two
            # chunks and double-count it at retrieval.
            if tail is not None and estimate_tokens(tail.text) <= overlap_tokens:
                current = [tail]
                current_tokens = estimate_tokens(tail.text)

        current.append(block)
        current_tokens += block_tokens

    emit()

    if not chunks:
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}::000",
                doc_id=doc.doc_id,
                text=doc.body,
                char_span=(0, len(doc.body)),
                heading_path="",
                contains_table=False,
                contains_numeric_threshold=bool(NUMERIC_RE.search(doc.body)),
            )
        )
    return chunks


def chunk_corpus(docs: list[Document], target_tokens: int = 400, overlap_tokens: int = 80):
    out: list[Chunk] = []
    for d in docs:
        out.extend(chunk_document(d, target_tokens, overlap_tokens))
    return out
