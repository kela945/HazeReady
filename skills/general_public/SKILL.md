---
name: general_public
role: general_public
description: Everyday personal haze decisions for members of the public — going
  for a run, taking a child to the playground, whether to wear a mask, what a
  reading means. Use when the asker is not acting in an institutional role.
governing_agencies: [NEA, MOH]
primary_index: psi_24h
route_terms: [i want to, should i, my kid, my child, my mum, my dad, jog, jogging,
  go for a run, run outside, going for a run, walk, playground, cycling,
  exercise outdoors, is it safe, can i go, myself]
---

## Decision procedure

1. Decide which index governs. An immediate decision in the next few minutes is
   a 1-hour PM2.5 decision; anything planned for later today or tomorrow is a
   24-hour PSI decision.
2. Resolve the governing band via `resolve_psi_band`.
3. Retrieve obligations via `lookup_role_obligations(role="general_public", ...)`.
4. Corroborate with `search_advisories`.
5. Abstain on anything clinical.

## Decision checklist

- [ ] Is the asker or the person concerned in a vulnerable group — elderly,
      pregnant, a child, or living with chronic lung or heart disease?
- [ ] Is the activity strenuous and prolonged, or light and brief? The advisory
      restricts the former.
- [ ] Is this about now, or about later? That decides the index.

## Output template

Plain language, short. Lead with the decision. Do not overstate the restriction:
below the Hazardous band the advisory restricts prolonged or strenuous exertion,
not being outdoors at all, and saying otherwise misinforms people.

## Known gaps

Guidance is silent on: whether to take medication, what symptoms mean, whether
to see a doctor; mask fit for young children; air purifier selection for the
home; the exact PM2.5 microgram boundaries between bands. Abstain on these and
name the authority — for anything clinical, the person's healthcare provider.
