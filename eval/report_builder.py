#!/usr/bin/env python3
"""Build reports/eval_report.html: a single self-contained file.

Written to be read in a browser by someone who will not run the code, and who
has about five minutes. The structure is six plain questions rather than a
catalogue of metrics:

  1. Does it work?
  2. Does routing the arithmetic to Python actually matter?
  3. Does grounding actually matter?
  4. Do the remaining components earn their place?
  5. Where does it fail?
  6. What you should not conclude from this.

Everything is inlined — CSS, JS, Plotly — so the report renders with no network.

Run: python eval/report_builder.py
"""

from __future__ import annotations

import html
import json
import platform
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.metrics import (  # noqa: E402
    WEIGHTING_SETS,
    ItemResult,
    confusion_matrix,
    mean_std,
    risk_score,
    worst_items,
)

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "reports" / "raw"
OUT = REPO / "reports" / "eval_report.html"

# The five metrics that carry the argument. Everything else is detail, and
# detail belongs in a collapsed table rather than in the reader's way.
HEADLINE = [
    ("decision_accuracy", "Accuracy", "higher"),
    ("over_permission_rate", "Over-permission", "lower"),
    ("abstention_f1", "Refusal F1", "higher"),
    ("risk_score", "Risk score", "lower"),
    ("p50_latency_ms", "p50 ms", "lower"),
]

DETAIL = [
    ("under_permission_rate", "Over-caution", "lower"),
    ("ordinal_error", "Ordinal error", "lower"),
    ("citation_recall", "Citation recall", "higher"),
    ("role_routing_accuracy", "Role routing", "higher"),
    ("trajectory_validity", "Trajectory validity", "higher"),
    ("p95_latency_ms", "p95 ms", "lower"),
    ("cost_usd", "Cost (USD)", "lower"),
]

CATEGORY_LABELS = {
    "threshold_boundary": "Threshold boundary",
    "role_conditioned": "Role conditioned",
    "multi_hop": "Multi-hop",
    "out_of_knowledge_base": "Out of knowledge base",
    "forecast_temporal": "Forecast / temporal",
    "robustness_paraphrase": "Robustness (Singlish)",
}

CATEGORY_BLURB = {
    "threshold_boundary": "Readings at and beside a band edge, where one index point flips the obligation.",
    "role_conditioned": "Same reading, six different roles, six different correct answers.",
    "multi_hop": "Needs live data, then a band, then a role lookup, in sequence.",
    "out_of_knowledge_base": "No published guidance exists. The correct answer is to refuse.",
    "forecast_temporal": "A decision about a future window, against a forecast range.",
    "robustness_paraphrase": "Singlish and colloquial rewordings with identical correct answers.",
}

# What it means when a given category is the weakest one. Written per category
# so the report's own commentary follows the data rather than an assumption
# about which category will come last.
WEAKEST_NOTE = {
    "threshold_boundary": "an index point either side of a band edge changes the obligation, "
    "so an error here is an error about the exact case the system exists to get right",
    "role_conditioned": "the same reading carries different obligations for a school and a "
    "worksite, and applying the wrong ladder gives a confidently wrong answer",
    "multi_hop": "these chain a live reading into a band into a role lookup, so a slip at any "
    "step is invisible in the final wording",
    "out_of_knowledge_base": "no published guidance exists for these, and the correct answer is "
    "to refuse — answering anyway is the confident wrongness this system was built to avoid",
    "forecast_temporal": "these commit to a decision about a window that has not happened yet, "
    "against a range rather than a number",
    "robustness_paraphrase": "the correct answers are identical to items the system gets right "
    "in standard English, so losses here are wording sensitivity rather than reasoning",
}

DIAGNOSES = {
    "role_routing": "Routed to the wrong role, so the wrong obligation ladder was applied.",
    "no_abstain": "Guidance is silent here, but the system answered instead of refusing.",
    "over_abstain": "Refused a question the corpus does cover.",
    "band_off": "The band applied does not match the governing band for the stated reading.",
    "cohort": "A cohort named in the question was not applied; the role default was used.",
    "other": "Differs from the expected answer for a reason the automated checks do not capture.",
}

