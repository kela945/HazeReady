# AI assistance disclosure

This project was built with heavy use of a coding agent (Claude Code). This
document says what that actually meant in practice — what was accepted, what was
rejected, and what was verified by hand.

---

## What the agent did

- Wrote the great majority of the Python and TypeScript, from a specification I
  supplied and refined.
- Drafted the 64 corpus documents, the 34-row policy matrix, the 180 benchmark
  items, and the six `SKILL.md` files.
- Built the evaluation harness, the metrics module, and the report generator.
- Ran the tooling: `robots.txt` checks, page fetches, the ablation grid, the
  test suite, and the browser-driven UI verification.

## What I directed rather than delegated

The decisions that determine whether this project is any good were specified up
front, not discovered by the agent:

- **Routing threshold arithmetic to deterministic Python**, and building an
  ablation arm specifically to quantify what that buys. This is the project's
  central claim and it was a design decision, not a suggestion.
- **The asymmetric cost model.** Over-permission is worse than over-restriction
  because the harms are not symmetric. The weights are a judgement call and the
  report says so, with a sensitivity table across three weightings.
- **Rejecting LLM-as-judge** on the grounds that the judge inherits the weakness
  being measured.
- **The abstention-first posture**: a confident wrong number during a health
  episode is worse than no answer.

---

## What I rejected from the agent's output

**Neural NLI for entailment.** The first design used a cross-encoder. I rejected
it: an NLI model is not calibrated for "does this span license this obligation",
and its errors are invisible. Replaced with a legible rule whose failure mode is
conservative. This makes the guardrail weaker on paper and more trustworthy in
practice, and the limitation is in the report.

**Fabricated evaluation numbers.** The agent initially wanted to report a
Cohen's κ. There was no second annotator, so there is no κ. The harness ships
ready to compute one. Similarly, cost defaults to `$0.0000` rather than a
plausible-looking figure when the token rates are unset.

**Silently passing arms.** When the local-model arm (then A6, on Ollama) could
not reach a model, the system fell back to the deterministic draft and scored
*identically to A4* — a completely false result that looked fine. I had
provider-failure tracking added so the runner detects it and the report banners
the arm as unavailable. The arm was later cut from the grid entirely: it asked a
procurement question rather than a question about this system's design, and an
arm that cannot run contributes a banner, not a result.

**Silent degradation in the product itself.** The same class of problem appeared
again when the Anthropic key was first wired in with no account credit: every
call 400'd, the system fell back to the deterministic matrix, and it served
answers that were *correct* — right decision, right band, right citations,
because those come from Python — with a rationale reading "composed from the
deterministic policy matrix" and nothing telling the operator the model was down.
The fallback was good enough to hide its own trigger. I had the error surfaced on
the advisory, in the UI above the reasoning trace, and in telemetry.

**Scraping `haze.gov.sg`.** Its `robots.txt` disallows all non-whitelisted bots.
The authoritative PM2.5 band table lives there. The agent's first instinct was to
fetch it anyway. It was not fetched; the gap is documented, the affected numbers
are marked unverified, and a benchmark item tests that the system abstains on
questions turning on them.

**Overclaiming in prose.** Several drafts described the chunker as if it were
doing meaningful work on the shipped corpus. It is not — documents are atomic, so
64 documents produce 64 chunks. That is now stated plainly in `DECISIONS.md` and
the chunker's own docstring.

---

## What I verified by hand

- **Every band boundary.** 0/50/51, 99/100/101, 199/200/201, 299/300/301 checked
  against NEA's published table and covered by exhaustive parametrised tests.
- **The `robots.txt` of every source**, before any fetch. Two sources
  (`haze.gov.sg`, `moh.gov.sg`) were excluded as a result, which materially
  changed what the corpus contains.
- **The MOM band table**, including the PSI > 400 full-face-respirator provision,
  read directly from the fetched page rather than taken from the agent's summary.
- **All 94 policy-matrix quotes**, mechanically: `app/policy.py` resolves each
  `source_quote` to a character span in its cited document at load time and the
  build fails if any does not resolve. This is stronger than reading them, and
  `scripts/validate_corpus.py` runs it in the test suite.
- **The failure diagnoses in the report's gallery** are generated from the
  trajectory data, not written by the model as free prose.
- **The UI end-to-end in a real browser** — the reasoning trace, the boundary
  annotation at PSI 101, the abstention card, and the citation side panel.

---

## Where AI assistance most likely left weaknesses

Stated because they are the places a reviewer should look hardest:

1. **Corpus wording.** 33 documents are paraphrases of fetched pages, written by
   the agent. I verified the numbers and the operative verbs ("minimise" vs
   "reduce" vs "avoid"), which are what the policy matrix keys on. I did not
   line-edit every sentence of every document.
2. **The 15 authored-interpretation documents** are the agent applying primary
   rules to situations. They are marked `explanatory`, cannot supply permission
   through the guardrail, and are excluded from being obligation sources — but
   they are reasoning, not sources.
3. **Benchmark gold labels** were drafted by the agent from the corpus and
   reviewed by me. They share an author with the policy matrix, which is the
   single largest validity limitation of the whole evaluation and is stated in
   the annotation guide, the report and the README.
4. **Singlish paraphrase items** were written by the agent. They are plausible
   but not collected from real users, so they test lexical robustness rather
   than genuine dialect distribution.
5. **Two defects were only reachable with a live model.** The stub provider let
   the entire system be built and tested without an API key, which was valuable
   — but it never echoed the user's question back, so a guardrail that rejected
   numerals the *asker* had written went unnoticed until real prose came back
   ("outdoor play in 20 minutes" → `20` flagged as an invented reading →
   spurious abstention). A test double that is too well-behaved hides the class
   of bug that lives in the interaction between model output and validation.

---

## Honest summary

The agent wrote most of the code and most of the words. Its most valuable
contribution was speed on the mechanical parts — the eval harness, the report
generator, the API and UI — which freed effort for the corpus and the policy
matrix, where the actual difficulty is.

Its most dangerous tendency was producing confident, well-formed artefacts that
were subtly wrong in ways that looked fine: an ablation arm scoring perfectly
because it had silently fallen back, a guardrail stripping correct content
because it was checking the wrong proposition, an evaluation number with no
basis. Every one of those was caught by insisting that claims be mechanically
checkable — the quote-to-span validator, the provider-failure tracker, the frozen
benchmark hash — rather than by reading the output and finding it plausible.

That is the transferable lesson: with a coding agent, the leverage is in
building the checks that make its output falsifiable, not in reviewing its
output for plausibility.
