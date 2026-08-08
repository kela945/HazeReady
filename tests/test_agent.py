"""Agent behaviour: extraction, routing, skills, guardrails and the end-to-end
loop under the deterministic stub provider."""

from __future__ import annotations

import pytest

from app.agent.guardrails import DISCLAIMER, over_permission, run_chain
from app.agent.reading_extract import (
    extract_cohort,
    extract_stated_forecast,
    extract_stated_reading,
)
from app.agent.router import SkillRouter
from app.agent.tools.registry import CoverageGaps, verify_claim_against_spans
from app.config import get_settings
from app.models import (
    AuthorityTier,
    ClaimVerdict,
    Decision,
    DraftAdvisory,
    IndexKind,
    RetrievedSpan,
    Role,
)

S = get_settings()


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,value,index",
    [
        ("24-hr PSI just hit 101 in the north.", 101, IndexKind.psi_24h),
        ("PSI is 210. Can my crew work?", 210, IndexKind.psi_24h),
        ("PSI of 165 right now", 165, IndexKind.psi_24h),
        ("1-hr PM2.5 is 152 right now.", 152, IndexKind.pm25_1h),
        ("PM2.5 is 60", 60, IndexKind.pm25_1h),
    ],
)
def test_stated_reading_extraction(question, value, index) -> None:
    r = extract_stated_reading(question)
    assert r is not None
    assert r.value == value
    assert r.index is index


def test_bare_numbers_are_not_read_as_readings() -> None:
    """'my K1 class of 20 children' must not become a PSI of 20."""
    assert extract_stated_reading("My K1 class of 20 children needs outdoor play") is None
    assert extract_stated_reading("We have 30 minutes of outdoor time") is None


def test_pm25_is_preferred_over_psi_when_both_patterns_could_match() -> None:
    r = extract_stated_reading("1-hr PM2.5 is 152, is that the same as PSI?")
    assert r is not None and r.index is IndexKind.pm25_1h and r.value == 152


@pytest.mark.parametrize(
    "question,low,high",
    [
        ("The 24-hr PSI forecast for tomorrow is 90 to 130.", 90, 130),
        ("Forecast for our race tomorrow is 180 to 220.", 180, 220),
        ("PSI is 88 now, forecast 120 to 150 for the 4pm training.", 120, 150),
        ("Forecast tomorrow 260 to 290. Outing?", 260, 290),
    ],
)
def test_forecast_range_extraction(question, low, high) -> None:
    """Reading only the first number of a forecast range resolves the band
    against the optimistic end, which is the permissive error."""
    f = extract_stated_forecast(question)
    assert f is not None
    assert (f.low, f.high) == (low, high)


def test_no_forecast_in_a_current_reading_question() -> None:
    assert extract_stated_forecast("PSI is 210. Can my crew work?") is None


@pytest.mark.parametrize(
    "question,cohort",
    [
        ("One of my workers is pregnant.", "vulnerable"),
        ("My father is 78 and has COPD.", "vulnerable"),
        ("A student with asthma feels unwell.", "vulnerable"),
        ("My workers are all healthy adults.", "healthy"),
        ("I am a healthy 30-year-old.", "healthy"),
        ("PSI 165. Outdoor play?", None),
    ],
)
def test_cohort_extraction(question, cohort) -> None:
    assert extract_cohort(question) == cohort


# --------------------------------------------------------------------------
# Skills and routing
# --------------------------------------------------------------------------


def test_all_six_skills_load() -> None:
    r = SkillRouter(S.skills_dir)
    assert len(r.skills) == 6
    assert {s.role for s in r.skills.values()} == set(Role)


def test_progressive_disclosure_exposes_only_descriptions() -> None:
    """The router stage-1 context must not contain the full skill bodies."""
    r = SkillRouter(S.skills_dir)
    d = r.descriptions_only()
    assert "preschool_operator" in d
    assert "## Decision procedure" not in d
    assert len(d) < 2000


def test_every_skill_declares_known_gaps() -> None:
    """Abstention is grounded in something inspectable rather than emergent."""
    r = SkillRouter(S.skills_dir)
    for s in r.skills.values():
        assert s.known_gaps, f"{s.name} has no Known gaps section"


