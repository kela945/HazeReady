# Data: provenance, licensing, privacy

Everything the system knows comes from three places: a hand-curated markdown
corpus, two live JSON APIs, and a hand-built policy matrix derived from the
corpus. This document accounts for each.

---

## 1. The corpus

**64 markdown documents** under `data/corpus/`, each with mandatory YAML
frontmatter. `scripts/validate_corpus.py` enforces the schema and fails the
build on any violation.

### 1.1 Provenance accounting

Every document declares how it came to exist. This is the honest version of
"we curated a corpus":

| `provenance` | n | What it means |
|---|---|---|
| `paraphrased_from_fetched` | 33 | The page **was retrieved by this system**, and the content restated in our own words with attribution |
| `fetched_and_verified` | 4 | Retrieved and reproduced structurally as fetched (API schemas, band tables) |
| `authored_interpretation` | 15 | Restates rules from primary documents and applies them to a specific operational situation. Adds no obligation of its own |
| `authored_from_domain_knowledge` | 7 | **Not retrieved.** Written from domain knowledge. Numbers in these are unverified and the document says so |
| `authored_coverage_note` | 5 | Records that guidance is *silent* on something. Never citable as an obligation source |

**37 of 64 documents are traceable to a page this system actually fetched.**
The remaining 27 are interpretations and coverage notes, labelled as such in
frontmatter, surfaced in the UI's citation panel, and excluded by the guardrail
from ever supplying permission for an activity.

### 1.2 Authority tiers

| Tier | n | Role |
|---|---|---|
| `primary` | 31 | Agency-attributable obligation or advisory, verified against a retrieved page |
| `secondary` | 6 | Agency-attributable, lesser operational force, or detail not retrieved |
| `explanatory` | 27 | Schema descriptions and authored interpretations |

When two `primary` documents from different agencies conflict, the guardrail
surfaces both rather than silently resolving it (`app/agent/guardrails.py`,
stage 3). An `explanatory` document can never override a `primary` one, and a
permissive statement appearing only in an explanatory document is rejected as a
basis for permitting an activity.

### 1.3 Sources and robots.txt

**Every source's `robots.txt` was checked before any fetch, and the result
changed what this system contains.**

| Source | robots.txt | Action taken |
|---|---|---|
| `nea.gov.sg` | `Allow: /` except `/search` | Fetched. Primary source for PSI bands, health advisories, index semantics |
| `mom.gov.sg` | Allowed except listed paths | Fetched. Primary source for employer obligations by band |
| `moe.gov.sg` | Allowed | Fetched. School continuity plan |
| `ecda.gov.sg` | Allowed except `*.aspx` | Fetched. Preschool requirements |
| `weather.gov.sg` | Allowed except `/wp-admin` | Fetched. Evidence that NEA publishes the forecast as a *range* |
| `data.gov.sg` | `Allow: /` | Fetched. Live PSI and PM2.5 APIs |
| **`haze.gov.sg`** | **`Disallow: /` for all non-whitelisted bots** | **Not fetched.** URL and paraphrase stored instead |
| **`moh.gov.sg`** | **robots.txt itself returns HTTP 403 (CloudFront)** | **Not fetched.** MOH content sourced indirectly via NEA's cross-agency release |
| `firms.modaps.eosdis.nasa.gov` | n/a | Not fetched; described from domain knowledge |
| `asmc.asean.org` | Not checked | **Not fetched.** Described only; no text reproduced |

#### The coverage gap this created

`haze.gov.sg` publishes the authoritative **1-hour PM2.5 microgram band
boundaries**, and its robots.txt disallows automated access. MOH's site, the
other publisher of that table, returned an access-denied response.

The consequence is stated rather than hidden:

- `data/corpus/nea-pm25-bands.md` carries `robots_txt_permits: false`,
  `verified_against_source: false`, and an in-document warning that the µg/m³
  boundaries are **unverified**.
- The band-to-PSI *correspondence* in that document **is** verified, from
  nea.gov.sg.
- The stated boundaries are consistent with a published NEA bulletin reporting
  readings of 30–94 µg/m³ as spanning Band 1 to Band 2, which places the Band 1/2
  boundary between 30 and 94. That is corroboration, not verification.
- Coverage gap `pm25_numeric_band_boundaries` makes the system **abstain** when
  a question turns on the exact boundary, and benchmark item `ok_021` tests it.

`test_no_document_claims_content_from_a_disallowed_source` in
`tests/test_policy_and_corpus.py` fails the build if any document ever claims
fetched provenance from a source whose robots.txt disallows it.

### 1.4 Licensing

Agency publications are reproduced as **paraphrase with attribution**, not
verbatim, and each document records its licence position in frontmatter. API
data is under the Singapore Open Data Licence 1.0. Where terms were not
verified (ASMC, NASA FIRMS), no text is reproduced at all — only a description
and the URL.

---

## 2. Live data

| Endpoint | Content | Licence |
|---|---|---|
| `https://api.data.gov.sg/v1/environment/psi` | 24-hour PSI + pollutant sub-indices, 5 regions + national | Singapore Open Data Licence 1.0 |
| `https://api.data.gov.sg/v1/environment/pm25` | 1-hour PM2.5, 5 regions | Singapore Open Data Licence 1.0 |

**Rate limiting and caching.** Responses are cached for `UPSTREAM_CACHE_TTL_S`
(default 300 s). Readings are published hourly, so a 5-minute cache cannot serve
anything staler than the endpoint itself would, and it prevents an evaluation
run from issuing hundreds of identical requests.

