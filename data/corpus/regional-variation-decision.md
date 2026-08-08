---
doc_id: regional-variation-decision
title: "Which region's reading applies"
issuing_agency: NEA
source_url: "https://api.data.gov.sg/v1/environment/psi"
retrieved_at: "2026-08-08"
licence: "Singapore Open Data Licence 1.0; interpretation authored for this system"
robots_txt_checked: true
robots_txt_permits: true
provenance: authored_interpretation
verified_against_source: false
applies_to_roles: [general_public, school, preschool, eldercare, worksite, event]
authority_tier: explanatory
---

# Which region's reading applies

Readings are published for north, south, east, west and central, plus a national
figure on the PSI endpoint. An institution applies the reading for the region it
is physically in.

Regional spread is real. An observed payload showed 57 north, 59 east, 59 west,
66 central, 57 south — nine index points in ordinary conditions, and wider
during an episode, because plume transport is directional.

Consequences:

- A national figure can sit in a lower band than the region an institution is
  in. Using it is the permissive error.
- An activity that crosses regions — an excursion from the west to the east —
  is exposed to the worst region on its route, not the region of departure.
- Where a reading straddles a band boundary between neighbouring regions, and
  the activity's location is uncertain, the higher band is the defensible basis.

This is an authored interpretation.
