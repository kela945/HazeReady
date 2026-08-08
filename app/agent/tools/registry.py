"""Typed tool registry.

Each tool declares a Pydantic input model and an output model. The docstring
becomes the LLM-facing description, so the description and the implementation
cannot drift apart.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.agent.tools.bands import resolve_psi_band as _resolve_band
from app.models import (
    AbstainReason,
    Abstention,
    AirQualityReading,
    Band,
    BandResult,
    ClaimVerdict,
    Forecast,
    HotspotSummary,
    IndexKind,
    ObligationSet,
    Region,
    RetrievedSpan,
    Role,
    VerificationResult,
)

# --------------------------------------------------------------------------
# Input models
# --------------------------------------------------------------------------


class GetCurrentAirQualityInput(BaseModel):
    region: Region | None = Field(
        default=None, description="One of north, south, east, west, central, national."
    )


class GetForecastInput(BaseModel):
    horizon_hours: int = Field(default=24, ge=1, le=72)
    region: Region | None = None


class GetHotspotsInput(BaseModel):
    days: int = Field(default=1, ge=1, le=7)


class ResolvePsiBandInput(BaseModel):
    value: float = Field(description="The numeric reading.")
    index: IndexKind = Field(
        default=IndexKind.psi_24h,
        description="psi_24h for the 24-hour PSI, pm25_1h for the 1-hour PM2.5.",
    )


class LookupRoleObligationsInput(BaseModel):
    role: Role
    band: Band
    index: IndexKind = IndexKind.psi_24h


class SearchAdvisoriesInput(BaseModel):
    query: str
    role: Role | None = None
    k: int = Field(default=5, ge=1, le=10)


class VerifyClaimInput(BaseModel):
    claim: str
    span_chunk_ids: list[str] = Field(default_factory=list)


class AbstainInput(BaseModel):
    reason: AbstainReason
    suggested_authority: str = ""
    gap_id: str | None = None


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[..., Any]
    concurrent_safe: bool = True

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def describe_for_prompt(self) -> str:
        lines = []
        for t in self._tools.values():
            props = t.input_model.model_json_schema().get("properties", {})
            args = ", ".join(props)
            lines.append(f"- {t.name}({args}): {t.description.strip().splitlines()[0]}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Claim verification (NLI-style entailment over retrieved spans)
# --------------------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on",
    "at", "be", "should", "must", "may", "can", "this", "that", "it", "with",
    "as", "by", "from", "not", "no", "your", "you", "we", "their",
}


def _content_terms(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())
    return {t for t in toks if t not in _STOPWORDS and len(t) > 2}


def verify_claim_against_spans(
    claim: str, spans: list[RetrievedSpan]
) -> VerificationResult:
    """Lexical-overlap entailment with a numeric-agreement gate.

    This is deliberately not a neural NLI model. A cross-encoder NLI model
    trained on general text is not calibrated for "does this span license this
    obligation", and its errors would be silent. The rule here is legible and
    its failure mode is conservative:

      - Every numeral in the claim must appear in some span. A claim asserting
        a threshold the sources never state is `not_entailed`, which is the
        error class that matters most here.
      - Content-word overlap above 0.55 with a single span is `entailed`;
        between 0.30 and 0.55 is `insufficient`; below is `not_entailed`.

    The A7 ablation removes this check to measure what it catches. Its
    limitations are stated in the report rather than papered over.
    """
    if not spans:
        return VerificationResult(claim=claim, verdict=ClaimVerdict.insufficient, score=0.0)

    claim_numbers = set(re.findall(r"\b\d{1,4}\b", claim))
    all_span_numbers: set[str] = set()
    for s in spans:
        all_span_numbers |= set(re.findall(r"\b\d{1,4}\b", s.text))

    unsupported_numbers = claim_numbers - all_span_numbers
    if unsupported_numbers:
        return VerificationResult(
            claim=claim,
            verdict=ClaimVerdict.not_entailed,
            score=0.0,
            best_span_doc_id=spans[0].doc_id,
            best_span_chunk_id=spans[0].chunk_id,
        )

    claim_terms = _content_terms(claim)
    if not claim_terms:
        return VerificationResult(claim=claim, verdict=ClaimVerdict.insufficient, score=0.0)

    best_score = 0.0
    best = spans[0]
    for s in spans:
        overlap = len(claim_terms & _content_terms(s.text)) / len(claim_terms)
        if overlap > best_score:
            best_score, best = overlap, s

    if best_score >= 0.55:
        verdict = ClaimVerdict.entailed
    elif best_score >= 0.30:
        verdict = ClaimVerdict.insufficient
    else:
        verdict = ClaimVerdict.not_entailed

    return VerificationResult(
        claim=claim,
        verdict=verdict,
        score=round(best_score, 4),
        best_span_doc_id=best.doc_id,
        best_span_chunk_id=best.chunk_id,
    )


# --------------------------------------------------------------------------
# Coverage gaps / abstention
# --------------------------------------------------------------------------


class CoverageGaps:
    def __init__(self, path) -> None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.gaps = data["gaps"]

    def match(self, question: str, role: Role | None = None) -> dict | None:
        """Return the gap whose trigger terms best match the question.

        Matching is bag-of-words rather than ordered substring: every word of a
        trigger term must appear in the question as a whole word, in any order.
        Ordered substring matching missed "what size air purifier" against the
        trigger "purifier size", which meant the system answered a question the
        guidance does not cover — the exact failure abstention exists to prevent.

        Longer trigger terms win, so a specific two-word trigger beats an
        incidental one-word one. Matching stays deliberately simple and
        inspectable; the benchmark's out_of_knowledge_base category measures
        whether it is sufficient, and reports where it is not.
        """
        words = set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", question.lower()))
        best: tuple[int, dict] | None = None
        for gap in self.gaps:
            if role is not None and role.value not in gap["applies_to_roles"]:
                continue
            for term in gap["trigger_terms"]:
                term_words = set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", term.lower()))
                if term_words and term_words <= words:
                    score = len(term_words)
                    if best is None or score > best[0]:
                        best = (score, gap)
        return best[1] if best else None

    def to_abstention(self, gap: dict) -> Abstention:
        return Abstention(
            reason=AbstainReason(gap["reason"]),
            plain_language=(
                f"The published guidance available to this system does not cover "
                f"{gap['topic'][0].lower()}{gap['topic'][1:]}."
            ),
            suggested_authority=gap["suggested_authority"],
            evidence_doc_id=gap["evidence_doc_id"],
            gap_id=gap["id"],
        )


def build_registry(
    *,
    air_quality_client,
    policy_matrix,
    retriever,
    coverage_gaps: CoverageGaps,
) -> ToolRegistry:
    registry = ToolRegistry()

    async def get_current_air_quality(region: Region | None = None) -> AirQualityReading:
        return await air_quality_client.get_current_air_quality(region)

    async def get_air_quality_forecast(
        horizon_hours: int = 24, region: Region | None = None
    ) -> Forecast:
        return await air_quality_client.get_air_quality_forecast(horizon_hours, region)

    async def get_regional_hotspots(days: int = 1) -> HotspotSummary:
        return await air_quality_client.get_regional_hotspots(days)

    def resolve_psi_band(value: float, index: IndexKind = IndexKind.psi_24h) -> BandResult:
        return _resolve_band(value, index.value if isinstance(index, IndexKind) else index)

    def lookup_role_obligations(
        role: Role, band: Band, index: IndexKind = IndexKind.psi_24h
    ) -> ObligationSet:
        return policy_matrix.lookup(role, band, index)

    def search_advisories(
        query: str, role: Role | None = None, k: int = 5
    ) -> list[RetrievedSpan]:
        return retriever.search(query, role=role, k=k)

    registry.register(
        Tool(
            "get_current_air_quality",
            get_current_air_quality.__doc__
            or "Fetch the current 24-hour PSI and 1-hour PM2.5 for a region, with "
            "the reading timestamp and how stale it is.",
            GetCurrentAirQualityInput,
            get_current_air_quality,
        )
    )
    registry.register(
        Tool(
            "get_air_quality_forecast",
            "Get the 24-hour PSI outlook as a band RANGE, not a point estimate. "
            "Use for any decision about a future window.",
            GetForecastInput,
            get_air_quality_forecast,
        )
    )
    registry.register(
        Tool(
            "get_regional_hotspots",
            "Regional fire hotspot count for context only. Never a basis for a "
            "decision; no published obligation is conditioned on hotspot count.",
            GetHotspotsInput,
            get_regional_hotspots,
        )
    )
    registry.register(
        Tool(
            "resolve_psi_band",
            "Resolve a numeric reading to its official band. Deterministic. "
            "ALWAYS use this instead of comparing numbers yourself.",
            ResolvePsiBandInput,
            resolve_psi_band,
            concurrent_safe=False,
        )
    )
    registry.register(
        Tool(
            "lookup_role_obligations",
            "Look up the published obligations and the governing decision for a "
            "role at a band. Deterministic lookup against the policy matrix.",
            LookupRoleObligationsInput,
            lookup_role_obligations,
            concurrent_safe=False,
        )
    )
    registry.register(
        Tool(
            "search_advisories",
            "Hybrid search over the advisory corpus. Returns spans with citations.",
            SearchAdvisoriesInput,
            search_advisories,
        )
    )
    registry.register(
        Tool(
            "verify_claim",
            "Check whether a claim is entailed by the retrieved spans.",
            VerifyClaimInput,
            verify_claim_against_spans,
        )
    )
    registry.register(
        Tool(
            "abstain",
            "Terminal. Decline to answer because no governing guidance exists, "
            "sources conflict, the question is out of scope, or it requires "
            "professional judgement.",
            AbstainInput,
            lambda reason, suggested_authority="", gap_id=None: Abstention(
                reason=reason,
                plain_language="No governing published guidance covers this question.",
                suggested_authority=suggested_authority or "NEA (nea.gov.sg)",
                gap_id=gap_id,
            ),
            concurrent_safe=False,
        )
    )
    return registry
