---
doc_id: nea-reading-cadence-and-staleness
title: "Reading cadence, timestamps and staleness"
issuing_agency: NEA
source_url: "https://api.data.gov.sg/v1/environment/psi"
retrieved_at: "2026-08-08"
licence: "Singapore Open Data Licence 1.0"
robots_txt_checked: true
robots_txt_permits: true
provenance: fetched_and_verified
verified_against_source: true
applies_to_roles: [general_public, school, preschool, eldercare, worksite, event]
authority_tier: explanatory
---

# Reading cadence, timestamps and staleness

PSI and PM2.5 readings are published hourly. Each payload carries two
timestamps: `timestamp`, the hour the reading represents, and
`update_timestamp`, the moment the record was written. In an observed payload
these were `2026-08-08T15:00:00+08:00` and `2026-08-08T15:00:56+08:00`
respectively — publication lag under a minute in normal operation.

Because readings are hourly, a reading can be up to roughly 60 minutes old and
still be the most recent one available. This is normal and is not an error
condition. It is, however, material during a fast-moving episode: a 1-hour PM2.5
value that is 55 minutes old is a poor basis for an immediate decision.

Any system presenting a reading should display its age explicitly rather than
implying the number is current. A reading older than two hours should be treated
as stale and flagged, because it indicates an upstream problem rather than
normal cadence.
