"""Hybrid retrieval: BM25 + dense, fused with Reciprocal Rank Fusion.

Why hybrid rather than dense alone. Threshold questions turn on exact numerals
("101", "PSI 200") and on scheme names ("N95", "PSI", "PM2.5"). Dense
embeddings place 100 and 101 in nearly the same place, which is precisely the
distinction that flips the obligation. BM25 keeps the numeral. The A1-vs-A2
ablation measures whether this actually pays.

RRF with k=60 needs no score normalisation between two retrievers whose scores
are not comparable, and no tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.models import AuthorityTier, IndexKind, RetrievedSpan, Role
from app.rag.index import load_index, tokenise

# Boost applied to a chunk whose document declares the asker's role. This is a
# soft preference, not a filter: a role-specific question sometimes has only a
# general-public answer, and that answer must remain retrievable.
ROLE_BOOST = 0.30
# Primary sources outrank explanatory ones at equal relevance.
TIER_BOOST = {"primary": 0.20, "secondary": 0.08, "explanatory": 0.0}


@dataclass
class RetrievalMode:
    """The retrieval configuration for one ablation arm."""

    use_dense: bool = True
    use_sparse: bool = True
    use_rerank: bool = False


class Retriever:
    def __init__(
        self,
        corpus_dir: Path,
        index_dir: Path,
        embedding_model: str,
        reranker_model: str = "",
    ) -> None:
        self.faiss_index, self.store, self.bm25 = load_index(corpus_dir, index_dir)
        self._embedding_model_name = embedding_model
        self._reranker_model_name = reranker_model
        self._embedder = None
        self._reranker = None
        self._reranker_failed = False

    # -- lazy model loading -------------------------------------------------

    @property
    def embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(self._embedding_model_name)
        return self._embedder

    @property
    def reranker(self):
        """Returns None if the cross-encoder cannot be loaded. The A3 arm then
        degrades to A2 behaviour and says so, rather than failing the run."""
        if self._reranker_failed or not self._reranker_model_name:
            return None
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder

                self._reranker = CrossEncoder(self._reranker_model_name)
            except Exception:
                self._reranker_failed = True
                return None
        return self._reranker

    # -- query expansion ----------------------------------------------------

    @staticmethod
    def expand(
        query: str, role: Role | None, band_token: str | None, index: IndexKind | None
    ) -> str:
        """Inject the resolved context as query tokens. The band comes from the
        deterministic resolver, never from the model, so expansion cannot
        introduce a band the arithmetic did not produce."""
        parts = [query]
        if role is not None:
            parts.append(role.value.replace("_", " "))
        if band_token:
            parts.append(band_token.replace("_", " "))
        if index is not None:
            parts.append("24-hour PSI" if index == IndexKind.psi_24h else "1-hour PM2.5")
        return " ".join(parts)

    # -- retrieval ----------------------------------------------------------

    def _dense_ranking(self, query: str, k: int) -> list[int]:
        vec = self.embedder.encode(
            [query], normalize_embeddings=True, show_progress_bar=False
        ).astype("float32")
        k = min(k, len(self.store))
        _, idx = self.faiss_index.search(vec, k)
        return [int(i) for i in idx[0] if i >= 0]

    def _sparse_ranking(self, query: str, k: int) -> list[int]:
        scores = self.bm25.get_scores(tokenise(query))
        k = min(k, len(self.store))
        return [int(i) for i in np.argsort(scores)[::-1][:k]]

    @staticmethod
    def _rrf(rankings: list[list[int]], rrf_k: int) -> dict[int, float]:
        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, doc_idx in enumerate(ranking):
                fused[doc_idx] = fused.get(doc_idx, 0.0) + 1.0 / (rrf_k + rank + 1)
        return fused

    def search(
        self,
        query: str,
        role: Role | None = None,
        band_token: str | None = None,
        index: IndexKind | None = None,
        k: int = 5,
        mode: RetrievalMode | None = None,
        bm25_top_k: int = 20,
        dense_top_k: int = 20,
        rrf_k: int = 60,
        fusion_top_k: int = 10,
    ) -> list[RetrievedSpan]:
        mode = mode or RetrievalMode()
        expanded = self.expand(query, role, band_token, index)

        rankings: list[list[int]] = []
        if mode.use_sparse:
            rankings.append(self._sparse_ranking(expanded, bm25_top_k))
        if mode.use_dense:
            rankings.append(self._dense_ranking(expanded, dense_top_k))
        if not rankings:
            return []

        fused = self._rrf(rankings, rrf_k)

        # Soft metadata preference, applied after fusion so it re-orders but
        # never removes.
        for idx in list(fused):
            meta = self.store.meta(idx)
            base = fused[idx]
            if role is not None and role.value in meta["applies_to_roles"]:
                fused[idx] = base * (1.0 + ROLE_BOOST)
            fused[idx] *= 1.0 + TIER_BOOST.get(meta["authority_tier"], 0.0)

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:fusion_top_k]

        if mode.use_rerank and self.reranker is not None:
            pairs = [(expanded, self.store.meta(i)["text"]) for i, _ in ordered]
            try:
                ce_scores = self.reranker.predict(pairs)
                ordered = [
                    (idx, float(s))
                    for (idx, _), s in sorted(
                        zip(ordered, ce_scores, strict=False), key=lambda t: t[1], reverse=True
                    )
                ]
            except Exception:
                # Degrade to fusion order rather than fail the query.
                self._reranker_failed = True

        spans: list[RetrievedSpan] = []
        for idx, score in ordered[:k]:
            m = self.store.meta(idx)
            spans.append(
                RetrievedSpan(
                    doc_id=m["doc_id"],
                    chunk_id=m["chunk_id"],
                    text=m["text"],
                    char_span=tuple(m["char_span"]),
                    score=float(score),
                    authority_tier=AuthorityTier(m["authority_tier"]),
                    issuing_agency=m["issuing_agency"],
                    title=m["title"],
                    source_url=m["source_url"],
                    retrieved_at=m["retrieved_at"],
                    heading_path=m["heading_path"],
                    provenance=m["provenance"],
                    verified_against_source=m["verified_against_source"],
                )
            )
        return spans
