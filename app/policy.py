"""Policy matrix loading and the quote-to-span resolution that grounds it.

Every action and obligation in data/policy_matrix.yaml carries a verbatim
`source_quote`. On load we locate that quote in the cited corpus document and
attach the resulting character span. A quote that does not appear verbatim is a
hard error: it means the matrix asserts something its cited source does not say,
which is exactly the failure mode this project exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.models import (
    Band,
    CohortVariant,
    Decision,
    IndexKind,
    ObligationSet,
    Role,
    SourcedStatement,
)
from app.rag.corpus import Document, load_corpus


class PolicyMatrixError(ValueError):
    """Raised when a matrix row cannot be grounded in its cited document."""


def _normalise(text: str) -> str:
    """Quotes are written in the YAML with the line breaks they have in the
    source document, but a maintainer editing either file will reflow lines.
    Matching on whitespace-collapsed text keeps the contract about *content*
    rather than about line wrapping."""
    return " ".join(text.split())


def locate_quote(doc: Document, quote: str) -> tuple[int, int]:
    """Return the character span of `quote` within the document body.

    Falls back to a whitespace-insensitive scan so that a reflowed source or a
    reflowed quote does not break the build for a cosmetic reason.
    """
    idx = doc.body.find(quote)
    if idx != -1:
        return (idx, idx + len(quote))

    target = _normalise(quote)
    if not target:
        raise PolicyMatrixError(f"empty source_quote for doc {doc.doc_id}")

    # Build a map from normalised-position to original-position, then search.
    positions: list[int] = []
    chars: list[str] = []
    prev_space = False
    for i, ch in enumerate(doc.body):
        if ch.isspace():
            if prev_space or not chars:
                continue
            chars.append(" ")
            positions.append(i)
            prev_space = True
        else:
            chars.append(ch)
            positions.append(i)
            prev_space = False
    flat = "".join(chars)

    j = flat.find(target)
    if j == -1:
        raise PolicyMatrixError(
            f"source_quote not found in {doc.doc_id}: {quote[:90]!r}"
        )
    start = positions[j]
    end_index = j + len(target) - 1
    end = positions[end_index] + 1
    return (start, end)


@dataclass
class PolicyMatrix:
    rows: dict[tuple[str, str, str], ObligationSet]
    role_governing_index: dict[str, str]
    role_default_cohort: dict[str, str]
    version: int

    def lookup(
        self, role: Role | str, band: Band | str, index: IndexKind | str = IndexKind.psi_24h
    ) -> ObligationSet:
        role_v = role.value if isinstance(role, Role) else role
        band_v = band.value if isinstance(band, Band) else band
        index_v = index.value if isinstance(index, IndexKind) else index
        found = self.rows.get((role_v, index_v, band_v))
        if found is not None:
            return found
        # A missing row is not an error and must not be silently treated as
        # permission. It is an abstention signal.
        return ObligationSet(
            role=Role(role_v),
            index=IndexKind(index_v),
            band=Band(band_v),
            decision=Decision.abstain,
            reason_codes=["no_matrix_row"],
            found=False,
            default_cohort=self.role_default_cohort.get(role_v, "healthy"),
        )

    def governing_index(self, role: Role | str) -> IndexKind:
        role_v = role.value if isinstance(role, Role) else role
        return IndexKind(self.role_governing_index.get(role_v, "psi_24h"))

    def all_source_doc_ids(self) -> set[str]:
        out: set[str] = set()
        for row in self.rows.values():
            for s in list(row.actions) + list(row.obligations):
                out.add(s.source_doc_id)
            for v in row.cohort_variants:
                out.add(v.source_doc_id)
        return out


def load_policy_matrix(
    matrix_path: Path, corpus_dir: Path, docs: list[Document] | None = None
) -> PolicyMatrix:
    data = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    docs = docs if docs is not None else load_corpus(corpus_dir)
    by_id = {d.doc_id: d for d in docs}

    def resolve(entry: dict, where: str) -> SourcedStatement:
        doc_id = entry["source_doc_id"]
        doc = by_id.get(doc_id)
        if doc is None:
            raise PolicyMatrixError(f"{where}: unknown source_doc_id {doc_id!r}")
        if not doc.is_obligation_source:
            raise PolicyMatrixError(
                f"{where}: {doc_id!r} is an authored coverage note and cannot be "
                "cited as the source of an action or obligation"
            )
        span = locate_quote(doc, entry["source_quote"])
        return SourcedStatement(
            text=entry["text"],
            source_doc_id=doc_id,
            source_quote=entry["source_quote"],
            char_span=span,
        )

    rows: dict[tuple[str, str, str], ObligationSet] = {}
    for raw in data["rows"]:
        key = (raw["role"], raw["index"], raw["band"])
        if key in rows:
            raise PolicyMatrixError(f"duplicate matrix row for {key}")
        where = f"row {key}"

        actions = [resolve(a, where) for a in raw.get("actions", [])]

        # Obligations may cite coverage notes, because "there is no published
        # threshold for this" is itself a legitimate thing to tell a user. The
        # guardrail treats such statements as non-permissive by construction.
        obligations: list[SourcedStatement] = []
        for o in raw.get("obligations", []):
            doc = by_id.get(o["source_doc_id"])
            if doc is None:
                raise PolicyMatrixError(
                    f"{where}: unknown source_doc_id {o['source_doc_id']!r}"
                )
            obligations.append(
                SourcedStatement(
                    text=o["text"],
                    source_doc_id=o["source_doc_id"],
                    source_quote=o["source_quote"],
                    char_span=locate_quote(doc, o["source_quote"]),
                )
            )

        variants: list[CohortVariant] = []
        for cohort, v in (raw.get("cohort_variants") or {}).items():
            doc = by_id.get(v["source_doc_id"])
            if doc is None:
                raise PolicyMatrixError(
                    f"{where}: unknown source_doc_id {v['source_doc_id']!r}"
                )
            variants.append(
                CohortVariant(
                    cohort=cohort,
                    decision=Decision(v["decision"]),
                    note=v["note"],
                    source_doc_id=v["source_doc_id"],
                    source_quote=v["source_quote"],
                    char_span=locate_quote(doc, v["source_quote"]),
                )
            )

        rows[key] = ObligationSet(
            role=Role(raw["role"]),
            index=IndexKind(raw["index"]),
            band=Band(raw["band"]),
            decision=Decision(raw["decision"]),
            reason_codes=raw.get("reason_codes", []),
            actions=actions,
            obligations=obligations,
            cohort_variants=variants,
            default_cohort=data["role_default_cohort"].get(raw["role"], "healthy"),
            found=True,
        )

    return PolicyMatrix(
        rows=rows,
        role_governing_index=data["role_governing_index"],
        role_default_cohort=data["role_default_cohort"],
        version=data["version"],
    )
