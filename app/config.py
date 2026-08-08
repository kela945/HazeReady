"""Central configuration. Every environment variable the system reads is
declared here, so there is exactly one place to look."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Paths -------------------------------------------------------------
    repo_root: Path = REPO_ROOT
    corpus_dir: Path = REPO_ROOT / "data" / "corpus"
    fixtures_dir: Path = REPO_ROOT / "data" / "fixtures"
    index_dir: Path = REPO_ROOT / "data" / "index"
    policy_matrix_path: Path = REPO_ROOT / "data" / "policy_matrix.yaml"
    coverage_gaps_path: Path = REPO_ROOT / "data" / "coverage_gaps.yaml"
    manifest_path: Path = REPO_ROOT / "data" / "manifest.yaml"
    skills_dir: Path = REPO_ROOT / "skills"
    reports_dir: Path = REPO_ROOT / "reports"
    telemetry_db_path: Path = REPO_ROOT / "data" / "telemetry.db"

    # --- Operating mode ----------------------------------------------------
    # OFFLINE_MODE serves committed fixtures instead of calling live upstreams.
    # It is what makes the demo and the evaluation reproducible without network.
    offline_mode: bool = Field(default=False, alias="OFFLINE_MODE")

    # --- LLM ---------------------------------------------------------------
    # `stub` is a deterministic non-LLM provider used by the test suite and by
    # anyone running the system without an API key. It is NOT a language model
    # and evaluation results produced under it are not evidence about model
    # behaviour; the runner labels them accordingly.
    llm_provider: Literal["stub", "anthropic", "openrouter", "google", "groq", "ollama"] = (
        Field(default="stub", alias="LLM_PROVIDER")
    )
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=1400, alias="LLM_MAX_TOKENS")
    llm_timeout_s: float = Field(default=90.0, alias="LLM_TIMEOUT_S")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    # Per-1M-token published rates, used for the cost projection in the report.
    # Set these to the rate for the model actually used; defaults are 0 so an
    # unconfigured run reports zero cost rather than a fabricated number.
    llm_cost_per_1m_input_usd: float = Field(default=0.0, alias="LLM_COST_IN")
    llm_cost_per_1m_output_usd: float = Field(default=0.0, alias="LLM_COST_OUT")

    # --- Retrieval ---------------------------------------------------------
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")
    reranker_model: str = Field(default="BAAI/bge-reranker-base", alias="RERANKER_MODEL")
    chunk_target_tokens: int = 400
    chunk_overlap_tokens: int = 80
    bm25_top_k: int = 20
    dense_top_k: int = 20
    rrf_k: int = 60
    fusion_top_k: int = 10
    final_top_k: int = 5
    # Below this fused score the query is treated as out-of-corpus. This is the
    # drift signal surfaced on the monitoring dashboard.
    out_of_corpus_score_threshold: float = Field(default=0.012, alias="OUT_OF_CORPUS_THRESHOLD")

    # --- Agent -------------------------------------------------------------
    max_tool_hops: int = 6

    # --- Upstreams ---------------------------------------------------------
    datagov_psi_url: str = "https://api.data.gov.sg/v1/environment/psi"
    datagov_pm25_url: str = "https://api.data.gov.sg/v1/environment/pm25"
    firms_api_key: str = Field(default="", alias="FIRMS_API_KEY")
    upstream_timeout_s: float = 12.0
    upstream_cache_ttl_s: int = Field(default=300, alias="UPSTREAM_CACHE_TTL_S")

    @property
    def resolved_llm_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        return {
            "stub": "stub-deterministic",
            "anthropic": "claude-haiku-4-5",
            "openrouter": "google/gemini-2.0-flash-001",
            "google": "gemini-2.0-flash",
            "groq": "llama-3.3-70b-versatile",
            "ollama": "qwen3:8b",
        }[self.llm_provider]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
