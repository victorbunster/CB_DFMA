"""The priority layer: constraints, dominance elimination, lexicographic
ranking under a declared profile, and the rank-stability check (spec §4).

Holds preferences only, and depends on indicator results alone (CLAUDE.md
§2 architecture invariant 2) — it never re-derives a finding or an
indicator; it consumes ``engine.EvaluationResult.indicators`` /
``indicator_intervals`` for the options it is asked to compare.

The profile's indifference band and the data's uncertainty band are kept
distinct throughout (CLAUDE.md architecture invariant 9): a dimension can
be un-ranked for either reason, and every place that happens says which.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from pathlib import Path
from typing import Literal

import yaml

from cdfma.engine import EvaluationResult
from cdfma.normalise import indistinguishable
from cdfma.schema import Interval

# Whether a lower or higher value is preferred, for each indicator this
# layer knows how to rank on. This is structural to what the indicator
# measures (spec §3.2), not a project-declared preference or a threshold,
# so it lives here as fixed metadata rather than in rules.yaml.
_DIRECTION: dict[str, Literal["max", "min"]] = {
    "IND-01": "max",
    "IND-02": "max",
    "IND-05": "min",
    "IND-06": "min",
    "IND-07_undiscounted": "min",
}


def _direction(indicator_id: str) -> Literal["max", "min"]:
    if indicator_id in _DIRECTION:
        return _DIRECTION[indicator_id]
    if indicator_id.startswith("IND-07@"):
        return "min"
    raise PriorityError(f"no ranking direction known for indicator {indicator_id!r}")


class PriorityError(Exception):
    pass


@dataclass
class Constraint:
    indicator_id: str
    comparator: Literal["<=", ">="]
    threshold: float


@dataclass
class Target:
    indicator_id: str
    comparator: Literal["<=", ">="]
    threshold: float


@dataclass
class Profile:
    dimensions: list[str]  # ordered indicator ids, highest priority first
    indifference_band: float  # fraction, e.g. 0.05 for a declared 5% band

    def __post_init__(self) -> None:
        if not (1 <= len(self.dimensions) <= 4):
            raise PriorityError("a profile declares at most 4 dimensions (spec §4)")


@dataclass
class ConstraintResult:
    surviving_option_ids: list[str]
    excluded: dict[str, list[str]]  # option_id -> violated constraint descriptions


@dataclass
class DimensionComparison:
    indicator_id: str
    winner: str | None  # option_id, or None if not ranked on this dimension
    reason: str | None  # set only when winner is None: "data_uncertainty" or "indifference_band"


@dataclass
class RankingResult:
    profile_dimensions: tuple[str, ...]
    order: list[str]  # option ids, best first
    comparisons: list[DimensionComparison]


@dataclass
class RankStabilityResult:
    baseline_winner: str | None
    reordering_flips: list[tuple[tuple[str, ...], str | None]]
    rate_flips: list[tuple[float, str | None]]
    stable: bool


def load_priority(path: Path) -> tuple[list[Constraint], list[Target], Profile]:
    """Load the ``priority:`` section of ``data/project_wall.yaml`` — see
    that file's header comment for why it lives there rather than in a
    file of its own.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PriorityError(f"could not read {path}: {exc}") from exc
    document = yaml.safe_load(text)
    if not isinstance(document, dict) or "priority" not in document:
        raise PriorityError(f"{path}: expected a top-level 'priority' mapping")
    raw = document["priority"]

    constraints = [Constraint(**c) for c in raw.get("constraints", [])]
    targets = [Target(**t) for t in raw.get("targets", [])]
    profile = Profile(**raw["profile"])
    return constraints, targets, profile


def apply_constraints(
    evaluations: dict[str, EvaluationResult], constraints: list[Constraint]
) -> ConstraintResult:
    """Step 1: exclude options outright (spec §4)."""
    excluded: dict[str, list[str]] = {}
    for option_id, evaluation in evaluations.items():
        violations = []
        for constraint in constraints:
            value = evaluation.indicators.get(constraint.indicator_id)
            if value is None:
                continue
            if constraint.comparator == "<=" and value > constraint.threshold:
                violations.append(f"{constraint.indicator_id} = {value:.3g} > {constraint.threshold:.3g}")
            elif constraint.comparator == ">=" and value < constraint.threshold:
                violations.append(f"{constraint.indicator_id} = {value:.3g} < {constraint.threshold:.3g}")
        if violations:
            excluded[option_id] = violations
    surviving = [option_id for option_id in evaluations if option_id not in excluded]
    return ConstraintResult(surviving_option_ids=surviving, excluded=excluded)


def check_targets(evaluations: dict[str, EvaluationResult], targets: list[Target]) -> dict[str, dict[str, bool]]:
    """Targets don't exclude — they're reported against as met/unmet
    (spec §4)."""
    report: dict[str, dict[str, bool]] = {}
    for option_id, evaluation in evaluations.items():
        option_report = {}
        for target in targets:
            value = evaluation.indicators.get(target.indicator_id)
            if value is None:
                continue
            met = value <= target.threshold if target.comparator == "<=" else value >= target.threshold
            option_report[target.indicator_id] = met
        report[option_id] = option_report
    return report


def _better(direction: Literal["max", "min"], value_a: float, value_b: float) -> bool:
    return value_a > value_b if direction == "max" else value_a < value_b


