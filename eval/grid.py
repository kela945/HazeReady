"""The ablation grid definition, readable without importing the application.

Kept separate from `eval/runner.py` so the report builder and the README
injector can ask what an arm is *called* without pulling in the orchestrator,
the embedding model and everything behind them.

Arm labels live here rather than in the run files. A run file records what was
measured; a label is how it is described, and descriptions get rewritten. When
a label changes, the committed results should pick it up without a four-hour
re-run — and a run file left over from a removed arm should still render under
the name it was produced with rather than crash the report.
"""

from __future__ import annotations

from pathlib import Path

import yaml

GRID_PATH = Path(__file__).resolve().parent / "ablations.yaml"


def load_grid() -> dict:
    return yaml.safe_load(GRID_PATH.read_text(encoding="utf-8"))


def arm_labels() -> dict[str, str]:
    """Map arm id → current label, from `eval/ablations.yaml`."""
    return {a["id"]: a["label"] for a in load_grid()["arms"]}


def label_for(arm: str, fallback: str = "") -> str:
    """The current label for `arm`, or `fallback` if it is no longer in the grid."""
    return arm_labels().get(arm, fallback or arm)
