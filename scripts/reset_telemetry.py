#!/usr/bin/env python3
"""Clear the telemetry store, then optionally replay a little real traffic.

Why this exists: the evaluation runner and the service share one SQLite file.
A full ablation grid writes several thousand advisory events into it, and the
monitoring dashboard then reports rates computed over benchmark runs — an
abstention rate of 36% that is a property of the benchmark's composition, not of
anything an operator did. The runner now disables telemetry, but a store that
was polluted before that fix has to be cleared.

  python scripts/reset_telemetry.py            # clear only
  python scripts/reset_telemetry.py --seed 12  # clear, then ask 12 real questions

`--seed` sends questions to a *running* server at --base-url. The events it
produces are real: each one is a full pass through routing, retrieval, tools,
the model and the guardrails. It is demo traffic, not fabricated telemetry —
nothing is inserted into the database directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402

# A spread across roles, bands, boundaries and one question the corpus does not
# cover, so the dashboard shows the shape of real use rather than one hot path.
DEMO_QUESTIONS: list[tuple[str, str]] = [
    (
        "preschool",
        "24-hr PSI just hit 101 in the north. My K1 class has outdoor play in 20 minutes — do I cancel?",
    ),
    ("preschool", "PSI is 88 and steady. Normal outdoor play this morning?"),
    ("school", "PSI 165. We have PE first period. What do I tell the teachers?"),
    (
        "school",
        "24-hr PSI is 210 and one of my students has asthma. Anything different for her?",
    ),
    ("worksite", "PSI 150. My workers are laying kerbs outdoors all day. What must I do?"),
    ("worksite", "24-hr PSI is 320. Do I stop work outright?"),
    ("eldercare", "PSI 120. Our residents have a morning garden walk scheduled."),
    ("eldercare", "PSI 205. Should residents with COPD be wearing N95s indoors?"),
    (
        "event",
        "24-hr PSI is 230. Our event is a seated outdoor film screening, no exertion. Proceed?",
    ),
    ("event", "Forecast is 90 to 130 for tomorrow. We have a 5km fun run booked."),
    ("general_public", "24-hr PSI is 75. Any reason not to go running?"),
    ("general_public", "PSI 190 and I am pregnant. Is it safe to walk to the MRT?"),
    ("preschool", "What size air purifier do I need for a 40 square metre classroom?"),
    ("school", "At exactly what PSI does MOE close schools?"),
    ("general_public", "1-hour PM2.5 is 180. Should I close my windows now?"),
    ("worksite", "PSI 100 exactly. Does anything change from PSI 99?"),
]


def clear(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        ]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        for t in tables:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
        conn.execute("VACUUM")
        return counts
    finally:
        conn.close()


async def seed(base_url: str, n: int) -> int:
    import httpx

    ok = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        for role, question in DEMO_QUESTIONS[:n]:
            try:
                r = await client.post(
                    f"{base_url}/api/ask", json={"question": question, "role": role}
                )
                r.raise_for_status()
                d = r.json()
                ok += 1
                print(
                    f"  {role:15s} {d['decision']:26s} {d['latency_ms']:>6} ms  {question[:52]}"
                )
            except Exception as exc:  # noqa: BLE001 — a seeding failure is not fatal
                print(f"  {role:15s} FAILED: {type(exc).__name__}: {exc}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0, metavar="N", help="replay N demo questions")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    db = Path(get_settings().telemetry_db_path)
    counts = clear(db)
    if counts:
        print(f"cleared {db}: " + ", ".join(f"{t}={n}" for t, n in counts.items()))
    else:
        print(f"{db} does not exist yet — nothing to clear")

    if args.seed:
        n = min(args.seed, len(DEMO_QUESTIONS))
        print(f"replaying {n} question(s) against {args.base_url} …")
        got = asyncio.run(seed(args.base_url, n))
        print(f"{got}/{n} recorded")
        if got == 0:
            print("Is the server running? Start it with: make run")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
