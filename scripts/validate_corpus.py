#!/usr/bin/env python3
"""Corpus and policy-matrix validation. Corpus validation failure fails the build.

Checks:
  1. Every corpus document parses and satisfies the frontmatter contract.
  2. Every policy-matrix row resolves to a real doc_id and a real char_span.
  3. No matrix action cites an authored coverage note as an obligation source.
  4. Every coverage gap points at a corpus document that exists.
  5. Every document whose robots.txt does not permit retrieval is marked as
     not fetched, so the corpus cannot contain scraped text we were not
     allowed to take.
  6. Writes data/manifest.yaml.

Run: python scripts/validate_corpus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.policy import PolicyMatrixError, load_policy_matrix  # noqa: E402
from app.rag.corpus import (  # noqa: E402
    CorpusError,
    build_manifest,
    load_corpus,
)

MIN_DOCUMENTS = 60


def main() -> int:
    settings = get_settings()
    errors: list[str] = []
    warnings: list[str] = []

    # --- 1. Corpus ---------------------------------------------------------
    try:
        docs = load_corpus(settings.corpus_dir)
    except CorpusError as exc:
        print(f"FAIL corpus: {exc}")
        return 1

    print(f"  corpus: {len(docs)} documents parsed")
    if len(docs) < MIN_DOCUMENTS:
        errors.append(f"corpus has {len(docs)} documents, minimum is {MIN_DOCUMENTS}")

    # --- 5. robots.txt consistency ----------------------------------------
    for d in docs:
        fetched = d.provenance in {"fetched_and_verified", "paraphrased_from_fetched"}
        if fetched and not d.robots_txt_permits:
            errors.append(
                f"{d.doc_id}: provenance={d.provenance} but robots_txt_permits=false. "
                "Content must not be taken from a source that disallows retrieval."
            )
        if fetched and not d.robots_txt_checked:
            errors.append(f"{d.doc_id}: fetched content without a robots.txt check")
        if not d.source_url and d.provenance not in {
            "authored_coverage_note",
            "authored_from_domain_knowledge",
        }:
            errors.append(f"{d.doc_id}: empty source_url with provenance={d.provenance}")

    # --- 2/3. Policy matrix ------------------------------------------------
    try:
        matrix = load_policy_matrix(settings.policy_matrix_path, settings.corpus_dir, docs)
    except PolicyMatrixError as exc:
        print(f"FAIL policy_matrix: {exc}")
        return 1

    span_count = 0
    by_id = {d.doc_id: d for d in docs}
    for key, row in matrix.rows.items():
        statements = list(row.actions) + list(row.obligations)
        for s in statements:
            if s.char_span is None:
                errors.append(f"{key}: unresolved span for {s.source_doc_id}")
                continue
            doc = by_id[s.source_doc_id]
            start, end = s.char_span
            extracted = doc.body[start:end]
            if " ".join(extracted.split()) != " ".join(s.source_quote.split()):
                errors.append(
                    f"{key}: span for {s.source_doc_id} does not extract the quote"
                )
            span_count += 1
        for v in row.cohort_variants:
            if v.char_span is None:
                errors.append(f"{key}: unresolved span for cohort variant {v.cohort}")
            else:
                span_count += 1

    print(f"  policy_matrix: {len(matrix.rows)} rows, {span_count} spans resolved")

    # Every role must have a complete PSI band ladder. A missing row abstains,
    # which is safe, but a silently incomplete ladder is a build defect.
    psi_bands = ["good", "moderate", "unhealthy", "very_unhealthy", "hazardous"]
    for role in matrix.role_governing_index:
        for band in psi_bands:
            if (role, "psi_24h", band) not in matrix.rows:
                errors.append(f"policy_matrix: missing row ({role}, psi_24h, {band})")

    # --- 4. Coverage gaps --------------------------------------------------
    gaps = yaml.safe_load(settings.coverage_gaps_path.read_text(encoding="utf-8"))
    for gap in gaps["gaps"]:
        if gap["evidence_doc_id"] not in by_id:
            errors.append(
                f"coverage_gap {gap['id']}: unknown evidence_doc_id "
                f"{gap['evidence_doc_id']!r}"
            )
        if not gap.get("suggested_authority"):
            errors.append(f"coverage_gap {gap['id']}: no suggested_authority")
    print(f"  coverage_gaps: {len(gaps['gaps'])} gaps")

    # --- 6. Manifest -------------------------------------------------------
    manifest = build_manifest(docs)
    settings.manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(f"  manifest: written to {settings.manifest_path.relative_to(settings.repo_root)}")
    print(f"  provenance: {manifest['counts_by_provenance']}")
    print(f"  authority tiers: {manifest['counts_by_authority_tier']}")

    unverified = [d.doc_id for d in docs if not d.verified_against_source]
    warnings.append(
        f"{len(unverified)} of {len(docs)} documents are not verified against a "
        "retrieved source page (expected: interpretations and coverage notes)"
    )

    for w in warnings:
        print(f"  note: {w}")

    if errors:
        print(f"\nFAIL: {len(errors)} error(s)")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\nOK: corpus and policy matrix valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
