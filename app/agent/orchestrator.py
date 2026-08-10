"""The agent orchestrator: tool-calling loop, max 6 hops, hard stop.

Control flow is explicit rather than framework-driven, because every hop has to
be defensible and every guardrail failure has to be debuggable. The loop is:

    route role -> resolve index and reading -> resolve band deterministically
    -> look up obligations -> retrieve corroboration -> compose -> guard

Independent calls (live reading, hotspots, retrieval) run concurrently via
asyncio.gather. The band resolution and the policy lookup are sequential
because each depends on the previous.

Ablation arms are configured here (`ArmConfig`), so a single code path serves
all nine arms and the arms cannot silently diverge from the production path.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.agent import guardrails
from app.agent.reading_extract import (
    extract_cohort,
    extract_stated_forecast,
    extract_stated_reading,
)
from app.agent.router import SkillRouter
from app.agent.tools.bands import resolve_psi_band, worse_band
from app.agent.tools.registry import CoverageGaps
from app.llm.providers.anthropic_provider import (
    DRAFT_ADVISORY_SCHEMA,
    ROLE_ROUTE_SCHEMA,
)
from app.models import (
    AbstainReason,
    Abstention,
    Advisory,
    AirQualityReading,
    Band,
    BandResult,
    Citation,
    Decision,
    DraftAdvisory,
    Forecast,
    HotspotSummary,
    IndexKind,
    ObligationSet,
    Region,
    RetrievedSpan,
    Role,
    ToolCallRecord,
)
from app.rag.retriever import RetrievalMode, Retriever

DECISION_LABELS = {
    Decision.proceed: "PROCEED",
    Decision.proceed_with_precautions: "PROCEED WITH PRECAUTIONS",
    Decision.restrict: "RESTRICT",
    Decision.suspend: "SUSPEND",
    Decision.abstain: "NO GOVERNING GUIDANCE",
}

SYSTEM_PROMPT = """You are HazeReady, an operational haze advisory assistant for Singapore.

You do NOT decide. A deterministic policy engine has already resolved the band \
and looked up the governing decision and obligations from published guidance. \
Your job is to compose a clear, correctly-hedged explanation of that decision \
and to select which supplied sources to cite.

Hard rules:
- Use the GOVERNING_DECISION exactly as given. Never substitute a different one.
- Never state a PSI or PM2.5 number that does not appear in the supplied context.
- Never invent a threshold, and never say guidance permits something unless a \
supplied source says so explicitly.
- Use the published verb. "Minimise" is not "cancel". "Reduce" is not "avoid".
- If the context says guidance is silent, say so plainly and name the authority.

Reply with JSON only, matching this shape:
{"decision": "...", "reason_codes": [...], "obligations": ["..."], \
"rationale": "...", "citation_doc_ids": ["..."], "abstain_reason": null, \
"abstain_authority": ""}
"""

# The A5 arm asks the model to do the band comparison itself. This is the
# headline ablation: everything else is held constant.
SYSTEM_PROMPT_LLM_BANDS = """You are HazeReady, an operational haze advisory assistant for Singapore.

You must work out the governing band yourself from the reading supplied, using \
the band table in the retrieved sources, and then decide what the role should do.

Reply with JSON only, matching this shape:
{"decision": "...", "reason_codes": [...], "obligations": ["..."], \
"rationale": "...", "citation_doc_ids": ["..."], "abstain_reason": null, \
"abstain_authority": ""}