def test_skills_are_hot_loadable(tmp_path) -> None:
    """Adding a directory adds a role with no code change."""
    import shutil

    staging = tmp_path / "skills"
    shutil.copytree(S.skills_dir, staging)
    r = SkillRouter(staging)
    assert len(r.skills) == 6

    new = staging / "clinic_operator"
    new.mkdir()
    (new / "SKILL.md").write_text(
        "---\nname: clinic_operator\nrole: eldercare\n"
        "description: Test skill added at runtime.\n"
        "governing_agencies: [MOH]\nprimary_index: psi_24h\n"
        "route_terms: [clinic, polyclinic]\n---\n\n"
        "## Decision procedure\n1. Test.\n\n## Known gaps\nEverything.\n",
        encoding="utf-8",
    )
    r.reload()
    assert len(r.skills) == 7
    assert r.load("clinic_operator") is not None


@pytest.mark.parametrize(
    "question,role",
    [
        ("My K1 class has outdoor play in 20 minutes", Role.preschool),
        ("Does the Sec 3 cross-country training run?", Role.school),
        ("Can my construction crew keep working outdoors?", Role.worksite),
        ("Should the day centre's garden walk run?", Role.eldercare),
        ("Does our 10km road race go ahead?", Role.event),
    ],
)
def test_deterministic_routing(question, role) -> None:
    r = SkillRouter(S.skills_dir)
    skill, confidence = r.route_deterministic(question)
    assert skill is not None and skill.role is role
    assert confidence > 0.0


def test_route_terms_match_on_word_boundaries() -> None:
    """`school` must not match inside `preschool`, and `pe` must not match
    inside `open`."""
    r = SkillRouter(S.skills_dir)
    skill, _ = r.route_deterministic("At what PSI must a preschool close?")
    assert skill is not None and skill.role is Role.preschool


def test_institutional_role_beats_general_public_on_a_tie() -> None:
    """'take the K2s to the playground' matches both preschool and
    general_public; answering as a member of the public drops the entire
    vulnerable-cohort posture."""
    r = SkillRouter(S.skills_dir)
    skill, _ = r.route_deterministic("Do we still take the K2s to the playground?")
    assert skill is not None and skill.role is Role.preschool


# --------------------------------------------------------------------------
# Coverage gaps
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,role,gap",
    [
        ("At what PSI do schools close?", Role.school, "school_closure_threshold"),
        ("What size air purifier do I need?", Role.preschool, "air_purifier_specification"),
        ("How many puffs of his inhaler should he take?", Role.general_public,
         "individual_medical_management"),
        ("What work rest cycle should we use?", Role.worksite, "haze_work_rest_cycle"),
        ("How many hotspots means I should postpone?", Role.event, "hotspot_based_decision"),
    ],
)
def test_coverage_gap_matching(question, role, gap) -> None:
    g = CoverageGaps(S.coverage_gaps_path).match(question, role)
    assert g is not None and g["id"] == gap


def test_gap_matching_is_word_order_independent() -> None:
    """Ordered substring matching missed 'what size air purifier' against the
    trigger 'purifier size', so the system answered a question the guidance does
    not cover."""
    cg = CoverageGaps(S.coverage_gaps_path)
    for phrasing in (
        "What size air purifier do I need?",
        "What purifier size should I buy?",
        "Which purifier should we choose?",
    ):
        assert cg.match(phrasing, Role.preschool) is not None


def test_ordinary_questions_do_not_match_a_gap() -> None:
    cg = CoverageGaps(S.coverage_gaps_path)
    assert cg.match("PSI is 165, does outdoor play run?", Role.preschool) is None
    assert cg.match("PSI is 210, can my crew work?", Role.worksite) is None


# --------------------------------------------------------------------------
# Guardrails
# --------------------------------------------------------------------------


def span(text: str, tier: AuthorityTier = AuthorityTier.primary) -> RetrievedSpan:
    return RetrievedSpan(
        doc_id="d", chunk_id="d::000", text=text, char_span=(0, len(text)),
        score=0.05, authority_tier=tier, issuing_agency="NEA", title="t",
        source_url="u", retrieved_at="2026-08-08",
    )


def test_unsourced_numeral_triggers_regeneration() -> None:
    draft = DraftAdvisory(decision=Decision.restrict, rationale="Cancel above PSI 175.")
    out = run_chain(draft, [span("x")], sourced_numbers={"101"},
                    matrix_decision=Decision.restrict, attempt=0)
    assert out.needs_regeneration
    assert any(e.guardrail == "numeric_integrity" and e.triggered for e in out.events)


