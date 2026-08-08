#!/usr/bin/env python3
"""Author the HazeQA benchmark.

IMPORTANT — independence. Gold decisions are declared in `GOLD` below, written
from a reading of data/corpus/. This module does NOT import the policy matrix
and does not call the system. That keeps the authoring path independent of the
implementation path, so a coding error in app/policy.py cannot silently define
its own ground truth.

It does NOT make the benchmark independent of the *author*: the same person read
the same corpus to build both the matrix and this table. A systematic misreading
of the guidance would appear in both and this benchmark could not detect it.
That is the single largest validity limitation of this evaluation and it is
stated in ANNOTATION_GUIDE.md, in the report, and in the README.

`check_agreement.py` reports where the authored gold and the implemented matrix
disagree. Disagreements are informative in both directions and are listed in the
report rather than reconciled away.

Run: python eval/hazeqa/author_items.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Authored gold: (role, band) -> decision, for the role's default cohort.
# Written from data/corpus/, not from data/policy_matrix.yaml.
# ---------------------------------------------------------------------------

GOLD: dict[str, dict[str, str]] = {
    # Healthy adult default. 101-200 "reduce prolonged or strenuous exertion";
    # 201-300 "avoid" it; above 300 "minimise outdoor activity".
    "general_public": {
        "good": "proceed",
        "moderate": "proceed",
        "unhealthy": "proceed_with_precautions",
        "very_unhealthy": "restrict",
        "hazardous": "restrict",
    },
    # Children are vulnerable. 101-200 schools "minimise outdoor activities"
    # AND "avoid strenuous indoor physical exercise".
    "school": {
        "good": "proceed",
        "moderate": "proceed",
        "unhealthy": "restrict",
        "very_unhealthy": "suspend",
        "hazardous": "suspend",
    },
    "preschool": {
        "good": "proceed",
        "moderate": "proceed",
        "unhealthy": "restrict",
        "very_unhealthy": "suspend",
        "hazardous": "suspend",
    },
    # Elderly are vulnerable; same ladder as a child cohort.
    "eldercare": {
        "good": "proceed",
        "moderate": "proceed",
        "unhealthy": "restrict",
        "very_unhealthy": "suspend",
        "hazardous": "suspend",
    },
    # Healthy employees. 101-200 "reduce"; 201-300 "avoid prolonged or
    # strenuous outdoor work"; above 300 "minimise outdoor work".
    "worksite": {
        "good": "proceed",
        "moderate": "proceed",
        "unhealthy": "proceed_with_precautions",
        "very_unhealthy": "restrict",
        "hazardous": "restrict",
    },
    # Participants are healthy by default, but above 300 the advisory reaches
    # outdoor activity as such and a mass outdoor event cannot proceed.
    "event": {
        "good": "proceed",
        "moderate": "proceed",
        "unhealthy": "proceed_with_precautions",
        "very_unhealthy": "restrict",
        "hazardous": "suspend",
    },
}

GOLD_PM25 = {
    "general_public": {
        "normal": "proceed",
        "elevated": "proceed_with_precautions",
        "high": "restrict",
        "very_high": "restrict",
    }
}


def band_of(psi: int) -> str:
    if psi <= 50:
        return "good"
    if psi <= 100:
        return "moderate"
    if psi <= 200:
        return "unhealthy"
    if psi <= 300:
        return "very_unhealthy"
    return "hazardous"


def pm25_band_of(v: int) -> str:
    if v <= 55:
        return "normal"
    if v <= 150:
        return "elevated"
    if v <= 250:
        return "high"
    return "very_high"


BAND_REASON = {
    "good": "band_good",
    "moderate": "band_moderate",
    "unhealthy": "band_unhealthy",
    "very_unhealthy": "band_very_unhealthy",
    "hazardous": "band_hazardous",
}

VULNERABLE_ROLES = {"school", "preschool", "eldercare"}

CITATIONS = {
    "preschool": ["ecda-preschool-outdoor-unhealthy", "nea-psi-health-advisory-vulnerable"],
    "school": ["moe-outdoor-activities-unhealthy", "nea-psi-health-advisory-vulnerable"],
    "eldercare": ["eldercare-vulnerable-cohort", "nea-psi-health-advisory-vulnerable"],
    "worksite": ["mom-outdoor-work-unhealthy", "nea-psi-health-advisory-healthy"],
    "event": ["event-participant-exertion", "event-organiser-risk-assessment"],
    "general_public": ["public-general-advisory", "nea-psi-health-advisory-healthy"],
}

PERMISSIVE_STRINGS = ["safe to proceed", "no action needed", "no restriction needed"]

items: list[dict] = []


def add(
    id_: str,
    category: str,
    role: str,
    question: str,
    gold_decision: str,
    reason_codes: list[str],
    citations: list[str],
    *,
    must_not_contain: list[str] | None = None,
    notes: str = "",
    fixture: str = "",
    gold_abstain_reason: str = "",
    gold_role: str = "",
) -> None:
    items.append(
        {
            "id": id_,
            "category": category,
            "role": gold_role or role,
            "question": question,
            "context_fixture": fixture,
            "gold_decision": gold_decision,
            "gold_reason_codes": reason_codes,
            "gold_citation_doc_ids": citations,
            "gold_abstain_reason": gold_abstain_reason,
            "must_not_contain": must_not_contain or [],
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 1. threshold_boundary (40)
# ---------------------------------------------------------------------------

BOUNDARY_SCENARIOS = [
    # (role, psi, question template)
    (
        "preschool",
        "My K1 class has outdoor play in 20 minutes. 24-hr PSI is {v} in the north. Do I cancel?",
    ),
    ("school", "24-hr PSI is {v}. Does the Sec 2 PE lesson outdoors go ahead?"),
    ("worksite", "24-hr PSI reads {v}. Can my crew continue the outdoor rebar work?"),
    ("eldercare", "24-hr PSI is {v}. Should the day centre's morning garden walk run?"),
    ("event", "24-hr PSI is {v} an hour before our outdoor 10km race. Do we start?"),
    ("general_public", "24-hr PSI is {v}. Can I take my usual long outdoor walk?"),
]

BOUNDARY_VALUES = [49, 50, 51, 99, 100, 101, 199, 200, 201, 299, 300, 301]

n = 0
for v in BOUNDARY_VALUES:
    for role, tmpl in BOUNDARY_SCENARIOS:
        if n >= 36:
            break
        b = band_of(v)
        gold = GOLD[role][b]
        n += 1
        add(
            f"tb_{n:03d}",
            "threshold_boundary",
            role,
            tmpl.format(v=v),
            gold,
            [BAND_REASON[b]] + (["vulnerable_cohort"] if role in VULNERABLE_ROLES else []),
            CITATIONS[role],
            must_not_contain=PERMISSIVE_STRINGS if gold in ("restrict", "suspend") else [],
            notes=f"Boundary item: PSI {v} is {b}. Adjacent value flips the band.",
            fixture=f"aq_boundary_{v}.json" if v in (50, 100, 101, 200, 201, 300, 301) else "",
        )
    if n >= 36:
        break

# Deliberate index confusion: a 1-hour PM2.5 value presented where the 24-hour
# PSI governs a planned institutional activity.
add(
    "tb_037",
    "threshold_boundary",
    "preschool",
    "1-hr PM2.5 is 60 right now. Do I need to cancel tomorrow morning's excursion?",
    "abstain",
    ["wrong_index_for_decision"],
    ["nea-psi-vs-pm25-purpose", "nea-forecast-is-a-range"],
    gold_abstain_reason="no_governing_guidance",
    notes="Index confusion. A tomorrow decision is a 24-hour PSI FORECAST decision. "
    "A current 1-hour PM2.5 value cannot govern it. The system should not "
    "convert the PM2.5 value into a PSI band and answer.",
    must_not_contain=["safe to proceed"],
)
add(
    "tb_038",
    "threshold_boundary",
    "worksite",
    "PM2.5 is 152. My supervisor says that's the same as PSI 152 so we are still in Unhealthy. Correct?",
    "abstain",
    ["wrong_index_for_decision"],
    ["nea-psi-vs-pm25-purpose", "nea-pm25-bands"],
    gold_abstain_reason="conflicting_sources",
    notes="1-hr PM2.5 152 is Band 3 (High), which corresponds to PSI 201-300, NOT "
    "PSI 152. Treating the two numbers as the same scale understates the band.",
)
add(
    "tb_039",
    "threshold_boundary",
    "school",
    "The pm25 sub-index reads 96 but psi_twenty_four_hourly reads 143. Which governs the PE decision?",
    "restrict",
    ["band_unhealthy", "vulnerable_cohort"],
    ["nea-subindex-is-not-psi", "moe-outdoor-activities-unhealthy"],
    notes="Sub-index vs PSI. The PSI (143, Unhealthy) governs. Reading the "
    "sub-index instead biases the band downward, toward permission.",
)
add(
    "tb_040",
    "threshold_boundary",
    "preschool",
    "National PSI is 96 but the north reading is 104 and we are in the north. Outdoor play?",
    "restrict",
    ["band_unhealthy", "vulnerable_cohort"],
    ["regional-variation-decision", "ecda-preschool-outdoor-unhealthy"],
    fixture="aq_regional_split.json",
    must_not_contain=PERMISSIVE_STRINGS,
    notes="Regional divergence across the 100/101 boundary. The institution's own "
    "region governs; the national figure is the permissive error.",
)

# ---------------------------------------------------------------------------
# 2. role_conditioned (40): same reading, different roles, different gold
# ---------------------------------------------------------------------------

ROLE_SCENARIOS = [
    (
        165,
        "24-hr PSI is 165.",
        {
            "preschool": "Our N2 children have their daily outdoor play slot at 10am. Does it run?",
            "school": "The Sec 3 cross-country training is scheduled for 4pm. Does it run?",
            "eldercare": "Our day centre has a walking group to the park at 9am. Does it run?",
            "worksite": "My healthy scaffolders have a full day of outdoor erection work. Do they work?",
            "event": "Our outdoor food festival with seated diners opens at noon. Does it open?",
            "general_public": "I was going to do my usual 10km run this evening. Should I?",
        },
    ),
    (
        230,
        "24-hr PSI is 230.",
        {
            "preschool": "Do we still take the K2s to the playground?",
            "school": "Does the outdoor sports day go ahead?",
            "eldercare": "Do we still run the outdoor tai chi session?",
            "worksite": "Can my healthy crew continue prolonged outdoor concreting?",
            "event": "Does our outdoor mass run go ahead?",
            "general_public": "Can I still cycle to work?",
        },
    ),
    (
        75,
        "24-hr PSI is 75.",
        {
            "preschool": "Any change to our outdoor play programme?",
            "school": "Any change to outdoor PE?",
            "eldercare": "Any change to the outdoor walking group?",
            "worksite": "Any change needed for outdoor work?",
            "event": "Any change needed for our outdoor carnival?",
            "general_public": "Any reason not to go running?",
        },
    ),
    (
        330,
        "24-hr PSI is 330.",
        {
            "preschool": "Outdoor play?",
            "school": "Outdoor assembly?",
            "eldercare": "Outdoor walking group?",
            "worksite": "Prolonged outdoor work for healthy staff?",
            "event": "Our outdoor concert this evening?",
            "general_public": "My evening walk?",
        },
    ),
]

n = 0
for psi, lead, per_role in ROLE_SCENARIOS:
    b = band_of(psi)
    for role, q in per_role.items():
        n += 1
        gold = GOLD[role][b]
        add(
            f"rc_{n:03d}",
            "role_conditioned",
            role,
            f"{lead} {q}",
            gold,
            [BAND_REASON[b]] + (["vulnerable_cohort"] if role in VULNERABLE_ROLES else []),
            CITATIONS[role],
            must_not_contain=PERMISSIVE_STRINGS if gold in ("restrict", "suspend") else [],
            notes=f"Identical reading ({psi}, {b}) across six roles. Tests that "
            "retrieval and policy lookup discriminate by role rather than "
            "matching on topic.",
        )

# Cohort discrimination within a single role.
add(
    "rc_025",
    "role_conditioned",
    "worksite",
    "24-hr PSI is 150. One of my workers is pregnant. Can she continue prolonged outdoor work?",
    "restrict",
    ["band_unhealthy", "susceptible_employee"],
    ["mom-outdoor-work-unhealthy", "mom-susceptible-employees"],
    notes="Susceptible employee at 101-200 gets 'minimise', not the healthy "
    "employee's 'reduce'. Tests the cohort variant.",
)
add(
    "rc_026",
    "role_conditioned",
    "worksite",
    "24-hr PSI is 150. My workers are all healthy adults. Prolonged outdoor work?",
    "proceed_with_precautions",
    ["band_unhealthy"],
    ["mom-outdoor-work-unhealthy"],
    notes="Healthy employee at 101-200 gets 'reduce'. Paired with rc_025.",
)
add(
    "rc_027",
    "role_conditioned",
    "general_public",
    "24-hr PSI is 150. My father is 78 and has COPD. Can he do his usual long morning walk?",
    "restrict",
    ["band_unhealthy", "vulnerable_cohort"],
    ["nea-psi-health-advisory-vulnerable", "moh-vulnerable-group-definition"],
    must_not_contain=PERMISSIVE_STRINGS,
    notes="Vulnerable individual within the general_public role.",
)
add(
    "rc_028",
    "role_conditioned",
    "general_public",
    "24-hr PSI is 150. I am a healthy 30-year-old. Long morning walk?",
    "proceed_with_precautions",
    ["band_unhealthy"],
    ["nea-psi-health-advisory-healthy"],
    notes="Healthy individual, same reading as rc_027. Paired contrast.",
)
add(
    "rc_029",
    "role_conditioned",
    "event",
    "24-hr PSI is 230. Our event is a seated outdoor film screening, no exertion. Proceed?",
    "restrict",
    ["band_very_unhealthy"],
    ["event-static-versus-strenuous", "event-participant-exertion"],
    notes="Static event at 201-300. The advisory targets prolonged or strenuous "
    "exertion, but vulnerable attendees and working crew are still in scope.",
)
add(
    "rc_030",
    "role_conditioned",
    "event",
    "24-hr PSI is 230. Our crew still needs to build the stage outdoors. What applies to them?",
    "restrict",
    ["band_very_unhealthy"],
    ["mom-outdoor-work-very-unhealthy", "event-static-versus-strenuous"],
    notes="Crew are workers. MOM worksite guidance applies to them independently "
    "of what applies to attendees.",
)
add(
    "rc_031",
    "role_conditioned",
    "school",
    "24-hr PSI is 150. We moved PE indoors to the hall and kept the same circuit training. Is that compliant?",
    "restrict",
    ["band_unhealthy", "vulnerable_cohort"],
    ["moe-outdoor-activities-unhealthy", "school-pe-lesson-decision"],
    must_not_contain=PERMISSIVE_STRINGS,
    notes="The classic error. At 101-200 both halves apply: minimise outdoor "
    "activity AND avoid strenuous indoor exercise. Moving indoors alone is "
    "not compliance.",
)
add(
    "rc_032",
    "school_placeholder" if False else "role_conditioned",
    "preschool",
    "24-hr PSI is 150. We swapped outdoor play for an indoor dance-and-run session. Fine?",
    "restrict",
    ["band_unhealthy", "vulnerable_cohort"],
    ["ecda-preschool-outdoor-unhealthy"],
    must_not_contain=PERMISSIVE_STRINGS,
    notes="Preschool version of rc_031: strenuous indoor substitute breaches the "
    "second half of the instruction.",
)
add(
    "rc_033",
    "role_conditioned",
    "worksite",
    "24-hr PSI is 250. Can I send someone out for a ten-minute equipment check?",
    "proceed_with_precautions",
    ["band_very_unhealthy", "brief_light_task"],
    ["worksite-brief-outdoor-tasks", "mom-risk-assessment-haze"],
    notes="The band restriction attaches to prolonged OR strenuous work. A brief "
    "light task is not directly addressed; the risk assessment governs. "
    "The answer must not be a bare permission.",
    must_not_contain=["no restriction", "safe to proceed"],
)
add(
    "rc_034",
    "role_conditioned",
    "worksite",
    "24-hr PSI is 420. We have prolonged outdoor work that cannot be moved. What respiratory protection?",
    "restrict",
    ["band_hazardous", "respirator_escalation"],
    ["mom-respirator-selection", "mom-outdoor-work-hazardous"],
    notes="Above PSI 400 the guidance names full face respirators for prolonged "
    "outdoor work.",
)
add(
    "rc_035",
    "role_conditioned",
    "eldercare",
    "24-hr PSI is 230. A client has a hospital appointment and must travel. Does the advisory stop that?",
    "proceed_with_precautions",
    ["band_very_unhealthy", "necessary_trip"],
    ["eldercare-outing-decision", "nea-psi-health-advisory-vulnerable"],
    notes="A necessary trip is not a discretionary outing. The advisory constrains "
    "prolonged or strenuous exertion, not necessary travel.",
)
add(
    "rc_036",
    "role_conditioned",
    "preschool",
    "24-hr PSI is 180. Does the infant care cohort under 2 have a different threshold from the K2s?",
    "restrict",
    ["band_unhealthy", "vulnerable_cohort", "no_separate_under_two_threshold"],
    ["preschool-excursion-and-under-twos", "nea-psi-health-advisory-vulnerable"],
    notes="No separate published under-two threshold exists. The answer must say "
    "both: the vulnerable advisory covers them, and no stricter separate "
    "number is published. Inventing one is the failure mode.",
)
add(
    "rc_037",
    "role_conditioned",
    "school",
    "24-hr PSI is 90 but a student has asthma and feels unwell. What do we do?",
    "proceed",
    ["band_moderate", "monitor_unwell_student"],
    ["moe-students-preexisting-conditions", "nea-psi-health-advisory-vulnerable"],
    notes="At Moderate no activity restriction applies, but the monitoring "
    "obligation is independent of the band. Clinical management is out of "
    "scope and must be routed away.",
)
add(
    "rc_038",
    "role_conditioned",
    "general_public",
    "24-hr PSI is 260. I just need to walk to the MRT, five minutes. Is that restricted?",
    "proceed_with_precautions",
    ["band_very_unhealthy", "brief_light_task"],
    ["nea-psi-health-advisory-healthy", "school-recess-and-transit"],
    notes="At 201-300 the advisory restricts prolonged or strenuous exertion, not "
    "brief incidental outdoor movement. Over-restricting here is the "
    "usability error.",
)
add(
    "rc_039",
    "role_conditioned",
    "eldercare",
    "24-hr PSI is 75. Do we need to deploy the air purifiers and cancel the outing?",
    "proceed",
    ["band_moderate"],
    ["eldercare-vulnerable-cohort", "moh-healthcare-facility-measures"],
    notes="At Moderate no activity restriction applies. Purifier deployment is a "
    "standing facility measure, not a band trigger.",
)
add(
    "rc_040",
    "role_conditioned",
    "event",
    "24-hr PSI is 95. Do I need to warn participants of our outdoor run about haze?",
    "proceed",
    ["band_moderate"],
    ["event-participant-exertion", "event-organiser-risk-assessment"],
    notes="No advisory constraint at Moderate. The organiser's risk-assessment "
    "duty is standing and independent of the band.",
)

# ---------------------------------------------------------------------------
# 3. multi_hop (25)
# ---------------------------------------------------------------------------

MULTI_HOP = [
    (
        "preschool",
        "What is the PSI in the north right now, and does my K1 outdoor play slot go ahead?",
        "aq_unhealthy_165.json",
        "unhealthy",
        ["ecda-preschool-outdoor-unhealthy"],
    ),
    (
        "school",
        "Check the current reading and tell me whether outdoor PE runs today.",
        "aq_unhealthy_165.json",
        "unhealthy",
        ["moe-outdoor-activities-unhealthy"],
    ),
    (
        "worksite",
        "Pull the current PSI and tell me what my healthy outdoor crew should be doing.",
        "aq_unhealthy_165.json",
        "unhealthy",
        ["mom-outdoor-work-unhealthy"],
    ),
    (
        "eldercare",
        "What is the reading now and does the garden walk run?",
        "aq_unhealthy_165.json",
        "unhealthy",
        ["eldercare-vulnerable-cohort"],
    ),
    (
        "event",
        "Current reading please, and does our outdoor race start?",
        "aq_unhealthy_165.json",
        "unhealthy",
        ["event-participant-exertion"],
    ),
    (
        "preschool",
        "What is the reading and do we take the K2s out?",
        "aq_very_unhealthy_250.json",
        "very_unhealthy",
        ["nea-psi-health-advisory-vulnerable"],
    ),
    (
        "school",
        "Current PSI, and does sports day go ahead?",
        "aq_very_unhealthy_250.json",
        "very_unhealthy",
        ["nea-psi-health-advisory-vulnerable"],
    ),
    (
        "worksite",
        "Current PSI, and can we keep doing prolonged outdoor work?",
        "aq_very_unhealthy_250.json",
        "very_unhealthy",
        ["mom-outdoor-work-very-unhealthy"],
    ),
    (
        "general_public",
        "What is it now and should I do my long run?",
        "aq_very_unhealthy_250.json",
        "very_unhealthy",
        ["nea-psi-health-advisory-healthy"],
    ),
    (
        "eldercare",
        "Reading now, and does the outing run?",
        "aq_very_unhealthy_250.json",
        "very_unhealthy",
        ["eldercare-vulnerable-cohort"],
    ),
    (
        "preschool",
        "Check the reading and tell me about outdoor play.",
        "aq_moderate_78.json",
        "moderate",
        ["nea-psi-health-advisory-vulnerable"],
    ),
    (
        "school",
        "Check the reading. Outdoor PE?",
        "aq_moderate_78.json",
        "moderate",
        ["nea-psi-health-advisory-healthy"],
    ),
    (
        "worksite",
        "Check the reading. Outdoor work restrictions?",
        "aq_moderate_78.json",
        "moderate",
        ["worksite-good-moderate-bands"],
    ),
    (
        "event",
        "Check the reading. Does our carnival open?",
        "aq_moderate_78.json",
        "moderate",
        ["event-participant-exertion"],
    ),
    (
        "general_public",
        "What is the reading and can I go running?",
        "aq_moderate_78.json",
        "moderate",
        ["public-general-advisory"],
    ),
    (
        "preschool",
        "Reading now. Outdoor play for K1?",
        "aq_hazardous_360.json",
        "hazardous",
        ["nea-psi-health-advisory-vulnerable"],
    ),
    (
        "school",
        "Reading now. Outdoor assembly?",
        "aq_hazardous_360.json",
        "hazardous",
        ["nea-psi-health-advisory-vulnerable"],
    ),
    (
        "worksite",
        "Reading now. Outdoor work for healthy staff?",
        "aq_hazardous_360.json",
        "hazardous",
        ["mom-outdoor-work-hazardous"],
    ),
    (
        "event",
        "Reading now. Does our outdoor concert proceed?",
        "aq_hazardous_360.json",
        "hazardous",
        ["event-static-versus-strenuous"],
    ),
    (
        "eldercare",
        "Reading now. Any outdoor activity?",
        "aq_hazardous_360.json",
        "hazardous",
        ["nea-psi-health-advisory-vulnerable"],
    ),
    (
        "preschool",
        "What is the north reading and what does it mean for our excursion this afternoon?",
        "aq_boundary_101.json",
        "unhealthy",
        ["ecda-preschool-outdoor-unhealthy"],
    ),
    (
        "school",
        "North reading, and does the outdoor CCA training run this afternoon?",
        "aq_boundary_101.json",
        "unhealthy",
        ["moe-outdoor-activities-unhealthy"],
    ),
    (
        "worksite",
        "North reading, and what posture for susceptible employees?",
        "aq_boundary_101.json",
        "unhealthy",
        ["mom-outdoor-work-unhealthy"],
    ),
    (
        "general_public",
        "North reading, and can I do my long cycle?",
        "aq_boundary_101.json",
        "unhealthy",
        ["nea-psi-health-advisory-healthy"],
    ),
    (
        "eldercare",
        "North reading, and does the walking group go?",
        "aq_boundary_101.json",
        "unhealthy",
        ["eldercare-vulnerable-cohort"],
    ),
]

for i, (role, q, fixture, b, cites) in enumerate(MULTI_HOP, start=1):
    gold = GOLD[role][b]
    add(
        f"mh_{i:03d}",
        "multi_hop",
        role,
        q,
        gold,
        [BAND_REASON[b]] + (["vulnerable_cohort"] if role in VULNERABLE_ROLES else []),
        cites + CITATIONS[role][:1],
        fixture=fixture,
        must_not_contain=PERMISSIVE_STRINGS if gold in ("restrict", "suspend") else [],
        notes="Requires live data -> band resolution -> role lookup -> corroboration "
        "in sequence. No reading is stated in the question.",
    )

# ---------------------------------------------------------------------------
# 4. out_of_knowledge_base (30) - gold is abstention
# ---------------------------------------------------------------------------

OOKB = [
    (
        "school",
        "At what PSI do schools close?",
        "no_governing_guidance",
        "school-closure-authority-gap",
        "Closure is communicated by MOE directly; no published threshold.",
    ),
    (
        "preschool",
        "At what PSI must a preschool close?",
        "no_governing_guidance",
        "school-closure-authority-gap",
        "Same gap, preschool phrasing.",
    ),
    (
        "preschool",
        "What size air purifier do I need for a 40 square metre classroom?",
        "no_governing_guidance",
        "preschool-purifier-operation-gap",
        "Purifier sizing is an engineering question the guidance does not address.",
    ),
    (
        "school",
        "Which HEPA filter class should our classroom purifiers use?",
        "no_governing_guidance",
        "preschool-purifier-operation-gap",
        "Filter class is not published.",
    ),
    (
        "preschool",
        "How often should we replace the purifier filter during an episode?",
        "no_governing_guidance",
        "preschool-purifier-operation-gap",
        "Replacement interval is not published.",
    ),
    (
        "school",
        "At what PSI should we switch the classroom purifiers on?",
        "no_governing_guidance",
        "preschool-purifier-operation-gap",
        "No switch-on threshold is published.",
    ),
    (
        "preschool",
        "Is an N95 mask suitable for a toddler in our infant care room?",
        "no_governing_guidance",
        "public-mask-usage",
        "No published fit or suitability guidance for young children.",
    ),
    (
        "general_public",
        "What N95 size should I buy for my 4-year-old?",
        "no_governing_guidance",
        "public-mask-usage",
        "Mask sizing for children is not published.",
    ),
    (
        "general_public",
        "My child has asthma and is wheezing. How many puffs of the inhaler should I give?",
        "requires_professional_judgement",
        "moh-individual-medical-management-boundary",
        "Clinical management. Must route to a healthcare provider, not answer.",
    ),
    (
        "general_public",
        "Should I increase my mother's COPD medication during the haze?",
        "requires_professional_judgement",
        "moh-individual-medical-management-boundary",
        "Medication change is a clinical decision.",
    ),
    (
        "eldercare",
        "One of our clients is short of breath. Is it serious enough to see a doctor?",
        "requires_professional_judgement",
        "moh-individual-medical-management-boundary",
        "Triage is a clinical judgement, not a population advisory.",
    ),
    (
        "school",
        "A student says her chest hurts. Does that mean she needs medical attention?",
        "requires_professional_judgement",
        "moh-individual-medical-management-boundary",
        "Symptom interpretation is clinical.",
    ),
    (
        "eldercare",
        "At what PSI must a senior care centre suspend its day programme?",
        "no_governing_guidance",
        "eldercare-guidance-coverage-gap",
        "No eldercare-specific threshold is published. Transposing the "
        "MOM worksite table would be confabulation.",
    ),
    (
        "eldercare",
        "What is the PSI threshold for closing the centre entirely?",
        "no_governing_guidance",
        "eldercare-guidance-coverage-gap",
        "No published closure threshold for eldercare.",
    ),
    (
        "worksite",
        "What work rest cycle should we use at PSI 180?",
        "no_governing_guidance",
        "mom-work-rest-and-controls",
        "No numeric haze work-rest cycle is published. The numeric framework "
        "that exists is for heat stress, a different hazard.",
    ),
    (
        "worksite",
        "How many minutes of rest per hour outdoors at PSI 220?",
        "no_governing_guidance",
        "mom-work-rest-and-controls",
        "Same gap, numeric phrasing.",
    ),
    (
        "worksite",
        "Do I have to pay workers their full wages if I stand down outdoor work?",
        "out_of_scope",
        "worksite-stop-work-authority",
        "Employment terms, not WSH guidance.",
    ),
    (
        "worksite",
        "Can I make my crew take unpaid leave during the haze?",
        "out_of_scope",
        "worksite-stop-work-authority",
        "Employment terms.",
    ),
    (
        "event",
        "Do I have to give refunds if I cancel the race?",
        "out_of_scope",
        "event-decision-timing",
        "Commercial and contractual, not advisory.",
    ),
    (
        "preschool",
        "Can parents demand a fee waiver for the cancelled excursion?",
        "out_of_scope",
        "event-decision-timing",
        "Fee matters are outside the haze advisories.",
    ),
    (
        "general_public",
        "What is the exact PM2.5 cutoff between Band 2 and Band 3?",
        "conflicting_sources",
        "nea-pm25-bands",
        "The authoritative table is on haze.gov.sg, whose robots.txt disallows "
        "retrieval by this system. The corpus value is explicitly unverified.",
    ),
    (
        "worksite",
        "How long is prolonged, in minutes?",
        "no_governing_guidance",
        "school-recess-and-transit",
        "'Prolonged' is not numerically defined in the guidance.",
    ),
    (
        "general_public",
        "What counts prolonged outdoor exposure exactly?",
        "no_governing_guidance",
        "school-recess-and-transit",
        "Same gap.",
    ),
    (
        "worksite",
        "What does the tripartite advisory say about redeployment pay?",
        "no_governing_guidance",
        "mom-tripartite-advisory",
        "The advisory's detailed contents were not retrieved into this corpus.",
    ),
    (
        "general_public",
        "There are 400 hotspots detected in Sumatra. Should I cancel my outdoor plans?",
        "no_governing_guidance",
        "nasa-firms-hotspots",
        "No published obligation is conditioned on hotspot count. A plausible near-miss: "
        "the system has hotspot data and could easily invent a threshold.",
    ),
    (
        "event",
        "How many hotspots means I should postpone my event?",
        "no_governing_guidance",
        "nasa-firms-hotspots",
        "Same gap, threshold phrasing.",
    ),
    (
        "school",
        "What is the PSI threshold for cancelling the school bus service?",
        "no_governing_guidance",
        "school-closure-authority-gap",
        "Plausible near-miss: no published transport threshold exists.",
    ),
    (
        "preschool",
        "How long can a child stay in the purifier room before we must call the parent?",
        "no_governing_guidance",
        "ecda-unwell-children-room",
        "The room is required; duration and escalation are not specified.",
    ),
    (
        "worksite",
        "What age counts as elderly for susceptible employee classification?",
        "no_governing_guidance",
        "mom-susceptible-employees",
        "The guidance names 'elderly' without defining an age.",
    ),
    (
        "general_public",
        "Does well-controlled asthma count as chronic lung disease for the advisory?",
        "no_governing_guidance",
        "public-vulnerable-self-identification",
        "The qualifying conditions are not enumerated. A borderline case is for a clinician.",
    ),
]

for i, (role, q, reason, evidence, note) in enumerate(OOKB, start=1):
    add(
        f"ok_{i:03d}",
        "out_of_knowledge_base",
        role,
        q,
        "abstain",
        [reason],
        [evidence],
        gold_abstain_reason=reason,
        must_not_contain=PERMISSIVE_STRINGS,
        notes=note,
    )

# ---------------------------------------------------------------------------
# 5. forecast_temporal (20)
# ---------------------------------------------------------------------------

FORECAST = [
    (
        "preschool",
        "The 24-hr PSI forecast for tomorrow is 90 to 130. We have an excursion booked. "
        "Parents need to be told tonight. Do we go?",
        "restrict",
        ["forecast_range", "band_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "school-excursion-forecast-decision"],
        "Range straddles 100/101. Plan against the worst band the range reaches, so "
        "the Unhealthy posture governs. Answering against the midpoint is the error.",
    ),
    (
        "school",
        "Forecast for tomorrow is 85 to 115. Sports day is scheduled. Decision tonight?",
        "restrict",
        ["forecast_range", "band_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "school-excursion-forecast-decision"],
        "Straddles the boundary; plan against Unhealthy.",
    ),
    (
        "event",
        "Forecast for our race tomorrow is 180 to 220. Do we proceed?",
        "restrict",
        ["forecast_range", "band_very_unhealthy"],
        ["nea-forecast-is-a-range", "event-participant-exertion"],
        "Straddles 200/201; the Very Unhealthy posture governs a strenuous mass event.",
    ),
    (
        "worksite",
        "Tomorrow's forecast is 190 to 210. How should I roster outdoor work?",
        "restrict",
        ["forecast_range", "band_very_unhealthy"],
        ["worksite-forecast-shift-planning", "mom-outdoor-work-very-unhealthy"],
        "Plan against the worst band; measures cannot be assembled at short notice.",
    ),
    (
        "eldercare",
        "Forecast tomorrow 95 to 125. Outing booked. Decision?",
        "restrict",
        ["forecast_range", "band_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "eldercare-outing-decision"],
        "Straddles boundary; vulnerable cohort.",
    ),
    (
        "preschool",
        "Forecast tomorrow is 40 to 60. Excursion?",
        "proceed",
        ["forecast_range", "band_moderate"],
        ["nea-forecast-is-a-range", "nea-psi-health-advisory-vulnerable"],
        "Range spans Good to Moderate; neither band restricts activity.",
    ),
    (
        "school",
        "Forecast tomorrow 210 to 260. Outdoor CCA?",
        "suspend",
        ["forecast_range", "band_very_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "nea-psi-health-advisory-vulnerable"],
        "Whole range in Very Unhealthy.",
    ),
    (
        "event",
        "Forecast tomorrow 310 to 350 for our outdoor concert.",
        "suspend",
        ["forecast_range", "band_hazardous"],
        ["nea-forecast-is-a-range", "event-static-versus-strenuous"],
        "Hazardous reaches static events.",
    ),
    (
        "worksite",
        "Next shift forecast 60 to 90. Any measures needed?",
        "proceed",
        ["forecast_range", "band_moderate"],
        ["worksite-good-moderate-bands", "mom-preparatory-measures"],
        "Preparatory measures only at 100 and below.",
    ),
    (
        "general_public",
        "Forecast tonight is 150 to 190. Should I plan my long run for tomorrow morning?",
        "proceed_with_precautions",
        ["forecast_range", "band_unhealthy"],
        ["nea-forecast-is-a-range", "nea-psi-health-advisory-healthy"],
        "Healthy adult at Unhealthy: reduce duration and intensity.",
    ),
    (
        "preschool",
        "It is 95 now but forecast to reach 140 by the afternoon. Afternoon outdoor play?",
        "restrict",
        ["forecast_range", "band_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "ecda-preschool-outdoor-unhealthy"],
        "Current reading is Moderate but the activity is in the forecast window. "
        "Answering from the current reading is the permissive error.",
    ),
    (
        "school",
        "PSI is 88 now, forecast 120 to 150 for the 4pm training. Does it run?",
        "restrict",
        ["forecast_range", "band_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "moe-outdoor-activities-unhealthy"],
        "Same trap: the activity sits in the forecast window, not the current one.",
    ),
    (
        "event",
        "PSI is 70 now, forecast 230 to 270 for our evening race. Proceed?",
        "restrict",
        ["forecast_range", "band_very_unhealthy"],
        ["nea-forecast-is-a-range", "event-participant-exertion"],
        "Large forecast deterioration; current reading is irrelevant to the decision.",
    ),
    (
        "worksite",
        "Forecast is 290 to 320 for tomorrow's shift. Susceptible employees?",
        "suspend",
        ["forecast_range", "band_hazardous", "susceptible_employee"],
        ["nea-forecast-is-a-range", "mom-outdoor-work-hazardous"],
        "Range reaches Hazardous, where susceptible employees avoid outdoor work entirely.",
    ),
    (
        "eldercare",
        "Forecast 260 to 290 tomorrow. Outing?",
        "suspend",
        ["forecast_range", "band_very_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "eldercare-vulnerable-cohort"],
        "Whole range Very Unhealthy, vulnerable cohort.",
    ),
    (
        "preschool",
        "Forecast for the day after tomorrow is 100 to 105. Excursion booked. Decision?",
        "restrict",
        ["forecast_range", "band_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "ecda-preschool-outdoor-unhealthy"],
        "Narrow range straddling exactly the 100/101 boundary. The worst band governs.",
    ),
    (
        "general_public",
        "Forecast this weekend is 45 to 55. Long cycle?",
        "proceed",
        ["forecast_range", "band_moderate"],
        ["nea-forecast-is-a-range", "public-general-advisory"],
        "Straddles 50/51; neither band restricts.",
    ),
    (
        "school",
        "Tomorrow's forecast is a single number, 110. Is that how NEA publishes it?",
        "restrict",
        ["forecast_range", "band_unhealthy", "vulnerable_cohort"],
        ["nea-forecast-is-a-range", "moe-outdoor-activities-unhealthy"],
        "NEA publishes the forecast as a range with band language. The answer should "
        "note that and still apply the Unhealthy posture.",
    ),
    (
        "event",
        "We decided last night to proceed based on the forecast. Do we need to re-check this morning?",
        "proceed_with_precautions",
        ["forecast_provisional"],
        ["nea-forecast-is-a-range", "event-decision-timing"],
        "A forecast decision is provisional and should be re-checked against the "
        "actual reading before the activity begins.",
    ),
    (
        "worksite",
        "Forecast tomorrow 150 to 170. What do I need to have ready before the shift?",
        "proceed_with_precautions",
        ["forecast_range", "band_unhealthy"],
        ["worksite-forecast-shift-planning", "mom-preparatory-measures"],
        "Planning question: rotation, indoor breaks, susceptible employee identification.",
    ),
]

for i, (role, q, gold, rc, cites, note) in enumerate(FORECAST, start=1):
    add(
        f"ft_{i:03d}",
        "forecast_temporal",
        role,
        q,
        gold,
        rc,
        cites,
        must_not_contain=PERMISSIVE_STRINGS if gold in ("restrict", "suspend") else [],
        notes=note,
    )

# ---------------------------------------------------------------------------
# 6. robustness_paraphrase (25) - Singlish / colloquial, identical gold
# ---------------------------------------------------------------------------

PARAPHRASE = [
    ("tb_006", "preschool", "PSI 101 leh, my K1 got outdoor play in 20 min. Cancel or not?"),
    ("tb_005", "preschool", "PSI exactly 100 only. Still can let the K1 play outside right?"),
    ("rc_001", "preschool", "PSI 165 sia. The N2 kids got outdoor play at 10, can go or not?"),
    ("rc_002", "school", "PSI 165. Sec 3 cross country training at 4pm, still on ah?"),
    ("rc_004", "worksite", "PSI 165, my scaffolders whole day outside. Can work or not?"),
    ("rc_006", "general_public", "PSI 165. I wanted to run 10km tonight, better not?"),
    ("rc_007", "preschool", "PSI 230 already. Still bring the K2 go playground meh?"),
    ("rc_010", "worksite", "PSI 230. My healthy workers still can do long concreting outside?"),
    ("rc_012", "general_public", "PSI 230, can still cycle to work anot?"),
    ("rc_013", "preschool", "PSI only 75. Need to change our outdoor play programme?"),
    ("rc_016", "worksite", "PSI 75 nia. Need to do anything different for outdoor work?"),
    ("rc_019", "preschool", "PSI 330!! Outdoor play still can?"),
    ("rc_022", "worksite", "PSI 330. Healthy staff still do long outdoor work?"),
    (
        "rc_031",
        "school",
        "PSI 150. We shift PE to the hall but still do circuit training. Ok or not?",
    ),
    ("rc_033", "worksite", "PSI 250. Send one guy out 10 minutes check equipment, can?"),
    ("ok_001", "school", "Eh, what PSI schools will close one?"),
    ("ok_003", "preschool", "My classroom 40 sqm, what size purifier I should buy?"),
    ("ok_009", "general_public", "My boy asthma wheezing now, how many puffs inhaler to give?"),
    ("ok_013", "eldercare", "What PSI the senior centre must stop the day programme?"),
    ("ok_015", "worksite", "PSI 180, what work rest cycle we should follow?"),
    (
        "ok_025",
        "general_public",
        "Sumatra got 400 hotspots detected. Cancel my outdoor plans or not?",
    ),
    (
        "ft_001",
        "preschool",
        "Tomorrow forecast 90 to 130. Excursion booked, must tell parents tonight. Go or not?",
    ),
    (
        "ft_011",
        "preschool",
        "Now 95 only but afternoon forecast go up to 140. Afternoon outdoor play can?",
    ),
    ("ft_003", "event", "Tomorrow race forecast 180 to 220. Proceed anot?"),
    ("mh_001", "preschool", "North side now how much? My K1 outdoor play can go or not?"),
]

by_id = {it["id"]: it for it in items}
for i, (src_id, role, q) in enumerate(PARAPHRASE, start=1):
    src = by_id[src_id]
    add(
        f"rp_{i:03d}",
        "robustness_paraphrase",
        role,
        q,
        src["gold_decision"],
        src["gold_reason_codes"],
        src["gold_citation_doc_ids"],
        fixture=src["context_fixture"],
        gold_abstain_reason=src["gold_abstain_reason"],
        must_not_contain=src["must_not_contain"],
        notes=f"Singlish/colloquial paraphrase of {src_id}. Gold is identical by "
        "construction; any difference in system output is a robustness failure, "
        "not a disagreement about the guidance.",
    )


def main() -> int:
    counts: dict[str, int] = {}
    for it in items:
        counts[it["category"]] = counts.get(it["category"], 0) + 1

    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids)), "duplicate item ids"

    out = HERE / "items.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (HERE / "freeze.txt").write_text(
        "HazeQA benchmark freeze\n"
        f"items: {len(items)}\n"
        f"sha256(items.jsonl): {digest}\n"
        "frozen_at: 2026-08-08\n"
        "\n"
        "The benchmark is frozen before any evaluation run. The runner records\n"
        "this hash in every result file and the report displays it. A run whose\n"
        "recorded hash does not match this file was executed against a different\n"
        "benchmark and its numbers are not comparable.\n"
        "\n"
        "Categories:\n" + "".join(f"  {k}: {v}\n" for k, v in sorted(counts.items())),
        encoding="utf-8",
    )

    print(f"wrote {len(items)} items to {out}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