def dominance_filter(evaluations: dict[str, EvaluationResult], option_ids: list[str], dimensions: list[str]) -> list[str]:
    """Step 2: an option is eliminated only if another surviving option is
    at least as good on every declared dimension and strictly better on
    at least one (spec §4)."""
    dominated: set[str] = set()
    for a in option_ids:
        for b in option_ids:
            if a == b:
                continue
            # Does b dominate a? b must be at least as good as a on every
            # dimension, and strictly better on at least one.
            at_least_as_good_everywhere = True
            strictly_better_somewhere = False
            for indicator_id in dimensions:
                direction = _direction(indicator_id)
                value_a = evaluations[a].indicators.get(indicator_id)
                value_b = evaluations[b].indicators.get(indicator_id)
                if value_a is None or value_b is None:
                    at_least_as_good_everywhere = False
                    break
                if _better(direction, value_a, value_b):
                    # a beats b on this dimension: b cannot dominate a.
                    at_least_as_good_everywhere = False
                    break
                if _better(direction, value_b, value_a):
                    strictly_better_somewhere = True
            if at_least_as_good_everywhere and strictly_better_somewhere:
                dominated.add(a)
    return [option_id for option_id in option_ids if option_id not in dominated]


def _dimension_winner(
    evaluations: dict[str, EvaluationResult], candidates: list[str], indicator_id: str, indifference_band: float
) -> DimensionComparison:
    if len(candidates) < 2:
        winner = candidates[0] if candidates else None
        return DimensionComparison(indicator_id=indicator_id, winner=winner, reason=None)

    direction = _direction(indicator_id)
    values = {option_id: evaluations[option_id].indicators.get(indicator_id) for option_id in candidates}
    if any(v is None for v in values.values()):
        return DimensionComparison(indicator_id=indicator_id, winner=None, reason="missing_data")

    best_id = max(values, key=lambda o: values[o]) if direction == "max" else min(values, key=lambda o: values[o])
    best_value = values[best_id]
    for option_id, value in values.items():
        if option_id == best_id:
            continue
        # Data-uncertainty check first (CLAUDE.md invariant 9: kept
        # separate from, and checked independently of, the profile band).
        interval_best = evaluations[best_id].indicator_intervals.get(indicator_id)
        interval_other = evaluations[option_id].indicator_intervals.get(indicator_id)
        if interval_best is not None and interval_other is not None and indistinguishable(interval_best, interval_other):
            return DimensionComparison(indicator_id=indicator_id, winner=None, reason="data_uncertainty")
        # Profile indifference band: a *stated preference*, never
        # substituted for the uncertainty check above.
        reference = abs(best_value) if best_value != 0 else abs(value)
        if reference and abs(value - best_value) / reference <= indifference_band:
            return DimensionComparison(indicator_id=indicator_id, winner=None, reason="indifference_band")

    return DimensionComparison(indicator_id=indicator_id, winner=best_id, reason=None)


def rank(
    evaluations: dict[str, EvaluationResult], option_ids: list[str], profile: Profile, dimension_order: list[str] | None = None
) -> RankingResult:
    """Step 3: lexicographic ranking under the profile (spec §4). Ties on
    a dimension (for either reason) fall through to the next dimension;
    an option left un-ranked all the way down keeps its relative
    position from ``option_ids``.
    """
    dimensions = dimension_order if dimension_order is not None else profile.dimensions
    remaining = list(option_ids)
    order: list[str] = []
    comparisons: list[DimensionComparison] = []

    while remaining:
        winner = None
        for indicator_id in dimensions:
            comparison = _dimension_winner(evaluations, remaining, indicator_id, profile.indifference_band)
            comparisons.append(comparison)
            if comparison.winner is not None:
                winner = comparison.winner
                break
        if winner is None:
            # Indistinguishable on every declared dimension: keep
            # relative order, take them in turn.
            winner = remaining[0]
        order.append(winner)
        remaining.remove(winner)

    return RankingResult(profile_dimensions=tuple(dimensions), order=order, comparisons=comparisons)


def rank_stability_check(
    evaluations: dict[str, EvaluationResult],
    option_ids: list[str],
    profile: Profile,
    sensitivity_rates: list[float],
) -> RankStabilityResult:
    """Step 4: re-rank across dimension reordering *and* across the
    declared discount rates (spec §4); flag whether the winner changes.
    """
    baseline = rank(evaluations, option_ids, profile)
    baseline_winner = baseline.order[0] if baseline.order else None

    reordering_flips = []
    for reordered in permutations(profile.dimensions):
        if list(reordered) == profile.dimensions:
            continue
        result = rank(evaluations, option_ids, profile, dimension_order=list(reordered))
        winner = result.order[0] if result.order else None
        if winner != baseline_winner:
            reordering_flips.append((reordered, winner))

    rate_flips = []
    if any(dim.startswith("IND-07") for dim in profile.dimensions):
        for rate in sensitivity_rates:
            rate_dimensions = [f"IND-07@{rate}" if dim.startswith("IND-07") else dim for dim in profile.dimensions]
            result = rank(evaluations, option_ids, profile, dimension_order=rate_dimensions)
            winner = result.order[0] if result.order else None
            if winner != baseline_winner:
                rate_flips.append((rate, winner))

    return RankStabilityResult(
        baseline_winner=baseline_winner,
        reordering_flips=reordering_flips,
        rate_flips=rate_flips,
        stable=not reordering_flips and not rate_flips,
    )
