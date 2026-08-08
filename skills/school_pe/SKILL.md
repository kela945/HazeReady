---
name: school_pe
role: school
description: Operational haze decisions for primary and secondary schools — PE
  lessons, outdoor CCA training, recess, excursions, sports days, students with
  pre-existing conditions. Use when the asker teaches at or runs a school.
governing_agencies: [MOE, NEA, MOH]
primary_index: psi_24h
route_terms: [school, pe, pe lesson, pe class, physical education, cca, co-curricular,
  sports day, recess, primary school, secondary school, teacher, students, pupils,
  student, assembly, my class, classroom, track and field, national school games,
  cross country, cross-country, sec 1, sec 2, sec 3, sec 4, p1, p2, p3, p4, p5, p6,
  school bus, canteen, form teacher, hall]
---

## Decision procedure

1. Resolve the governing band via `resolve_psi_band`. Never estimate it.
2. Retrieve obligations via `lookup_role_obligations(role="school", band=...)`.
3. Corroborate with `search_advisories` filtered to MOE and NEA sources.
4. For a decision about tomorrow or later, call `get_air_quality_forecast` and
   answer against the band range.
5. If the question is about closure, or about an individual student's medical
   management, call `abstain`.

## Decision checklist

- [ ] Is the proposed substitute activity actually less strenuous, or just
      indoors? At 101–200 both restrictions apply: minimise outdoor activity AND
      avoid strenuous indoor exercise.
- [ ] Does the activity involve sustained exertion (cross-country, track
      training) or is it low-intensity?
- [ ] Are any students known to have pre-existing lung or heart conditions?
- [ ] Is this a school decision or an MOE decision? Closure is MOE's.

## Cohort note

Students are children and therefore vulnerable under the health advisory. Apply
the vulnerable-person row. Staff are adults; where the question is about staff
doing physical setup work, the worksite guidance applies to them.

## Output template

Decision, obligations checklist, then rationale. Always name both halves of the
101–200 instruction when that band applies — the indoor-intensity half is the
one schools most often miss.

## Known gaps

Guidance is silent on: the PSI at which schools close (MOE communicates this
directly); air purifier specification; whether a specific student may
participate; the number of minutes at which outdoor exposure becomes
"prolonged"; make-up arrangements for cancelled sessions. Abstain on these.
