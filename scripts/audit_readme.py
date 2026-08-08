#!/usr/bin/env python3
"""Check every quantitative claim in README.md against the repository.

Code-writeup mismatch is a disqualifying failure for this project, so the check
is mechanical rather than a careful re-read. Run it before committing.

Run: python scripts/audit_readme.py
"""

from __future__ import annotations

import json
import pickle
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.policy import load_policy_matrix  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    s = get_settings()
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    failures: list[str] = []

    def claim(name: str, present: str, actual) -> None:
        if present not in readme:
            failures.append(f"{name}: README no longer states {present!r} (actual: {actual})")

    manifest = yaml.safe_load((REPO / "data" / "manifest.yaml").read_text())
    matrix = load_policy_matrix(s.policy_matrix_path, s.corpus_dir)
    gaps = yaml.safe_load(s.coverage_gaps_path.read_text())["gaps"]
    items = [
        json.loads(x)
        for x in (REPO / "eval/hazeqa/items.jsonl").read_text().splitlines()
        if x.strip()
    ]
    chunks = (
        pickle.loads((s.index_dir / "chunks.pkl").read_bytes())
        if (s.index_dir / "chunks.pkl").exists()
        else []
    )
    spans = sum(
        len(r.actions) + len(r.obligations) + len(r.cohort_variants)
        for r in matrix.rows.values()
    )

    claim(
        "corpus size",
        f"{manifest['document_count']} curated markdown documents",
        manifest["document_count"],
    )
    claim(
        "traceable docs",
        f"**{manifest['retrieved_from_a_page_this_system_fetched']} are\ntraceable",
        manifest["retrieved_from_a_page_this_system_fetched"],
    )
    claim("matrix rows", f"{len(matrix.rows)} rows", len(matrix.rows))
    claim("spans", f"All {spans} spans currently resolve", spans)
    claim("benchmark size", f"{len(items)} hand-authored items", len(items))
    claim(
        "coverage gaps",
        "Twelve coverage gaps" if len(gaps) == 12 else f"{len(gaps)} coverage gaps",
        len(gaps),
    )

    # Deployment section hard limit: 150-250 words.
    body = readme.split("## 6. Deployment considerations", 1)[1].split("---", 1)[0]
    body = re.sub(r"\*\*|_|\[|\]\([^)]*\)", "", body)
    words = len([w for w in body.split() if any(c.isalnum() for c in w)])
    if not 150 <= words <= 250:
        failures.append(f"deployment section is {words} words; the hard limit is 150-250")

    # The demo video placeholder must be replaced before submission.
    if "REPLACE" in readme.split("\n", 4)[2]:
        failures.append("demo video URL is still a placeholder")

    # Docker must not be described as verified.
    if "docker compose up" in readme and "never**\nbuilt or run" not in readme:
        failures.append("README mentions docker without the unverified caveat")

    print(
        f"corpus={manifest['document_count']} traceable={manifest['retrieved_from_a_page_this_system_fetched']} "
        f"matrix_rows={len(matrix.rows)} spans={spans} items={len(items)} gaps={len(gaps)} "
        f"chunks={len(chunks)} deployment_words={words}"
    )

    if failures:
        print(f"\nFAIL: {len(failures)} README claim(s) do not match the repo")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: every checked README claim matches the repository")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
