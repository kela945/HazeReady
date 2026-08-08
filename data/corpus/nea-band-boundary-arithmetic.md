---
doc_id: nea-band-boundary-arithmetic
title: "Band boundary arithmetic and off-by-one errors"
issuing_agency: NEA
source_url: "https://www.nea.gov.sg/our-services/pollution-control/air-pollution/faqs"
retrieved_at: "2026-08-08"
licence: "Singapore public agency publication; interpretation authored for this system"
robots_txt_checked: true
robots_txt_permits: true
provenance: authored_interpretation
verified_against_source: false
applies_to_roles: [general_public, school, preschool, eldercare, worksite, event]
authority_tier: explanatory
---

# Band boundary arithmetic and off-by-one errors

The published bands are stated as closed integer intervals: 0–50, 51–100,
101–200, 201–300, above 300. The consequences at the edges:

| Reading | Band | Adjacent reading | Band |
|---|---|---|---|
| 50 | Good | 51 | Moderate |
| 100 | Moderate | 101 | Unhealthy |
| 200 | Unhealthy | 201 | Very Unhealthy |
| 300 | Very Unhealthy | 301 | Hazardous |

The 100/101 boundary is the operationally significant one. It is where "normal
activities" becomes "reduce prolonged or strenuous outdoor physical exertion",
and where the school and preschool instruction to minimise outdoor activities
begins. A single index point changes the obligation.

Two failure modes follow, and both are common:

1. **Off-by-one.** Treating 100 as Unhealthy, or 101 as Moderate. At 100 no
   activity restriction applies; at 101 it does.
2. **Rounding.** PSI is published as an integer. There is no rounding step for
   the reader to perform, and inventing one at a boundary changes the band.

This document is an authored interpretation of the published band table. It adds
no obligation of its own; the obligations live in the agency documents.