decision must be one of: proceed, proceed_with_precautions, restrict, suspend, abstain.
"""


@dataclass
class ArmConfig:
    """One ablation configuration. A4 is the proposed system."""

    arm: str = "A4"
    use_retrieval: bool = True
    use_dense: bool = True
    use_sparse: bool = True
    use_rerank: bool = False
    use_tools: bool = True
    deterministic_bands: bool = True
    use_skills: bool = True
    use_entailment_guardrail: bool = True

    def retrieval_mode(self) -> RetrievalMode:
        return RetrievalMode(
            use_dense=self.use_dense, use_sparse=self.use_sparse, use_rerank=self.use_rerank
        )


@dataclass
class OrchestratorDeps:
    air_quality_client: Any
    policy_matrix: Any
    retriever: Retriever
    skill_router: SkillRouter
    coverage_gaps: CoverageGaps
    llm: Any
    telemetry: Any = None


@dataclass
class _Trace:
    records: list[ToolCallRecord] = field(default_factory=list)
    hop: int = 0

    def add(
        self, tool: str, args: dict, result: Any, ms: int, ok: bool = True, error: str = ""
    ) -> None:
        self.hop += 1
        self.records.append(
            ToolCallRecord(
                hop=self.hop,
                tool=tool,
                arguments=args,
                result_summary=_summarise(result),
                latency_ms=ms,
                ok=ok,
                error=error,
            )
        )


def _summarise(result: Any) -> str:
    if isinstance(result, BandResult):
        return f"{result.value} {result.index.value} -> {result.band_label}"
    if isinstance(result, AirQualityReading):
        return (
            f"psi_24h={result.psi_24h} pm25_1h={result.pm25_1h} "
            f"region={result.region.value} source={result.source}"
        )
    if isinstance(result, Forecast):
        return (
            f"{result.psi_low}-{result.psi_high} "
            f"({result.band_low.value}..{result.band_high.value})"
        )
    if isinstance(result, ObligationSet):
        return (
            f"{result.role.value}/{result.band.value} -> {result.decision.value}, "
            f"{len(result.actions)} actions, {len(result.obligations)} obligations"
        )
    if isinstance(result, HotspotSummary):
        return f"{result.count} hotspots ({result.source})"
    if isinstance(result, list):
        return f"{len(result)} spans: " + ", ".join(
            getattr(s, "doc_id", "?") for s in result[:4]
        )
    if isinstance(result, Abstention):
        return f"abstain: {result.reason.value}"
    return str(result)[:160]


class Orchestrator:
    def __init__(self, deps: OrchestratorDeps, settings) -> None:
        self.d = deps
        self.s = settings
        self._last_llm_error = ""

    # -- public entry point -------------------------------------------------

    async def answer(
        self,
        question: str,
        role: Role | None = None,
        region: Region | None = None,
        arm: ArmConfig | None = None,
        fixture_client: Any = None,
        events: list | None = None,
    ) -> Advisory:
        arm = arm or ArmConfig()
        self._last_llm_error = ""
        client = fixture_client or self.d.air_quality_client
        started = time.perf_counter()
        trace = _Trace()
        query_id = str(uuid.uuid4())

        def emit(kind: str, payload: dict) -> None:
            if events is not None:
                events.append({"type": kind, **payload})

        # --- 1. Role routing -----------------------------------------------
        routed_by = "explicit"
        confidence = 1.0
        if role is None:
            skill, confidence = self.d.skill_router.route_deterministic(question)
            routed_by = "router"
            if skill is None or confidence < 0.5:
                skill, confidence = await self._route_with_llm(question, skill, confidence)
            role = skill.role if skill else Role.general_public
        skill = self.d.skill_router.by_role(role) if arm.use_skills else None
        emit("role", {"role": role.value, "confidence": confidence, "routed_by": routed_by})

        # --- 2. Early abstention on a known coverage gap --------------------
        gap = self.d.coverage_gaps.match(question, role)
        if gap is not None:
            abstention = self.d.coverage_gaps.to_abstention(gap)
            emit("abstain", {"reason": abstention.reason.value, "gap": gap["id"]})
            spans = (
                self.d.retriever.search(question, role=role, k=3, mode=arm.retrieval_mode())
                if arm.use_retrieval
                else []
            )
            return self._finalise_abstention(
                query_id,
                question,
                role,
                routed_by,
                confidence,
                abstention,
                spans,
                trace,
                started,
                arm,
            )

        # --- 3. Concurrent context gathering --------------------------------
        # Live reading, hotspots and retrieval are mutually independent.
        wants_forecast = self._is_forecast_question(question)

        async def _reading():
            t0 = time.perf_counter()
            r = await client.get_current_air_quality(region)
            trace.add(
                "get_current_air_quality",
                {"region": (region or Region.national).value},
                r,
                int((time.perf_counter() - t0) * 1000),
            )
            return r

        async def _forecast():
            if not wants_forecast:
                return None
            t0 = time.perf_counter()
            f = await client.get_air_quality_forecast(24, region)
            trace.add(
                "get_air_quality_forecast",
                {"horizon_hours": 24},
                f,
                int((time.perf_counter() - t0) * 1000),
            )
            return f

        async def _hotspots():
            t0 = time.perf_counter()
            h = await client.get_regional_hotspots(1)
            trace.add(
                "get_regional_hotspots",{"days": 1},h, int((time.perf_counter() - t0) * 1000)
            )
            return h

        if arm.use_tools:
            reading, forecast, hotspots = await asyncio.gather(
                _reading(), _forecast(), _hotspots()
            )
        else:
            reading, forecast, hotspots = None, None, None

        emit(
            "reading",
            {
                "psi_24h": getattr(reading, "psi_24h", None),
                "source": getattr(reading, "source", "none"),
            },
        )

        # --- 4. Deterministic band resolution -------------------------------
        index = self._governing_index(question, role, wants_forecast)
        band_result: BandResult | None = None
        governing_band: Band | None = None

        # A reading stated in the question is the situation the asker is asking
        # about, so it governs. The live reading is still reported alongside, so
        # a disagreement between the two is visible rather than hidden.
        stated = extract_stated_reading(question)
        stated_forecast = extract_stated_forecast(question)
        cohort = extract_cohort(question)

        # A forecast range quoted in the question is a 24-hour PSI range by
        # definition -- NEA publishes no PM2.5 forecast -- so it pins the index.
        if stated_forecast is not None:
            index = IndexKind.psi_24h
            forecast = Forecast(
                horizon_hours=24,
                psi_low=stated_forecast.low,
                psi_high=stated_forecast.high,
                band_low=resolve_psi_band(stated_forecast.low).band,
                band_high=resolve_psi_band(stated_forecast.high).band,
                straddles_boundary=(
                    resolve_psi_band(stated_forecast.low).band
                    != resolve_psi_band(stated_forecast.high).band
                ),
                issued_at=datetime.now(UTC),
                source="live",
                note=f'Forecast range quoted by the asker: "{stated_forecast.matched_text}".',
            )
            trace.add(
                "get_air_quality_forecast",
                {
                    "source": "stated_in_question",
                    "range": [stated_forecast.low, stated_forecast.high],
                },
                forecast,
                0,
            )
        elif stated is not None:
            index = stated.index

        # Index mismatch: a decision about a future window cannot be governed by
        # a current 1-hour PM2.5 value. Converting between the indices to answer
        # anyway is the category error the corpus warns about.
        if (
            wants_forecast
            and stated is not None
            and stated.index == IndexKind.pm25_1h
            and stated_forecast is None
        ):
            abstention = Abstention(
                reason=AbstainReason.no_governing_guidance,
                plain_language=(
                    "This is a decision about a future window, which NEA guidance "
                    "says is governed by the 24-hour PSI forecast. A current "
                    "1-hour PM2.5 reading cannot govern it, and converting between "
                    "the two indices to answer would be a category error."
                ),
                suggested_authority=(
                    "NEA (nea.gov.sg) for the 24-hour PSI forecast for the relevant period"
                ),
                evidence_doc_id="nea-psi-vs-pm25-purpose",
            )
            emit("abstain", {"reason": abstention.reason.value, "gap": "index_mismatch"})
            spans = (
                self.d.retriever.search(question, role=role, k=3, mode=arm.retrieval_mode())
                if arm.use_retrieval
                else []
            )
            return self._finalise_abstention(
                query_id,
                question,
                role,
                routed_by,
                confidence,
                abstention,
                spans,
                trace,
                started,
                arm,
            )

        if arm.use_tools and (reading is not None or stated is not None):
            if stated is not None:
                value: int | None = stated.value
            else:
                value = reading.psi_24h if index == IndexKind.psi_24h else reading.pm25_1h
            if value is not None and arm.deterministic_bands:
                t0 = time.perf_counter()
                band_result = resolve_psi_band(float(value), index.value)
                trace.add(
                    "resolve_psi_band",
                    {
                        "value": value,
                        "index": index.value,
                        "value_source": "stated_in_question" if stated else "live_reading",
                    },
                    band_result,
                    int((time.perf_counter() - t0) * 1000),
                )
                governing_band = band_result.band
                emit("band", {"value": value, "band": band_result.band_label})

            # A forecast decision is planned against the worst band the range
            # reaches. Only meaningful when the current band is on the same
            # index; mixing a PM2.5 band with a PSI forecast band is undefined.
            if forecast is not None and arm.deterministic_bands and index == IndexKind.psi_24h:
                if governing_band is not None:
                    governing_band = worse_band(governing_band, forecast.band_high)
                else:
                    governing_band = forecast.band_high
                if stated_forecast is not None:
                    # The question is about the forecast window, so the forecast
                    # governs outright rather than being merged with "now".
                    governing_band = worse_band(forecast.band_low, forecast.band_high)
                    band_result = resolve_psi_band(float(stated_forecast.high))

        # --- 5. Policy lookup ----------------------------------------------
        obligation_set: ObligationSet | None = None
        if governing_band is not None:
            t0 = time.perf_counter()
            obligation_set = self.d.policy_matrix.lookup(role, governing_band, index)
            trace.add(
                "lookup_role_obligations",
                {"role": role.value, "band": governing_band.value, "index": index.value},
                obligation_set,
                int((time.perf_counter() - t0) * 1000),
            )
            # Where the asker names a cohort and the guidance differentiates,
            # the named cohort governs rather than the role default.
            if cohort is not None and obligation_set.found:
                variant = next(
                    (
                        v
                        for v in obligation_set.cohort_variants
                        if v.cohort in (cohort, "susceptible")
                        and cohort != obligation_set.default_cohort
                    ),
                    None,
                )
                if variant is not None:
                    obligation_set = obligation_set.model_copy(
                        update={
                            "decision": variant.decision,
                            "reason_codes": obligation_set.reason_codes
                            + [f"cohort_{variant.cohort}"],
                        }
                    )
                    trace.add(
                        "apply_cohort_variant", {"cohort": variant.cohort}, obligation_set, 0
                    )
            emit(
                "obligations",
                {
                    "decision": obligation_set.decision.value,
                    "count": len(obligation_set.actions),
                },
            )

        # --- 6. Retrieval ---------------------------------------------------
        spans: list[RetrievedSpan] = []
        if arm.use_retrieval:
            t0 = time.perf_counter()
            spans = self.d.retriever.search(
                question,
                role=role,
                band_token=governing_band.value if governing_band else None,
                index=index,
                k=self.s.final_top_k,
                mode=arm.retrieval_mode(),
                bm25_top_k=self.s.bm25_top_k,
                dense_top_k=self.s.dense_top_k,
                rrf_k=self.s.rrf_k,
                fusion_top_k=self.s.fusion_top_k,
            )
            trace.add(
                "search_advisories",
                {"query": question[:80], "k": self.s.final_top_k},
                spans,
                int((time.perf_counter() - t0) * 1000),
            )
            emit(
                "retrieval",
                {"count": len(spans), "top_score": round(spans[0].score, 5) if spans else 0.0},
            )

        top_score = spans[0].score if spans else 0.0

        # --- 7. Composition by the language model ---------------------------
        matrix_decision = (
            obligation_set.decision
            if obligation_set and obligation_set.found
            else Decision.abstain
        )
        draft, usage = await self._compose(
            question,
            role,
            skill,
            band_result,
            obligation_set,
            spans,
            reading,
            forecast,
            arm,
            stated=stated,
        )

        # --- 8. Guardrail chain ---------------------------------------------
        sourced_numbers = self._sourced_numbers(question, reading, band_result, forecast, spans)
        if stated is not None:
            sourced_numbers.add(str(stated.value))
        if stated_forecast is not None:
            sourced_numbers.update({str(stated_forecast.low), str(stated_forecast.high)})
        # Numerals inside policy-matrix statements are grounded by construction:
        # each carries a source_quote whose character span was resolved against
        # the cited document at load time. Requiring them to also appear in a
        # top-k retrieval punished correct, cited content and caused spurious
        # abstentions (e.g. "30 minutes of outdoor activity daily").
        if obligation_set is not None and obligation_set.found:
            import re as _re

            for st in list(obligation_set.actions) + list(obligation_set.obligations):
                sourced_numbers.update(_re.findall(r"\b\d{1,4}\b", st.text))
                sourced_numbers.update(_re.findall(r"\b\d{1,4}\b", st.source_quote))
        grounded_claims = set()
        if obligation_set is not None and obligation_set.found:
            grounded_claims = {
                s.text for s in list(obligation_set.actions) + list(obligation_set.obligations)
            }
        outcome = guardrails.run_chain(
            draft,
            spans,
            sourced_numbers,
            matrix_decision,
            attempt=0,
            grounded_claims=grounded_claims,
        )
        if outcome.needs_regeneration:
            emit("guardrail", {"action": "regenerate"})
            draft2, usage2 = await self._compose(
                question,
                role,
                skill,
                band_result,
                obligation_set,
                spans,
                reading,
                forecast,
                arm,
                retry=True,
                stated=stated,
            )
            usage = (usage[0] + usage2[0], usage[1] + usage2[1])
            outcome = guardrails.run_chain(
                draft2,
                spans,
                sourced_numbers,
                matrix_decision,
                attempt=1,
                grounded_claims=grounded_claims,
            )

        if not arm.use_entailment_guardrail:
            # A7 removes the entailment stage. Restore the stripped claims so the
            # arm measures what the guardrail was catching.
            restored = list(outcome.draft.obligations) + outcome.stripped_claims
            outcome.draft = outcome.draft.model_copy(update={"obligations": restored})
            outcome.events = [e for e in outcome.events if e.guardrail != "citation_entailment"]

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if outcome.abstention is not None:
            return self._finalise_abstention(
                query_id,
                question,
                role,
                routed_by,
                confidence,
                outcome.abstention,
                spans,
                trace,
                started,
                arm,
                guardrail_events=outcome.events,
            )

        advisory = Advisory(
            query_id=query_id,
            question=question,
            role=role,
            role_routed_by=routed_by,
            router_confidence=confidence,
            decision=outcome.draft.decision,
            decision_label=DECISION_LABELS[outcome.draft.decision],
            reason_codes=(
                obligation_set.reason_codes if obligation_set else outcome.draft.reason_codes
            ),
            obligations=outcome.draft.obligations,
            rationale=outcome.draft.rationale,
            citations=self._build_citations(
                outcome.draft.citation_doc_ids, spans, obligation_set
            ),
            band_result=band_result,
            reading=reading,
            forecast=forecast,
            hotspots=hotspots,
            conflicts=outcome.conflicts,
            trajectory=trace.records,
            guardrail_events=outcome.events,
            disclaimer=guardrails.DISCLAIMER,
            latency_ms=elapsed_ms,
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            model=getattr(self.d.llm, "model", ""),
            provider=getattr(self.d.llm, "name", ""),
            arm=arm.arm,
            top_retrieval_score=top_score,
            llm_error=self._last_llm_error,
        )
        if self.d.telemetry is not None:
            self.d.telemetry.record_advisory(advisory)
        return advisory

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _is_forecast_question(question: str) -> bool:
        q = question.lower()
        return any(
            t in q
            for t in (
                "tomorrow",
                "next week",
                "later",
                "tonight",
                "this evening",
                "forecast",
                "next day",
                "plan",
                "planning",
                "scheduled",
                "upcoming",
                "friday",
                "monday",
                "weekend",
                "in two days",
                "day after",
            )
        )

    def _governing_index(self, question: str, role: Role, wants_forecast: bool) -> IndexKind:
        """The 24-hour PSI governs planned and institutional decisions. The
        1-hour PM2.5 governs an immediate personal go/no-go. Choosing the wrong
        one is a category error even when both readings are correct."""
        if wants_forecast:
            return IndexKind.psi_24h
        q = question.lower()
        immediate = any(
            t in q for t in ("right now", "at this moment", "now", "next few minutes")
        )
        if role == Role.general_public and immediate:
            return IndexKind.pm25_1h
        return self.d.policy_matrix.governing_index(role)

    async def _route_with_llm(self, question: str, fallback, fallback_conf: float):
        system, user = self.d.skill_router.route_prompt(question)
        resp = await self.d.llm.complete(
            system, user, temperature=0.0, max_tokens=120, schema=ROLE_ROUTE_SCHEMA
        )
        if not resp.ok:
            return fallback, fallback_conf
        try:
            data = json.loads(_extract_json(resp.text))
            skill = self.d.skill_router.load(data["skill"])
            if skill is not None:
                return skill, _as_float(data.get("confidence"), 0.6)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            pass
        return fallback, fallback_conf

    @staticmethod
    def _sourced_numbers(
        question, reading, band_result, forecast, spans: list[RetrievedSpan]
    ) -> set[str]:
        """Numbers the draft is permitted to state.

        A numeral is sourced if it came from a tool output, appears in a
        retrieved span, or was written by the asker in the question itself.

        The last case matters more than it looks. The guardrail exists to catch
        an *invented* threshold, but its regex sees every 2-4 digit numeral —
        including the ones the model restates back from the question ("outdoor
        play in 20 minutes", "a class of 24"). Treating those as unsourced made
        the system abstain on well-covered questions purely because it repeated
        the user's own words. A number the asker supplied is traceable to the
        asker; it is not a fabricated reading.
        """
        import re

        out: set[str] = set(re.findall(r"\b\d{1,4}\b", question or ""))
        if reading is not None:
            for v in (reading.psi_24h, reading.pm25_1h):
                if v is not None:
                    out.add(str(v))
        if band_result is not None:
            out.add(str(int(band_result.value)))
            out.add(str(band_result.lower_bound))
            if band_result.upper_bound is not None:
                out.add(str(band_result.upper_bound))
        if forecast is not None:
            out.update({str(forecast.psi_low), str(forecast.psi_high)})
        for s in spans:
            out.update(re.findall(r"\b\d{1,4}\b", s.text))
        return out

    def _build_citations(
        self, doc_ids: list[str], spans: list[RetrievedSpan], obligation_set
    ) -> list[Citation]:
        by_doc = {s.doc_id: s for s in spans}
        chosen: list[str] = []
        # Policy-matrix sources always cite, because they are what the decision
        # actually rests on.
        if obligation_set is not None:
            for st in list(obligation_set.actions) + list(obligation_set.obligations):
                if st.source_doc_id not in chosen:
                    chosen.append(st.source_doc_id)
        for d in doc_ids:
            if d not in chosen and d in by_doc:
                chosen.append(d)

        citations: list[Citation] = []
        matrix_spans = {}
        if obligation_set is not None:
            for st in list(obligation_set.actions) + list(obligation_set.obligations):
                matrix_spans.setdefault(st.source_doc_id, st)

        for i, doc_id in enumerate(chosen, start=1):
            span = by_doc.get(doc_id)
            st = matrix_spans.get(doc_id)
            if span is not None:
                citations.append(
                    Citation(
                        marker=i,
                        doc_id=doc_id,
                        chunk_id=span.chunk_id,
                        title=span.title,
                        issuing_agency=span.issuing_agency,
                        source_url=span.source_url,
                        retrieved_at=span.retrieved_at,
                        char_span=st.char_span if st and st.char_span else span.char_span,
                        authority_tier=span.authority_tier,
                        quote=st.source_quote if st else span.text[:240],
                    )
                )
            elif st is not None:
                meta = self._doc_meta(doc_id)
                if meta is None:
                    continue
                citations.append(
                    Citation(
                        marker=i,
                        doc_id=doc_id,
                        chunk_id=f"{doc_id}::000",
                        title=meta["title"],
                        issuing_agency=meta["issuing_agency"],
                        source_url=meta["source_url"],
                        retrieved_at=meta["retrieved_at"],
                        char_span=st.char_span or (0, 0),
                        authority_tier=meta["authority_tier"],
                        quote=st.source_quote,
                    )
                )
        return citations

    def _doc_meta(self, doc_id: str) -> dict | None:
        doc = self.d.retriever.store.docs_by_id.get(doc_id)
        if doc is None:
            return None
        return {
            "title": doc.title,
            "issuing_agency": doc.issuing_agency,
            "source_url": doc.source_url,
            "retrieved_at": doc.retrieved_at,
            "authority_tier": doc.authority_tier,
        }

    def _finalise_abstention(
        self,
        query_id,
        question,
        role,
        routed_by,
        confidence,
        abstention,
        spans,
        trace,
        started,
        arm,
        guardrail_events=None,
    ) -> Advisory:
        advisory = Advisory(
            query_id=query_id,
            question=question,
            role=role,
            role_routed_by=routed_by,
            router_confidence=confidence,
            decision=Decision.abstain,
            decision_label=DECISION_LABELS[Decision.abstain],
            reason_codes=[abstention.reason.value],
            rationale=abstention.plain_language,
            abstention=abstention,
            citations=self._build_citations([], spans, None),
            trajectory=trace.records,
            guardrail_events=guardrail_events or [],
            disclaimer=guardrails.DISCLAIMER,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=getattr(self.d.llm, "model", ""),
            provider=getattr(self.d.llm, "name", ""),
            arm=arm.arm,
            top_retrieval_score=spans[0].score if spans else 0.0,
            llm_error=self._last_llm_error,
        )
        if self.d.telemetry is not None:
            self.d.telemetry.record_advisory(advisory)
        return advisory

    # -- composition --------------------------------------------------------

    async def _compose(
        self,
        question,
        role,
        skill,
        band_result,
        obligation_set,
        spans,
        reading,
        forecast,
        arm: ArmConfig,
        retry: bool = False,
        stated=None,
    ) -> tuple[DraftAdvisory, tuple[int, int]]:
        system = SYSTEM_PROMPT if arm.deterministic_bands else SYSTEM_PROMPT_LLM_BANDS
        if arm.use_skills and skill is not None:
            system = f"{system}\n\n--- Governing skill: {skill.name} ---\n{skill.body}"
        if retry:
            system += (
                "\n\nYour previous draft failed a guardrail. Restate only what the "
                "supplied sources support. Do not introduce any number that is not "
                "in the context."
            )

        user = self._build_context(
            question,
            role,
            band_result,
            obligation_set,
            spans,
            reading,
            forecast,
            arm,
            stated,
        )
        resp = await self.d.llm.complete(
            system,
            user,
            temperature=self.s.llm_temperature,
            max_tokens=self.s.llm_max_tokens,
            schema=DRAFT_ADVISORY_SCHEMA,
        )
        usage = (resp.prompt_tokens, resp.completion_tokens)

        if not resp.ok:
            # Upstream failure. Fall back to the deterministic decision rather
            # than emitting nothing, and propagate the reason so the caller can
            # surface it instead of silently serving a degraded answer.
            self._last_llm_error = resp.error
            return self._deterministic_draft(obligation_set), usage

        try:
            data = json.loads(_extract_json(resp.text))
            draft = DraftAdvisory.model_validate(data)
        except Exception as exc:
            self._last_llm_error = f"unparseable model response: {type(exc).__name__}"
            return self._deterministic_draft(obligation_set), usage

        self._last_llm_error = ""

        # In deterministic-band arms the matrix decision is authoritative. The
        # model's `decision` field is retained only so the guardrail can detect
        # and report disagreement.
        return draft, usage

    @staticmethod
    def _deterministic_draft(obligation_set) -> DraftAdvisory:
        if obligation_set is None or not obligation_set.found:
            return DraftAdvisory(
                decision=Decision.abstain,
                reason_codes=["no_matrix_row"],
                rationale="No governing published guidance covers this combination.",
                abstain_reason=AbstainReason.no_governing_guidance,
                abstain_authority="NEA (nea.gov.sg)",
            )
        return DraftAdvisory(
            decision=obligation_set.decision,
            reason_codes=obligation_set.reason_codes,
            obligations=[a.text for a in obligation_set.actions]
            + [o.text for o in obligation_set.obligations],
            rationale=(
                "Composed from the deterministic policy matrix; the language model "
                "was unavailable or returned an unusable response."
            ),
            citation_doc_ids=[a.source_doc_id for a in obligation_set.actions],
        )

    def _build_context(
        self,
        question,
        role,
        band_result,
        obligation_set,
        spans,
        reading,
        forecast,
        arm,
        stated=None,
    ) -> str:
        lines = [f"QUESTION: {question}", f"ROLE: {role.value}"]

        if stated is not None:
            lines.append(
                f"STATED_BY_ASKER: {stated.value} on {stated.index.value} "
                f'(from "{stated.matched_text}"). This is the situation the asker '
                "is asking about and it governs the answer."
            )
        if reading is not None:
            lines.append(
                f"READING: region={reading.region.value} psi_24h={reading.psi_24h} "
                f"pm25_1h={reading.pm25_1h} taken_at={reading.reading_timestamp.isoformat()} "
                f"age_seconds={reading.staleness_seconds} source={reading.source}"
            )
        if forecast is not None:
            lines.append(
                f"FORECAST_24H: psi range {forecast.psi_low}-{forecast.psi_high} "
                f"(bands {forecast.band_low.value} to {forecast.band_high.value}), "
                f"straddles_boundary={forecast.straddles_boundary}. {forecast.note}"
            )

        if arm.deterministic_bands and band_result is not None:
            lines.append(
                f"RESOLVED_BAND: {band_result.band_label} "
                f"(reading {int(band_result.value)} on {band_result.index.value}, "
                f"band covers {band_result.lower_bound}-"
                f"{band_result.upper_bound if band_result.upper_bound is not None else 'above'})"
            )
            if band_result.boundary_note:
                lines.append(f"BOUNDARY_NOTE: {band_result.boundary_note}")

        if obligation_set is not None and obligation_set.found:
            lines.append(f"GOVERNING_DECISION: {obligation_set.decision.value}")
            lines.append(f"REASON_CODES: {', '.join(obligation_set.reason_codes)}")
            lines.append("OBLIGATIONS_START")
            for a in obligation_set.actions:
                lines.append(f"- {a.text}")
            for o in obligation_set.obligations:
                lines.append(f"- {o.text}")
            lines.append("OBLIGATIONS_END")
            if obligation_set.cohort_variants:
                lines.append("COHORT_VARIANTS:")
                for v in obligation_set.cohort_variants:
                    lines.append(f"- {v.cohort}: {v.decision.value} — {v.note}")
            lines.append(f"DEFAULT_COHORT: {obligation_set.default_cohort}")
        elif arm.deterministic_bands:
            lines.append("GOVERNING_DECISION: abstain")
            lines.append("ABSTAIN_REASON: no_governing_guidance")
            lines.append("ABSTAIN_AUTHORITY: NEA (nea.gov.sg)")

        if spans:
            lines.append("RETRIEVED_SOURCES:")
            for s in spans:
                lines.append(
                    f"[{s.doc_id}] ({s.issuing_agency}, tier={s.authority_tier.value})\n{s.text}"
                )
            lines.append(f"CITABLE_DOC_IDS: {', '.join(s.doc_id for s in spans)}")

        return "\n".join(lines)


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_json(text: str) -> str:
    """Models wrap JSON in prose or fences despite instructions. Extract the
    outermost object rather than failing the item."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text
