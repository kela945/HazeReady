#!/usr/bin/env python3
"""Report where the authored gold table disagrees with the implemented matrix.

The benchmark's gold decisions (eval/hazeqa/author_items.py) and the system's
policy matrix (data/policy_matrix.yaml) were both written from data/corpus/ by
the same author, through two independent code paths. This script measures how
far the two agree.

What a high agreement rate does and does not mean:
  - It DOES show the implementation faithfully encodes what the author intended.
  - It does NOT validate that intention. A systematic misreading of the
    published guidance would appear identically in both and produce 100%
    agreement while being wrong.

Read this number as an implementation-fidelity check, never as evidence the
gold labels are correct. Independent human annotation is the only thing that
establishes that, and none was available for this build.

Run: python eval/hazeqa/check_agreement.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings  # noqa: E402
from app.policy import load_policy_matrix  # noqa: E402
from eval.hazeqa.author_items import GOLD, GOLD_PM25  # noqa: E402


def main() -> int:
    s = get_settings()
    matrix = load_policy_matrix(s.policy_matrix_path, s.corpus_dir)

    agree = 0
    total = 0
    disagreements: list[str] = []

    for role, bands in GOLD.items():
        for band, authored in bands.items():
            total += 1
            implemented = matrix.lookup(role, band, "psi_24h").decision.value
            if implemented == authored:
                agree += 1
            else:
                disagreements.append(
                    f"  (role={role}, band={band}): authored={authored} "
                    f"implemented={implemented}"
                )

    for role, bands in GOLD_PM25.items():
        for band, authored in bands.items():
            total += 1
            implemented = matrix.lookup(role, band, "pm25_1h").decision.value
            if implemented == authored:
                agree += 1
            else:
                disagreements.append(
                    f"  (role={role}, index=pm25_1h, band={band}): "
                    f"authored={authored} implemented={implemented}"
                )

    rate = agree / total if total else 0.0
    print(f"authored-gold vs implemented-matrix agreement: {agree}/{total} = {rate:.1%}")
    if disagreements:
        print("\ndisagreements (each is either a matrix bug or a gold-label bug):")
        for d in disagreements:
            print(d)
    else:
        print("\nno disagreements.")
    print(
        "\nNote: this is an implementation-fidelity check, not label validation. "
        "Both artefacts share a single author and would agree on a shared "
        "misreading of the guidance."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
