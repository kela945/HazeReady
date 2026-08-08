---
doc_id: datagov-pm25-api
title: "data.gov.sg real-time PM2.5 API schema"
issuing_agency: data.gov.sg
source_url: "https://api.data.gov.sg/v1/environment/pm25"
retrieved_at: "2026-08-08"
licence: "Singapore Open Data Licence 1.0"
robots_txt_checked: true
robots_txt_permits: true
provenance: fetched_and_verified
verified_against_source: true
applies_to_roles: [general_public, school, preschool, eldercare, worksite, event]
authority_tier: explanatory
---

# data.gov.sg real-time PM2.5 API schema

`GET https://api.data.gov.sg/v1/environment/pm25`

Each item carries `timestamp`, `update_timestamp`, and a `readings` object with
a single key, `pm25_one_hourly`, mapping region name to concentration in
micrograms per cubic metre for `north`, `south`, `east`, `west` and `central`.

Note that unlike the PSI endpoint, the PM2.5 endpoint does not report a
`national` figure — only the five regions. A system that assumes a `national`
key exists on this endpoint will fail.

`pm25_one_hourly` is the index NEA designates for immediate decisions. It is not
interchangeable with `pm25_twenty_four_hourly` on the PSI endpoint, which is a
24-hour average of the same pollutant and a different number entirely.
