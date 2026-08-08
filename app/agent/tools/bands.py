"""Deterministic band resolution. Pure Python. No language model.

This module is the design constraint the whole project is built around. Band
boundaries are closed integer intervals, and a single index point at 100/101
changes what a preschool is obliged to do. Threshold comparison is arithmetic,
it has a correct answer, and there is no reason to delegate it to a system that
predicts tokens.

The A5 ablation arm replaces this module with the language model, specifically
to measure what that costs.
"""

from __future__ import annotations

from app.models import Band, BandResult, IndexKind

# (lower_inclusive, upper_inclusive_or_None, band, label, source_doc_id)
PSI_24H_BANDS: list[tuple[int, int | None, Band, str]] = [
    (0, 50, Band.good, "Good"),
    (51, 100, Band.moderate, "Moderate"),
    (101, 200, Band.unhealthy, "Unhealthy"),
    (201, 300, Band.very_unhealthy, "Very Unhealthy"),
    (301, None, Band.hazardous, "Hazardous"),
]

PM25_1H_BANDS: list[tuple[int, int | None, Band, str]] = [
    (0, 55, Band.normal, "Normal (Band 1)"),
    (56, 150, Band.elevated, "Elevated (Band 2)"),
    (151, 250, Band.high, "High (Band 3)"),
    (251, None, Band.very_high, "Very High (Band 4)"),
]

PSI_SOURCE_DOC = "nea-psi-bands"
PM25_SOURCE_DOC = "nea-pm25-bands"


class BandResolutionError(ValueError):
    pass


def resolve_psi_band(value: float, index: str = "psi_24h") -> BandResult:
    """Resolve a reading to its band.

    Boundary rule: bands are closed integer intervals. A value of exactly 100 is
    Moderate; 101 is Unhealthy. The published index is an integer, so a
    non-integer input is truncated toward zero rather than rounded — rounding
    0.5 upward at a boundary would move the reading into the more restrictive
    band on the strength of a digit the agency does not publish, and inventing
    precision at a boundary is the error this function exists to prevent.
    Truncation is recorded in `boundary_note` so the choice is visible.
    """
    kind = IndexKind(index)
    table = PSI_24H_BANDS if kind == IndexKind.psi_24h else PM25_1H_BANDS
    source_doc = PSI_SOURCE_DOC if kind == IndexKind.psi_24h else PM25_SOURCE_DOC

    if value != value or value in (float("inf"), float("-inf")):
        raise BandResolutionError(f"non-finite reading: {value!r}")
    if value < 0:
        raise BandResolutionError(f"negative reading: {value!r}")

    truncated = int(value)
    notes: list[str] = []
    if truncated != value:
        notes.append(
            f"Input {value} truncated to {truncated}; the published index is an integer."
        )

    for lower, upper, band, label in table:
        if truncated >= lower and (upper is None or truncated <= upper):
            if truncated == lower and lower > 0:
                notes.append(
                    f"{truncated} is the lower bound of {label}; "
                    f"{truncated - 1} would be the band below."
                )
            if upper is not None and truncated == upper:
                notes.append(
                    f"{truncated} is the upper bound of {label}; "
                    f"{truncated + 1} would be the band above."
                )
            return BandResult(
                value=value,
                index=kind,
                band=band,
                band_label=label,
                lower_bound=lower,
                upper_bound=upper,
                boundary_note=" ".join(notes),
                source_doc_id=source_doc,
            )

    raise BandResolutionError(f"no band covers {value!r} for index {index!r}")


def band_label(band: Band) -> str:
    for _, _, b, label in PSI_24H_BANDS + PM25_1H_BANDS:
        if b == band:
            return label
    return band.value


def worse_band(a: Band, b: Band) -> Band:
    """Return the more severe of two bands on the same index. Used to plan
    against the worst band a forecast range reaches."""
    order = [x[2] for x in PSI_24H_BANDS]
    if a in order and b in order:
        return a if order.index(a) >= order.index(b) else b
    order = [x[2] for x in PM25_1H_BANDS]
    if a in order and b in order:
        return a if order.index(a) >= order.index(b) else b
    raise BandResolutionError(f"cannot compare bands across indices: {a} and {b}")
