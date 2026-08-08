"""Composition root. Builds the object graph once and hands it out."""

from __future__ import annotations

from functools import lru_cache

from app.agent.orchestrator import Orchestrator, OrchestratorDeps
from app.agent.router import SkillRouter
from app.agent.tools.registry import CoverageGaps, build_registry
from app.config import Settings, get_settings
from app.data_sources.air_quality import AirQualityClient
from app.llm.providers import make_provider
from app.policy import load_policy_matrix
from app.rag.retriever import Retriever
from app.telemetry.store import TelemetryStore


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.policy_matrix = load_policy_matrix(
            settings.policy_matrix_path, settings.corpus_dir
        )
        self.retriever = Retriever(
            settings.corpus_dir,
            settings.index_dir,
            settings.embedding_model,
            settings.reranker_model,
        )
        self.skill_router = SkillRouter(settings.skills_dir)
        self.coverage_gaps = CoverageGaps(settings.coverage_gaps_path)
        self.air_quality = AirQualityClient(
            settings.datagov_psi_url,
            settings.datagov_pm25_url,
            settings.fixtures_dir,
            offline=settings.offline_mode,
            timeout_s=settings.upstream_timeout_s,
            cache_ttl_s=settings.upstream_cache_ttl_s,
        )
        self.llm = make_provider(
            settings.llm_provider,
            settings.resolved_llm_model,
            settings.llm_api_key,
            settings.ollama_base_url,
            settings.llm_timeout_s,
        )
        self.telemetry = TelemetryStore(settings.telemetry_db_path)
        self.tools = build_registry(
            air_quality_client=self.air_quality,
            policy_matrix=self.policy_matrix,
            retriever=self.retriever,
            coverage_gaps=self.coverage_gaps,
        )
        self.orchestrator = Orchestrator(
            OrchestratorDeps(
                air_quality_client=self.air_quality,
                policy_matrix=self.policy_matrix,
                retriever=self.retriever,
                skill_router=self.skill_router,
                coverage_gaps=self.coverage_gaps,
                llm=self.llm,
                telemetry=self.telemetry,
            ),
            settings,
        )


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container(get_settings())
