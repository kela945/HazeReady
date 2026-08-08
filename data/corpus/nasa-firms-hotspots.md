---
doc_id: nasa-firms-hotspots
title: "NASA FIRMS active fire hotspot data"
issuing_agency: NASA
source_url: "https://firms.modaps.eosdis.nasa.gov/api/"
retrieved_at: "2026-08-08"
licence: "NASA open data policy; free and open use with attribution"
robots_txt_checked: true
robots_txt_permits: true
provenance: authored_from_domain_knowledge
verified_against_source: false
applies_to_roles: [general_public, event, worksite]
authority_tier: explanatory
---

# NASA FIRMS active fire hotspot data

NASA's Fire Information for Resource Management System (FIRMS) publishes active
fire detections from the VIIRS and MODIS instruments, as point detections with
latitude, longitude, acquisition time, brightness and a confidence class.

**What hotspot counts are good for:** regional situational context and trend.
A rising hotspot count over Sumatra or Kalimantan during the dry season is a
leading indicator that transboundary smoke may follow.

**What they must never be used for:** the operational decision itself. A hotspot
detection is a thermal anomaly at a location upwind; it is not a measurement of
air quality in Singapore. Whether smoke arrives depends on wind, rainfall and
plume height. Published haze obligations are conditioned on PSI and PM2.5, not
on hotspot counts, and no agency publishes an action threshold on hotspot count.

This system therefore treats hotspots as context to display, never as an input
to a decision. A question of the form "there are 400 hotspots in Sumatra, should
I cancel tomorrow's excursion?" cannot be answered from hotspot data.

**Coverage note.** The FIRMS API documentation was not retrieved by this system;
this description is authored from domain knowledge.
