"""FastAPI application: REST + SSE, Prometheus metrics, static SPA hosting."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.deps import get_container
from app.models import Advisory, Region, Role

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the container eagerly so the first request does not pay for model
    # loading, and so a broken index fails at startup rather than mid-query.
    get_container()
    yield


app = FastAPI(
    title="HazeReady",
    description=(
        "Role-aware, forecast-aware, strictly-grounded haze advisory. "
        "Decision-support prototype; official advisories at nea.gov.sg govern."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    role: Role | None = None
    region: Region | None = None


class FeedbackRequest(BaseModel):
    query_id: str
    rating: str = Field(pattern="^(up|down)$")
    reason: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Advisory
# ---------------------------------------------------------------------------


@app.post("/api/ask", response_model=Advisory)
async def ask(req: AskRequest) -> Advisory:
    c = get_container()
    return await c.orchestrator.answer(req.question, role=req.role, region=req.region)


@app.get("/api/ask/stream")
async def ask_stream(
    request: Request,
    question: str = Query(min_length=1, max_length=2000),
    role: Role | None = None,
    region: Region | None = None,
):
    """Stream tool-call events as they happen, then the final advisory.

    The reasoning trace is the most informative part of the interface: it shows
    that the band came from a deterministic function rather than from the model.
    """
    c = get_container()

    async def generator():
        events: list[dict] = []
        task = asyncio.create_task(
            c.orchestrator.answer(question, role=role, region=region, events=events)
        )
        emitted = 0
        while not task.done():
            while emitted < len(events):
                if await request.is_disconnected():
                    task.cancel()
                    return
                yield {"event": "step", "data": json.dumps(events[emitted])}
                emitted += 1
            await asyncio.sleep(0.04)

        while emitted < len(events):
            yield {"event": "step", "data": json.dumps(events[emitted])}
            emitted += 1

        try:
            advisory = task.result()
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"detail": str(exc)})}
            return
        yield {"event": "advisory", "data": advisory.model_dump_json()}

    return EventSourceResponse(generator())


# ---------------------------------------------------------------------------
# Live conditions
# ---------------------------------------------------------------------------


@app.get("/api/conditions")
async def conditions(region: Region | None = None):
    c = get_container()
    reading, forecast, hotspots = await asyncio.gather(
        c.air_quality.get_current_air_quality(region),
        c.air_quality.get_air_quality_forecast(24, region),
        c.air_quality.get_regional_hotspots(1),
    )
    from app.agent.tools.bands import resolve_psi_band

    all_regions = {}
    try:
        for r in (Region.north, Region.south, Region.east, Region.west, Region.central):
            rd = await c.air_quality.get_current_air_quality(r)
            all_regions[r.value] = {
                "psi_24h": rd.psi_24h,
                "pm25_1h": rd.pm25_1h,
                "band": resolve_psi_band(float(rd.psi_24h or 0)).band_label,
            }
    except Exception:
        pass

    band = resolve_psi_band(float(reading.psi_24h or 0))
    pm_band = resolve_psi_band(float(reading.pm25_1h or 0), "pm25_1h")
    return {
        "reading": reading.model_dump(mode="json"),
        "band": band.model_dump(mode="json"),
        "pm25_band": pm_band.model_dump(mode="json"),
        "forecast": forecast.model_dump(mode="json"),
        "hotspots": hotspots.model_dump(mode="json"),
        "regions": all_regions,
        "offline_mode": settings.offline_mode,
        "is_stale": reading.is_stale,
    }


@app.get("/api/psi/history")
async def psi_history(hours: int = Query(default=24, ge=6, le=72)):
    """Hourly 24-hour PSI per region, for the map's trend lines."""
    c = get_container()
    return await c.air_quality.get_psi_history(hours)


# ---------------------------------------------------------------------------
# Source documents (for the citation side panel)
# ---------------------------------------------------------------------------


@app.get("/api/roles")
async def roles():
    c = get_container()
    return [
        {
            "role": s.role.value,
            "skill": s.name,
            "description": s.description,
            "governing_agencies": s.governing_agencies,
            "primary_index": s.primary_index.value,
            "known_gaps": s.known_gaps,
        }
        for s in c.skill_router.skills.values()
    ]


