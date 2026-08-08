"""Domain models shared by the agent, the API and the evaluation harness.

These are the contract boundary. Pydantic validates LLM output against them, so
a model that returns something structurally wrong fails loudly here rather than
propagating a malformed advisory to the user.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class Role(str, Enum):
    general_public = "general_public"
    school = "school"
    preschool = "preschool"
    eldercare = "eldercare"
    worksite = "worksite"
    event = "event"


class Region(str, Enum):
    north = "north"
    south = "south"
    east = "east"
    west = "west"
    central = "central"
    national = "national"


class IndexKind(str, Enum):
    psi_24h = "psi_24h"
    pm25_1h = "pm25_1h"


class Band(str, Enum):
    """Bands for both indices. PSI uses good..hazardous; PM2.5 uses
    normal..very_high. Keeping them in one enum keeps the ordinal comparison
    total, but `resolve_psi_band` never mixes the two vocabularies."""

    good = "good"
    moderate = "moderate"
    unhealthy = "unhealthy"
    very_unhealthy = "very_unhealthy"
    hazardous = "hazardous"
    normal = "normal"
    elevated = "elevated"
    high = "high"
    very_high = "very_high"


class Decision(str, Enum):
    proceed = "proceed"
    proceed_with_precautions = "proceed_with_precautions"
    restrict = "restrict"
    suspend = "suspend"
    abstain = "abstain"


DECISION_ORDER: list[str] = [
    Decision.proceed.value,
    Decision.proceed_with_precautions.value,
    Decision.restrict.value,
    Decision.suspend.value,
]
"""Ordinal scale, least to most restrictive. `abstain` is deliberately outside
the ordinal scale: it is a different kind of answer, not a fifth degree of
restriction, and averaging it into an ordinal distance would be meaningless."""


class AbstainReason(str, Enum):
    no_governing_guidance = "no_governing_guidance"
    conflicting_sources = "conflicting_sources"
    out_of_scope = "out_of_scope"
    requires_professional_judgement = "requires_professional_judgement"


class AuthorityTier(str, Enum):
    primary = "primary"
    secondary = "secondary"
    explanatory = "explanatory"


# --------------------------------------------------------------------------
# Readings and forecasts
# --------------------------------------------------------------------------


class AirQualityReading(BaseModel):
    region: Region
    psi_24h: int | None = None
    pm25_1h: int | None = None
    reading_timestamp: datetime
    fetched_at: datetime
    staleness_seconds: int
    source: Literal["live", "fixture"] = "live"
    source_url: str = ""
    note: str = ""

    @property
    def is_stale(self) -> bool:
        """Readings are published hourly, so up to ~60 minutes of age is normal
        cadence. Beyond two hours indicates an upstream problem."""
        return self.staleness_seconds > 7200


class Forecast(BaseModel):
    """NEA publishes the 24-hour PSI forecast as a range with band language, so
    this model carries a range. Collapsing it to a point estimate would discard
    the uncertainty the published forecast exists to convey."""

    horizon_hours: int
    psi_low: int
    psi_high: int
    band_low: Band
    band_high: Band
    straddles_boundary: bool
    issued_at: datetime
    source: Literal["live", "fixture", "derived"] = "derived"
    note: str = ""


class HotspotSummary(BaseModel):
    days: int
    count: int
    bbox: tuple[float, float, float, float]
    source: Literal["live", "fixture", "unavailable"] = "fixture"
    note: str = (
        "Hotspots are regional context only. No published obligation is "
        "conditioned on hotspot count."
    )


class BandResult(BaseModel):
    """Output of the deterministic band resolver."""

    value: float
    index: IndexKind
    band: Band
    band_label: str
    lower_bound: int
    upper_bound: int | None
    boundary_note: str
    source_doc_id: str


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------


class RetrievedSpan(BaseModel):
    doc_id: str
    chunk_id: str
    text: str
    char_span: tuple[int, int]
    score: float
    authority_tier: AuthorityTier
    issuing_agency: str
    title: str
    source_url: str
    retrieved_at: str
    heading_path: str = ""
    provenance: str = ""
    verified_against_source: bool = False


# --------------------------------------------------------------------------
# Policy matrix
# --------------------------------------------------------------------------


class SourcedStatement(BaseModel):
    text: str
    source_doc_id: str
    source_quote: str
    char_span: tuple[int, int] | None = None


class CohortVariant(BaseModel):
    cohort: str
    decision: Decision
    note: str
    source_doc_id: str
    source_quote: str
    char_span: tuple[int, int] | None = None


class ObligationSet(BaseModel):
    role: Role
    index: IndexKind
    band: Band
    decision: Decision
    reason_codes: list[str] = Field(default_factory=list)
    actions: list[SourcedStatement] = Field(default_factory=list)
    obligations: list[SourcedStatement] = Field(default_factory=list)
    cohort_variants: list[CohortVariant] = Field(default_factory=list)
    default_cohort: str = "healthy"
    found: bool = True


# --------------------------------------------------------------------------
# Verification and abstention
# --------------------------------------------------------------------------


class ClaimVerdict(str, Enum):
    entailed = "entailed"
    not_entailed = "not_entailed"
    insufficient = "insufficient"


class VerificationResult(BaseModel):
    claim: str
    verdict: ClaimVerdict
    score: float
    best_span_chunk_id: str | None = None
    best_span_doc_id: str | None = None


class Abstention(BaseModel):
    reason: AbstainReason
    plain_language: str
    suggested_authority: str
    evidence_doc_id: str | None = None
    gap_id: str | None = None


# --------------------------------------------------------------------------
# Agent trajectory and answers
# --------------------------------------------------------------------------


class ToolCallRecord(BaseModel):
    hop: int
    tool: str
    arguments: dict[str, Any]
    result_summary: str
    latency_ms: int
    ok: bool = True
    error: str = ""


class GuardrailEvent(BaseModel):
    guardrail: str
    triggered: bool
    detail: str = ""
    action: Literal["pass", "strip", "regenerate", "abstain", "flag"] = "pass"


class Citation(BaseModel):
    marker: int
    doc_id: str
    chunk_id: str
    title: str
    issuing_agency: str
    source_url: str
    retrieved_at: str
    char_span: tuple[int, int]
    authority_tier: AuthorityTier
    quote: str


class Advisory(BaseModel):
    """The complete response object. Everything the UI renders and everything
    the evaluator scores comes from here."""

    query_id: str
    question: str
    role: Role
    role_routed_by: Literal["explicit", "router"] = "router"
    router_confidence: float = 0.0

    decision: Decision
    decision_label: str
    reason_codes: list[str] = Field(default_factory=list)

    obligations: list[str] = Field(default_factory=list)
    rationale: str = ""
    citations: list[Citation] = Field(default_factory=list)

    band_result: BandResult | None = None
    reading: AirQualityReading | None = None
    forecast: Forecast | None = None
    hotspots: HotspotSummary | None = None

    abstention: Abstention | None = None
    conflicts: list[str] = Field(default_factory=list)

    trajectory: list[ToolCallRecord] = Field(default_factory=list)
    guardrail_events: list[GuardrailEvent] = Field(default_factory=list)

    disclaimer: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    provider: str = ""
    arm: str = "A4"
    top_retrieval_score: float = 0.0
    # Set when the language model call failed and the response was composed from
    # the deterministic policy matrix instead. Surfaced in the UI and recorded in
    # telemetry: a system that quietly degrades to a fallback is a system whose
    # operator does not know the model is down.
    llm_error: str = ""


# --------------------------------------------------------------------------
# LLM structured output
# --------------------------------------------------------------------------


class DraftAdvisory(BaseModel):
    """What the language model is asked to return. Note what is absent: no
    band, no numeric threshold, no decision that is not one of the supplied
    options. The model composes and explains; the decision arrives from the
    deterministic matrix."""

    decision: Decision
    reason_codes: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    rationale: str = ""
    citation_doc_ids: list[str] = Field(default_factory=list)
    abstain_reason: AbstainReason | None = None
    abstain_authority: str = ""