def test_numerals_the_asker_wrote_are_sourced() -> None:
    """The model restating the question's own figures is not confabulation.
    An early version abstained on "outdoor play in 20 minutes" because it
    treated the echoed 20 as an invented reading."""
    from app.agent.orchestrator import Orchestrator

    sourced = Orchestrator._sourced_numbers(
        "PSI just hit 101. My K1 class has outdoor play in 20 minutes.",
        None, None, None, [],
    )
    assert "20" in sourced
    assert "101" in sourced


def test_second_unsourced_numeral_failure_abstains() -> None:
    draft = DraftAdvisory(decision=Decision.restrict, rationale="Cancel above PSI 175.")
    out = run_chain(draft, [span("x")], sourced_numbers={"101"},
                    matrix_decision=Decision.restrict, attempt=1)
    assert out.abstention is not None


def test_matrix_sourced_claims_are_not_re_verified() -> None:
    """Matrix statements are grounded by construction via validated char spans.
    Re-checking them against a retrieval stripped correct obligations that
    merely used different wording, causing spurious abstentions."""
    claim = "Full-day preschools provide at least 30 minutes of outdoor activity daily."
    draft = DraftAdvisory(decision=Decision.restrict, obligations=[claim])
    out = run_chain(draft, [span("unrelated text about masks")],
                    sourced_numbers={"30"}, matrix_decision=Decision.restrict,
                    grounded_claims={claim})
    assert claim in out.draft.obligations


def test_model_introduced_claim_is_still_verified() -> None:
    draft = DraftAdvisory(
        decision=Decision.restrict,
        obligations=["Centres must install ultraviolet sterilisation in every room."],
    )
    out = run_chain(draft, [span("Minimise outdoor activities at this band.")],
                    sourced_numbers=set(), matrix_decision=Decision.restrict,
                    grounded_claims=set())
    assert out.draft.obligations == [] or out.needs_regeneration


def test_over_permission_rejects_permission_by_absence() -> None:
    """A permissive decision must be backed by an EXPLICIT permissive statement.
    Inferring permission from the absence of a prohibition is the failure this
    guardrail exists to prevent."""
    draft = DraftAdvisory(decision=Decision.proceed, rationale="Nothing forbids it.")
    ev = over_permission(draft, [span("Minimise outdoor activities.")], Decision.proceed)
    assert ev.triggered


def test_over_permission_accepts_an_explicit_permission() -> None:
    draft = DraftAdvisory(decision=Decision.proceed, rationale="No restriction applies.")
    ev = over_permission(
        draft, [span("| 0 - 100 (Good, Moderate) | Normal activities |")],
        Decision.proceed,
    )
    assert not ev.triggered


def test_explanatory_spans_cannot_supply_permission() -> None:
    """An authored interpretation must never license an action the agencies
    never permitted."""
    draft = DraftAdvisory(decision=Decision.proceed, rationale="Fine to go.")
    ev = over_permission(
        draft,
        [span("Normal activities apply here.", AuthorityTier.explanatory)],
        Decision.proceed,
    )
    assert ev.triggered


def test_model_more_permissive_than_matrix_is_rejected() -> None:
    draft = DraftAdvisory(decision=Decision.proceed, rationale="Go ahead.")
    ev = over_permission(draft, [span("x")], Decision.suspend)
    assert ev.triggered
    assert "more permissive" in ev.detail


def test_disclaimer_is_always_injected() -> None:
    draft = DraftAdvisory(decision=Decision.restrict, rationale="Restricted.")
    out = run_chain(draft, [span("Minimise outdoor activities.")],
                    sourced_numbers=set(), matrix_decision=Decision.restrict)
    assert any(e.guardrail == "disclaimer_injection" for e in out.events)
    assert "nea.gov.sg" in DISCLAIMER


# --------------------------------------------------------------------------
# Claim verification
# --------------------------------------------------------------------------


def test_claim_with_an_unsupported_numeral_is_not_entailed() -> None:
    r = verify_claim_against_spans(
        "Cancel outdoor play above PSI 175.",
        [span("Minimise outdoor activities at 101 to 200.")],
    )
    assert r.verdict is ClaimVerdict.not_entailed


def test_well_supported_claim_is_entailed() -> None:
    r = verify_claim_against_spans(
        "Minimise outdoor activities and avoid strenuous indoor exercise.",
        [span("Schools should minimise outdoor activities and avoid strenuous "
              "indoor physical exercise at this band.")],
    )
    assert r.verdict is ClaimVerdict.entailed


def test_no_spans_yields_insufficient_not_entailed() -> None:
    r = verify_claim_against_spans("Anything.", [])
    assert r.verdict is ClaimVerdict.insufficient
