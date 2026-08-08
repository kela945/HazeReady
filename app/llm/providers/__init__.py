"""Provider implementations and the factory that selects one."""

from __future__ import annotations

from app.llm.protocol import LLMProvider
from app.llm.providers.anthropic_provider import AnthropicProvider
from app.llm.providers.http_providers import (
    GoogleProvider,
    GroqProvider,
    OllamaProvider,
    OpenRouterProvider,
)
from app.llm.providers.stub import StubProvider

__all__ = [
    "AnthropicProvider",
    "GoogleProvider",
    "GroqProvider",
    "OllamaProvider",
    "OpenRouterProvider",
    "StubProvider",
    "make_provider",
]


def make_provider(
    provider: str,
    model: str,
    api_key: str = "",
    ollama_base_url: str = "http://localhost:11434",
    timeout_s: float = 90.0,
) -> LLMProvider:
    if provider == "stub":
        return StubProvider(model=model)
    if provider == "anthropic":
        return AnthropicProvider(model=model, api_key=api_key, timeout_s=timeout_s)
    if provider == "openrouter":
        return OpenRouterProvider(model=model, api_key=api_key, timeout_s=timeout_s)
    if provider == "google":
        return GoogleProvider(model=model, api_key=api_key, timeout_s=timeout_s)
    if provider == "groq":
        return GroqProvider(model=model, api_key=api_key, timeout_s=timeout_s)
    if provider == "ollama":
        return OllamaProvider(model=model, base_url=ollama_base_url, timeout_s=timeout_s)
    raise ValueError(f"unknown provider {provider!r}")
