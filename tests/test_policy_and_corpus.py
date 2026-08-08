"""Corpus contract and policy-matrix grounding.

These are the tests that make "every claim traces to a source" enforceable
rather than aspirational.
"""

from __future__ import annotations

import pytest
import yaml

from app.config import get_settings
from app.models import Band, Decision, IndexKind, Role
from app.policy import PolicyMatrixError, load_policy_matrix, locate_quote
from app.rag.corpus import CorpusError, load_corpus, parse_document

S = get_settings()
DOCS = load_corpus(S.corpus_dir)
MATRIX = load_policy_matrix(S.policy_matrix_path, S.corpus_dir, DOCS)


def test_corpus_meets_the_minimum_size() -> None:
    assert len(DOCS) >= 60


def test_every_document_declares_provenance_and_licensing() -> None:
    for d in DOCS:
        assert d.provenance
        assert d.licence
        assert d.authority_tier in {"primary", "secondary", "explanatory"}


def test_no_document_claims_content_from_a_disallowed_source() -> None:
    """The integrity rule that matters for the data-thinking claim: nothing was
    scraped from a site whose robots.txt disallows it."""
    for d in DOCS:
        if d.provenance in {"fetched_and_verified", "paraphrased_from_fetched"}:
            assert d.robots_txt_checked, f"{d.doc_id}: fetched without a robots check"
            assert d.robots_txt_permits, (
                f"{d.doc_id}: content taken from a source that disallows retrieval"
            )


def test_verified_flag_is_consistent_with_provenance() -> None:
    for d in DOCS:
        if d.verified_against_source:
            assert d.provenance in {"fetched_and_verified", "paraphrased_from_fetched"}


def test_every_matrix_quote_resolves_to_its_cited_document() -> None:
    """The core grounding contract. A quote that does not appear verbatim in the
    document it cites means the matrix asserts something its source does not
    say."""
    by_id = {d.doc_id: d for d in DOCS}
    checked = 0
    for key, row in MATRIX.rows.items():
        for st in list(row.actions) + list(row.obligations):
            doc = by_id[st.source_doc_id]
            start, end = st.char_span
            extracted = " ".join(doc.body[start:end].split())
            assert extracted == " ".join(st.source_quote.split()), (
                f"{key}: span for {st.source_doc_id} does not extract its quote"
            )
            checked += 1
        for v in row.cohort_variants:
            assert v.char_span is not None
            checked += 1
    assert checked >= 90, "expected the matrix to be substantially sourced"


def test_no_action_cites_an_authored_coverage_note() -> None:
    """Coverage notes record that guidance is SILENT. Citing one as the source
    of an obligation would invert its meaning."""
    by_id = {d.doc_id: d for d in DOCS}
    for key, row in MATRIX.rows.items():
        for st in row.actions:
            assert by_id[st.source_doc_id].is_obligation_source, (
                f"{key}: action cites coverage note {st.source_doc_id}"
            )


def test_every_role_has_a_complete_psi_band_ladder() -> None:
    for role in Role:
        for band in ("good", "moderate", "unhealthy", "very_unhealthy", "hazardous"):
            row = MATRIX.lookup(role, band, IndexKind.psi_24h)
            assert row.found, f"missing matrix row for {role.value}/{band}"


def test_decisions_are_monotonic_across_bands() -> None:
    """A more severe band must never yield a more permissive decision. This is
    the internal-consistency property the whole safety argument rests on."""
    order = [
        Decision.proceed,
        Decision.proceed_with_precautions,
        Decision.restrict,
        Decision.suspend,
    ]
    ladder = ["good", "moderate", "unhealthy", "very_unhealthy", "hazardous"]
    for role in Role:
        prev = -1
        for band in ladder:
            d = MATRIX.lookup(role, band, IndexKind.psi_24h).decision
            idx = order.index(d)
            assert idx >= prev, (
                f"{role.value}: {band} is more permissive than the band below it"
            )
            prev = idx


def test_missing_row_abstains_rather_than_permitting() -> None:
    """A gap in the matrix must never read as permission."""
    row = MATRIX.lookup(Role.worksite, Band.very_high, IndexKind.pm25_1h)
    assert not row.found
    assert row.decision is Decision.abstain


def test_locate_quote_is_whitespace_insensitive() -> None:
    doc = DOCS[0]
    words = doc.body.split()[3:9]
    reflowed = "\n".join(words)
    start, end = locate_quote(doc, reflowed)
    assert " ".join(doc.body[start:end].split()) == " ".join(words)


def test_locate_quote_raises_on_a_quote_that_is_not_present() -> None:
    with pytest.raises(PolicyMatrixError):
        locate_quote(DOCS[0], "this sentence appears in no corpus document at all")


def test_coverage_gaps_point_at_real_documents() -> None:
    gaps = yaml.safe_load(S.coverage_gaps_path.read_text(encoding="utf-8"))["gaps"]
    ids = {d.doc_id for d in DOCS}
    assert len(gaps) >= 10
    for g in gaps:
        assert g["evidence_doc_id"] in ids
        assert g["suggested_authority"]
        assert g["trigger_terms"]


def test_frontmatter_contract_is_enforced(tmp_path) -> None:
    bad = tmp_path / "bad-doc.md"
    bad.write_text("---\ndoc_id: bad-doc\ntitle: x\n---\n\nbody\n", encoding="utf-8")
    with pytest.raises(CorpusError):
        parse_document(bad)
