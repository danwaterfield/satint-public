"""Shared metric calculations and publication-quality gates."""

from __future__ import annotations

import re


_FLIGHT_SOURCE_RE = re.compile(r"^source=([a-z0-9_]+);")
MIN_PUBLISHABLE_SAR_COVERAGE = 0.5


def percentage_change(value: float, baseline: float | None) -> float | None:
    """Return percentage change when the baseline is defined and positive."""
    if baseline is None or baseline <= 0:
        return None
    return (value - baseline) / baseline * 100


def normalise_sar_count(
    vessel_count: int,
    scene_coverage: float | None,
) -> float | None:
    """Adjust a SAR vessel count for the fraction of the AOI observed."""
    if scene_coverage is None or scene_coverage <= 0:
        return None
    return vessel_count / scene_coverage


def sar_percentage_change(
    vessel_count: int,
    scene_coverage: float | None,
    baseline_count: float | None,
) -> float | None:
    """Compare a coverage-normalised SAR count with its like-for-like baseline."""
    if scene_coverage is None or scene_coverage < MIN_PUBLISHABLE_SAR_COVERAGE:
        return None
    current = normalise_sar_count(vessel_count, scene_coverage)
    return percentage_change(current, baseline_count) if current is not None else None


def flight_source_key(coverage_note: str | None) -> str | None:
    """Extract the explicit source tag required for flight comparisons."""
    match = _FLIGHT_SOURCE_RE.match(coverage_note or "")
    return match.group(1) if match else None


def flight_comparison_is_publishable(
    *,
    observation_state: str,
    coverage_note: str | None,
    baseline: float | None,
    pct_change: float | None,
) -> bool:
    """Require verified coverage and an explicit source-matched baseline tag."""
    return (
        observation_state in {"observed", "observed_zero", "partial"}
        and flight_source_key(coverage_note) is not None
        and baseline is not None
        and baseline > 0
        and pct_change is not None
    )
