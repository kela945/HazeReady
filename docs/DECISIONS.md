# Development narrative: decisions, iterations and discards

Written as the work happened, including the things that did not work. Where I
disagreed with the build specification I implemented it first and recorded the
objection here, as the spec requires.

---

## 1. The core architectural bet

**Decision: numeric threshold comparison never touches the language model.**

Singapore's haze guidance is threshold-conditional. At 24-hour PSI 100 a
preschool has no activity restriction; at 101 it must minimise outdoor
activities. One index point changes the obligation.

Language models are poor at exactly this and fail *silently* — a wrong band
produces a fluent, confident, correctly-formatted advisory. So `resolve_psi_band`
is 40 lines of pure Python over closed integer intervals, and the model receives
the already-resolved band.

The A5 ablation exists to quantify what that buys. Everything else is held
constant and only the band comparison moves into the model.

**What this cost.** The model cannot fix a bad band, so the deterministic path
has to be right. That pushed effort into the policy matrix and its validation,
which turned out to be the highest-leverage work in the project.

---

## 2. Discarded approaches

### 2.0 Provider choice: Anthropic Haiku 4.5 over a larger model

The model's job is to compose and explain a decision the deterministic engine has
already made, and to pick which supplied sources to cite. It cannot resolve
bands, cannot do threshold arithmetic, and cannot override the decision. That is
short-context, shallow-reasoning work, so the smallest current Claude model is
the right tool; paying Opus rates to rephrase a validated lookup would be
indefensible at national scale.

Two consequences worth stating. First, **structured outputs** are used rather
than JSON-mode prompting — the response is constrained to the advisory schema at
decode time, so a malformed advisory cannot reach the guardrail chain at all.
Second, **extended thinking is deliberately off**: the reasoning this system
depends on lives in Python, and `effort` is not even a valid parameter on Haiku
4.5. A migration to a larger model would need to revisit both, plus drop
`temperature`, which newer models reject.

### 2.1 Neural NLI for citation entailment — discarded

The plan was a cross-encoder NLI model to verify each claim against its cited
span. I discarded it after thinking about the failure mode: a general-purpose
NLI model is not calibrated for "does this span *license* this obligation", and
when it is wrong it is wrong invisibly. Replacing one opaque judgement with
another does not improve grounding.

Replaced with a legible rule (`verify_claim_against_spans`): every numeral in a
claim must appear in some span, plus content-word overlap thresholds. Crude, but
its failure mode is conservative and inspectable, and the A7 ablation measures
what it catches. This is a real limitation and it is in the report.

### 2.2 LLM-as-judge for decision quality — discarded

The obvious methodology, and wrong here. A preschool either is or is not
required to minimise outdoor activity at PSI 165, and the answer is determinable
from published guidance. Where ground truth is determinable, a hand-curated
benchmark dominates, because **the judge inherits the same threshold-reasoning
weakness being measured**.

I ended up using no LLM judge at all. The spec anticipated confining it to
free-text rationale quality with a κ against human labels; without a second
human annotator that κ could not be computed, and a judge score with no
calibration is not evidence. Reporting nothing is more honest than reporting an
uncalibrated number.

### 2.3 Verifying matrix obligations against retrieval — discarded after it broke things

The first guardrail implementation checked *every* obligation against the
retrieved spans. It produced spurious abstentions on well-covered questions: a
correct, cited obligation would be stripped simply because the top-5 retrieval
worded it differently, and when all obligations were stripped the chain
abstained.

The fix was a correction of category. Matrix obligations are grounded **by
construction** — each carries a `source_quote` whose character span was resolved
against the cited document at load time, and the build fails if it does not
resolve. Re-checking them against a *retrieval* tests a weaker and different
proposition. The entailment stage now polices only claims the model introduced
on its own, which is where confabulation actually enters.

Same class of error appeared in `numeric_integrity`: numerals inside matrix
statements ("at least 30 minutes of outdoor activity daily") were treated as
unsourced because they were absent from the top-k spans. Same fix.

### 2.4 LangChain — not adopted

