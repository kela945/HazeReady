"""Index construction and loading: FAISS IndexFlatIP for dense, BM25Okapi for
sparse.

IndexFlatIP over L2-normalised vectors is exact inner-product search. At this
corpus size (order 10^2 chunks) an approximate index would add tuning
parameters and reproducibility risk to buy latency we do not need.
"""

from __future__ import annotations

import json
import pickle
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np

from app.rag.chunker import Chunk, chunk_corpus
from app.rag.corpus import Document, load_corpus

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def tokenise(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, keeping decimals intact so that `pm2.5`
    survives as a token rather than becoming `pm2` and `5`."""
    return _TOKEN_RE.findall(text.lower().replace("pm2.5", "pm2.5"))


class ChunkStore:
    """Chunks plus their document metadata, addressable by position."""

    def __init__(self, chunks: list[Chunk], docs: list[Document]) -> None:
        self.chunks = chunks
        self.docs_by_id = {d.doc_id: d for d in docs}

    def meta(self, i: int) -> dict:
        c = self.chunks[i]
        d = self.docs_by_id[c.doc_id]
        return {
            "doc_id": c.doc_id,
            "chunk_id": c.chunk_id,
            "text": c.text,
            "char_span": c.char_span,
            "heading_path": c.heading_path,
            "authority_tier": d.authority_tier,
            "issuing_agency": d.issuing_agency,
            "title": d.title,
            "source_url": d.source_url,
            "retrieved_at": d.retrieved_at,
            "applies_to_roles": d.applies_to_roles,
            "provenance": d.provenance,
            "verified_against_source": d.verified_against_source,
        }

    def __len__(self) -> int:
        return len(self.chunks)


def build_index(corpus_dir: Path, index_dir: Path, embedding_model: str) -> dict:
    """Build and persist the dense and sparse indices. Returns build stats."""
    from sentence_transformers import SentenceTransformer

    index_dir.mkdir(parents=True, exist_ok=True)
    docs = load_corpus(corpus_dir)
    chunks = chunk_corpus(docs)

    model = SentenceTransformer(embedding_model)
    texts = [c.text for c in chunks]
    embeddings = model.encode(
        texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32
    ).astype("float32")

    import faiss

    dim = embeddings.shape[1]
    faiss_index = faiss.IndexFlatIP(dim)
    faiss_index.add(embeddings)
    faiss.write_index(faiss_index, str(index_dir / "dense.faiss"))

    with (index_dir / "chunks.pkl").open("wb") as fh:
        pickle.dump([asdict(c) for c in chunks], fh)

    stats = {
        "documents": len(docs),
        "chunks": len(chunks),
        "embedding_model": embedding_model,
        "dimension": int(dim),
        "chunks_with_tables": sum(1 for c in chunks if c.contains_table),
        "chunks_with_numeric_thresholds": sum(
            1 for c in chunks if c.contains_numeric_threshold
        ),
        "mean_chunk_chars": int(np.mean([len(c.text) for c in chunks])),
        "max_chunk_chars": int(max(len(c.text) for c in chunks)),
    }
    (index_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def load_index(corpus_dir: Path, index_dir: Path):
    """Load the persisted index. Returns (faiss_index, ChunkStore, bm25)."""
    import faiss
    from rank_bm25 import BM25Okapi

    faiss_index = faiss.read_index(str(index_dir / "dense.faiss"))
    with (index_dir / "chunks.pkl").open("rb") as fh:
        chunk_dicts = pickle.load(fh)
    chunks = [Chunk(**cd) for cd in chunk_dicts]
    for c in chunks:
        c.char_span = tuple(c.char_span)  # type: ignore[assignment]

    docs = load_corpus(corpus_dir)
    store = ChunkStore(chunks, docs)
    bm25 = BM25Okapi([tokenise(c.text) for c in chunks])
    return faiss_index, store, bm25
