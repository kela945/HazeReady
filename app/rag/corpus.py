"""Corpus loading and frontmatter parsing.

The frontmatter schema is enforced here and re-checked by
scripts/validate_corpus.py in the test suite. A document that does not declare
its provenance cannot enter the index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REQUIRED_FRONTMATTER_KEYS = {
    "doc_id",
    "title",
    "issuing_agency",
    "source_url",
    "retrieved_at",
    "licence",
    "robots_txt_checked",
    "robots_txt_permits",
    "provenance",
    "verified_against_source",
    "applies_to_roles",
    "authority_tier",
}

VALID_TIERS = {"primary", "secondary", "explanatory"}

VALID_PROVENANCE = {
    # Retrieved by this system and reproduced structurally as fetched.
    "fetched_and_verified",
    # Retrieved by this system, then restated in our own words.
    "paraphrased_from_fetched",
    # Not retrieved; written from domain knowledge. Numbers here are NOT
    # verified and the document must say so.
    "authored_from_domain_knowledge",
    # Restates rules from primary documents and applies them to a situation.
    # Adds no obligation of its own.
    "authored_interpretation",
    # Records that guidance is silent on something. Never an obligation source.
    "authored_coverage_note",
}

VALID_ROLES = {
    "general_public",
    "school",
    "preschool",
    "eldercare",
    "worksite",
    "event",
}


class CorpusError(ValueError):
    """Raised when a document violates the frontmatter contract."""


@dataclass
class Document:
    doc_id: str
    title: str
    issuing_agency: str
    source_url: str
    retrieved_at: str
    licence: str
    robots_txt_checked: bool
    robots_txt_permits: bool
    provenance: str
    verified_against_source: bool
    applies_to_roles: list[str]
    authority_tier: str
    body: str
    path: Path
    body_offset: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def is_obligation_source(self) -> bool:
        """Coverage notes record silence; they must never be cited as the
        source of an obligation. The guardrail chain relies on this."""
        return self.provenance != "authored_coverage_note"


def parse_document(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise CorpusError(f"{path.name}: missing YAML frontmatter")

    end = raw.find("\n---", 3)
    if end == -1:
        raise CorpusError(f"{path.name}: unterminated YAML frontmatter")

    fm_text = raw[3:end]
    body_start = end + len("\n---")
    # Skip the newline that follows the closing fence.
    if raw[body_start : body_start + 1] == "\n":
        body_start += 1
    body = raw[body_start:]

    try:
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise CorpusError(f"{path.name}: invalid YAML frontmatter: {exc}") from exc

    missing = REQUIRED_FRONTMATTER_KEYS - set(meta)
    if missing:
        raise CorpusError(f"{path.name}: missing frontmatter keys {sorted(missing)}")

    if meta["authority_tier"] not in VALID_TIERS:
        raise CorpusError(
            f"{path.name}: authority_tier {meta['authority_tier']!r} not in {sorted(VALID_TIERS)}"
        )
    if meta["provenance"] not in VALID_PROVENANCE:
        raise CorpusError(
            f"{path.name}: provenance {meta['provenance']!r} not in {sorted(VALID_PROVENANCE)}"
        )

    roles = meta["applies_to_roles"] or []
    unknown_roles = set(roles) - VALID_ROLES
    if unknown_roles:
        raise CorpusError(f"{path.name}: unknown roles {sorted(unknown_roles)}")

    if meta["doc_id"] != path.stem:
        raise CorpusError(
            f"{path.name}: doc_id {meta['doc_id']!r} does not match filename stem"
        )

    # A document claiming verification must have been fetched.
    if meta["verified_against_source"] and meta["provenance"] not in {
        "fetched_and_verified",
        "paraphrased_from_fetched",
    }:
        raise CorpusError(
            f"{path.name}: verified_against_source=true is inconsistent with "
            f"provenance={meta['provenance']!r}"
        )

    known = {k: meta[k] for k in REQUIRED_FRONTMATTER_KEYS}
    extra = {k: v for k, v in meta.items() if k not in REQUIRED_FRONTMATTER_KEYS}

    return Document(
        body=body, path=path, body_offset=body_start, extra=extra, **known
    )


def load_corpus(corpus_dir: Path) -> list[Document]:
    docs = [parse_document(p) for p in sorted(corpus_dir.glob("*.md"))]
    seen: dict[str, Path] = {}
    for doc in docs:
        if doc.doc_id in seen:
            raise CorpusError(
                f"duplicate doc_id {doc.doc_id!r} in {doc.path.name} and {seen[doc.doc_id].name}"
            )
        seen[doc.doc_id] = doc.path
    return docs


def build_manifest(docs: list[Document]) -> dict:
    """Machine-readable aggregate of all frontmatter, plus the provenance
    accounting that docs/DATA.md reports."""
    by_provenance: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_agency: dict[str, int] = {}
    for d in docs:
        by_provenance[d.provenance] = by_provenance.get(d.provenance, 0) + 1
        by_tier[d.authority_tier] = by_tier.get(d.authority_tier, 0) + 1
        by_agency[d.issuing_agency] = by_agency.get(d.issuing_agency, 0) + 1

    return {
        "document_count": len(docs),
        "counts_by_provenance": dict(sorted(by_provenance.items())),
        "counts_by_authority_tier": dict(sorted(by_tier.items())),
        "counts_by_issuing_agency": dict(sorted(by_agency.items())),
        "retrieved_from_a_page_this_system_fetched": sum(
            1
            for d in docs
            if d.provenance in {"fetched_and_verified", "paraphrased_from_fetched"}
        ),
        "documents": [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "issuing_agency": d.issuing_agency,
                "source_url": d.source_url,
                "retrieved_at": d.retrieved_at,
                "licence": d.licence,
                "robots_txt_checked": d.robots_txt_checked,
                "robots_txt_permits": d.robots_txt_permits,
                "provenance": d.provenance,
                "verified_against_source": d.verified_against_source,
                "applies_to_roles": d.applies_to_roles,
                "authority_tier": d.authority_tier,
                "body_chars": len(d.body),
            }
            for d in docs
        ],
    }