The spec forbade it and I agree. The agent loop is ~200 lines and every hop is
auditable. Debugging why a guardrail fired through a framework's abstractions
would have cost more than writing the loop. The cost is that provider quirks are
handled by hand in `app/llm/providers/`, which is about 200 lines of adapter.

### 2.5 An approximate vector index — not adopted

FAISS `IndexFlatIP` over 64 chunks is exact and instant. An approximate index
would add tuning parameters and reproducibility risk to buy latency that does
not exist at this scale.

---

## 3. Things the frozen benchmark caught

The benchmark was authored and frozen before the first evaluation run. The first
run scored **0.650** decision accuracy. The failures were system bugs, not
benchmark bugs, and fixing them took accuracy to **0.844** with over-permission
falling from 0.311 to 0.117.

| # | Defect | Consequence | Fix |
|---|---|---|---|
| 1 | Forecast ranges were never parsed | "Forecast 90 to 130" resolved against the *live fixture*, so `forecast_temporal` scored 0.15 with 0.85 over-permission | `extract_stated_forecast`; plan against the worst band the range reaches |
| 2 | `worse_band` compared a PM2.5 band with a PSI band | Hard crash on item `tb_037` | Guard raises; index mismatch now abstains, which is the gold answer |
| 3 | Matrix-sourced numerals treated as unsourced | Spurious abstention on PSI 49/50 preschool items | Numerals in validated matrix statements are sourced by construction |
| 4 | Route terms matched as substrings | `school` matched inside `preschool`; `pe` would match inside `open` | Word-boundary matching |
| 5 | Route-term recall too narrow | Questions naming the *activity* but not the institution ("Outdoor PE?") fell to `general_public`, dropping the vulnerable-cohort posture. Role routing was 0.644 | Expanded terms; institutional roles beat `general_public` on a tie |
| 6 | Plurals not matched | `k2` failed against "the K2s", so preschool scored zero hits. Caught by a unit test, not the benchmark | Optional trailing `s` on the final word |
| 7 | Coverage-gap matching was ordered-substring | "What size air purifier" missed the trigger `purifier size`, so the system answered a question guidance does not cover | Bag-of-words matching, longest trigger wins |
| 8 | Named cohorts ignored | "One of my workers is pregnant" got the healthy-employee posture | `extract_cohort`; apply the matrix `cohort_variants` |

Two further defects appeared only once a **real** model was wired in, and neither
was reachable with the stub:

| # | Defect | Consequence | Fix |
|---|---|---|---|
| 9 | `numeric_integrity` rejected numerals the asker wrote | The model restated the question — *"outdoor play in **20** minutes"* — and the guardrail flagged `20` as an invented reading, forcing a spurious abstention on a well-covered question. The stub never echoed the question, so this was invisible | Numerals present in the question are sourced by construction: they are traceable to the asker, not fabricated |
| 10 | LLM failure degraded **silently** | With the API returning 400, the system fell back to the deterministic matrix and served a correct-looking answer whose rationale read "composed from the deterministic policy matrix" — with nothing telling the operator the model was down | `Advisory.llm_error`, surfaced in the UI above the reasoning trace and recorded in telemetry |

Defect 10 is the more important of the two. A health-safety tool that quietly
degrades is worse than one that fails loudly, and the fallback was *good enough
to hide the problem* — every decision and band was still correct, because those
come from Python. That is the deterministic design working as intended; it should
still say so.

**Overfitting risk, stated honestly.** The benchmark was frozen first and its
hash is recorded in every result file, but I iterated the system against the
full 180 items and no held-out split was reserved. The mitigation is that every
fix above is a principled defect — a crash, an unparsed input, a
wrong-grounding-source bug — rather than an item-specific patch. The reported
numbers are nonetheless partly in-sample and the report says so.

---

## 4. Things I would flag as weak

**Role routing is the largest remaining error source** and the component most
dependent on a real language model. The deterministic keyword pass reaches 0.878
under the stub; the LLM stage-2 router never runs because the stub cannot
classify. With a real model this should improve substantially, and that gap is
the clearest illustration of why the stub run is a floor, not a result.

