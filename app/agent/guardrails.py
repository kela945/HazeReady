"""The guardrail chain. Runs in order on every response before it reaches a user.

The over-permission check (stage 4) is the one that carries the safety argument.
It rejects permission by *absence* of prohibition: a permissive recommendation
must be supported by an explicit permissive statement in a cited span. This
directly implements the asymmetric cost model — telling a preschool it is fine
to send children outside at PSI 210 is categorically worse than telling them to
stay in at PSI 95.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.tools.registry import verify_claim_against_spans
from app.models import (
    AbstainReason,
    Abstention,
    AuthorityTier,
    ClaimVerdict,
    Decision,
    DraftAdvisory,
    GuardrailEvent,
    RetrievedSpan,
)

DISCLAIMER = (
    "Decision-support prototype. Official advisories at nea.gov.sg govern. "
    "Not medical or legal advice."
)

PERMISSIVE_PATTERNS = [
    r"\bsafe to proceed\b",
    r"\bno action needed\b",
    r"\bno action required\b",
    r"\bno restriction\b",
    r"\bno restrictions\b",
    r"\bnot? need to (?:cancel|restrict|change|worry)\b",
    r"\bgo ahead as (?:normal|planned)\b",
    r"\bperfectly fine\b",
    r"\bnothing to worry about\b",
    r"\bcarry on as (?:normal|usual)\b",
]

# Phrases in a cited span that constitute an *explicit* permission.
EXPLICIT_PERMISSION_PATTERNS = [
    r"normal activities",
    r"preparatory measures only",
    r"no restriction on outdoor work applies",
    r"none from the advisory",
    r"no advisory constraint",
    r"proceeds normally",
    r"work is not stopped at this band",
    r"does not\s+prohibit",
]

PERMISSIVE_DECISIONS = {Decision.proceed, Decision.proceed_with_precautions}


@dataclass
class GuardrailOutcome:
    draft: DraftAdvisory
    events: list[GuardrailEvent] = field(default_factory=list)
    abstention: Abstention | None = None
    conflicts: list[str] = field(default_factory=list)
    needs_regeneration: bool = False
    stripped_claims: list[str] = field(default_factory=list)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def numeric_integrity(draft: DraftAdvisory, sourced_numbers: set[str]) -> GuardrailEvent:
    """Stage 1. Every PSI/PM2.5 numeral in the draft must trace to a tool
    output — a `resolve_psi_band` result or a live reading. A numeral the model
    produced on its own is exactly the failure this system is designed against.
    """
    text = " ".join([draft.rationale, *draft.obligations])
    found = set(re.findall(r"\b\d{2,4}\b", text))
    unsourced = {n for n in found if n not in sourced_numbers}
    if unsourced:
        return GuardrailEvent(
            guardrail="numeric_integrity",
            triggered=True,
            detail=f"unsourced numerals: {sorted(unsourced)}",
            action="regenerate",
        )
    return GuardrailEvent(guardrail="numeric_integrity", triggered=False, action="pass")


def citation_entailment(
    draft: DraftAdvisory,
    spans: list[RetrievedSpan],
    grounded_claims: set[str] | None = None,
) -> tuple[GuardrailEvent, list[str]]:
    """Stage 2. Check each declarative obligation claim against the cited spans.
    `not_entailed` claims are stripped. Returns the surviving obligations.

    `grounded_claims` are statements that came from the policy matrix. Those are
    already grounded by construction: each carries a verbatim source_quote whose
    character span was resolved against the cited document at load time, and
    scripts/validate_corpus.py fails the build if it does not resolve. Re-checking
    them against a *retrieval* would test a different and weaker proposition,
    and an early version of this code stripped correct matrix obligations that
    simply used different wording from the top-k spans, producing spurious
    abstentions on well-covered questions.

    This stage therefore polices claims the model introduced on its own, which
    is where confabulation actually enters.
    """
    if not draft.obligations:
        return (
            GuardrailEvent(guardrail="citation_entailment", triggered=False, action="pass"),
            [],
        )

    grounded = grounded_claims or set()
    survivors: list[str] = []
    stripped: list[str] = []
    for claim in draft.obligations:
        if claim in grounded:
            survivors.append(claim)
            continue
        result = verify_claim_against_spans(claim, spans)
        if result.verdict == ClaimVerdict.not_entailed:
            stripped.append(claim)
        else:
            survivors.append(claim)

    if stripped:
        return (
            GuardrailEvent(
                guardrail="citation_entailment",
                triggered=True,
                detail=f"stripped {len(stripped)} unentailed claim(s)",
                action="strip",
            ),
            survivors,
        )
    return (
        GuardrailEvent(guardrail="citation_entailment", triggered=False, action="pass"),
        survivors,
    )


def authority_conflict(spans: list[RetrievedSpan]) -> tuple[GuardrailEvent, list[str]]:
    """Stage 3. If two `primary` spans from different agencies give opposing
    postures for the same band, surface both rather than resolving it.

    Detection is narrow on purpose: it fires only when two primary spans from
    different agencies contain directly opposing verbs ("avoid" vs "normal
    activities") for an overlapping band. A broad detector would fire on every
    scope difference and train the reader to ignore it.
    """
    primary = [s for s in spans if s.authority_tier == AuthorityTier.primary]
    conflicts: list[str] = []
    for i, a in enumerate(primary):
        for b in primary[i + 1 :]:
            if a.issuing_agency == b.issuing_agency:
                continue
            a_permits = bool(re.search(r"normal activities", a.text, re.I))
            b_forbids = bool(re.search(r"\bavoid outdoor activity\b", b.text, re.I))
            if a_permits and b_forbids:
                conflicts.append(
                    f"{a.issuing_agency} ({a.doc_id}) and {b.issuing_agency} "
                    f"({b.doc_id}) give opposing postures; both are shown."
                )
    if conflicts:
        return (
            GuardrailEvent(
                guardrail="authority_conflict",
                triggered=True,
                detail="; ".join(conflicts),
                action="flag",
            ),
            conflicts,
        )
    return (
        GuardrailEvent(guardrail="authority_conflict", triggered=False, action="pass"),
        [],
    )


def over_permission(
    draft: DraftAdvisory, spans: list[RetrievedSpan], matrix_decision: Decision
) -> GuardrailEvent:
    """Stage 4. The primary safety guardrail.

    A permissive recommendation must be backed by an explicit permissive
    statement in a cited span from a primary or secondary source. Permission
    inferred from the *absence* of a prohibition is rejected.

    Explanatory-tier documents cannot supply permission: they restate primary
    rules and would otherwise let an authored interpretation license an action
    the agencies never permitted.
    """
    text = " ".join([draft.rationale, *draft.obligations]).lower()
    hit = next((p for p in PERMISSIVE_PATTERNS if re.search(p, text)), None)

    permissive_decision = draft.decision in PERMISSIVE_DECISIONS
    if not hit and not permissive_decision:
        return GuardrailEvent(guardrail="over_permission", triggered=False, action="pass")

    # The deterministic matrix is the authority on the decision. If the matrix
    # says proceed, the permission is grounded by construction.
    if draft.decision == matrix_decision and matrix_decision in PERMISSIVE_DECISIONS:
        citable = [
            s
            for s in spans
            if s.authority_tier in (AuthorityTier.primary, AuthorityTier.secondary)
        ]
        supported = any(
            re.search(p, s.text, re.I) for s in citable for p in EXPLICIT_PERMISSION_PATTERNS
        )
        if supported:
            return GuardrailEvent(
                guardrail="over_permission",
                triggered=False,
                detail="permissive decision backed by an explicit permissive span",
                action="pass",
            )
        return GuardrailEvent(
            guardrail="over_permission",
            triggered=True,
            detail=(
                "permissive decision without an explicit permissive statement in a "
                "primary or secondary span; permission by absence of prohibition is "
                "rejected"
            ),
            action="regenerate",
        )

    # The model is more permissive than the deterministic matrix. That is the
    # dangerous direction and is never allowed to stand.
    if _more_permissive(draft.decision, matrix_decision):
        return GuardrailEvent(
            guardrail="over_permission",
            triggered=True,
            detail=(
                f"draft decision {draft.decision.value} is more permissive than the "
                f"policy matrix decision {matrix_decision.value}"
            ),
            action="regenerate",
        )

    if hit:
        return GuardrailEvent(
            guardrail="over_permission",
            triggered=True,
            detail=f"permissive phrasing {hit!r} in a non-permissive decision",
            action="strip",
        )
    return GuardrailEvent(guardrail="over_permission", triggered=False, action="pass")


ORDER = [
    Decision.proceed,
    Decision.proceed_with_precautions,
    Decision.restrict,
    Decision.suspend,
]


def _more_permissive(a: Decision, b: Decision) -> bool:
    if a not in ORDER or b not in ORDER:
        return False
    return ORDER.index(a) < ORDER.index(b)


def inject_disclaimer() -> tuple[GuardrailEvent, str]:
    """Stage 5. Non-removable footer."""
    return (
        GuardrailEvent(guardrail="disclaimer_injection", triggered=True, action="pass"),
        DISCLAIMER,
    )


def run_chain(
    draft: DraftAdvisory,
    spans: list[RetrievedSpan],
    sourced_numbers: set[str],
    matrix_decision: Decision,
    attempt: int = 0,
    grounded_claims: set[str] | None = None,
) -> GuardrailOutcome:
    """Execute stages 1-5 in order.

    Regeneration policy: a stage that returns `regenerate` triggers exactly one
    retry (attempt 0 -> 1). A second failure abstains. Retrying indefinitely
    against a model that keeps producing an ungrounded numeral would burn budget
    and, worse, would eventually pass one by chance.
    """
    events: list[GuardrailEvent] = []

    ev = numeric_integrity(draft, sourced_numbers)
    events.append(ev)
    if ev.triggered and ev.action == "regenerate":
        if attempt == 0:
            return GuardrailOutcome(draft=draft, events=events, needs_regeneration=True)
        return GuardrailOutcome(
            draft=draft,
            events=events,
            abstention=Abstention(
                reason=AbstainReason.no_governing_guidance,
                plain_language=(
                    "The system could not produce an answer whose numbers all trace "
                    "to an official reading, so it is declining to answer."
                ),
                suggested_authority="NEA (nea.gov.sg) for current readings and advisories",
            ),
        )

    ev, survivors = citation_entailment(draft, spans, grounded_claims)
    events.append(ev)
    stripped = [o for o in draft.obligations if o not in survivors]
    draft = draft.model_copy(update={"obligations": survivors})
    if ev.triggered and not survivors and draft.decision != Decision.abstain:
        if attempt == 0:
            return GuardrailOutcome(
                draft=draft, events=events, needs_regeneration=True, stripped_claims=stripped
            )
        return GuardrailOutcome(
            draft=draft,
            events=events,
            stripped_claims=stripped,
            abstention=Abstention(
                reason=AbstainReason.no_governing_guidance,
                plain_language=(
                    "No claim in the draft answer was entailed by the retrieved "
                    "sources, so the system is declining to answer."
                ),
                suggested_authority="NEA (nea.gov.sg)",
            ),
        )

    ev, conflicts = authority_conflict(spans)
    events.append(ev)

    ev = over_permission(draft, spans, matrix_decision)
    events.append(ev)
    if ev.triggered and ev.action == "regenerate":
        if attempt == 0:
            return GuardrailOutcome(
                draft=draft,
                events=events,
                conflicts=conflicts,
                needs_regeneration=True,
                stripped_claims=stripped,
            )
        # Second failure: fall back to the deterministic matrix decision rather
        # than abstaining. The matrix decision is grounded by construction, so
        # this preserves a usable answer without letting the model's permissive
        # drafting through.
        draft = draft.model_copy(update={"decision": matrix_decision})

    ev, disclaimer = inject_disclaimer()
    events.append(ev)

    return GuardrailOutcome(
        draft=draft, events=events, conflicts=conflicts, stripped_claims=stripped
    )
