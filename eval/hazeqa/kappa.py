#!/usr/bin/env python3
"""Compute Cohen's kappa between the authored gold and a second annotator.

Reads eval/hazeqa/second_annotator_labels.tsv (<id>\t<decision> per line).
Exits 2 with an explanatory message if that file does not exist -- no second
annotation was collected for this build, and no kappa is reported rather than
a fabricated one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from eval.metrics import cohens_kappa  # noqa: E402


def main() -> int:
    labels_path = HERE / "second_annotator_labels.tsv"
    if not labels_path.exists():
        print(
            "No second-annotator labels found at "
            f"{labels_path.relative_to(HERE.parents[1])}.\n"
            "No Cohen's kappa is reported for this build. See ANNOTATION_GUIDE.md "
            "section 9 for the protocol to collect one."
        )
        return 2

    gold = {
        json.loads(line)["id"]: json.loads(line)["gold_decision"]
        for line in (HERE / "items.jsonl").read_text().splitlines()
        if line.strip()
    }
    a, b, ids = [], [], []
    for line in labels_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        item_id, decision = line.split("\t")
        if item_id not in gold:
            print(f"unknown item id: {item_id}")
            return 1
        ids.append(item_id)
        a.append(gold[item_id])
        b.append(decision)

    k = cohens_kappa(a, b)
    agree = sum(1 for x, y in zip(a, b, strict=False) if x == y)
    print(f"items compared: {len(ids)}")
    print(f"raw agreement:  {agree}/{len(ids)} = {agree / len(ids):.1%}")
    print(f"Cohen's kappa:  {k:.3f}")
    if k < 0.7:
        print("\nkappa < 0.7: revise ANNOTATION_GUIDE.md where it was ambiguous and re-label.")
    print("\nDisagreements:")
    for i, x, y in zip(ids, a, b, strict=False):
        if x != y:
            print(f"  {i}: gold={x} annotator2={y}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
