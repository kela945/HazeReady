---
doc_id: datagov-psi-api
title: "data.gov.sg real-time PSI API schema"
issuing_agency: data.gov.sg
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

# data.gov.sg real-time PSI API schema

`GET https://api.data.gov.sg/v1/environment/psi`

Response contains `region_metadata`, `items`, and `api_info`. Each item carries
`timestamp`, `update_timestamp`, and a `readings` object whose keys are:

| Reading key | Meaning |
|---|---|
| `psi_twenty_four_hourly` | 24-hour PSI — the index that governs published band guidance |
| `pm25_twenty_four_hourly` | 24-hour PM2.5 concentration |
| `pm25_sub_index` | PM2.5 contribution to the PSI |
| `pm10_twenty_four_hourly`, `pm10_sub_index` | PM10 |
| `o3_eight_hour_max`, `o3_sub_index` | Ozone |
| `co_eight_hour_max`, `co_sub_index` | Carbon monoxide |
| `so2_twenty_four_hourly`, `so2_sub_index` | Sulphur dioxide |
| `no2_one_hour_max` | Nitrogen dioxide |

Each reading maps region name to value, for `north`, `south`, `east`, `west`,
`central` and `national`.

The key to use for band resolution is `psi_twenty_four_hourly`. The sub-index
fields are diagnostic — they say which pollutant drove the index — and are not
themselves the PSI. Reading a sub-index as if it were the PSI understates the
value.