**`out_of_knowledge_base` is the weakest category** (0.700). Coverage-gap
matching is keyword-driven, so a question that reaches an unpublished topic by
unusual phrasing gets answered instead of abstained. This is the safety-relevant
failure mode and the report calls it out by name.

**Chunking is a no-op on the shipped corpus.** Documents are atomic by
construction, so 64 documents produce 64 chunks. The structure-aware chunker and
its never-split-a-band-table guard exist and are unit-tested with synthetic
documents, because a deployment ingesting full agency pages needs them
immediately — but on this corpus they do no work. Claiming sophisticated
chunking here would be an overclaim.

**Hybrid retrieval is not demonstrated to pay.** A2 buys +0.006 citation recall
over dense-only A1. The rationale for BM25 (exact numerals and scheme names that
dense embeddings blur) is sound in principle, but on a corpus this small and
this uniformly on-topic, dense already surfaces the right documents. Honest
reading: cheap insurance whose value is unproven at this scale.

**Reranking does not pay at all here** — 57× p50 latency for +0.009 citation
recall. Kept as an off-by-default profile because the calculus changes with
corpus size.

---

## 5. Deviations from the specification

| Spec | What I did | Why |
|---|---|---|
| §5 `lookup_role_obligations(role, band)` | Kept the signature; added `cohort_variants` to the returned `ObligationSet` and a separate cohort extractor | The published guidance differentiates healthy from susceptible at 101–200. Ignoring that under-protects a named individual. Extending the tool signature would have been the bigger deviation |
| §8.2 second annotator, report Cohen's κ | Implemented the harness; **reported no κ** | No second annotator was available. A fabricated agreement statistic is worse than none. `kappa.py`, the 30-item stratified subset and the protocol are all ready |
| §13 `docker compose up` | Dockerfile and compose file provided but **not executed** | Docker is not installed on the build machine and the user explicitly scoped it out. Marked unverified in the README rather than claimed |
| §3.1 local model `qwen3:8b` | An Ollama arm was configured, then **removed from the grid** | It could not be run (the model is not pulled on this machine), and it answers a procurement question — "is a small local model good enough?" — rather than a question about this system's design. The runner still detects provider failure and banners any unavailable arm, so a future local arm cannot silently report fallback scores as results |
| §8.6 report is "committed" | Committed, and regenerated from committed raw results | No deviation, noted for completeness |
| §4.1 "60–100 documents" | 64 | Met, but see §4 above on what fraction is agency-sourced |

**Objection recorded, as §0 requires.** The spec's §8.5 ablation grid treats
A1/A2/A3 as comparable to A4 on *decision accuracy*. In this architecture that
comparison is structurally empty: the decision comes from a deterministic lookup
keyed by `(role, band, index)`, and retrieval is not an input to it. Retrieval
determines which sources are cited and what the rationale may say. I implemented
the grid as specified and added a dedicated report section comparing the
retrieval arms on citation recall and latency, which are the metrics retrieval
can actually move.

---

## 6. Evaluation status

The committed report is a **real model evaluation**: `claude-haiku-4-5`, eight
arms, three runs each, against the frozen 180-item benchmark.

An earlier iteration was run with `LLM_PROVIDER=stub`, a deterministic non-LLM
composer. That was never presented as a model result — the report bannered it in
red and A5/A7/A8 carried specific warnings — but it earned its place twice over.
It let the whole pipeline be built and tested with no API access, and it isolated
a **floor**: the gap between the stub and Haiku on the same benchmark is the
model's actual contribution, which is a more informative baseline than "no
retrieval" alone. It also remains the reproducibility path — `make demo` and the
test suite run against it with no key and no network.

The stub run's most useful property turned out to be diagnostic. Because it
removed the model entirely, every failure it produced was a failure of the
deterministic scaffolding, which is how defects 1–8 above were isolated cleanly.
Defects 9 and 10 then required the opposite — a real model — because they are
failures of the *interaction* between model output and the guardrails.
