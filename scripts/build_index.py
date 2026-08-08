#!/usr/bin/env python3
"""Build the FAISS + BM25 index from data/corpus/.

Run: python scripts/build_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.rag.index import build_index  # noqa: E402


def main() -> int:
    s = get_settings()
    print(f"building index from {s.corpus_dir.relative_to(s.repo_root)} ...")
    stats = build_index(s.corpus_dir, s.index_dir, s.embedding_model)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
