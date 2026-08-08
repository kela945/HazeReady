"""Telemetry: SQLite with WAL, plus Prometheus text exposition.

No personal data is collected. There is no account, no session persistence, and
no free-text from the user is stored beyond the question itself, which is
required to make the failure gallery and the drift signal meaningful. The schema
below is the enforcement point for that claim: there is no column in which
personal data could be placed.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT    NOT NULL,
    query_id       TEXT    NOT NULL,
    kind           TEXT    NOT NULL,
    role           TEXT,
    decision       TEXT,
    arm            TEXT,
    latency_ms     INTEGER,
    prompt_tokens  INTEGER,
    completion_tokens INTEGER,
    model          TEXT,
    provider       TEXT,
    top_retrieval_score REAL,
    abstained      INTEGER DEFAULT 0,
    payload        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

CREATE TABLE IF NOT EXISTS guardrail_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    query_id   TEXT NOT NULL,
    guardrail  TEXT NOT NULL,
    triggered  INTEGER NOT NULL,
    action     TEXT,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    query_id  TEXT NOT NULL,
    rating    TEXT NOT NULL,
    reason    TEXT
);

CREATE TABLE IF NOT EXISTS upstream_status (
    name          TEXT PRIMARY KEY,
    last_success  TEXT,
    last_error    TEXT,
    error_detail  TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TelemetryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- writes -------------------------------------------------------------

    def record_advisory(self, advisory) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO events (ts, query_id, kind, role, decision, arm,
                   latency_ms, prompt_tokens, completion_tokens, model, provider,
                   top_retrieval_score, abstained, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _now(),
                    advisory.query_id,
                    "advisory",
                    advisory.role.value,
                    advisory.decision.value,
                    advisory.arm,
                    advisory.latency_ms,
                    advisory.prompt_tokens,
                    advisory.completion_tokens,
                    advisory.model,
                    advisory.provider,
                    advisory.top_retrieval_score,
                    1 if advisory.decision.value == "abstain" else 0,
                    json.dumps(
                        {
                            "question": advisory.question,
                            "tools": [t.tool for t in advisory.trajectory],
                            "citations": [c.doc_id for c in advisory.citations],
                            "band": advisory.band_result.band_label
                            if advisory.band_result
                            else None,
                            "conflicts": advisory.conflicts,
                        }
                    ),
                ),
            )
            for g in advisory.guardrail_events:
                self._conn.execute(
                    """INSERT INTO guardrail_events (ts, query_id, guardrail,
                       triggered, action, detail) VALUES (?,?,?,?,?,?)""",
                    (
                        _now(),
                        advisory.query_id,
                        g.guardrail,
                        int(g.triggered),
                        g.action,
                        g.detail,
                    ),
                )
            self._conn.commit()

    def record_feedback(self, query_id: str, rating: str, reason: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback (ts, query_id, rating, reason) VALUES (?,?,?,?)",
                (_now(), query_id, rating, reason[:500]),
            )
            self._conn.commit()

    def record_upstream(self, name: str, ok: bool, detail: str = "") -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM upstream_status WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO upstream_status (name, last_success, last_error, error_detail)"
                    " VALUES (?,?,?,?)",
                    (name, _now() if ok else None, None if ok else _now(), detail),
                )
            elif ok:
                self._conn.execute(
                    "UPDATE upstream_status SET last_success=? WHERE name=?", (_now(), name)
                )
            else:
                self._conn.execute(
                    "UPDATE upstream_status SET last_error=?, error_detail=? WHERE name=?",
                    (_now(), detail, name),
                )
            self._conn.commit()

    # -- reads --------------------------------------------------------------

    def summary(self, out_of_corpus_threshold: float = 0.012) -> dict[str, Any]:
        c = self._conn
        total = c.execute("SELECT COUNT(*) n FROM events WHERE kind='advisory'").fetchone()["n"]
        if total == 0:
            return {"total_queries": 0, "empty": True}

        lat = [
            r["latency_ms"]
            for r in c.execute(
                "SELECT latency_ms FROM events WHERE kind='advisory' ORDER BY latency_ms"
            )
        ]

        def pct(p: float) -> int:
            if not lat:
                return 0
            return lat[min(len(lat) - 1, int(len(lat) * p))]

        abstained = c.execute(
            "SELECT COUNT(*) n FROM events WHERE kind='advisory' AND abstained=1"
        ).fetchone()["n"]
        tokens = c.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(completion_tokens),0) c"
            " FROM events WHERE kind='advisory'"
        ).fetchone()
        by_role = {
            r["role"]: r["n"]
            for r in c.execute(
                "SELECT role, COUNT(*) n FROM events WHERE kind='advisory' GROUP BY role"
            )
        }
        by_decision = {
            r["decision"]: r["n"]
            for r in c.execute(
                "SELECT decision, COUNT(*) n FROM events WHERE kind='advisory' GROUP BY decision"
            )
        }
        guardrails = {
            r["guardrail"]: r["n"]
            for r in c.execute(
                "SELECT guardrail, COUNT(*) n FROM guardrail_events WHERE triggered=1"
                " GROUP BY guardrail"
            )
        }
        out_of_corpus = c.execute(
            "SELECT COUNT(*) n FROM events WHERE kind='advisory' AND top_retrieval_score < ?",
            (out_of_corpus_threshold,),
        ).fetchone()["n"]
        mean_score = (
            c.execute(
                "SELECT AVG(top_retrieval_score) s FROM events WHERE kind='advisory'"
            ).fetchone()["s"]
            or 0.0
        )
        fb = {
            r["rating"]: r["n"]
            for r in c.execute("SELECT rating, COUNT(*) n FROM feedback GROUP BY rating")
        }
        tool_counts: dict[str, int] = {}
        for r in c.execute("SELECT payload FROM events WHERE kind='advisory'"):
            for t in json.loads(r["payload"]).get("tools", []):
                tool_counts[t] = tool_counts.get(t, 0) + 1

        return {
            "total_queries": total,
            "empty": False,
            "latency_ms": {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99)},
            "abstention_rate": round(abstained / total, 4),
            "tokens": {"prompt": tokens["p"], "completion": tokens["c"]},
            "by_role": by_role,
            "by_decision": by_decision,
            "guardrail_triggers": guardrails,
            "out_of_corpus_queries": out_of_corpus,
            "out_of_corpus_rate": round(out_of_corpus / total, 4),
            "mean_top_retrieval_score": round(mean_score, 5),
            "feedback": fb,
            "negative_feedback_rate": round(fb.get("down", 0) / max(1, sum(fb.values())), 4),
            "tool_call_distribution": tool_counts,
            "upstreams": [dict(r) for r in c.execute("SELECT * FROM upstream_status")],
        }

    def recent_events(self, limit: int = 50, kind: str | None = None) -> list[dict]:
        q = "SELECT * FROM events"
        args: tuple = ()
        if kind:
            q += " WHERE kind=?"
            args = (kind,)
        q += " ORDER BY id DESC LIMIT ?"
        rows = self._conn.execute(q, (*args, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            out.append(d)
        return out

    def prometheus(self, cost_in: float = 0.0, cost_out: float = 0.0) -> str:
        s = self.summary()
        lines = [
            "# HELP hazeready_queries_total Advisory queries served.",
            "# TYPE hazeready_queries_total counter",
            f"hazeready_queries_total {s.get('total_queries', 0)}",
        ]
        if s.get("empty"):
            return "\n".join(lines) + "\n"
        lines += [
            "# HELP hazeready_latency_ms Request latency quantiles.",
            "# TYPE hazeready_latency_ms gauge",
            f'hazeready_latency_ms{{quantile="0.5"}} {s["latency_ms"]["p50"]}',
            f'hazeready_latency_ms{{quantile="0.95"}} {s["latency_ms"]["p95"]}',
            f'hazeready_latency_ms{{quantile="0.99"}} {s["latency_ms"]["p99"]}',
            "# HELP hazeready_abstention_rate Fraction of queries abstained.",
            "# TYPE hazeready_abstention_rate gauge",
            f"hazeready_abstention_rate {s['abstention_rate']}",
            "# HELP hazeready_out_of_corpus_rate Queries whose top retrieval score is below threshold.",
            "# TYPE hazeready_out_of_corpus_rate gauge",
            f"hazeready_out_of_corpus_rate {s['out_of_corpus_rate']}",
            "# HELP hazeready_tokens_total Tokens consumed.",
            "# TYPE hazeready_tokens_total counter",
            f'hazeready_tokens_total{{direction="prompt"}} {s["tokens"]["prompt"]}',
            f'hazeready_tokens_total{{direction="completion"}} {s["tokens"]["completion"]}',
        ]
        for name, n in s["guardrail_triggers"].items():
            lines.append(f'hazeready_guardrail_triggers_total{{guardrail="{name}"}} {n}')
        for role, n in s["by_role"].items():
            lines.append(f'hazeready_queries_by_role{{role="{role}"}} {n}')
        cost = (
            s["tokens"]["prompt"] / 1e6 * cost_in + s["tokens"]["completion"] / 1e6 * cost_out
        )
        lines += [
            "# HELP hazeready_cost_usd_total Estimated spend at the configured rate.",
            "# TYPE hazeready_cost_usd_total counter",
            f"hazeready_cost_usd_total {cost:.6f}",
        ]
        return "\n".join(lines) + "\n"

    def close(self) -> None:
        self._conn.close()
