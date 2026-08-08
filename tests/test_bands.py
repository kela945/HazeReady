"""Band resolution is the load-bearing determinism in this system.

Boundary behaviour is tested exhaustively at every published edge, because a
single index point at 100/101 changes what a preschool is obliged to do.
"""

from __future__ import annotations

import pytest

from app.agent.tools.bands import (
    BandResolutionError,
    resolve_psi_band,
    worse_band,
)
from app.models import Band


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, Band.good),
        (1, Band.good),
        (49, Band.good),
        (50, Band.good),
        (51, Band.moderate),
        (99, Band.moderate),
        (100, Band.moderate),
        (101, Band.unhealthy),
        (150, Band.unhealthy),
        (199, Band.unhealthy),
        (200, Band.unhealthy),
        (201, Band.very_unhealthy),
        (299, Band.very_unhealthy),
        (300, Band.very_unhealthy),
        (301, Band.hazardous),
        (400, Band.hazardous),
        (1000, Band.hazardous),
    ],
)
def test_psi_boundaries(value: int, expected: Band) -> None:
    assert resolve_psi_band(value).band is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, Band.normal),
        (55, Band.normal),
        (56, Band.elevated),
        (150, Band.elevated),
        (151, Band.high),
        (250, Band.high),
        (251, Band.very_high),
    ],
)
def test_pm25_boundaries(value: int, expected: Band) -> None:
    assert resolve_psi_band(value, "pm25_1h").band is expected


def test_every_adjacent_pair_across_a_boundary_differs() -> None:
    """The property that matters: at each published edge, n and n+1 are in
    different bands."""
    for edge in (50, 100, 200, 300):
        assert resolve_psi_band(edge).band is not resolve_psi_band(edge + 1).band


def test_boundary_note_is_emitted_at_edges() -> None:
    assert "lower bound" in resolve_psi_band(101).boundary_note
    assert "upper bound" in resolve_psi_band(100).boundary_note
    assert resolve_psi_band(150).boundary_note == ""


def test_non_integer_is_truncated_not_rounded() -> None:
    """Rounding 100.5 up would move the reading into Unhealthy on the strength
    of a digit NEA does not publish. Truncation is the conservative choice
    against inventing precision, and it must be recorded in the note."""
    r = resolve_psi_band(100.9)
    assert r.band is Band.moderate
    assert "truncated" in r.boundary_note


def test_rejects_invalid_input() -> None:
    with pytest.raises(BandResolutionError):
        resolve_psi_band(-1)
    with pytest.raises(BandResolutionError):
        resolve_psi_band(float("nan"))


def test_worse_band_picks_the_more_severe() -> None:
    assert worse_band(Band.moderate, Band.unhealthy) is Band.unhealthy
    assert worse_band(Band.hazardous, Band.good) is Band.hazardous
    assert worse_band(Band.normal, Band.high) is Band.high


def test_worse_band_refuses_to_mix_indices() -> None:
    """Comparing a PM2.5 band with a PSI band is undefined, and silently
    returning one of them crashed the orchestrator on a real benchmark item."""
    with pytest.raises(BandResolutionError):
        worse_band(Band.elevated, Band.moderate)
