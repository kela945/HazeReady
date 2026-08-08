"""A thin LLM provider protocol.

Deliberately not LangChain. The agent loop in this system is about 200 lines and
every hop is auditable; a framework would hide the control flow behind
abstractions that have to be explained in interview and debugged through when a
guardrail misfires. The cost of this choice is that provider quirks are handled
here by hand — see `providers/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    provider: str = ""
    raw: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1400,
        schema: dict | None = None,
    ) -> LLMResponse:
        """Complete a prompt.

        `schema`, when given, is a JSON Schema the response must conform to.
        Providers that support constrained decoding (Anthropic structured
        outputs) enforce it at decode time; the rest ignore it and fall back to
        JSON-mode prompting. Callers must not assume enforcement — the
        orchestrator still validates the parsed result against the Pydantic
        model either way.
        """
        ...
