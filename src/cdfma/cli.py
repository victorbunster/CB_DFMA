"""Entry point (CLAUDE.md §8): ``python -m cdfma.cli --project
data/project_wall.yaml`` runs the assessment and prints the three reports
— findings, option comparison, gap report (spec §6).

``evaluate_project`` is the reusable core of this: it does the loading and
running, and returns everything needed to render the three reports. Both
``main`` below and ``gui.py`` call it, so there is exactly one place that
orchestrates library -> graph -> rules -> engine -> priority.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from cdfma.engine import EvaluationResult, break_even_year, run_engine
from cdfma.graph import load_options
from cdfma.library import Library
from cdfma.priority import (
    ConstraintResult,
    Profile,
    RankingResult,
    RankStabilityResult,
    apply_constraints,
    check_targets,
    load_priority,
)
from cdfma.priority import rank as rank_options
from cdfma.priority import rank_stability_check
from cdfma.report import render_comparison, render_findings, render_gap_report
from cdfma.rules import load_rules


@dataclass
class ProjectResult:
    library: Library
    evaluations: dict[str, EvaluationResult]
    profile: Profile | None
    constraint_result: ConstraintResult | None
    target_report: dict[str, dict[str, bool]] | None
    ranking: RankingResult | None
    stability: RankStabilityResult | None
    break_evens: dict[str, int | None] | None
    priority_error: str | None


def list_option_ids(project_path: Path) -> list[str]:
    """Every option id declared in a project file, sorted — so a caller
    (gui.py's option selectors) can offer a pick list before running
    anything.
    """
    return sorted(load_options(project_path))


def evaluate_project(data_dir: Path, project_path: Path, option_ids: list[str] | None = None) -> ProjectResult:
    """Run the assessment. By default every option in ``project_path`` is
    evaluated together (unchanged behaviour). Pass ``option_ids`` (e.g.
    exactly two) to restrict the run to those — useful once a project
    file accumulates more than two options (CLAUDE.md's declared scope is
    "two compared variants", and the ranking/rank-stability/IND-08
    break-even machinery below is built around exactly two; selecting
    down to two keeps that meaningful instead of silently going quiet
    once a third option exists).
    """
    library = Library.load(data_dir)
    rules = load_rules(data_dir / "rules.yaml")
    options = load_options(project_path)
    if option_ids is not None:
        missing = [oid for oid in option_ids if oid not in options]
        if missing:
            raise ValueError(f"{project_path}: no such option(s): {', '.join(missing)}")
        options = {oid: options[oid] for oid in option_ids}

    evaluations = {
        option_id: run_engine(option_id, library, graph, rules, library.project_parameters)
        for option_id, graph in sorted(options.items())
    }

    profile = constraint_result = ranking = stability = break_evens = None
    target_report: dict[str, dict[str, bool]] | None = None
    priority_error = None
    try:
        constraints, targets, profile = load_priority(project_path)
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not fatal
        priority_error = str(exc)
    else:
        constraint_result = apply_constraints(evaluations, constraints)
        target_report = check_targets(evaluations, targets)
        surviving = {oid: evaluations[oid] for oid in constraint_result.surviving_option_ids}
        if surviving:
            ranking = rank_options(surviving, list(surviving), profile)
        if len(surviving) > 1:
            stability = rank_stability_check(
                surviving, list(surviving), profile, library.project_parameters.sensitivity_rates
            )
        if len(evaluations) == 2:
            option_ids = sorted(evaluations)
            study_period = library.project_parameters.study_period
            break_evens = {
                "carbon": break_even_year(
                    evaluations[option_ids[0]].lifecycle, evaluations[option_ids[1]].lifecycle, study_period, "ghg"
                ),
                "cost": break_even_year(
                    evaluations[option_ids[0]].lifecycle, evaluations[option_ids[1]].lifecycle, study_period, "cost"
                ),
            }

    return ProjectResult(
        library=library,
        evaluations=evaluations,
        profile=profile,
        constraint_result=constraint_result,
        target_report=target_report,
        ranking=ranking,
        stability=stability,
        break_evens=break_evens,
        priority_error=priority_error,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cdfma", description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="path to the project graph YAML (e.g. data/project_wall.yaml)")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="directory holding the library YAML files (default: data)")
    parser.add_argument(
        "--option",
        action="append",
        dest="options",
        metavar="OPTION_ID",
        help="restrict the run to this option id; repeat to select more than one (e.g. --option a --option b). "
        "Default: every option in the project file.",
    )
    args = parser.parse_args(argv)

    result = evaluate_project(args.data_dir, args.project, option_ids=args.options)

    for option_id in sorted(result.evaluations):
        print(render_findings(result.evaluations[option_id]))
        print()

    print(render_gap_report(list(result.evaluations.values())))
    print()

    if result.priority_error:
        print(f"(no priority declarations: {result.priority_error})")
        return 0

    print(render_comparison(result.evaluations, result.ranking, result.stability, result.break_evens))
    print()
    if result.constraint_result and result.constraint_result.excluded:
        print("Excluded by constraint:")
        for option_id, reasons in sorted(result.constraint_result.excluded.items()):
            print(f"  {option_id}: {'; '.join(reasons)}")
        print()
    if result.target_report:
        print("Targets:")
        for option_id in sorted(result.target_report):
            for indicator_id, met in sorted(result.target_report[option_id].items()):
                print(f"  {option_id} {indicator_id}: {'met' if met else 'NOT MET'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