@app.get("/api/examples")
async def examples(role: Role = Role.general_public):
    """Role-appropriate example questions for the input chips."""
    by_role = {
        "preschool": [
            "24-hr PSI just hit 101 in the north. My K1 class has outdoor play in 20 minutes — do I cancel?",
            "Forecast for tomorrow is 90 to 130 and we have an excursion booked. Parents need to know tonight.",
            "We swapped outdoor play for an indoor dance-and-run session at PSI 150. Is that enough?",
            "What size air purifier do I need for a 40 square metre classroom?",
        ],
        "school": [
            "24-hr PSI is 165. Does the Sec 3 cross-country training run at 4pm?",
            "We moved PE indoors to the hall and kept the circuit training. Is that compliant at PSI 150?",
            "At what PSI do schools close?",
            "PSI is 88 now but forecast 120 to 150 for the 4pm training.",
        ],
        "eldercare": [
            "PSI 165 — should the day centre's morning garden walk run?",
            "A client has a hospital appointment at PSI 230. Does the advisory stop that?",
            "At what PSI must a senior care centre suspend its day programme?",
            "Forecast 260 to 290 tomorrow. Outing booked.",
        ],
        "worksite": [
            "PSI is 210. Can my construction crew keep working outdoors?",
            "PSI 150 and one of my workers is pregnant. Prolonged outdoor work?",
            "PSI 420 with prolonged outdoor work that cannot be moved. What respiratory protection?",
            "What work rest cycle should we use at PSI 180?",
        ],
        "event": [
            "PSI forecast is 180 to 220 for tomorrow's 10km road race. Do we proceed?",
            "PSI 230 and our event is a seated outdoor film screening. Proceed?",
            "Our crew still needs to build the stage outdoors at PSI 230.",
            "Do I have to give refunds if I cancel the race?",
        ],
        "general_public": [
            "Should I go for a run right now?",
            "24-hr PSI is 150 and my father is 78 with COPD. Can he do his morning walk?",
            "PSI is 260 — I just need to walk to the MRT, five minutes. Restricted?",
            "There are 400 hotspots in Sumatra. Should I cancel my outdoor plans?",
        ],
    }
    return by_role.get(role.value, by_role["general_public"])


@app.get("/api/doc/{doc_id}")
async def get_doc(doc_id: str):
    c = get_container()
    doc = c.retriever.store.docs_by_id.get(doc_id)
    if doc is None:
        raise HTTPException(404, f"unknown doc_id {doc_id!r}")
    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "issuing_agency": doc.issuing_agency,
        "source_url": doc.source_url,
        "retrieved_at": doc.retrieved_at,
        "licence": doc.licence,
        "provenance": doc.provenance,
        "verified_against_source": doc.verified_against_source,
        "authority_tier": doc.authority_tier,
        "robots_txt_permits": doc.robots_txt_permits,
        "body": doc.body,
    }


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    c = get_container()
    c.telemetry.record_feedback(req.query_id, req.rating, req.reason)
    return {"ok": True}


@app.get("/api/metrics/summary")
async def metrics_summary():
    c = get_container()
    summary = c.telemetry.summary(settings.out_of_corpus_score_threshold)
    summary["upstream_live"] = {
        "data.gov.sg/psi": c.air_quality.last_success.get("data.gov.sg/psi"),
        "data.gov.sg/pm25": c.air_quality.last_success.get("data.gov.sg/pm25"),
        "errors": c.air_quality.last_error,
    }
    summary["config"] = {
        "provider": settings.llm_provider,
        "model": settings.resolved_llm_model,
        "offline_mode": settings.offline_mode,
        "out_of_corpus_threshold": settings.out_of_corpus_score_threshold,
        "cost_per_1m_input_usd": settings.llm_cost_per_1m_input_usd,
        "cost_per_1m_output_usd": settings.llm_cost_per_1m_output_usd,
    }
    return summary


@app.get("/api/metrics/events")
async def metrics_events(limit: int = 50, kind: str | None = None):
    c = get_container()
    return c.telemetry.recent_events(limit=limit, kind=kind)


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus text exposition. This is the integration point for real
    observability infrastructure, which is deliberately not implemented here."""
    c = get_container()
    return c.telemetry.prometheus(
        settings.llm_cost_per_1m_input_usd, settings.llm_cost_per_1m_output_usd
    )


@app.get("/api/health")
async def health():
    c = get_container()
    return {
        "status": "ok",
        "corpus_documents": len(c.retriever.store.docs_by_id),
        "chunks": len(c.retriever.store),
        "policy_matrix_rows": len(c.policy_matrix.rows),
        "skills": list(c.skill_router.skills),
        "coverage_gaps": len(c.coverage_gaps.gaps),
        "provider": settings.llm_provider,
        "model": settings.resolved_llm_model,
        "offline_mode": settings.offline_mode,
    }


# ---------------------------------------------------------------------------
# Evaluation report
# ---------------------------------------------------------------------------


@app.get("/report/eval_report.html", response_class=HTMLResponse)
async def eval_report_file():
    path = settings.reports_dir / "eval_report.html"
    if not path.exists():
        raise HTTPException(
            404, "reports/eval_report.html not built. Run: make eval"
        )
    return FileResponse(path, media_type="text/html")


# ---------------------------------------------------------------------------
# Static SPA
# ---------------------------------------------------------------------------

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def spa(full_path: str):
        return FileResponse(WEB_DIST / "index.html")
else:

    @app.get("/", response_class=HTMLResponse)
    async def no_ui():
        return HTMLResponse(
            "<h1>HazeReady API</h1>"
            "<p>The frontend bundle is not built. Run <code>make web</code>, "
            "or use the API directly at <a href='/docs'>/docs</a>.</p>",
            status_code=200,
        )
