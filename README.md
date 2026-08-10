# HazeReady

**Demo video:** [Watch the demo](https://youtu.be/cKQYkXzBkf0)

A role-aware, forecast-aware, strictly-grounded haze advisory assistant for
Singapore. It answers operational questions — *"24-hour PSI just hit 101, my K1
class has outdoor play in twenty minutes, do I cancel?"* — with citations to
published agency guidance, and **refuses to answer when that guidance does not
cover the case**.

> Decision-support prototype. Official advisories at
> [nea.gov.sg](https://www.nea.gov.sg) govern. Not medical or legal advice.

---

## 1. The problem

During a haze episode the binding constraint is **not information scarcity**.
NEA publishes PSI and PM2.5 hourly and everyone knows the colour bands. The
constraint is that operational guidance is:

- **Threshold-conditional.** Obligations change discontinuously at PSI 50 / 100 /
  200 / 300. At 24-hour PSI 100 a preschool has no activity restriction; at 101
  it must minimise outdoor activities. One index point changes the obligation.
- **Role-specific.** At the same reading, a preschool operator, a WSH officer, an
  eldercare manager and an event organiser face different obligations, published
  by different agencies.
- **Made ahead of the reading.** The decision to cancel tomorrow's excursion is
  taken this evening, against a *forecast* — which NEA publishes as a **range**,
  not a number.
- **Scattered.** NEA, MOH, MOM/WSH and MOE/ECDA publish separately.

**Users:** frontline decision-makers in institutions with duty-of-care
obligations — preschools, schools, eldercare facilities, worksites, event
organisers — plus a general-public mode.

---

## 2. The design decision this project is built around

**Numeric threshold comparison never touches the language model.**

`resolve_psi_band` is ~40 lines of pure Python over closed integer intervals. The
model receives an already-resolved band, an already-looked-up obligation set, and
a set of retrieved sources. It composes and explains; it does not decide.

This is a deliberate constraint, not an optimisation, and it is measured. Models
are poor at exactly this kind of boundary arithmetic and they fail *silently* — a
wrong band produces a fluent, confident, correctly-formatted advisory. The
evaluation includes an ablation arm (**A5**) that moves the band comparison into
the same model with everything else held constant, specifically to quantify what
that costs.

Four AI components are load-bearing and each is measured independently:

| Layer | What the AI does | Measured by |
|---|---|---|
| Role routing | Selects the governing role skill | Role-routing accuracy |
| Retrieval | Hybrid BM25 + dense + RRF over a multi-agency corpus | Citation recall / precision |
| Agentic reasoning | Live data → deterministic band → role lookup → retrieval → synthesis | Decision accuracy, trajectory validity |
| Guardrail | Numeric integrity, entailment, conflict, over-permission | Over-permission rate, abstention F1 |

---

## 3. Quickstart

Requires **Python 3.11** and **Node 20+**. Verified on macOS (arm64).

```bash
git clone <this-repo> && cd haze-ready
cp .env.example .env          # then set LLM_API_KEY
make setup                    # venv, deps, frontend bundle, corpus validation, index
make run                      # http://localhost:8000
```

`make setup` takes a few minutes: it installs PyTorch and downloads the
`bge-small-en-v1.5` embedding weights (~130 MB), then builds the FAISS + BM25
index from `data/corpus/`.

### Run it with no API key and no network

```bash
make demo     # OFFLINE_MODE=true LLM_PROVIDER=stub
```

Serves committed fixtures and composes answers with a deterministic non-LLM
provider. Every decision, band, citation and abstention is still correct, because
those come from Python — but the prose is templated, and the UI says so. This is
the reproducibility path, not the product.

### Other commands

```bash
make test        # 116 tests + corpus/policy-matrix validation
make eval        # full 8-arm ablation grid, rebuilds reports/eval_report.html
make report      # rebuild the report from existing reports/raw/
make validate    # corpus + policy matrix only
make lint
make help
```

**Docker:** `Dockerfile` and `docker-compose.yml` are provided but were **never
built or run** — Docker was not installed on the build machine. They are marked
as unverified in their own headers. The verified path is the native one above.

---

## 4. Architecture

```
React SPA (Vite + TS + Tailwind)          /  advisory console
                                          /monitor  operations dashboard
        │ REST + SSE                      /report   evaluation report
┌───────▼──────────────────────────────────────────────────┐
│ FastAPI                                                  │
│  Orchestrator  route role → fetch reading → RESOLVE BAND  │
│                → lookup obligations → retrieve → compose  │
│                → guardrail chain            (max 6 hops)  │
│                                                           │
│  RAG: FAISS IndexFlatIP + BM25Okapi, RRF k=60            │
│  Policy matrix: 34 rows, every row quote-to-span verified │
│  Telemetry: SQLite + WAL, /metrics in Prometheus format   │
└───────┬──────────────────────────────────────────────────┘
        ├── Anthropic (claude-haiku-4-5) │ or stub / ollama / …
        └── data.gov.sg  PSI + PM2.5
```

Independent calls (live reading, hotspots, retrieval) run concurrently via
`asyncio.gather`. The agent loop is hand-written, not LangChain. `app/agent/orchestrator.py` is
1010 lines including the ablation wiring and context construction; the loop body
itself is short and every hop is auditable, which is what matters when a
guardrail misfires at 2am.

### The grounding contract

Every row of `data/policy_matrix.yaml` carries a **verbatim `source_quote`**. At
load time `app/policy.py` locates that quote inside the cited corpus document and
attaches the resulting character span. **A quote that does not appear verbatim
fails the build.** All 94 spans currently resolve, and
`tests/test_policy_and_corpus.py` enforces it.

This is what makes "grounded" checkable rather than rhetorical — the matrix
cannot assert something its cited source does not say, and clicking a citation in
the UI opens the source document scrolled to that exact span.

### Guardrail chain

Runs in order on every response:

1. **Numeric integrity** — every numeral traces to a tool output, a retrieved
   span, a validated matrix statement, or the asker's own question.
2. **Citation entailment** — claims the *model* introduced are checked against
   the retrieved spans. Matrix statements are exempt: they are grounded by
   construction via validated spans.
3. **Authority conflict** — two `primary` sources disagreeing are surfaced, not
   silently resolved.
4. **Over-permission** — the safety guardrail. A permissive answer needs an
   **explicit permissive statement** in a primary or secondary span. Permission
   inferred from the *absence* of a prohibition is rejected, and an
   `explanatory`-tier document can never supply it.
5. **Disclaimer injection** — non-removable.

### Abstention

Twelve coverage gaps in `data/coverage_gaps.yaml`, each pointing at the corpus
document that records the silence — so *"there is no guidance on this"* is itself
a grounded claim. The system abstains on school-closure thresholds, air-purifier
specification, individual medical management, haze work-rest cycles, and eight
more. Each abstention names the authority who can actually answer.

---

## 5. Evaluation

**Methodology: hand-curated benchmark + systematic ablation. No LLM-as-judge.**

> Threshold-conditional advisory questions have *objectively checkable* ground
> truth — a preschool either is or is not required to minimise outdoor play at
> 24-hour PSI 165, and the answer is determinable from published guidance. Where
> ground truth is determinable, a hand-curated benchmark dominates LLM-as-judge,
> because the judge inherits the same threshold-reasoning weakness being
> measured. No LLM judge is used anywhere in this evaluation; every metric is
> computed against an objective key.

**HazeQA:** 180 hand-authored items across six categories — `threshold_boundary`
(40), `role_conditioned` (40), `out_of_knowledge_base` (30), `multi_hop` (25),
`robustness_paraphrase` (25, Singlish), `forecast_temporal` (20). Frozen before
the first run; the SHA-256 is recorded in every result file and displayed in the
report header.

Full results, per-category breakdown, confusion matrix, failure gallery and
limitations: **`reports/eval_report.html`** (committed, self-contained, also
served at `/report`).

<!-- EVAL_RESULTS_START -->

**Run:** `anthropic` / `claude-haiku-4-5`, 3 runs per arm, 180 items, benchmark hash matches the freeze.

| Arm | What it changes | Accuracy ↑ | Over-perm ↓ | Abstention F1 ↑ | Risk ↓ | p50 ms |
|---|---|---|---|---|---|---|
| A0 | Model alone — no retrieval, no tools, no band resolver | 0.328 | 0.078 | 0.429 | 0.469 | 1,733 |
| A1 | Dense retrieval only | 0.907 | 0.044 | 0.953 | 0.155 | 3,901 |
| A2 | Hybrid retrieval (BM25 + dense) | 0.904 | 0.050 | 0.943 | 0.162 | 4,062 |
| A3 | Hybrid + cross-encoder reranker | 0.904 | 0.043 | 0.941 | 0.146 | 4,773 |
| **A4** | Full system | 0.906 | 0.050 | 0.947 | 0.161 | 4,264 |
| **A5** | Model does the band arithmetic | 0.587 | 0.272 | 0.838 | 0.669 | 4,293 |
| A7 | Without the entailment guardrail | 0.902 | 0.050 | 0.939 | 0.163 | 4,135 |
| A8 | Without role skills | 0.900 | 0.056 | 0.933 | 0.181 | 3,963 |

**The headline result.** A4 and A5 differ in exactly one thing: whether a 40-line Python function or the language model performs the band comparison. Overall accuracy moves 0.906 → 0.587; on the `threshold_boundary` items, where a single index point flips the obligation, it moves **0.950 → 0.708**.

**What grounding buys.** A0 is the same model with no retrieval, no tools and no deterministic band — 0.328 accuracy answering from its own knowledge, against 0.906 for the full system.

<!-- EVAL_RESULTS_END -->

### Cost-weighted risk score

An asymmetric loss: telling a preschool it is fine to send children outside at
PSI 210 is categorically worse than telling them to stay in at PSI 95.
Over-permissive errors are weighted 2–3×, over-restrictive 1×, answering where
the gold is abstention 2.5×. **These weights are a judgement call, not derived
from harm data**, and the report recomputes every arm under three weightings so a
reader can see whether the ranking survives a different judgement.

---

## 6. Deployment considerations

**Target user and environment.** Frontline operational staff — preschool
supervisors, WSH officers, eldercare managers — deciding on a phone, under time
pressure, during an episode. Not a public-facing chatbot.

**Cost and compute at scale.** Measured per-query cost with `claude-haiku-4-5` is
**$0.0039** (≈2,770 input + 220 output tokens at $1/$5 per MTok). Stated
assumption, not a surveyed figure: 2,000 covered institutions, 10% active on any
episode day, 5 queries each → 1,000 queries/day × $0.0039 = **$3.90/day**, or
**~$120/month** of continuous episode conditions. Retrieval adds no marginal API
cost: the embedding model is 384-dimensional and CPU-resident, and a 64-document
FAISS `IndexFlatIP` fits in tens of megabytes, so one small instance serves the
whole load. Inference cost is not the constraint at national scale; corpus
curation is.

**Three metrics to monitor.** (1) **Over-permission incidents** — the only error
class that can hurt someone; tracked from user feedback on `restrict`/`suspend`
answers. (2) **Out-of-corpus query rate** — queries whose top retrieval score
falls below threshold; the early warning that guidance changed and the corpus did
not. (3) **Abstention rate** — a sudden fall means the system started answering
things it previously declined.

**Deployment risk: corpus staleness during an active episode.** If NEA revises an
advisory mid-episode and the corpus is not re-indexed, the system confidently
cites superseded guidance — and confident wrongness during a health emergency is
worse than no system. **Detection:** the out-of-corpus rate on the dashboard,
plus a source-hash checker over every `source_url`. **Mitigation:** fail to
abstention when a source hash changes, rather than serving stale content.

_(247 words)_

---

## 7. Model selection

**`claude-haiku-4-5`**, the smallest current Claude model, selected on **task fit,
latency and cost-at-scale** — explicitly *not* on privacy, which would be a false
justification here: this system handles no personal data, so local inference
would buy nothing.

- **Task fit.** The model's job is deliberately narrow: compose and explain a
  decision the deterministic engine has already made, and choose which supplied
  sources to cite. It cannot resolve bands, perform threshold arithmetic, or
  override the decision. That is short-context, shallow-reasoning work — exactly
  Haiku's shape. Paying Opus rates to rephrase a validated lookup would be
  indefensible at national scale.
- **Latency.** Measured p50 end-to-end is in the seconds, on a decision someone
  is making with a class of children waiting.
- **Cost at scale.** See §6 — $1/$5 per MTok keeps a national deployment at
  ~$130/month.

**Structured outputs** constrain the response to the advisory schema at decode
time, so a malformed advisory cannot reach the guardrail chain. Extended thinking
is deliberately off: the reasoning this system depends on is in Python.

Swapping providers is one env var (`LLM_PROVIDER`). `anthropic`, `openrouter`,
`google`, `groq`, `ollama` and `stub` are implemented behind a thin
`LLMProvider` protocol — no LangChain.

**If the model is unavailable, the system says so.** It falls back to the
deterministic matrix and marks the answer as degraded in the UI and in telemetry.
An early version did this silently, which for a health-safety tool is the wrong
failure mode.

---

## 8. Data

64 curated markdown documents with mandatory provenance frontmatter. **37 are
traceable to a page this system actually fetched**; the rest are authored
interpretations and coverage notes, labelled as such and barred by the guardrail
from ever supplying permission.

**robots.txt was checked before any fetch, and it changed what this repo
contains.** `haze.gov.sg` disallows all non-whitelisted bots and `moh.gov.sg`
returned an access-denied response — so neither was fetched. The authoritative
1-hour PM2.5 microgram band table lives on `haze.gov.sg`, so those specific
numbers are marked `verified_against_source: false`, a coverage gap makes the
system abstain when a question turns on them, and benchmark item `ok_021` tests
exactly that.

Full accounting — provenance breakdown, licensing, privacy, fixtures, and what
the data does *not* cover: **[`docs/DATA.md`](docs/DATA.md)**.

**Privacy:** no personal data is collected, stored or transmitted. No accounts,
no session persistence beyond a per-query UUID. The telemetry schema is the
enforcement point — there is no column personal data could go in.

---

## 9. Honest limitations

The report's §12 is the full list. The three that matter most:

1. **Single annotator, shared with the policy matrix.** The same person authored
   the gold labels and `data/policy_matrix.yaml` from the same corpus reading. A
   systematic misreading of the published guidance would appear in both and this
   benchmark could not detect it. This is the largest validity threat here.
2. **No inter-annotator agreement.** The spec calls for a second annotator and a
   Cohen's κ. None was available, so **no κ is reported** — the harness
   (`eval/hazeqa/kappa.py`), the stratified 30-item subset and the protocol all
   ship ready to run. A fabricated agreement statistic would be worse than none.
3. **The system was iterated against this benchmark.** It was frozen first and
   the hash is recorded, but no held-out split was reserved, so the numbers are
   partly in-sample. Every fix was a principled defect — a crash, an unparsed
   forecast range, a wrong grounding source — not an item-specific patch. The
   development narrative lists all of them.

Also: chunking is a no-op on this corpus (documents are atomic by construction),
hybrid retrieval buys only +0.022 citation recall over dense-only at this scale,
reranking *loses* 0.019 citation recall while adding 57% to p95 latency, and the
forecast is *derived* from the current reading when the asker does not quote one
— labelled `derived` everywhere it appears.

---

## 10. Documentation

| Document | Contents |
|---|---|
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Development narrative: what was discarded and why, the eight defects the frozen benchmark caught, deviations from spec |
| [`docs/DATA.md`](docs/DATA.md) | Provenance, robots.txt findings, licensing, privacy, coverage gaps |
| [`docs/AI_ASSISTANCE.md`](docs/AI_ASSISTANCE.md) | How coding agents were used, what was rejected, what was verified by hand |
| [`eval/hazeqa/ANNOTATION_GUIDE.md`](eval/hazeqa/ANNOTATION_GUIDE.md) | Label definitions and the second-annotator protocol |

---

## 11. AI assistance

This project was built with heavy use of a coding agent. The full disclosure —
what was accepted, what was rejected, what was verified by hand, and where the
assistance most likely left weaknesses — is in
**[`docs/AI_ASSISTANCE.md`](docs/AI_ASSISTANCE.md)**.

The short version: the agent wrote most of the code and most of the prose. Its
most dangerous tendency was producing confident, well-formed artefacts that were
subtly wrong in ways that looked fine — an ablation arm scoring perfectly because
it had silently fallen back to a non-LLM path, a guardrail stripping correct
content because it was checking the wrong proposition. Each was caught by
insisting claims be *mechanically* checkable — the quote-to-span validator, the
provider-failure tracker, the frozen benchmark hash — rather than by reading the
output and finding it plausible.
