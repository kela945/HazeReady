---
name: outdoor_worksite
role: worksite
description: Haze decisions for outdoor workplaces — construction sites, landscaping,
  marine and logistics yards. Employer obligations, risk assessment, respirator
  provision, susceptible employees, work rotation. Use when the asker is an
  employer, WSH officer, site supervisor or safety coordinator.
governing_agencies: [MOM, WSH Council, NEA]
primary_index: psi_24h
route_terms: [worksite, work site, construction, site supervisor, wsh, safety officer,
  employees, workers, worker, my crew, crew, employer, outdoor work, scaffold,
  scaffolders, landscaping, shipyard, foreman, contractor, labourers, manpower,
  shift, roster, concreting, rebar, work rest, susceptible employees, staff,
  redeployment, tripartite]
---

## Decision procedure

1. Resolve the governing band via `resolve_psi_band`.
2. Retrieve obligations via `lookup_role_obligations(role="worksite", band=...)`.
3. Corroborate with `search_advisories` filtered to MOM sources.
4. For shift and roster planning, call `get_air_quality_forecast` and plan
   against the worst band in the range.
5. Abstain on employment-terms questions (pay, leave) and on any request for a
   numeric haze work-rest cycle — none is published.

## Decision checklist

- [ ] Healthy or susceptible employees? At 101–200 the postures differ
      ("reduce" versus "minimise"); at 201–300 they converge.
- [ ] Is the work prolonged or strenuous, or brief and light? The band
      restrictions attach to the former below 300.
- [ ] Have preparatory measures been done — susceptible employees identified,
      masks fit-tested and stocked, criteria set in advance?
- [ ] Above 300: has respirator escalation been considered, including full face
      respirators for prolonged outdoor work above PSI 400?

## Framing note

There is no published PSI at which outdoor work automatically becomes unlawful.
The regime is a risk-assessment duty under the WSH Act. Never answer a worksite
question with a bare permission or prohibition; answer with the posture the band
requires and the assessment that governs the residue.

## Output template

Decision, obligations checklist, rationale. Distinguish healthy from susceptible
employees explicitly whenever the band differentiates them.

## Known gaps

Guidance is silent on: numeric haze work-rest cycles (the published numeric
framework is for heat stress, a different hazard, and must not be transposed);
pay or leave during stand-down; the detailed provisions of the tripartite
advisory; what age counts as "elderly" for susceptibility. Abstain on these.
