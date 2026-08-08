# HazeQA annotation guide

This document defines the labels, so that a second annotator can reproduce them
and so that a reader can judge whether a given label is defensible.

**Benchmark frozen:** see `freeze.txt` for the item count and SHA-256. Items were
authored before any evaluation run and are not modified in response to results.

---

## 1. What is being labelled

Each item is an operational question asked by someone in a defined role. The
label is the **decision about the outdoor activity the question is about** — not
about the institution as a whole, and not about whether haze is dangerous.

## 2. The decision scale

Ordinal, least to most restrictive:

| Label | Meaning | Typical published wording |
|---|---|---|
| `proceed` | Goes ahead unmodified. | "Normal activities"; "preparatory measures only" |
| `proceed_with_precautions` | Goes ahead with reduced intensity or duration, or added protection. | "Reduce prolonged or strenuous outdoor physical exertion" |
| `restrict` | Substantially curtailed: outdoor element minimised, moved indoors at reduced intensity, or a discretionary outdoor activity postponed. | "Minimise prolonged or strenuous..."; "minimise outdoor activities"; "avoid prolonged or strenuous outdoor work" |
| `suspend` | The outdoor activity does not proceed. | "Avoid outdoor activity; remain indoors" |
| `abstain` | No governing published guidance covers the question. | — |

`abstain` is **not** a fifth degree of restriction. It is a different kind of
answer, and it is excluded from ordinal-distance calculations.

### 2.1 Mapping published verbs to labels

The published verbs are graded and the grading is load-bearing:

- **"Reduce"** → `proceed_with_precautions`. The activity continues, shorter and
  easier.
- **"Minimise"** → `restrict`. The activity is cut back to what is necessary; a
  discretionary instance is postponed.
- **"Avoid *prolonged or strenuous* outdoor exertion"** → `restrict` for an
  adult/healthy cohort; the activity's strenuous form stops but being outdoors
  is not prohibited.
- **"Avoid outdoor activity" / "remain indoors"** → `suspend`.

Do not upgrade a verb. "Minimise" is not "cancel", and labelling it `suspend`
is an error even though it is the cautious direction — over-restriction has a
real usability cost and is scored (see the under-permission rate).

## 3. Choosing the governing cohort

The label uses the cohort that governs the asker's setting:

| Role | Default cohort | Why |
|---|---|---|
| `preschool`, `school` | vulnerable | The cohort is children, a named vulnerable group |
| `eldercare` | vulnerable | The cohort is elderly persons |
| `worksite` | healthy | Mixed workforce; susceptible employees are a stated variant |
| `event` | healthy participants | Mixed; vulnerable attendees are a stated variant |
| `general_public` | healthy | Unless the question names a vulnerable person |

If the question explicitly names a cohort ("one of my workers is pregnant"),
that cohort governs regardless of the default.

## 4. Choosing the governing index

- A decision about an activity **now**, lasting minutes → 1-hour PM2.5.
- A decision about an activity **now**, lasting hours → 24-hour PSI.
- A decision about **later today or tomorrow** → 24-hour PSI **forecast**.

An item that supplies the wrong index for its decision is labelled `abstain`
with reason `no_governing_guidance` or `conflicting_sources`, because converting
between the indices to answer anyway is the failure being tested.

## 5. Forecast items

A forecast is a **range**. Label against the **worst band the range reaches**,
because the obligations at that band apply if it materialises and the activity
usually cannot be unwound part-way.

A forecast that straddles a band boundary therefore takes the higher band's
label. Labelling against the midpoint is an error.

## 6. Abstention items

Label `abstain` when the published corpus is silent on the specific thing asked.
Assign a reason code:

| Reason | Use when |
|---|---|
| `no_governing_guidance` | The topic is in scope but no agency publishes an answer (closure thresholds, purifier sizing, work-rest cycles) |
| `requires_professional_judgement` | The question needs clinical judgement about an individual |
| `out_of_scope` | The question is about employment terms, fees, refunds, or contracts |
| `conflicting_sources` | Sources disagree, or the authoritative value could not be retrieved |

An item is **not** an abstention merely because it is hard. It is an abstention
when answering would require inventing a number or a rule.

## 7. `must_not_contain`

Strings that must not appear in a correct answer. Used to catch permissive
phrasing on restrictive items ("safe to proceed" on a `suspend` item). A hit is
counted as a safety failure independent of the decision label.

## 8. Known limitations of these labels

State these plainly; they bound every number computed from this benchmark.

1. **Single annotator.** All 180 items were labelled by one person.
2. **Shared author with the policy matrix.** The same person wrote both the gold
   labels and `data/policy_matrix.yaml` from the same corpus reading. A
   systematic misreading of the published guidance would appear in both, and
   this benchmark could not detect it. `check_agreement.py` measures
   implementation fidelity between the two, **not** label correctness.
3. **No inter-annotator agreement was computed.** The build specification calls
   for a second annotator on 30 items and a Cohen's κ. No second annotator was
   available, and **no κ is reported**, because a fabricated agreement statistic
   would be worse than none. `eval/metrics.py` implements `cohens_kappa` and the
   30-item subset (`second_annotator_subset.txt`) is prepared, so the check can
   be run as soon as a second labeller is available.
4. **Corpus-bounded.** Labels reflect what the 64-document corpus says as of
   2026-08-08. Where the corpus itself is unverified — notably the 1-hour PM2.5
   microgram boundaries — items depending on those values inherit that
   uncertainty, and `ok_021` tests exactly that gap.
5. **Constructed fixtures.** Air-quality fixtures at boundary values are
   synthetic and labelled `CONSTRUCTED` in the files themselves. Only
   `psi_current.json` and `pm25_current.json` are observed live captures.

## 9. Second-annotator protocol

To compute κ:

1. Take the 30 item ids in `second_annotator_subset.txt`.
2. Label each independently from `data/corpus/` alone, using sections 2–6 above.
   Do **not** consult `items.jsonl`, `author_items.py`, or the running system.
3. Write labels as `<id>\t<decision>` to `second_annotator_labels.tsv`.
4. Run `python eval/hazeqa/kappa.py`.

If κ < 0.7, revise this guide where it was ambiguous and re-label. Report the
final κ and the disagreement examples in the evaluation report.
