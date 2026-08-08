"""A deterministic non-LLM provider.

Purpose: let the whole system — agent loop, guardrails, API, UI, evaluation
harness — run and be tested with no API key and no network. It composes an
answer from the structured context the orchestrator has already assembled.

What it is NOT: a language model. It performs no reasoning. Evaluation runs
under this provider measure the deterministic scaffolding (band resolution,
policy lookup, retrieval, guardrails) and nothing about model behaviour. The
evaluation runner labels such runs `provider=stub` and the report states that
the result is a floor for the pipeline, not a model comparison.

It is useful precisely because it isolates that floor: the gap between the stub
and a real model on the same benchmark is the model's contribution.
"""

from __future__ import annotations

import json
import re

from app.llm.protocol import LLMResponse


class StubProvider:
    name = "stub"

    def __init__(self, model: str = "stub-deterministic") -> None:
        self.model = model or "stub-deterministic"

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1400,
        schema: dict | None = None,
    ) -> LLMResponse:
        payload = self._compose(user)
        text = json.dumps(payload)
        return LLMResponse(
            text=text,
            prompt_tokens=len((system + user).split()),
            completion_tokens=len(text.split()),
            model=self.model,
            provider=self.name,
        )

    # -- composition --------------------------------------------------------

    @staticmethod
    def _compose(user: str) -> dict:
        """Read the structured context block the orchestrator supplies and echo
        the deterministic decision back. Parsing rather than reasoning."""
        decision = "abstain"
        m = re.search(r"GOVERNING_DECISION:\s*([a-z_]+)", user)
        if m:
            decision = m.group(1)

        reason_codes: list[str] = []
        m = re.search(r"REASON_CODES:\s*(.+)", user)
        if m:
            reason_codes = [c.strip() for c in m.group(1).split(",") if c.strip()]

        obligations: list[str] = []
        block = re.search(r"OBLIGATIONS_START\n(.*?)\nOBLIGATIONS_END", user, re.S)
        if block:
            obligations = [
                line.strip("- ").strip()
                for line in block.group(1).splitlines()
                if line.strip()
            ]

        doc_ids: list[str] = []
        block = re.search(r"CITABLE_DOC_IDS:\s*(.+)", user)
        if block:
            doc_ids = [d.strip() for d in block.group(1).split(",") if d.strip()]

        band_label = ""
        m = re.search(r"RESOLVED_BAND:\s*(.+)", user)
        if m:
            band_label = m.group(1).strip()

        if decision == "abstain":
            authority = ""
            m = re.search(r"ABSTAIN_AUTHORITY:\s*(.+)", user)
            if m:
                authority = m.group(1).strip()
            reason = "no_governing_guidance"
            m = re.search(r"ABSTAIN_REASON:\s*([a-z_]+)", user)
            if m:
                reason = m.group(1)
            return {
                "decision": "abstain",
                "reason_codes": reason_codes,
                "obligations": [],
                "rationale": (
                    "The published guidance available to this system does not "
                    "cover this question, so no advisory is given."
                ),
                "citation_doc_ids": doc_ids[:2],
                "abstain_reason": reason,
                "abstain_authority": authority,
            }

        rationale = (
            f"The governing band is {band_label}. "
            if band_label
            else ""
        ) + (
            "The decision follows from the published obligations for this role at "
            "this band, as set out in the cited sources."
        )
        return {
            "decision": decision,
            "reason_codes": reason_codes,
            "obligations": obligations,
            "rationale": rationale,
            "citation_doc_ids": doc_ids[:4],
            "abstain_reason": None,
            "abstain_authority": "",
        }
