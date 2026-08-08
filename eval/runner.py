#!/usr/bin/env python3
"""Evaluation runner.

Design points that matter for the numbers being trustworthy:

  * Every item runs against a pinned fixture where one is specified, so a run is
    reproducible regardless of live conditions.
  * The benchmark hash is recorded in every result file. A run whose hash does
    not match eval/hazeqa/freeze.txt was executed against a different benchmark
    and the report says so.
  * Runs are resumable and LLM responses are cached by (prompt hash, model,
    temperature), so a free-tier rate limit interrupts a run rather than
    invalidating it.
  * Each arm runs `runs_per_arm` times; the report shows mean +/- std. A
    single-run ablation table is not evidence.

Run: python eval/runner.py [--arms A4,A5] [--runs 3] [--limit 20]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.orchestrator import ArmConfig  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.data_sources.air_quality import AirQualityClient  # noqa: E402
from app.deps import Container  # noqa: E402
from app.llm.providers import make_provider  # noqa: E402
from eval.metrics import ItemResult, by_category, summarise  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HAZEQA = REPO / "eval" / "hazeqa"
RAW = REPO / "reports" / "raw"


# ---------------------------------------------------------------------------
# LLM response cache
# ---------------------------------------------------------------------------


class CachingProvider:
    """Wraps a provider with an on-disk cache keyed by (prompt, model, temp).

    Free-tier rate limits make a 9-arm x 180-item x 3-run grid fragile. Caching
    makes a resumed run cheap and makes repeated runs of the SAME arm return the
    same text -- which is why between-run variance is reported as measured, and
    why runs at temperature > 0 are only meaningfully varied when the cache is
    cold. This is stated in the report rather than hidden.
    """

    last_error: str = ""

    def __init__(self, inner, cache_path: Path, enabled: bool = True) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "unknown")
        self.model = getattr(inner, "model", "")
        self.cache_path = cache_path
        self.enabled = enabled
        self._cache: dict[str, dict] = {}
        if enabled and cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._cache[rec["key"]] = rec["value"]
        self.hits = 0
        self.misses = 0
        self.errors = 0
        self.calls = 0

    def _key(self, system: str, user: str, temperature: float, schema=None) -> str:
        from app.llm.providers.anthropic_provider import schema_fingerprint

        h = hashlib.sha256()
        h.update(f"{self.name}|{self.model}|{temperature}|".encode())
        h.update(schema_fingerprint(schema).encode())
        h.update(system.encode())
        h.update(b"\x00")
        h.update(user.encode())
        return h.hexdigest()

    async def complete(self, system, user, temperature=0.2, max_tokens=1400, schema=None):
        from app.llm.protocol import LLMResponse

        self.calls += 1
        key = self._key(system, user, temperature, schema)
        if self.enabled and key in self._cache:
            self.hits += 1
            return LLMResponse(**self._cache[key])

        self.misses += 1
        resp = await self.inner.complete(system, user, temperature, max_tokens, schema)
        if not resp.ok:
            self.errors += 1
            self.last_error = resp.error
        if self.enabled and resp.ok:
            value = {
                "text": resp.text,
                "prompt_tokens": resp.prompt_tokens,
                "completion_tokens": resp.completion_tokens,
                "model": resp.model,
                "provider": resp.provider,
                "error": "",
            }
            self._cache[key] = value
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"key": key, "value": value}) + "\n")
        return resp


# ---------------------------------------------------------------------------
# Fixture pinning
# ---------------------------------------------------------------------------


class PinnedAirQualityClient(AirQualityClient):
    """Serves a specific fixture file regardless of OFFLINE_MODE, so an item's
    reading is fixed by the benchmark rather than by the clock."""

    def __init__(self, base: AirQualityClient, fixture_name: str) -> None:
        super().__init__(
            base.psi_url,
            base.pm25_url,
            base.fixtures_dir,
            offline=True,
            timeout_s=base.timeout_s,
            cache_ttl_s=base.cache_ttl_s,
        )
        self.fixture_name = fixture_name

    async def _get(self, url, fixture_name, label):
        if url == self.pm25_url:
            pm = self.fixtures_dir / self.fixture_name.replace(".json", "_pm25.json")
            if pm.exists():
                return json.loads(pm.read_text(encoding="utf-8")), "fixture"
            return self._fixture("pm25_current.json"), "fixture"
        return self._fixture(self.fixture_name), "fixture"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def load_items(limit: int | None = None) -> list[dict]:
    items = [
        json.loads(line)
        for line in (HAZEQA / "items.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return items[:limit] if limit else items


def benchmark_hash() -> str:
    return hashlib.sha256((HAZEQA / "items.jsonl").read_bytes()).hexdigest()


def frozen_hash() -> str:
    for line in (HAZEQA / "freeze.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("sha256(items.jsonl):"):
            return line.split(":", 1)[1].strip()
    return ""


def git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "not-a-git-repo"


async def run_item(container: Container, item: dict, arm_cfg: ArmConfig) -> ItemResult:
    fixture = item.get("context_fixture") or ""
    client = (
        PinnedAirQualityClient(container.air_quality, fixture)
        if fixture
        else container.air_quality
    )

    t0 = time.perf_counter()
    try:
        advisory = await container.orchestrator.answer(
            item["question"], role=None, arm=arm_cfg, fixture_client=client
        )
    except Exception as exc:  # keep one bad item from aborting a 4860-item grid
        return ItemResult(
            item_id=item["id"],
            category=item["category"],
            gold_decision=item["gold_decision"],
            pred_decision="error",
            gold_role=item["role"],
            pred_role="",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error=f"{type(exc).__name__}: {exc}",
            question=item["question"],
            notes=item.get("notes", ""),
        )

    if advisory.llm_error:
        # Count it toward the arm's failure rate so the report can banner it.
        pass

    text = " ".join([advisory.rationale, *advisory.obligations]).lower()
    hits = [s for s in item.get("must_not_contain", []) if s.lower() in text]

    tools = [t.tool for t in advisory.trajectory]
    resolve_called = "resolve_psi_band" in tools
    band_before_lookup = False
    if resolve_called:
        ri = tools.index("resolve_psi_band")
        band_before_lookup = "lookup_role_obligations" not in tools or ri < tools.index(
            "lookup_role_obligations"
        )

    return ItemResult(
        item_id=item["id"],
        category=item["category"],
        gold_decision=item["gold_decision"],
        pred_decision=advisory.decision.value,
        gold_role=item["role"],
        pred_role=advisory.role.value,
        gold_citation_doc_ids=item.get("gold_citation_doc_ids", []),
        pred_citation_doc_ids=[c.doc_id for c in advisory.citations],
        gold_abstain_reason=item.get("gold_abstain_reason", ""),
        pred_abstain_reason=(advisory.abstention.reason.value if advisory.abstention else ""),
        must_not_contain=item.get("must_not_contain", []),
        must_not_contain_hits=hits,
        band_resolved_before_claim=band_before_lookup,
        resolve_band_called=resolve_called,
        tools_called=tools,
        latency_ms=advisory.latency_ms,
        prompt_tokens=advisory.prompt_tokens,
        completion_tokens=advisory.completion_tokens,
        top_retrieval_score=advisory.top_retrieval_score,
        question=item["question"],
        rationale=advisory.rationale,
        notes=item.get("notes", ""),
    )


async def run_arm(
    container: Container, arm: dict, items: list[dict], run_index: int, settings
) -> dict:
    cfg = ArmConfig(arm=arm["id"], **arm.get("config", {}))
    results: list[ItemResult] = []
    for i, item in enumerate(items, start=1):
        results.append(await run_item(container, item, cfg))
        if i % 30 == 0:
            print(f"    {arm['id']} run{run_index}: {i}/{len(items)}")

    return {
        "arm": arm["id"],
        "label": arm["label"],
        "question": arm["question"],
        "run_index": run_index,
        "summary": summarise(
            results, settings.llm_cost_per_1m_input_usd, settings.llm_cost_per_1m_output_usd
        ),
        "by_category": by_category(results),
        "items": [asdict(r) for r in results],
    }


async def main_async(args) -> int:
    settings = get_settings()
    grid = yaml.safe_load((REPO / "eval" / "ablations.yaml").read_text(encoding="utf-8"))

    selected = (
        [a for a in grid["arms"] if a["id"] in args.arms.split(",")]
        if args.arms
        else grid["arms"]
    )
    runs = args.runs or grid["runs_per_arm"]
    items = load_items(args.limit)

    bh, fh = benchmark_hash(), frozen_hash()
    if bh != fh:
        print(f"WARNING: benchmark hash {bh[:12]} != frozen {fh[:12]}")
        print("         Results are NOT comparable to a run against the frozen set.")

    RAW.mkdir(parents=True, exist_ok=True)
    container = Container(settings)

    # The evaluation shares the orchestrator with the running service, which
    # means it also shares the telemetry store. Left alone, a single `make eval`
    # writes ~4,900 advisory events into the same SQLite file the monitoring
    # dashboard reads, burying real operational traffic under benchmark runs and
    # making every dashboard rate meaningless. The eval has its own result files
    # in reports/raw/; it does not need the telemetry store.
    container.orchestrator.d.telemetry = None

    print(f"provider={settings.llm_provider} model={settings.resolved_llm_model}")
    print(f"items={len(items)} arms={[a['id'] for a in selected]} runs={runs}")
    if settings.llm_provider == "stub":
        print(
            "NOTE: provider=stub is a deterministic non-LLM composer. Results "
            "measure the deterministic pipeline only and say nothing about model "
            "behaviour. Set LLM_PROVIDER to run a real evaluation."
        )

    manifest = {
        "started_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "benchmark_sha256": bh,
        "frozen_sha256": fh,
        "benchmark_matches_freeze": bh == fh,
        "provider": settings.llm_provider,
        "model": settings.resolved_llm_model,
        "temperature": grid["temperature"],
        "runs_per_arm": runs,
        "n_items": len(items),
        "arms": [a["id"] for a in selected],
        "offline_mode": settings.offline_mode,
        "cost_per_1m_input_usd": settings.llm_cost_per_1m_input_usd,
        "cost_per_1m_output_usd": settings.llm_cost_per_1m_output_usd,
        "runs": [],
    }

    for arm in selected:
        base_provider = container.llm
        if arm.get("provider_override"):
            base_provider = make_provider(
                arm["provider_override"],
                "qwen3:8b"
                if arm["provider_override"] == "ollama"
                else settings.resolved_llm_model,
                settings.llm_api_key,
                settings.ollama_base_url,
                settings.llm_timeout_s,
            )
        cache = REPO / "data" / "llm_cache" / f"{arm['id']}.jsonl"
        container.orchestrator.d.llm = CachingProvider(
            base_provider, cache, enabled=not args.no_cache
        )

        for run_index in range(1, runs + 1):
            out = RAW / f"{arm['id']}_run{run_index}.json"
            if out.exists() and not args.force:
                print(f"  {arm['id']} run{run_index}: cached, skipping")
                manifest["runs"].append(str(out.relative_to(REPO)))
                continue
            print(f"  {arm['id']} run{run_index}: {arm['label']}")
            t0 = time.perf_counter()
            payload = await run_arm(container, arm, items, run_index, settings)
            payload["wall_seconds"] = round(time.perf_counter() - t0, 1)
            prov = container.orchestrator.d.llm
            payload["provider"] = getattr(prov, "name", "")
            payload["llm_calls"] = getattr(prov, "calls", 0)
            payload["llm_errors"] = getattr(prov, "errors", 0)
            payload["llm_cache_hits"] = getattr(prov, "hits", 0)
            payload["llm_last_error"] = getattr(prov, "last_error", "")
            calls = max(1, getattr(prov, "calls", 0))
            payload["llm_failure_rate"] = round(getattr(prov, "errors", 0) / calls, 4)
            if payload["llm_failure_rate"] > 0.5:
                payload["provider_unavailable"] = True
                print(
                    f"    WARNING: {payload['llm_failure_rate']:.0%} of LLM calls failed "
                    f"({payload['llm_last_error'][:90]}). This arm fell back to the "
                    "deterministic draft; its scores do NOT reflect model behaviour."
                )
            payload["model"] = getattr(container.orchestrator.d.llm, "model", "")
            payload["benchmark_sha256"] = bh
            out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            manifest["runs"].append(str(out.relative_to(REPO)))
            s = payload["summary"]
            print(
                f"    acc={s['decision_accuracy']:.3f} over_perm={s['over_permission_rate']:.3f} "
                f"risk={s['risk_score']:.3f} abst_f1={s['abstention_f1']:.3f} "
                f"({payload['wall_seconds']}s)"
            )

    manifest["finished_at"] = datetime.now(UTC).isoformat()
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"\nwrote {len(manifest['runs'])} run files to {RAW.relative_to(REPO)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arms", default="", help="comma-separated arm ids, e.g. A4,A5")
    p.add_argument("--runs", type=int, default=0)
    p.add_argument("--limit", type=int, default=0, help="first N items only (smoke test)")
    p.add_argument("--force", action="store_true", help="re-run arms with existing output")
    p.add_argument("--no-cache", action="store_true", help="bypass the LLM response cache")
    args = p.parse_args()
    args.limit = args.limit or None
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
