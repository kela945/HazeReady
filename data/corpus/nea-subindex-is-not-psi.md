---
doc_id: nea-subindex-is-not-psi
title: "Sub-indices are not the PSI"
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

# Sub-indices are not the PSI

The PSI is the maximum of its pollutant sub-indices. The API therefore reports
both the index and its components: `psi_twenty_four_hourly` alongside
`pm25_sub_index`, `pm10_sub_index`, `o3_sub_index`, `co_sub_index` and
`so2_sub_index`.

During a haze episode PM2.5 is normally the driving pollutant, so
`pm25_sub_index` and `psi_twenty_four_hourly` are often equal. They are not the
same field and they diverge when another pollutant dominates.

Band resolution must read `psi_twenty_four_hourly`. Reading any sub-index in its
place produces a value that is less than or equal to the PSI, which biases the
resulting band *downward* — that is, toward a more permissive answer. Errors of
this shape are the dangerous direction.

Similarly, `pm25_twenty_four_hourly` on the PSI endpoint is a 24-hour average
concentration and is not the 1-hour PM2.5 reading used for immediate decisions.
