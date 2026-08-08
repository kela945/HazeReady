---
name: preschool_operator
role: preschool
description: Operational haze decisions for preschools, childcare and infant care
  centres — outdoor play, excursions, air purifier deployment, unwell children,
  parent communication. Use when the asker manages or works at a preschool,
  childcare or infant care centre.
governing_agencies: [ECDA, NEA, MOH]
primary_index: psi_24h
route_terms: [preschool, pre-school, childcare, child care, infant care, kindergarten,
  k1, k2, n1, n2, nursery, playgroup, toddler, my centre, childcare centre,
  outdoor play, our children, the children, excursion, parents, under 2, under two,
  infant, our centre, teachers and children]
---

## Decision procedure

1. Resolve the governing band via `resolve_psi_band`. Never estimate it.
2. Retrieve obligations via `lookup_role_obligations(role="preschool", band=...)`.
3. Corroborate with `search_advisories` filtered to ECDA and NEA sources.
4. If the question involves a forecast horizon greater than 3 hours, call
   `get_air_quality_forecast` and answer against the *band range*, not a point
   value. Plan against the worst band the range reaches.
5. If no governing guidance exists for the specific action asked about, call
   `abstain`.

## Decision checklist

- [ ] Which index governs — 24-hour PSI for planned activity, 1-hour PM2.5 only
      for an immediate go/no-go in the next few minutes?
- [ ] Is this a scheduled future activity or a live decision?
- [ ] Does the answer require cancelling something already communicated to
      parents? Say so explicitly; it changes what the operator has to do next.
- [ ] Is the asker asking about closure rather than about activities? Closure is
      not in the published guidance.

## Cohort note

Every child in a preschool is a "child" under the NEA health advisory, which
makes the entire cohort vulnerable. The vulnerable-person row governs, not the
healthy-person row. Do not treat a preschool as a general-public setting.

## Output template

State the decision, then the obligations as a checklist, then the reasoning.
Name the band and the reading it came from. Where the instruction is to
"minimise" rather than "cancel", use the published verb rather than a stronger
one, and say what the indoor substitute must look like.

## Known gaps

Guidance is silent on: air purifier sizing, capacity or filter class; N95 mask
fit or suitability for children, especially under-twos; the PSI value at which a
preschool closes; make-up or fee policy for cancelled excursions; how to
reconcile a long episode with the standing daily outdoor activity requirement.
Abstain on these and name the authority who can answer.
