#!/usr/bin/env python3
"""Write the README's evaluation table from reports/raw/, mechanically.

The README must never describe something the code did not produce, and a
hand-copied results table is the easiest place for that to go wrong. This
regenerates the table between the EVAL_RESULTS markers from the same run files
the HTML report is built from, so the two cannot disagree.

Run: python scripts/inject_results.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eval.metrics import mean_std  # noqa: E402

RAW = REPO / "reports" / "raw"
START = "<!-- EVAL_RESULTS_START -->"
END = "<!-- EVAL_RESULTS_END -->"


def main() -> int:
    manifest_path = RAW / "manifest.json"
    if not manifest_path.exists():
        print("no reports/raw/manifest.json — run `make eval` first")
        return 1
    manifest = json.loads(manifest_path.read_text())

    by_arm: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(RAW.glob("A*_run*.json")):
        d = json.loads(p.read_text())
        by_arm[d["arm"]].append(d)
    if not by_arm:
        print("no run files")
        return 1

    lines: list[str] = []
    lines.append(
        f"**Run:** `{manifest['provider']}` / `{manifest['model']}`, "
        f"{manifest['runs_per_arm']} runs per arm, {manifest['n_items']} items, "
        f"benchmark hash "
        f"{'matches' if manifest['benchmark_matches_freeze'] else '**MISMATCH** vs'}"
        f" the freeze.\n"
    )
    lines.append("| Arm | What it changes | Accuracy ↑ | Over-perm ↓ | Abstention F1 ↑ | Risk ↓ | p50 ms |")
    lines.append("|---|---|---|---|---|---|---|")

    for arm in sorted(by_arm):
        runs = by_arm[arm]
        label = runs[0]["label"]
        unavailable = any(r.get("provider_unavailable") for r in runs)

        def m(key: str, _runs=runs) -> float:
            return mean_std(r["summary"][key] for r in _runs)[0]

        note = " ⚠️ provider unavailable" if unavailable else ""
        bold = "**" if arm in ("A4", "A5") else ""
        lines.append(
            f"| {bold}{arm}{bold} | {label}{note} | {m('decision_accuracy'):.3f} | "
            f"{m('over_permission_rate'):.3f} | {m('abstention_f1'):.3f} | "
            f"{m('risk_score'):.3f} | {m('p50_latency_ms'):,.0f} |"
        )

    # The headline comparison, stated from the data rather than asserted.
    if "A4" in by_arm and "A5" in by_arm:
        def cat(arm: str, c: str) -> float:
            return mean_std(r["by_category"][c]["decision_accuracy"] for r in by_arm[arm])[0]

        a4, a5 = cat("A4", "threshold_boundary"), cat("A5", "threshold_boundary")
        a4o = mean_std(r["summary"]["decision_accuracy"] for r in by_arm["A4"])[0]
        a5o = mean_std(r["summary"]["decision_accuracy"] for r in by_arm["A5"])[0]
        lines.append("")
        lines.append(
            f"**The headline result.** A4 and A5 differ in exactly one thing: whether a "
            f"40-line Python function or the language model performs the band comparison. "
            f"Overall accuracy moves {a4o:.3f} → {a5o:.3f}; on the `threshold_boundary` "
            f"items, where a single index point flips the obligation, it moves "
            f"**{a4:.3f} → {a5:.3f}**."
        )

    if "A0" in by_arm and "A4" in by_arm:
        a0 = mean_std(r["summary"]["decision_accuracy"] for r in by_arm["A0"])[0]
        a4o = mean_std(r["summary"]["decision_accuracy"] for r in by_arm["A4"])[0]
        lines.append("")
        lines.append(
            f"**What grounding buys.** A0 is the same model with no retrieval, no tools "
            f"and no deterministic band — {a0:.3f} accuracy answering from its own "
            f"knowledge, against {a4o:.3f} for the full system."
        )

    block = f"{START}\n\n" + "\n".join(lines) + f"\n\n{END}"

    readme_path = REPO / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    if START not in readme or END not in readme:
        print("README is missing the EVAL_RESULTS markers")
        return 1
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    readme_path.write_text(head + block + tail, encoding="utf-8")

    print(f"injected results for {len(by_arm)} arms ({manifest['model']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
