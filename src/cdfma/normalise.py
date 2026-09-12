"""Declared-unit resolution, assembly quantities, and interval arithmetic
(spec §5.4). This is where silent errors enter, so every branch below is
covered by a unit test.

CLAUDE.md §5: "Declared-unit resolution happens only in normalise.py."
Nothing here is a judgement — no thresholds, no rule logic — only unit
conversion and arithmetic.

Design decision (resolves docs/open-questions.md #4): ``DataQuality.
uncertainty`` is parsed here as a symmetric "±X%" string, e.g. ``"±30%"``.
This is the one format the spec's worked example ever uses, so it is
adopted as the machine format rather than left ambiguous; a different
format raises ``NormaliseError`` rather than being silently misread.
"""

from __future__ import annotations

import math
import re

from cdfma.schema import ElementType, Interval

_MM_PER_M = 1000.0

_UNCERTAINTY_PATTERN = re.compile(r"^\s*±\s*(\d+(?:\.\d+)?)\s*%\s*$")


class NormaliseError(Exception):
    """Raised for a declared unit or uncertainty band this module cannot
    resolve — never resolved by guessing."""


def face_area_m2(element_type: ElementType) -> float:
    """Envelope face area (length × width), corrected by
    ``envelope_fill_ratio`` (spec §5.4 and §2.1), in m². Uses the
    envelope's two largest dimensions as the face, on the assumption
    (planar/linear archetypes) that thickness is the through-thickness
    dimension, not part of the face.
    """
    dims = sorted([element_type.envelope.length, element_type.envelope.width, element_type.envelope.thickness])
    face_length_mm, face_width_mm = dims[-1], dims[-2]
    return (face_length_mm / _MM_PER_M) * (face_width_mm / _MM_PER_M) * element_type.envelope_fill_ratio


def governing_dimension_m(element_type: ElementType) -> float:
    """The envelope dimension a "per m" figure is quantified against.
    Spec §5.4 names this "the governing envelope dimension" without
    defining which one; taken here as the longest dimension (e.g. a
    linear member's length), since that is what "per m" figures (rails,
    battens, seals) are conventionally quantified against.
    """
    return max(element_type.envelope.length, element_type.envelope.width, element_type.envelope.thickness) / _MM_PER_M


def resolve_per_element(value: float, declared_unit: str, element_type: ElementType) -> float:
    """Convert a declared-unit figure (spec §2.1's ``declared_unit``) to a
    per-element quantity (spec §5.4)."""
    if declared_unit == "per_element":
        return value
    if declared_unit == "per_m2":
        return value * face_area_m2(element_type)
    if declared_unit == "per_kg":
        return value * element_type.mass
    if declared_unit == "per_m":
        return value * governing_dimension_m(element_type)
    raise NormaliseError(f"unknown declared_unit {declared_unit!r}")


def assembly_quantity(per_element_value: float, instance_count: int) -> float:
    """Assembly quantity = instance count × per-element figure (spec
    §5.4). Waste and offcut allowances are not modelled in the MVP."""
    return per_element_value * instance_count


def parse_uncertainty_fraction(uncertainty: str) -> float:
    """Parse a "±X%" band into a fraction (e.g. ``"±30%"`` -> ``0.30``).
    See the module docstring: this is the one format adopted for Slice 1.
    """
    match = _UNCERTAINTY_PATTERN.match(uncertainty)
    if match is None:
        raise NormaliseError(
            f"uncertainty {uncertainty!r} is not in the supported '±X%' format"
        )
    return float(match.group(1)) / 100.0


def to_interval(value: float, uncertainty: str) -> Interval:
    """A point value plus its uncertainty band, as an ``Interval``. Do not
    unwrap back to ``value`` for convenience once built (CLAUDE.md §5)."""
    fraction = parse_uncertainty_fraction(uncertainty)
    a, b = value * (1 - fraction), value * (1 + fraction)
    return Interval(low=min(a, b), high=max(a, b))


def add(a: Interval, b: Interval) -> Interval:
    return Interval(low=a.low + b.low, high=a.high + b.high)


def sum_intervals(intervals: list[Interval]) -> Interval:
    if not intervals:
        return Interval(low=0.0, high=0.0)
    total = intervals[0]
    for interval in intervals[1:]:
        total = add(total, interval)
    return total


def scale(a: Interval, factor: float) -> Interval:
    x, y = a.low * factor, a.high * factor
    return Interval(low=min(x, y), high=max(x, y))


def subtract(a: Interval, b: Interval) -> Interval:
    return Interval(low=a.low - b.high, high=a.high - b.low)


def indistinguishable(a: Interval, b: Interval) -> bool:
    """True when ``a`` and ``b``'s difference falls inside their combined
    band — i.e. zero is within ``a - b`` (CLAUDE.md architecture
    invariant 8). This is the uncertainty band, never the priority
    profile's indifference band (invariant 9) — callers must not conflate
    the two.
    """
    diff = subtract(a, b)
    return diff.low <= 0.0 <= diff.high


def present_value(amount: float, rate: float, year: int) -> float:
    """Discount ``amount`` occurring at ``year`` back to year 0 at
    ``rate`` (spec §2.8). ``rate: 0.0`` is the undiscounted case."""
    return amount / ((1.0 + rate) ** year)


def replacement_count(service_life: int, study_period: int) -> int:
    """DRV-05: ``ceil(study_period ÷ service_life) − 1`` (spec §3.2)."""
    return math.ceil(study_period / service_life) - 1


def replacement_years(service_life: int, study_period: int) -> list[int]:
    """The years within the study period at which a natural (non-cascaded)
    replacement falls, one per DRV-05 replacement count."""
    return [service_life * k for k in range(1, replacement_count(service_life, study_period) + 1)]
