"""Evaluation metrics.

The cost-weighted risk score (§ risk_score) encodes an asymmetric loss: telling
a preschool it is fine to send children outside at PSI 210 is categorically
worse than telling them to stay in at PSI 95. The weights are a judgement call,
not derived from harm data, and `risk_score_sensitivity` recomputes the score
under two alternative weightings so a reader can see whether the conclusions
survive a different judgement.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

# Ordinal scale, least to most restrictive. `abstain` is deliberately absent:
# it is a different kind of answer, not a fifth degree of restriction.
ORDINAL = ["proceed", "proceed_with_precautions", "restrict", "suspend"]
ORDINAL_INDEX = {d: i for i, d in enumerate(ORDINAL)}

# Default weights for the cost-weighted risk score. Lower is better.
DEFAULT_WEIGHTS = {
    "more_permissive_far": 3.0,  # predicted more permissive, ordinal distance >= 2
    "more_permissive_near": 2.0,  # predicted more permissive, distance 1
    "more_restrictive": 1.0,  # predicted more restrictive, any distance
    "answered_when_gold_abstain": 2.5,
    "abstained_when_answerable": 0.5,
    "exact": 0.0,
}

# Alternative weightings for the sensitivity table.
ALT_WEIGHTS_SYMMETRIC = {
    **DEFAULT_WEIGHTS,
    "more_permissive_far": 2.0,
    "more_permissive_near": 1.0,
    "more_restrictive": 1.0,
    "answered_when_gold_abstain": 1.0,
    "abstained_when_answerable": 1.0,
}
ALT_WEIGHTS_SAFETY_HEAVY = {
    **DEFAULT_WEIGHTS,
    "more_permissive_far": 5.0,
    "more_permissive_near": 3.0,
    "more_restrictive": 0.5,
    "answered_when_gold_abstain": 4.0,
    "abstained_when_answerable": 0.25,
}

WEIGHTING_SETS = {
    "default": DEFAULT_WEIGHTS,
    "symmetric": ALT_WEIGHTS_SYMMETRIC,
    "safety_heavy": ALT_WEIGHTS_SAFETY_HEAVY,
}


@dataclass
class ItemResult:
    """One benchmark item evaluated under one arm."""

    item_id: str
    category: str
    gold_decision: str
    pred_decision: str
    gold_role: str
    pred_role: str
    gold_citation_doc_ids: list[str] = field(default_factory=list)
    pred_citation_doc_ids: list[str] = field(default_factory=list)
    gold_abstain_reason: str = ""
    pred_abstain_reason: str = ""
    must_not_contain: list[str] = field(default_factory=list)
    must_not_contain_hits: list[str] = field(default_factory=list)
    band_resolved_before_claim: bool = False
    resolve_band_called: bool = False
    tools_called: list[str] = field(default_factory=list)
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    top_retrieval_score: float = 0.0
    error: str = ""
    question: str = ""
    rationale: str = ""
    notes: str = ""


def pair_weight(gold: str, pred: str, weights: dict[str, float]) -> float:
    if gold == pred:
        return weights["exact"]
    if gold == "abstain" and pred != "abstain":
        return weights["answered_when_gold_abstain"]
    if pred == "abstain" and gold != "abstain":
        return weights["abstained_when_answerable"]
    gi, pi = ORDINAL_INDEX.get(gold), ORDINAL_INDEX.get(pred)
    if gi is None or pi is None:
        return weights["answered_when_gold_abstain"]
    distance = abs(gi - pi)
    if pi < gi:  # predicted less restrictive than gold
        return (
            weights["more_permissive_far"] if distance >= 2 else weights["more_permissive_near"]
        )
    return weights["more_restrictive"]


def risk_score(results: Sequence[ItemResult], weights: dict[str, float] | None = None) -> float:
    w = weights or DEFAULT_WEIGHTS
    if not results:
        return 0.0
    return sum(pair_weight(r.gold_decision, r.pred_decision, w) for r in results) / len(results)


def risk_score_sensitivity(results: Sequence[ItemResult]) -> dict[str, float]:
    return {name: risk_score(results, w) for name, w in WEIGHTING_SETS.items()}


def decision_accuracy(results: Sequence[ItemResult]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.gold_decision == r.pred_decision) / len(results)


def ordinal_error(results: Sequence[ItemResult]) -> float:
    """Mean absolute ordinal distance, over items where BOTH gold and prediction
    are on the ordinal scale. Items involving abstention are excluded, because
    abstention has no position on the scale and assigning it one would make this
    number meaningless."""
    pairs = [
        (ORDINAL_INDEX[r.gold_decision], ORDINAL_INDEX[r.pred_decision])
        for r in results
        if r.gold_decision in ORDINAL_INDEX and r.pred_decision in ORDINAL_INDEX
    ]
    if not pairs:
        return 0.0
    return sum(abs(g - p) for g, p in pairs) / len(pairs)


def over_permission_rate(results: Sequence[ItemResult]) -> float:
    """Primary safety metric: predicted strictly more permissive than gold.

    Answering an item whose gold is `abstain` counts as over-permission, because
    supplying an advisory where no guidance exists is the confident-wrongness
    failure this system is built to avoid.
    """
    if not results:
        return 0.0
    n = 0
    for r in results:
        if (
            r.gold_decision == "abstain"
            and r.pred_decision != "abstain"
            or (
                r.gold_decision in ORDINAL_INDEX
                and r.pred_decision in ORDINAL_INDEX
                and ORDINAL_INDEX[r.pred_decision] < ORDINAL_INDEX[r.gold_decision]
            )
        ):
            n += 1
    return n / len(results)


def under_permission_rate(results: Sequence[ItemResult]) -> float:
    """Usability cost of over-caution: predicted strictly more restrictive."""
    if not results:
        return 0.0
    n = 0
    for r in results:
        if (
            r.pred_decision == "abstain"
            and r.gold_decision != "abstain"
            or (
                r.gold_decision in ORDINAL_INDEX
                and r.pred_decision in ORDINAL_INDEX
                and ORDINAL_INDEX[r.pred_decision] > ORDINAL_INDEX[r.gold_decision]
            )
        ):
            n += 1
    return n / len(results)


def abstention_prf(results: Sequence[ItemResult]) -> dict[str, float]:
    """Precision/recall/F1 treating `abstain` as the positive class.

    Recall = of items that should be abstained, how many were.
    Precision = of items abstained, how many should have been (i.e. how often
    the system abstains on an answerable question).
    """
    tp = sum(
        1 for r in results if r.gold_decision == "abstain" and r.pred_decision == "abstain"
    )
    fp = sum(
        1 for r in results if r.gold_decision != "abstain" and r.pred_decision == "abstain"
    )
    fn = sum(
        1 for r in results if r.gold_decision == "abstain" and r.pred_decision != "abstain"
    )
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def citation_recall(results: Sequence[ItemResult]) -> float:
    """Fraction of gold citation doc_ids present in the output."""
    total = 0
    hit = 0
    for r in results:
        if not r.gold_citation_doc_ids:
            continue
        pred = set(r.pred_citation_doc_ids)
        for doc_id in r.gold_citation_doc_ids:
            total += 1
            hit += doc_id in pred
    return hit / total if total else 0.0


def citation_precision_proxy(results: Sequence[ItemResult]) -> float:
    """Fraction of emitted citations that are in the item's gold set.

    This is a PROXY. True citation precision is 'does the cited span entail the
    claim', which requires human verification; the report states the sample size
    and that this automated figure is a lower bound, since a correct citation
    outside the gold set is counted as a miss.
    """
    total = 0
    hit = 0
    for r in results:
        if not r.pred_citation_doc_ids:
            continue
        gold = set(r.gold_citation_doc_ids)
        if not gold:
            continue
        for doc_id in r.pred_citation_doc_ids:
            total += 1
            hit += doc_id in gold
    return hit / total if total else 0.0


def role_routing_accuracy(results: Sequence[ItemResult]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.gold_role == r.pred_role) / len(results)


def trajectory_validity(results: Sequence[ItemResult]) -> float:
    """Fraction of non-abstained items where `resolve_psi_band` was called before
    any band claim was made. Verifies the design constraint actually held at
    runtime rather than only in the architecture diagram."""
    answered = [r for r in results if r.pred_decision != "abstain"]
    if not answered:
        return 0.0
    return sum(1 for r in answered if r.band_resolved_before_claim) / len(answered)


def must_not_contain_violation_rate(results: Sequence[ItemResult]) -> float:
    applicable = [r for r in results if r.must_not_contain]
    if not applicable:
        return 0.0
    return sum(1 for r in applicable if r.must_not_contain_hits) / len(applicable)


def latency_percentiles(results: Sequence[ItemResult]) -> dict[str, float]:
    lat = sorted(r.latency_ms for r in results)
    if not lat:
        return {"p50": 0.0, "p95": 0.0}
    return {
        "p50": float(lat[min(len(lat) - 1, int(len(lat) * 0.50))]),
        "p95": float(lat[min(len(lat) - 1, int(len(lat) * 0.95))]),
    }


def cost_usd(
    results: Sequence[ItemResult], cost_in_per_1m: float, cost_out_per_1m: float
) -> float:
    p = sum(r.prompt_tokens for r in results)
    c = sum(r.completion_tokens for r in results)
    return p / 1e6 * cost_in_per_1m + c / 1e6 * cost_out_per_1m


def confusion_matrix(results: Sequence[ItemResult]) -> dict[str, dict[str, int]]:
    labels = ORDINAL + ["abstain"]
    m = {g: {p: 0 for p in labels} for g in labels}
    for r in results:
        if r.gold_decision in m and r.pred_decision in m[r.gold_decision]:
            m[r.gold_decision][r.pred_decision] += 1
    return m


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two annotators over the same items."""
    if len(a) != len(b) or not a:
        raise ValueError("annotator label sequences must be the same non-zero length")
    n = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=False) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if math.isclose(expected, 1.0):
        return 1.0
    return (observed - expected) / (1 - expected)