**Failure behaviour.** On any upstream error the client falls back to a
committed fixture and labels the reading `source: fixture`. The UI shows a
`CACHED FIXTURE` badge. A reading is never presented as live when it is not.

### 2.1 What is *not* live

**NASA FIRMS hotspots** require an API key. Without one, `get_regional_hotspots`
returns `source: "unavailable"` rather than a number, because a fabricated
hotspot count is indistinguishable from a real one in the UI. Hotspots are
context only: no published obligation is conditioned on hotspot count, and
coverage gap `hotspot_based_decision` makes the system abstain on questions that
try to use them for a decision.

**The NEA 24-hour PSI forecast** is not exposed by data.gov.sg as a structured
endpoint. Where a question does not quote a forecast range, the system *derives*
one around the current reading (±20%, minimum ±10 index points) and labels it
`source: "derived"` in the API response and `DERIVED range, not an NEA forecast
product` in the UI. **This is an approximation, not a forecast model.** Where the
asker quotes a real forecast range, that range is used and labelled as quoted.

---

## 3. Fixtures

`data/fixtures/` contains 27 JSON files.

- **`psi_current.json`, `pm25_current.json`** — genuine live captures from
  data.gov.sg on 2026-08-08.
- **All others** — **synthetic**, constructed to place readings at specific band
  boundaries (49/50/51, 99/100/101, 199/200/201, 299/300/301) and at
  mid-band values. Every one carries a `_fixture_note` field beginning
  `CONSTRUCTED.` inside the file itself.

Synthetic fixtures are defensible here because they encode nothing but a
reading: a PSI of exactly 100 in the north is a well-formed observation that the
real endpoint could return, and pinning it is the only way to test boundary
behaviour deterministically. They are not used to fabricate agency guidance.

---

## 4. The policy matrix

`data/policy_matrix.yaml` — 34 rows mapping `(role, index, band)` to a decision,
actions and obligations. Hand-built from the corpus.

Every action and obligation carries a **verbatim `source_quote`**. At load time
`app/policy.py` locates that quote in the cited document and attaches the
resulting character span. **A quote that does not appear verbatim is a hard
error that fails the build.** All 94 spans currently resolve.

This is what makes "grounded" checkable rather than rhetorical: the matrix
cannot assert something its cited source does not say, and the citation side
panel in the UI opens the source document scrolled to the exact span.

---

## 5. The benchmark

`eval/hazeqa/items.jsonl` — 180 hand-authored items, frozen before any
evaluation run (SHA-256 in `freeze.txt`, recorded in every result file and shown
in the report header).

Gold labels are declared in `eval/hazeqa/author_items.py`, which **does not
import the policy matrix** — the authoring path is independent of the
implementation path. It is **not** independent of the author: the same person
read the same corpus to build both. `check_agreement.py` reports 100% agreement,
which is an implementation-fidelity check, **not** label validation. See
`ANNOTATION_GUIDE.md` §8.

No personal data appears in any item. Scenarios are invented; no real
institution, worker, child or client is described.

---

## 6. Privacy

**No personal data is collected, stored or transmitted.**

- No accounts, no authentication, no session persistence beyond a per-query
  UUID used to correlate an advisory with its feedback.
- The telemetry schema (`app/telemetry/store.py`) is the enforcement point:
  there is no column in which personal data could be placed. Stored per query:
  timestamp, UUID, role, decision, latency, token counts, model, retrieval
  score, tool names, cited doc ids, and the question text.
- The question text is stored because the failure gallery and the out-of-corpus
  drift signal are meaningless without it. Users are told this on the monitoring
  page. A deployment handling questions that might contain personal details
  should hash or drop this field; the schema makes that a one-line change.
- Free-text feedback is capped at 500 characters and is optional.
- Telemetry is a local SQLite file. Nothing is sent to any external service.
- The system never asks for, and has no field for, a name, contact detail,
  location more precise than one of five NEA reporting regions, or any health
  information about an identifiable person.

### Health data

Users may voluntarily type health information into a question ("my father has
COPD"). The system uses it only to select a cohort variant within the request,
and it lands in the stored question text like any other query text. It is not
linked to an identity, because no identity is collected. This is stated in the
UI footer.

---

## 7. What the data does not cover

Stated plainly, because the limits bound every result:

1. **Eldercare has no sector-specific published thresholds.** Cross-agency
   measures name schools, preschools, workplaces and healthcare facilities, but
   no eldercare threshold table. The system applies the general vulnerable-person
   advisory and abstains on requests for an eldercare-specific number.
2. **Numeric definitions are absent throughout.** "Elderly", "children",
   "prolonged", and the qualifying chronic conditions are named but never
   defined numerically in the published guidance.
3. **No published closure threshold** exists for schools or preschools.
4. **No published haze work-rest cycle** exists. Singapore's numeric work-rest
   framework is for *heat stress*, a different hazard, and must not be
   transposed.
5. **Air purifiers are required but unspecified** — no capacity, filter class,
   air-change rate, or switch-on threshold is published.
6. **Temporal validity.** The corpus is a snapshot dated 2026-08-08. Guidance
   changes, and a stale corpus confidently cited is worse than no system. See
   the deployment-risk section of the README.

All twelve gaps are enumerated in `data/coverage_gaps.yaml`, each pointing at
the corpus document that records the silence, so "there is no guidance on this"
is itself a grounded claim.
