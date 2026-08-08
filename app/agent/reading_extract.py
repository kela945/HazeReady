"""Extract a reading the asker has stated in their own question.

Operational questions almost always carry the number: "PSI just hit 101 in the
north, do I cancel?" A system that silently answered that against a different
live reading would be answering a question nobody asked.

The rule adopted here:
  - If the asker states a reading, that reading governs the answer, because it
    is the situation they are asking about.
  - The live reading is still fetched and reported alongside, so a stated value
    that disagrees with the official one is visible rather than hidden.

The extractor is deliberately conservative. It requires an explicit index cue
(PSI, PM2.5) near the number, so "my K1 class of 20 children" does not become a
PSI of 20.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import IndexKind, Region

# "24-hr PSI is 101", "PSI 210", "PSI of 165", "psi hit 101"
_PSI_RE = re.compile(
    r"(?:24[\s-]*(?:hr|hour|hourly)?[\s-]*)?\bpsi\b[^0-9\n]{0,24}?(\d{1,4})", re.I
)
# "PM2.5 is 152", "1-hr PM2.5 of 60"
_PM25_RE = re.compile(
    r"(?:1[\s-]*(?:hr|hour|hourly)?[\s-]*)?\bpm\s*2\.?5\b[^0-9\n]{0,24}?(\d{1,4})", re.I
)
# "101 PSI", "250 pm2.5"
_VALUE_FIRST_PSI = re.compile(r"\b(\d{1,4})\s*(?:on the\s+)?psi\b", re.I)
_VALUE_FIRST_PM25 = re.compile(
    r"\b(\d{1,4})\s*(?:µg|ug|micrograms?)?[^0-9\n]{0,12}?pm\s*2\.?5\b", re.I
)

_REGION_RE = re.compile(
    r"\b(?:in|at|for|the)\s+(north|south|east|west|central)(?:ern)?\b", re.I
)


@dataclass
class StatedReading:
    value: int
    index: IndexKind
    region: Region | None
    matched_text: str


def extract_stated_reading(question: str) -> StatedReading | None:
    """Return the reading the asker stated, or None.

    PM2.5 is checked first: "1-hr PM2.5 is 152" also contains no 'psi', but a
    question mentioning both indices is ambiguous, and preferring the more
    specific PM2.5 pattern avoids reading a PM2.5 value as a PSI value — the
    error that would silently understate the band.
    """
    for regex, kind in (
        (_PM25_RE, IndexKind.pm25_1h),
        (_VALUE_FIRST_PM25, IndexKind.pm25_1h),
        (_PSI_RE, IndexKind.psi_24h),
        (_VALUE_FIRST_PSI, IndexKind.psi_24h),
    ):
        m = regex.search(question)
        if not m:
            continue
        try:
            value = int(m.group(1))
        except (ValueError, IndexError):
            continue
        if not 0 <= value <= 2000:
            continue
        return StatedReading(
            value=value,
            index=kind,
            region=_extract_region(question),
            matched_text=m.group(0).strip(),
        )
    return None


def _extract_region(question: str) -> Region | None:
    m = _REGION_RE.search(question)
    if not m:
        return None
    try:
        return Region(m.group(1).lower())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Forecast ranges
# ---------------------------------------------------------------------------

# "forecast for tomorrow is 90 to 130", "forecast 120 to 150", "forecast 180-220"
_FORECAST_RANGE_RE = re.compile(
    r"(?:forecast|outlook|expected|predicted)[^0-9\n]{0,40}?"
    r"(\d{1,4})\s*(?:to|-|–|—|and)\s*(\d{1,4})",
    re.I,
)
# "PSI is forecast to be 120 to 150"
_RANGE_THEN_FORECAST_RE = re.compile(
    r"(\d{1,4})\s*(?:to|-|–|—)\s*(\d{1,4})[^.\n]{0,30}?(?:forecast|tomorrow|outlook)", re.I
)


@dataclass
class StatedForecast:
    low: int
    high: int
    matched_text: str


def extract_stated_forecast(question: str) -> StatedForecast | None:
    """Extract a forecast RANGE stated in the question.

    NEA publishes the 24-hour PSI forecast as a range, and operational questions
    quote it that way ("forecast for tomorrow is 90 to 130"). Reading only the
    first number of that range resolves the band against the optimistic end,
    which is the permissive error: a range spanning 90-130 straddles the 100/101
    boundary and the Unhealthy obligations are the ones that must be planned for.
    """
    for regex in (_FORECAST_RANGE_RE, _RANGE_THEN_FORECAST_RE):
        m = regex.search(question)
        if not m:
            continue
        try:
            low, high = int(m.group(1)), int(m.group(2))
        except (ValueError, IndexError):
            continue
        if low > high:
            low, high = high, low
        if not (0 <= low <= 2000 and 0 <= high <= 2000):
            continue
        return StatedForecast(low=low, high=high, matched_text=m.group(0).strip())
    return None


# ---------------------------------------------------------------------------
# Cohort
# ---------------------------------------------------------------------------

_VULNERABLE_CUES = [
    r"\bpregnan\w*",
    r"\belderly\b",
    r"\bsenior\b",
    r"\bchronic\b",
    r"\bcopd\b",
    r"\basthma\w*",
    r"\bheart (?:disease|condition)\b",
    r"\blung (?:disease|condition)\b",
    r"\bvulnerable\b",
    r"\bsusceptible\b",
    r"\b(?:my|his|her|their) (?:father|mother|dad|mum|mom|grandfather|grandmother)\b",
    r"\b(?:aged|age)\s*(?:6[5-9]|[7-9]\d|1\d\d)\b",
    r"\b(?:6[5-9]|[7-9]\d)[- ]year[- ]old\b",
    r"\bpre-?existing condition\b",
]
_HEALTHY_CUES = [
    r"\ball healthy\b",
    r"\bhealthy adults?\b",
    r"\bhealthy (?:workers?|staff|employees?)\b",
    r"\bhealthy \d{1,3}[- ]year[- ]old\b",
    r"\bi am (?:a )?healthy\b",
]


def extract_cohort(question: str) -> str | None:
    """Detect a cohort the asker has named explicitly.

    Returns "vulnerable", "healthy", or None. The policy matrix carries
    cohort_variants wherever the published guidance differentiates (at PSI
    101-200 a susceptible employee is told to "minimise" where a healthy one is
    told to "reduce"), and without this the system answers every question with
    the role's default cohort and silently under-protects the named individual.

    Healthy cues are checked first so an explicit "all healthy workers" is not
    overridden by an incidental mention of a condition elsewhere in the question.
    """
    q = question.lower()
    for pat in _HEALTHY_CUES:
        if re.search(pat, q):
            return "healthy"
    for pat in _VULNERABLE_CUES:
        if re.search(pat, q):
            return "vulnerable"
    return None
