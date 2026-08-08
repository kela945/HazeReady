---
name: eldercare_facility
role: eldercare
description: Operational haze decisions for eldercare and senior care settings —
  day centres, nursing homes, group outings, indoor programming, clients with
  chronic conditions. Use when the asker manages or works at an eldercare
  facility or senior activity centre.
governing_agencies: [MOH, NEA, AIC]
primary_index: psi_24h
route_terms: [eldercare, elder care, nursing home, senior care, senior centre, day centre,
  day care centre, senior activity, residents, elderly clients, seniors,
  aged care, dementia day, my residents, our clients, walking group, tai chi,
  day programme, day program, garden walk, outing]
---

## Decision procedure

1. Resolve the governing band via `resolve_psi_band`.
2. Retrieve obligations via `lookup_role_obligations(role="eldercare", band=...)`.
3. Corroborate with `search_advisories` filtered to MOH and NEA sources.
4. For a planned outing, call `get_air_quality_forecast` and answer against the
   band range.
5. Abstain on anything requiring an eldercare-specific numeric threshold — none
   is published — and on any individual clinical question.

## Decision checklist

- [ ] Is this a discretionary outing or a necessary trip (medical appointment,
      transport home)? The advisory constrains the first far more than the
      second.
- [ ] Do clients have chronic lung or heart disease on top of age? It does not
      change the band posture, but it changes how closely to monitor.
- [ ] Is the question about the activity, or about closing the centre? Closure
      has no published threshold.

## Cohort note

Elderly persons are a named vulnerable group. The whole cohort falls under the
vulnerable-person advisory without individual assessment.

## Output template

Decision, obligations checklist, rationale. Where the answer rests on the
general vulnerable-person advisory rather than eldercare-specific guidance, say
so plainly — the absence of sector-specific guidance is information the manager
needs.

## Known gaps

Guidance is silent on: any eldercare-specific PSI threshold for suspending a day
programme or closing a centre; air purifier specification; individual medical
management; staffing or transport arrangements during an episode. Abstain and
route to the facility's licensing agency.