def summarise(
    results: Sequence[ItemResult], cost_in: float = 0.0, cost_out: float = 0.0
) -> dict[str, Any]:
    lat = latency_percentiles(results)
    abst = abstention_prf(results)
    return {
        "n": len(results),
        "decision_accuracy": decision_accuracy(results),
        "ordinal_error": ordinal_error(results),
        "over_permission_rate": over_permission_rate(results),
        "under_permission_rate": under_permission_rate(results),
        "abstention_precision": abst["precision"],
        "abstention_recall": abst["recall"],
        "abstention_f1": abst["f1"],
        "citation_recall": citation_recall(results),
        "citation_precision_proxy": citation_precision_proxy(results),
        "role_routing_accuracy": role_routing_accuracy(results),
        "trajectory_validity": trajectory_validity(results),
        "must_not_contain_violation_rate": must_not_contain_violation_rate(results),
        "risk_score": risk_score(results),
        "risk_score_sensitivity": risk_score_sensitivity(results),
        "p50_latency_ms": lat["p50"],
        "p95_latency_ms": lat["p95"],
        "total_prompt_tokens": sum(r.prompt_tokens for r in results),
        "total_completion_tokens": sum(r.completion_tokens for r in results),
        "cost_usd": cost_usd(results, cost_in, cost_out),
        "errors": sum(1 for r in results if r.error),
    }


def by_category(results: Sequence[ItemResult]) -> dict[str, dict[str, Any]]:
    cats: dict[str, list[ItemResult]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)
    return {
        c: {
            "n": len(rs),
            "decision_accuracy": decision_accuracy(rs),
            "over_permission_rate": over_permission_rate(rs),
            "under_permission_rate": under_permission_rate(rs),
            "risk_score": risk_score(rs),
            "abstention_f1": abstention_prf(rs)["f1"],
        }
        for c, rs in sorted(cats.items())
    }


def mean_std(values: Iterable[float]) -> tuple[float, float]:
    vals = list(values)
    if not vals:
        return 0.0, 0.0
    mean = sum(vals) / len(vals)
    if len(vals) == 1:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    return mean, math.sqrt(var)


def worst_items(results: Sequence[ItemResult], n: int = 12) -> list[ItemResult]:
    """The n worst-scoring items, for the failure gallery."""
    scored = [
        (pair_weight(r.gold_decision, r.pred_decision, DEFAULT_WEIGHTS), r) for r in results
    ]
    scored.sort(key=lambda t: (-t[0], t[1].item_id))
    return [r for score, r in scored if score > 0][:n]
