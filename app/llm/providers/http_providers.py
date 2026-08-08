"""HTTP providers: OpenRouter, Google AI Studio, Groq, Ollama.

Three of the four speak the OpenAI chat-completions shape, so they share a base
class. Google's Generative Language API does not, and is implemented separately
rather than being forced through a compatibility shim.

All four return errors as `LLMResponse(error=...)` rather than raising, so one
failed call in an ablation arm degrades that item instead of aborting the run.
"""

from __future__ import annotations

import httpx

from app.llm.protocol import LLMResponse


class _OpenAIShapeProvider:
    name = "openai-shape"
    base_url = ""

    def __init__(self, model: str, api_key: str, timeout_s: float = 90.0) -> None:
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1400,
        schema: dict | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="",
                model=self.model,
                provider=self.name,
                error=f"{self.name}: LLM_API_KEY is not set",
            )
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    self.base_url, headers=self._headers(), json=body
                )
                if resp.status_code >= 400:
                    return LLMResponse(
                        text="",
                        model=self.model,
                        provider=self.name,
                        error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                    )
                data = resp.json()
        except Exception as exc:
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error=f"unexpected response shape: {str(data)[:300]}",
            )
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            model=data.get("model", self.model),
            provider=self.name,
            raw=data,
        )


class OpenRouterProvider(_OpenAIShapeProvider):
    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            **super()._headers(),
            "HTTP-Referer": "https://localhost",
            "X-Title": "HazeReady",
        }


class GroqProvider(_OpenAIShapeProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1/chat/completions"


class OllamaProvider:
    """Local inference. No API key. Used for the A6 ablation arm and as the
    fully offline demo path."""

    name = "ollama"

    def __init__(
        self, model: str, base_url: str = "http://localhost:11434", timeout_s: float = 90.0
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1400,
        schema: dict | None = None,
    ) -> LLMResponse:
        body = {
            "model": self.model,
            "prompt": user,
            "system": system,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=body)
                if resp.status_code >= 400:
                    return LLMResponse(
                        text="", model=self.model, provider=self.name,
                        error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                    )
                data = resp.json()
        except Exception as exc:
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )
        return LLMResponse(
            text=data.get("response", ""),
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            model=self.model,
            provider=self.name,
            raw=data,
        )


class GoogleProvider:
    """Google AI Studio Generative Language API."""

    name = "google"

    def __init__(self, model: str, api_key: str, timeout_s: float = 90.0) -> None:
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1400,
        schema: dict | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error="google: LLM_API_KEY is not set",
            )
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    url, params={"key": self.api_key}, json=body
                )
                if resp.status_code >= 400:
                    return LLMResponse(
                        text="", model=self.model, provider=self.name,
                        error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                    )
                data = resp.json()
        except Exception as exc:
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error=f"unexpected response shape: {str(data)[:300]}",
            )
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
            model=self.model,
            provider=self.name,
            raw=data,
        )
