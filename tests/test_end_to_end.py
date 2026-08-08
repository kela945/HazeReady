"""End-to-end behaviour through the real orchestrator, offline.

These run against the deterministic stub provider and committed fixtures, so
they assert the properties the deterministic scaffolding guarantees regardless
of which language model is configured.
"""

from __future__ import annotations

import pytest

from app.agent.orchestrator import ArmConfig
from app.config import Settings
from app.deps import Container
from app.models import Decision, Role


@pytest.fixture(scope="module")
def container() -> Container:
    return Container(Settings(OFFLINE_MODE=True, LLM_PROVIDER="stub"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,role,decision",
    [
        # The 100/101 boundary flips a preschool from proceed to restrict.
        ("24-hr PSI is exactly 100 in the north. K1 outdoor play?",
         Role.preschool, Decision.proceed),
        ("24-hr PSI just hit 101 in the north. K1 outdoor play?",
         Role.preschool, Decision.restrict),
        # 200/201 flips a worksite from proceed_with_precautions to restrict.
        ("PSI is 200 exactly. Prolonged outdoor work for healthy staff?",
         Role.worksite, Decision.proceed_with_precautions),
        ("PSI is 201. Prolonged outdoor work for healthy staff?",
         Role.worksite, Decision.restrict),
        # Hazardous suspends outdoor activity for a vulnerable cohort.
        ("PSI 305. Do we hold outdoor assembly?", Role.school, Decision.suspend),
    ],
)
async def test_boundary_decisions(container, question, role, decision) -> None:
    a = await container.orchestrator.answer(question, role=role)
    assert a.decision is decision, f"{question!r} -> {a.decision}"


@pytest.mark.asyncio
async def test_band_is_always_resolved_before_the_decision(container) -> None:
    """The design constraint, verified at runtime: resolve_psi_band must run
    before lookup_role_obligations on every answered query."""
    a = await container.orchestrator.answer(
        "PSI 165. Does outdoor PE run?", role=Role.school
    )
    tools = [t.tool for t in a.trajectory]
    assert "resolve_psi_band" in tools
    assert tools.index("resolve_psi_band") < tools.index("lookup_role_obligations")


@pytest.mark.asyncio
async def test_stated_reading_governs_over_the_live_fixture(container) -> None:
    """The fixture reads 66 (Moderate); the question states 210. The question is
    the situation the asker is asking about."""
    a = await container.orchestrator.answer(
        "PSI is 210. Can my crew keep working outdoors?", role=Role.worksite
    )
    assert a.band_result is not None
    assert a.band_result.value == 210
    assert a.band_result.band_label == "Very Unhealthy"


@pytest.mark.asyncio
async def test_forecast_range_plans_against_the_worst_band(container) -> None:
    """A range spanning 90-130 straddles 100/101. Planning against the midpoint
    would return proceed; the Unhealthy obligations are the ones that must be
    planned for."""
    a = await container.orchestrator.answer(
        "The 24-hr PSI forecast for tomorrow is 90 to 130. We have an excursion "
        "booked and parents need to know tonight. Do we go?",
        role=Role.preschool,
    )
    assert a.decision is Decision.restrict
    assert a.forecast is not None
    assert (a.forecast.psi_low, a.forecast.psi_high) == (90, 130)
    assert a.forecast.straddles_boundary


@pytest.mark.asyncio
async def test_named_cohort_overrides_the_role_default(container) -> None:
    healthy = await container.orchestrator.answer(
        "24-hr PSI is 150. My workers are all healthy adults. Prolonged outdoor work?",
        role=Role.worksite,
    )
    pregnant = await container.orchestrator.answer(
        "24-hr PSI is 150. One of my workers is pregnant. Prolonged outdoor work?",
        role=Role.worksite,
    )
    assert healthy.decision is Decision.proceed_with_precautions
    assert pregnant.decision is Decision.restrict


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,role",
    [
        ("At what PSI do schools close?", Role.school),
        ("What size air purifier do I need for a 40 square metre classroom?", Role.preschool),
        ("How many puffs of his inhaler should he take?", Role.general_public),
        ("What work rest cycle should we use at PSI 180?", Role.worksite),
        ("There are 400 hotspots detected in Sumatra. Cancel my plans?", Role.general_public),
    ],
)
async def test_abstains_where_guidance_is_silent(container, question, role) -> None:
    a = await container.orchestrator.answer(question, role=role)
    assert a.decision is Decision.abstain
    assert a.abstention is not None
    assert a.abstention.suggested_authority, "an abstention must name an authority"


@pytest.mark.asyncio
async def test_index_mismatch_abstains_rather_than_converting(container) -> None:
    """A tomorrow decision is a 24-hour PSI forecast decision. Converting a
    current 1-hour PM2.5 value to answer it is a category error."""
    a = await container.orchestrator.answer(
        "1-hr PM2.5 is 60 right now. Do I need to cancel tomorrow morning's excursion?",
        role=Role.preschool,
    )
    assert a.decision is Decision.abstain


@pytest.mark.asyncio
async def test_every_answer_carries_a_disclaimer(container) -> None:
    for q, r in [
        ("PSI 165. Outdoor play?", Role.preschool),
        ("At what PSI do schools close?", Role.school),
    ]:
        a = await container.orchestrator.answer(q, role=r)
        assert "nea.gov.sg" in a.disclaimer


@pytest.mark.asyncio
async def test_answers_are_cited(container) -> None:
    a = await container.orchestrator.answer(
        "PSI 165. Does outdoor play run?", role=Role.preschool
    )
    assert a.citations, "a non-abstained answer must cite its sources"
    for c in a.citations:
        assert c.issuing_agency and c.retrieved_at and c.quote


@pytest.mark.asyncio
async def test_hop_budget_is_respected(container) -> None:
    a = await container.orchestrator.answer(
        "PSI 165. Does outdoor play run?", role=Role.preschool
    )
    assert len(a.trajectory) <= 6


@pytest.mark.asyncio
async def test_no_retrieval_arm_still_answers_without_crashing(container) -> None:
    """A0 removes retrieval and tools entirely; it must degrade, not fail."""
    a = await container.orchestrator.answer(
        "PSI 165. Does outdoor play run?",
        role=Role.preschool,
        arm=ArmConfig(arm="A0", use_retrieval=False, use_tools=False,
                      deterministic_bands=False, use_skills=False),
    )
    assert a.decision in set(Decision)