COMPONENTS = ["A1", "A2", "A3", "A7", "A8"]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load() -> tuple[dict[str, list[dict]], dict]:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(RAW.glob("A*_run*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        by_arm[d["arm"]].append(d)
    mp = RAW / "manifest.json"
    manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    return dict(sorted(by_arm.items())), manifest


def aggregate(by_arm: dict[str, list[dict]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for arm, runs in by_arm.items():
        out[arm] = {
            "label": runs[0]["label"],
            "question": runs[0]["question"],
            "metrics": {
                k: mean_std(r["summary"][k] for r in runs) for k, _, _ in HEADLINE + DETAIL
            },
            "unavailable": any(r.get("provider_unavailable") for r in runs),
        }
    return out


def items_of(runs: list[dict]) -> list[ItemResult]:
    return [ItemResult(**it) for it in runs[0]["items"]]


def diagnose(it: ItemResult) -> str:
    if it.error:
        return "other"
    if it.gold_role != it.pred_role:
        return "role_routing"
    if it.gold_decision == "abstain" and it.pred_decision != "abstain":
        return "no_abstain"
    if it.pred_decision == "abstain" and it.gold_decision != "abstain":
        return "over_abstain"
    if any(
        w in it.question.lower() for w in ("pregnant", "copd", "asthma", "healthy", "elderly")
    ):
        return "cohort"
    return "band_off"


def esc(s) -> str:
    return html.escape(str(s))


def fmt(v: float, key: str) -> str:
    if "latency" in key:
        return f"{v:,.0f}"
    if key == "cost_usd":
        return f"${v:.4f}"
    return f"{v:.3f}"


# ---------------------------------------------------------------------------
# Fragments
# ---------------------------------------------------------------------------


def stat(value: str, label: str, note: str = "", tone: str = "") -> str:
    return (
        f'<div class="card {tone}"><div class="v">{esc(value)}</div>'
        f'<div class="l">{esc(label)}</div><div class="n">{esc(note)}</div></div>'
    )


def arm_table(a: dict[str, dict], arms: list[str], metrics=HEADLINE) -> str:
    present = [x for x in arms if x in a]
    if not present:
        return '<p class="note">Not present in this run.</p>'
    best: dict[str, float] = {}
    for key, _, direction in metrics:
        vals = [a[x]["metrics"][key][0] for x in present if not a[x]["unavailable"]]
        if vals:
            best[key] = max(vals) if direction == "higher" else min(vals)

    head = "".join(
        f'<th>{esc(lbl)}<span class="dir">{"↑" if d == "higher" else "↓"}</span></th>'
        for _, lbl, d in metrics
    )
    rows = []
    for x in present:
        cells = []
        for key, _, _ in metrics:
            mean, sd = a[x]["metrics"][key]
            cls = "best" if key in best and abs(mean - best[key]) < 1e-9 else ""
            sd_txt = f'<span class="sd">±{fmt(sd, key)}</span>' if sd > 0 else ""
            cells.append(f'<td class="{cls}">{fmt(mean, key)}{sd_txt}</td>')
        warn = (
            ' <span class="badge bad">provider unavailable</span>'
            if a[x]["unavailable"]
            else ""
        )
        rows.append(
            f'<tr><th><span class="lab">{esc(a[x]["label"])}</span>'
            f'<span class="code">{esc(x)}</span>{warn}</th>{"".join(cells)}</tr>'
        )
    return (
        '<div class="scroll"><table class="grid">'
        f"<thead><tr><th>Configuration</th>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def category_table(by_arm: dict[str, list[dict]]) -> tuple[str, str, float, str]:
    runs = by_arm.get("A4")
    if not runs:
        return "", "", 0.0, ""
    cats = runs[0]["by_category"]
    acc = {c: mean_std(r["by_category"][c]["decision_accuracy"] for r in runs)[0] for c in cats}
    over = {
        c: mean_std(r["by_category"][c]["over_permission_rate"] for r in runs)[0] for c in cats
    }
    weakest = min(acc, key=lambda c: acc[c])
    rows = "".join(
        f'<tr><th><span class="lab">{esc(CATEGORY_LABELS.get(c, c))}</span>'
        f'<span class="blurb">{esc(CATEGORY_BLURB.get(c, ""))}</span></th>'
        f"<td>{cats[c]['n']}</td>"
        f'<td class="{"weak" if c == weakest else ""}">{acc[c]:.3f}</td>'
        f"<td>{over[c]:.3f}</td></tr>"
        for c in sorted(cats, key=lambda c: acc[c])
    )
    table = (
        '<div class="scroll"><table class="grid">'
        "<thead><tr><th>Question type</th><th>n</th><th>Accuracy ↑</th>"
        "<th>Over-permission ↓</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )
    return table, CATEGORY_LABELS.get(weakest, weakest), acc[weakest], weakest


def confusion(items: list[ItemResult]) -> str:
    m = confusion_matrix(items)
    labels = ["proceed", "proceed_with_precautions", "restrict", "suspend", "abstain"]
    short = {
        "proceed": "proceed",
        "proceed_with_precautions": "proceed+",
        "restrict": "restrict",
        "suspend": "suspend",
        "abstain": "refuse",
    }
    order = {x: i for i, x in enumerate(labels)}
    head = "".join(f"<th>{esc(short[x])}</th>" for x in labels)
    rows = []
    for g in labels:
        cells = []
        for p in labels:
            n = m[g][p]
            cls = ""
            if g == p:
                cls = "diag"
            elif (g == "abstain" and p != "abstain") or (
                p != "abstain" and g != "abstain" and order[p] < order[g]
            ):
                # Answering where a refusal was required, or answering less
                # restrictively than required: both are over-permissive.
                cls = "overperm"
            cells.append(f'<td class="{cls}">{n or ""}</td>')
        rows.append(f"<tr><th>{esc(short[g])}</th>{''.join(cells)}</tr>")
    return (
        '<div class="scroll"><table class="grid confusion">'
        f'<thead><tr><th>correct \\ given</th>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def failure_gallery(items: list[ItemResult]) -> str:
    worst = worst_items(items, 10)
    if not worst:
        return '<p class="ok">No scoring failures in this configuration.</p>'
    cards = []
    for it in worst:
        key = diagnose(it)
        tools = " → ".join(it.tools_called) or "none"
        forbidden = (
            f'<dt>Forbidden phrase</dt><dd class="err">{esc(", ".join(it.must_not_contain_hits))}</dd>'
            if it.must_not_contain_hits
            else ""
        )
        cards.append(
            f"""<details class="fail">
<summary><span class="cat">{esc(CATEGORY_LABELS.get(it.category, it.category))}</span>
<span class="gp">expected <b>{esc(it.gold_decision)}</b> · gave <b>{esc(it.pred_decision)}</b></span></summary>
<div class="fb">
<p class="q">{esc(it.question)}</p>
<dl>
<dt>Why</dt><dd class="diag">{esc(DIAGNOSES[key])}</dd>
<dt>Role</dt><dd>expected <code>{esc(it.gold_role)}</code>, routed <code>{esc(it.pred_role or "—")}</code></dd>
<dt>Tools</dt><dd><code>{esc(tools)}</code></dd>
<dt>Cited</dt><dd><code>{esc(", ".join(it.pred_citation_doc_ids) or "none")}</code></dd>
<dt>What it said</dt><dd class="rat">{esc(it.rationale or "—")}</dd>
<dt>Annotator note</dt><dd>{esc(it.notes)}</dd>
{forbidden}
</dl></div></details>"""
        )
    return "".join(cards)


PLOT_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {
        "family": "ui-monospace, SFMono-Regular, Menlo, monospace",
        "size": 12,
        "color": "#4a4740",
    },
    "margin": {"l": 56, "r": 16, "t": 20, "b": 78},
    "legend": {"orientation": "h", "y": -0.3},
}


def plot(div_id: str, data: list, layout: dict) -> str:
    return (
        f'<div id="{div_id}" class="plot"></div>'
        f"<script>window.__PLOTS=window.__PLOTS||[];window.__PLOTS.push("
        f"[{json.dumps(div_id)},{json.dumps(data)},{json.dumps(layout)}]);</script>"
    )


def band_chart(by_arm: dict[str, list[dict]]) -> str:
    if "A4" not in by_arm or "A5" not in by_arm:
        return '<p class="note">Both configurations are needed for this chart.</p>'
    cats = sorted(by_arm["A4"][0]["by_category"])
    data = []
    for arm, colour, name in (
        ("A4", "#2f6b4a", "Python resolves the band"),
        ("A5", "#a8321f", "The model resolves the band"),
    ):
        means, errs = [], []
        for c in cats:
            m, s = mean_std(r["by_category"][c]["decision_accuracy"] for r in by_arm[arm])
            means.append(round(m, 4))
            errs.append(round(s, 4))
        data.append(
            {
                "type": "bar",
                "name": name,
                "x": [CATEGORY_LABELS.get(c, c) for c in cats],
                "y": means,
                "error_y": {"type": "data", "array": errs, "visible": True},
                "marker": {"color": colour},
            }
        )
    return plot(
        "bandchart",
        data,
        {
            **PLOT_LAYOUT,
            "barmode": "group",
            "yaxis": {"title": "accuracy", "range": [0, 1], "gridcolor": "#e3e0d8"},
            "xaxis": {"tickangle": -22},
        },
    )


def grounding_chart(a: dict[str, dict]) -> str:
    arms = [x for x in ("A0", "A1", "A4") if x in a]
    if len(arms) < 2:
        return ""
    names = {"A0": "Model alone", "A1": "+ retrieval and tools", "A4": "Full system"}
    return plot(
        "grounding",
        [
            {
                "type": "bar",
                "x": [names.get(x, x) for x in arms],
                "y": [round(a[x]["metrics"]["decision_accuracy"][0], 4) for x in arms],
                "marker": {"color": ["#a8321f", "#8a6a12", "#2f6b4a"][: len(arms)]},
                "text": [f"{a[x]['metrics']['decision_accuracy'][0]:.3f}" for x in arms],
                "textposition": "outside",
            }
        ],
        {
            **PLOT_LAYOUT,
            "showlegend": False,
            "yaxis": {"title": "accuracy", "range": [0, 1.1], "gridcolor": "#e3e0d8"},
            "margin": {"l": 56, "r": 16, "t": 20, "b": 42},
        },
    )


def sensitivity(by_arm: dict[str, list[dict]]) -> str:
    names = list(WEIGHTING_SETS)
    head = "".join(f"<th>{esc(n.replace('_', ' '))}</th>" for n in names)
    rows = []
    for arm in by_arm:
        its = items_of(by_arm[arm])
        cells = "".join(f"<td>{risk_score(its, WEIGHTING_SETS[n]):.3f}</td>" for n in names)
        rows.append(f"<tr><th>{esc(arm)}</th>{cells}</tr>")
    return (
        '<div class="scroll"><table class="grid">'
        f"<thead><tr><th>Arm</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def main() -> int:
    by_arm, manifest = load()
    if not by_arm:
        print("No run files in reports/raw/. Run: python eval/runner.py")
        return 1

    a = aggregate(by_arm)
    primary = a.get("A4") or next(iter(a.values()))
    a4_items = items_of(by_arm["A4"]) if "A4" in by_arm else []
    is_stub = manifest.get("provider") == "stub"

    cat_table, weakest, weakest_acc, weakest_id = category_table(by_arm)
    weakest_note = WEAKEST_NOTE.get(weakest_id, "it is the category with the least headroom")

    acc = primary["metrics"]["decision_accuracy"][0]
    over = primary["metrics"]["over_permission_rate"][0]
    under = primary["metrics"]["under_permission_rate"][0]
    abst = primary["metrics"]["abstention_f1"][0]
    traj = primary["metrics"]["trajectory_validity"][0]

    def acc_of(arm: str) -> float:
        return a[arm]["metrics"]["decision_accuracy"][0] if arm in a else 0.0

    def tb(arm: str) -> float:
        if arm not in by_arm:
            return 0.0
        return mean_std(
            r["by_category"]["threshold_boundary"]["decision_accuracy"] for r in by_arm[arm]
        )[0]

    import plotly

    pkg = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    plotly_src = pkg.read_text(encoding="utf-8") if pkg.exists() else ""

    stub_banner = (
        """<div class="banner bad"><b>This run used the deterministic stub provider, not a
language model.</b> The numbers measure the deterministic pipeline only — band resolution,
policy lookup, retrieval, routing and guardrails — and say nothing about model behaviour.
Set <code>LLM_PROVIDER</code> and re-run <code>make eval</code>.</div>"""
        if is_stub
        else ""
    )
    unavailable = [x for x, v in a.items() if v["unavailable"]]
    unav_banner = (
        f"""<div class="banner warn"><b>Provider unavailable for {esc(", ".join(unavailable))}.</b>
Every model call in those configurations failed, so the system fell back to its
deterministic draft. Those rows show the fallback's scores, not the model's.</div>"""
        if unavailable
        else ""
    )

    freeze_badge = (
        '<span class="badge ok">frozen</span>'
        if manifest.get("benchmark_matches_freeze")
        else '<span class="badge bad">HASH MISMATCH</span>'
    )

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HazeReady — evaluation</title>
<style>
:root {{
  --paper:#faf9f7; --panel:#fff; --line:#e3e0d8;
  --ink:#1a1a18; --soft:#4a4740; --mute:#78756c;
  --good:#2f6b4a; --warn:#8a6a12; --bad:#a8321f;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);
 font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:1000px;margin:0 auto;padding:2.5rem 1.25rem 5rem}}
h1{{font-size:2rem;margin:0 0 .3rem;letter-spacing:-.02em}}
h2{{font-size:1.3rem;margin:3.5rem 0 .5rem;letter-spacing:-.015em;line-height:1.3}}
h2 .qn{{color:var(--mute);font-family:var(--mono);font-size:.8rem;
 display:block;margin-bottom:.2rem;letter-spacing:.09em;text-transform:uppercase}}
h3{{font-size:1rem;margin:2rem 0 .4rem}}
p{{margin:.7rem 0;max-width:74ch}}
.sub{{color:var(--mute);margin:0 0 1.5rem;max-width:74ch}}
code{{font-family:var(--mono);font-size:.88em;background:#f1efea;
 padding:.1em .35em;border-radius:3px}}
.meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
 gap:.5rem 1.5rem;font-family:var(--mono);font-size:.78rem;background:var(--panel);
 border:1px solid var(--line);border-radius:8px;padding:.9rem 1.1rem}}
.meta span.k{{color:var(--mute);display:block;font-size:.68rem;text-transform:uppercase;
 letter-spacing:.07em}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));
 gap:.75rem;margin:1.25rem 0}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:.9rem 1rem}}
.card.good{{border-color:rgba(47,107,74,.45);background:rgba(47,107,74,.05)}}
.card.bad{{border-color:rgba(168,50,31,.45);background:rgba(168,50,31,.05)}}
.card .v{{font-family:var(--mono);font-size:1.7rem;font-variant-numeric:tabular-nums;
 letter-spacing:-.03em}}
.card .l{{font-size:.82rem;margin-top:.1rem}}
.card .n{{color:var(--mute);font-size:.71rem;margin-top:.25rem;line-height:1.35}}
.lede{{font-size:1.05rem;line-height:1.6;border-left:3px solid var(--good);
 padding-left:1rem;margin:1.25rem 0;max-width:72ch}}
.scroll{{overflow-x:auto;max-width:100%;margin:1rem 0;border:1px solid var(--line);
 border-radius:8px;background:var(--panel)}}
table.grid{{border-collapse:collapse;width:100%;font-size:.85rem}}
table.grid th,table.grid td{{padding:.55rem .75rem;text-align:right;
 border-bottom:1px solid var(--line);white-space:nowrap}}
table.grid thead th{{background:#f6f4ef;font-weight:600;font-size:.75rem;color:var(--soft)}}
table.grid tbody th,table.grid thead th:first-child{{text-align:left}}
table.grid tbody tr:last-child td,table.grid tbody tr:last-child th{{border-bottom:0}}
table.grid td{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.lab{{display:block;font-weight:600}}
.code{{display:block;font-family:var(--mono);font-size:.7rem;color:var(--mute)}}
.blurb{{display:block;font-weight:400;color:var(--mute);font-size:.74rem;
 white-space:normal;max-width:44ch;line-height:1.4}}
td.best{{background:rgba(47,107,74,.13);font-weight:600}}
td.weak{{background:rgba(168,50,31,.13);font-weight:600}}
.sd{{color:var(--mute);font-size:.78em;margin-left:.3em}}
.dir{{color:var(--mute);margin-left:.25em}}
.confusion td{{text-align:center}}
.confusion td.diag{{background:rgba(47,107,74,.16);font-weight:700}}
.confusion td.overperm{{background:rgba(168,50,31,.15)}}
.banner{{border-radius:8px;padding:.9rem 1.1rem;margin:1.25rem 0;font-size:.88rem;
 border:1px solid;max-width:74ch}}
.banner.bad{{border-color:var(--bad);background:rgba(168,50,31,.07)}}
.banner.warn{{border-color:var(--warn);background:rgba(138,106,18,.08)}}
.badge{{font-family:var(--mono);font-size:.64rem;padding:.1rem .38rem;border-radius:3px;
 text-transform:uppercase;letter-spacing:.05em;color:#fff}}
.badge.bad{{background:var(--bad)}} .badge.ok{{background:var(--good)}}
details.fail{{border:1px solid var(--line);border-radius:8px;margin:.45rem 0;background:var(--panel)}}
details.fail summary{{cursor:pointer;padding:.65rem .85rem;font-size:.85rem;
 display:flex;gap:.7rem;align-items:center;flex-wrap:wrap}}
details.fail .cat{{color:var(--mute);font-size:.76rem}}
details.fail .gp{{margin-left:auto;font-family:var(--mono);font-size:.75rem}}
.fb{{padding:0 .85rem 1rem;border-top:1px solid var(--line)}}
.fb .q{{font-style:italic;margin:.75rem 0}}
.fb dl{{display:grid;grid-template-columns:minmax(120px,auto) 1fr;gap:.3rem .9rem;
 font-size:.82rem;margin:0}}
.fb dt{{color:var(--mute)}} .fb dd{{margin:0}}
.diag{{font-weight:600}} .rat{{color:var(--soft)}}
.err{{color:var(--bad);font-family:var(--mono);font-size:.78rem}}
.plot{{width:100%;height:330px;margin:1rem 0}}
.note{{color:var(--mute);font-size:.86rem;max-width:74ch}}
.ok{{color:var(--good)}}
ul{{max-width:74ch}} ul li{{margin:.4rem 0}}
details.more summary{{cursor:pointer;color:var(--mute);font-size:.85rem;margin:1rem 0 0}}
footer{{margin-top:4rem;padding-top:1rem;border-top:1px solid var(--line);
 color:var(--mute);font-size:.78rem}}
</style></head><body><div class="wrap">

<h1>HazeReady — evaluation</h1>
<p class="sub">Can this system be trusted with a threshold decision? Six questions,
answered from a 180-item benchmark that was frozen before the first run.</p>

<div class="meta">
<div><span class="k">Model</span>{esc(manifest.get("provider", "—"))} / {esc(manifest.get("model", "—"))}</div>
<div><span class="k">Benchmark</span>{esc(manifest.get("n_items", "—"))} items {freeze_badge}</div>
<div><span class="k">Runs per configuration</span>{esc(manifest.get("runs_per_arm", "—"))}</div>
<div><span class="k">Run at</span>{esc(str(manifest.get("finished_at", "—"))[:16])}</div>
<div><span class="k">Commit</span>{esc(manifest.get("git_commit", "—"))}</div>
<div><span class="k">Machine</span>{esc(platform.platform().split("-")[0])} · Python {esc(platform.python_version())}</div>
</div>

{stub_banner}
{unav_banner}

<h2><span class="qn">Question 1</span>Does it work?</h2>

<div class="cards">
{stat(f"{acc:.0%}", "correct decisions", "exact match on a 5-point scale", "good" if acc >= 0.8 else "")}
{stat(f"{over:.1%}", "over-permissive", "said it was safer than guidance allows", "bad" if over > 0.15 else "good")}
{stat(f"{under:.1%}", "over-cautious", "stricter than needed — a usability cost")}
{stat(f"{abst:.2f}", "refusal F1", "refusing when guidance is silent")}
{stat(f"{traj:.0%}", "band resolved first", "Python ran before any band claim")}
</div>

<p class="lede">On {int(round(acc * 100))} questions in 100 the system gives the decision the
published guidance requires. The errors that matter — telling someone an activity is safer
than the guidance allows — occur on {over:.1%} of items. It errs toward caution rather than
permission, which is the direction you want when the downside is children outdoors at
PSI 210.</p>

<h2><span class="qn">Question 2</span>Does routing the arithmetic to Python actually matter?</h2>

<p>This is the design bet the system rests on. Band boundaries are closed integer
intervals — 100 is Moderate, 101 is Unhealthy — and the obligation changes at that line.
The system resolves the band in a 40-line Python function and hands the model the result.</p>

<p>The two configurations below are identical in every other respect: same corpus, same
retrieval, same prompts, same guardrails. The only difference is who compares the numbers.</p>

{arm_table(a, ["A4", "A5"])}
{band_chart(by_arm)}

<p class="lede">Moving that one comparison into the model costs
<b>{acc_of("A4"):.3f} → {acc_of("A5"):.3f}</b> overall, and
<b>{tb("A4"):.3f} → {tb("A5"):.3f}</b> on questions that sit at a band edge — exactly where
the obligation flips, and exactly where a confident wrong answer does harm.</p>

<h2><span class="qn">Question 3</span>Does grounding actually matter?</h2>

<p>The same model, the same questions, with nothing but its own knowledge — no corpus, no
retrieval, no live reading, no band resolver.</p>

{grounding_chart(a)}
{arm_table(a, ["A0", "A4"])}

<p>Answering from memory alone gets {acc_of("A0"):.0%} of decisions right. That is the
honest baseline for "just ask a model about haze rules", and it is why the corpus, the
policy matrix and the citation machinery exist.</p>

<h2><span class="qn">Question 4</span>Do the remaining components earn their place?</h2>

<p>Each row changes exactly one thing against the full system. Read it as a cost-benefit
table, not a leaderboard — and note that <b>accuracy is deliberately flat across the
retrieval rows</b>. That is structural, not a null result: the decision comes from a
deterministic lookup keyed by role and band, and retrieval is not an input to it. Retrieval
decides which sources get cited, so it is judged on citation recall and latency.</p>

{arm_table(a, COMPONENTS)}

<p class="note">Reranking is the clearest verdict: a fraction of a point of citation recall
for a large multiple of the latency, on a 64-document corpus that hybrid fusion already
orders well. It ships off by default and stays configurable, because that calculus changes
as a corpus grows.</p>

<details class="more"><summary>Show every metric for every configuration</summary>
{arm_table(a, list(a), HEADLINE + DETAIL)}
</details>

<h2><span class="qn">Question 5</span>Where does it fail?</h2>

{cat_table}

<p class="lede">The weakest category is <b>{esc(weakest)}</b> at {weakest_acc:.0%} — and it is
worth dwelling on, because {esc(weakest_note)}. That is where the remaining risk sits.</p>

<h3>Which way do the errors go?</h3>
<p class="note">Correct answer down the side, given answer across the top. Shaded cells are
over-permissive — less restrictive than the guidance. Those are the ones that could hurt
someone; the mirror image costs usability, not safety.</p>
{confusion(a4_items)}

<h3>The ten worst answers</h3>
<p class="note">Expand a card for the question, the tool trajectory, what was cited, and a
one-line diagnosis.</p>
{failure_gallery(a4_items)}

<h2><span class="qn">Question 6</span>What you should not conclude from this</h2>

<ul>
<li><b>The benchmark and the policy matrix share an author.</b> The same person wrote the
correct answers and the rules the system looks them up in, from the same reading of the
corpus. A systematic misreading of the published guidance would appear in both, and this
benchmark could not detect it. This is the largest threat to everything above.</li>
<li><b>No second annotator, so no agreement statistic.</b> Cohen's κ is not reported
because none was measured. The harness, a stratified 30-item subset and the protocol are in
the repo ready to run; a fabricated number would be worse than none.</li>
<li><b>The system was iterated against this benchmark.</b> It was frozen first and its hash
is recorded above, but no held-out split was reserved, so these numbers are partly
in-sample. The fixes were principled defects — a crash, an unparsed forecast range, a
guardrail checking the wrong proposition — not item-specific patches.</li>
<li><b>180 items is small.</b> The smallest category has 20. Differences of a few points
per category are not resolvable at this size.</li>
<li><b>The corpus is a snapshot</b> dated 2026-08-08, and two sources could not be fetched
at all: <code>haze.gov.sg</code> disallows automated access in robots.txt and
<code>moh.gov.sg</code> refused the request. The 1-hour PM2.5 microgram boundaries are
therefore unverified, marked as such, and a benchmark item checks that the system refuses
questions turning on them.</li>
<li><b>Citation precision is automated and approximate.</b> A correct citation outside the
expected set scores as a miss, so the figure is a lower bound. No human span-level check
was performed.</li>
<li><b>Repeated runs share a response cache.</b> Runs after the first are served from it,
so the reported standard deviations understate real between-run variance.</li>
</ul>

<h3>The risk score is a judgement call</h3>
<p class="note">It weights an over-permissive error 2–3× an over-cautious one, and
answering-where-you-should-refuse at 2.5×. Those weights are argued, not derived from harm
data. Below, every configuration is rescored under three weightings — including one that
removes the asymmetry entirely — so you can check whether the ranking survives disagreeing
with us.</p>
{sensitivity(by_arm)}

<footer>
Generated by <code>eval/report_builder.py</code> from the run files in
<code>reports/raw/</code>. Self-contained — no network access required to view.
HazeReady is a decision-support prototype. Official advisories at nea.gov.sg govern.
</footer>
</div>
<script>{plotly_src}</script>
<script>
(function () {{
  var q = window.__PLOTS || [];
  if (typeof Plotly === "undefined") {{
    document.querySelectorAll(".plot").forEach(function (el) {{
      el.textContent = "Charts unavailable: the Plotly bundle was not inlined at build time.";
      el.style.cssText += "color:var(--mute);font-size:.85rem;height:auto;padding:1rem;border:1px solid var(--line);border-radius:8px";
    }});
    return;
  }}
  q.forEach(function (p) {{
    try {{ Plotly.newPlot(p[0], p[1], p[2], {{displayModeBar:false, responsive:true}}); }}
    catch (e) {{ var el = document.getElementById(p[0]); if (el) el.textContent = "Chart failed: " + e.message; }}
  }});
}})();
</script>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size / 1e6:.2f} MB)")
    print(f"  configurations: {', '.join(a)}")
    print(
        f"  A4 accuracy {acc:.3f} | over-permission {over:.3f} | weakest {weakest} {weakest_acc:.3f}"
    )
    if not plotly_src:
        print("  WARNING: Plotly not inlined; charts will not render.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
