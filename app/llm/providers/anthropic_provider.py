"""Anthropic provider, via the official `anthropic` SDK.

Model selection rationale (this is the choice defended in the README):

  Claude Haiku 4.5 is the smallest current Claude model. The job it does here is
  deliberately narrow — it composes and explains a decision that the
  deterministic policy engine has already made, and selects which of the
  supplied sources to cite. It does not resolve bands, does not perform
  threshold arithmetic, and cannot override the decision. That is a
  short-context, low-reasoning-depth task, which is exactly the shape Haiku is
  for. Paying Opus rates to rephrase a lookup result would be an unjustifiable
  cost at scale.

  The corollary matters for the evaluation: because the model is doing the easy
  half of the work, the A4 arm should be close to the deterministic ceiling. The
  A5 arm moves band arithmetic into this same small model, which is where the
  design constraint gets tested.

Structured outputs are used rather than JSON-mode prompting: the response is
constrained to the exact schema at decode time, so a malformed advisory cannot
reach the guardrail chain in the first place. Haiku 4.5 supports this.

Thinking is deliberately not enabled. The reasoning this system depends on is in
Python, not in the model, and extended thinking on a composition task would add
latency and cost for no measurable gain. Note also that `effort` is not a valid
parameter on Haiku 4.5 and must not be sent.
"""

from __future__ import annotations

import json

from app.llm.protocol import LLMResponse

# Published rates for claude-haiku-4-5, USD per million tokens. Used only as a
# default so an unconfigured run still reports a real cost rather than zero;
# LLM_COST_IN / LLM_COST_OUT override it.
HAIKU_45_COST_PER_1M_INPUT_USD = 1.00
HAIKU_45_COST_PER_1M_OUTPUT_USD = 5.00


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, model: str, api_key: str, timeout_s: float = 90.0, max_retries: int = 2
    ) -> None:
        self.model = model or "claude-haiku-4-5"
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(
                api_key=self.api_key or None,
                timeout=self.timeout_s,
                max_retries=self.max_retries,
            )
        return self._client

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1400,
        schema: dict | None = None,
    ) -> LLMResponse:
        import anthropic

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            # Valid on Haiku 4.5. It is removed on Opus 4.7+/Sonnet 5/Fable 5,
            # so a future model swap must drop it.
            "temperature": temperature,
        }
        if schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }

        try:
            message = await self.client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error=f"HTTP {exc.status_code}: {str(exc)[:300]}",
            )
        except Exception as exc:
            return LLMResponse(
                text="", model=self.model, provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

        # A refusal returns HTTP 200 with an empty or partial content list.
        # Reading content[0] unconditionally would raise here.
        if message.stop_reason == "refusal":
            detail = getattr(message, "stop_details", None)
            category = getattr(detail, "category", None) if detail else None
            return LLMResponse(
                text="", model=message.model, provider=self.name,
                error=f"refusal (category={category})",
            )

        text = "".join(b.text for b in message.content if b.type == "text")
        if not text:
            return LLMResponse(
                text="", model=message.model, provider=self.name,
                error=f"empty response (stop_reason={message.stop_reason})",
            )

        return LLMResponse(
            text=text,
            prompt_tokens=message.usage.input_tokens,
            completion_tokens=message.usage.output_tokens,
            model=message.model,
            provider=self.name,
            raw={"stop_reason": message.stop_reason},
        )


# --------------------------------------------------------------------------
# Response schemas
# --------------------------------------------------------------------------
#
# Hand-written rather than generated from the Pydantic models, because the
# structured-outputs subset is narrower than JSON Schema: no numeric or string
# constraints, `additionalProperties: false` is required on every object, and
# every property must appear in `required`. Generating from Pydantic and
# stripping the unsupported keywords is more fragile than stating the contract
# once, here, next to the model that has to satisfy it.

DECISIONS = [
    "proceed",
    "proceed_with_precautions",
    "restrict",
    "suspend",
    "abstain",
]

ABSTAIN_REASONS = [
    "no_governing_guidance",
    "conflicting_sources",
    "out_of_scope",
    "requires_professional_judgement",
]

DRAFT_ADVISORY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": DECISIONS},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "obligations": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
        "citation_doc_ids": {"type": "array", "items": {"type": "string"}},
        "abstain_reason": {
            "anyOf": [
                {"type": "string", "enum": ABSTAIN_REASONS},
                {"type": "null"},
            ]
        },
        "abstain_authority": {"type": "string"},
    },
    "required": [
        "decision",
        "reason_codes",
        "obligations",
        "rationale",
        "citation_doc_ids",
        "abstain_reason",
        "abstain_authority",
    ],
    "additionalProperties": False,
}

ROLE_ROUTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "skill": {
            "type": "string",
            "enum": [
                "general_public",
                "preschool_operator",
                "school_pe",
                "eldercare_facility",
                "outdoor_worksite",
                "mass_event_organiser",
            ],
        },
        "confidence": {"type": "string"},
    },
    "required": ["skill", "confidence"],
    "additionalProperties": False,
}


def schema_fingerprint(schema: dict | None) -> str:
    """Stable identity for a schema, for use in a cache key."""
    if schema is None:
        return "none"
    return json.dumps(schema, sort_keys=True)
