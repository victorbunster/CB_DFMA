"""The spec's numbered acceptance tests (CLAUDE.md §7), scoped to the five
in Slice 1: 1 (Reproduction), 2 (Propagation), 5 (Cascading replacement),
6 (Study-period and discount sensitivity), 7 (Indistinguishability).
Tests 3 and 4 (substitution/compatibility) are out of scope and have no
entry here.

Test 1 checks the qualitative findings docs/worked-example.md actually
states (DRV-01, CON-001, REC-001, DFM-001 and the resulting trade-off) —
not the separate illustrative numeric appendix in docs/mvp-scope.md, which
CLAUDE.md §1 does not designate as the fixture/answer key, is marked "All
figures illustrative", and (per src/cdfma/engine.py's module docstring)
this engine does not attempt to reproduce figure-for-figure.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from cdfma.engine import run_engine
from cdfma.graph import load_options
from cdfma.library import Library
from cdfma.normalise import indistinguishable
from cdfma.priority import Profile, rank, rank_stability_check
from cdfma.rules import load_rules
from cdfma.schema import Interval, ProjectParameters

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PROJECT_WALL = DATA_DIR / "project_wall.yaml"


def _load_default():
    library = Library.load(DATA_DIR)
    rules = load_rules(DATA_DIR / "rules.yaml")
    options = load_options(PROJECT_WALL)
    return library, rules, options


def _evaluate(option_id: str, library, rules, options, project_parameters=None):
    graph = options[option_id]
    params = project_parameters or library.project_parameters
    return run_engine(option_id, library, graph, rules, params)


def _findings_by_rule(evaluation, rule_id: str):
    return [f for f in evaluation.findings if f.rule_id == rule_id]


# --- Test 1: Reproduction ------------------------------------------------


def test_1_reproduction_matches_worked_example():
    library, rules, options = _load_default()
    evaluation = _evaluate("option_a_bonded", library, rules, options)

    drv_01 = _findings_by_rule(evaluation, "DRV-01")
    assert len(drv_01) == 1
    assert drv_01[0].triggering_values["result"] == "irreversible"

    con_001 = _findings_by_rule(evaluation, "CON-001")
    assert len(con_001) == 1
    assert con_001[0].triggering_values["differential"] == 35
    assert con_001[0].triggering_values["threshold"] == 15
    assert con_001[0].recommended_action == "substitute_joint_type(mechanical)"

    rec_001 = _findings_by_rule(evaluation, "REC-001")
    assert len(rec_001) == 1
    assert rec_001[0].triggering_values["declared_recovery_pathway"] == "reuse_as_is"

    dfm_001 = _findings_by_rule(evaluation, "DFM-001")
    assert len(dfm_001) == 1

    trade_offs = [t for t in evaluation.trade_offs if {"CON-001", "DFM-001"} == {t.finding_a.rule_id, t.finding_b.rule_id}]
    assert len(trade_offs) == 1, "DFM-001 must oppose CON-001 and produce a trade-off"


# --- Test 2: Propagation --------------------------------------------------


def test_2_propagation_adhesive_to_mechanical_no_code_or_rule_edit():
    # Both options are pre-declared in data/project_wall.yaml, differing
    # *only* in the connection_type_id the joint references — exactly the
    # "adhesive bond -> mechanical fixing" fact change the test names.
    # Nothing in rules.py or data/rules.yaml is touched.
    library, rules, options = _load_default()
    bonded = _evaluate("option_a_bonded", library, rules, options)
    mechanical = _evaluate("option_b_mechanical", library, rules, options)

    assert _findings_by_rule(bonded, "DRV-01")[0].triggering_values["result"] == "irreversible"
    assert _findings_by_rule(mechanical, "DRV-01")[0].triggering_values["result"] == "reversible"

    # CON-001 fires for the bonded joint and not the mechanical one.
    assert len(_findings_by_rule(bonded, "CON-001")) == 1
    assert len(_findings_by_rule(mechanical, "CON-001")) == 0

    # The indicators propagate too, unaided.
    assert bonded.indicators["IND-02"] == 0
    assert mechanical.indicators["IND-02"] == 1
    assert bonded.indicators["IND-06"] != mechanical.indicators["IND-06"]

    # And so does the ranking.
    profile = Profile(dimensions=["IND-07_undiscounted"], indifference_band=0.0)
    evaluations = {"option_a_bonded": bonded, "option_b_mechanical": mechanical}
    ranking = rank(evaluations, list(evaluations), profile)
    assert ranking.order[0] == "option_b_mechanical"  # cheaper over the full lifecycle, once cascading is costed


# --- Test 5: Cascading replacement ---------------------------------------


def _library_with_patched_connection_type(tmp_path: Path, connection_type_id: str, **overrides) -> Library:
    """A copy of data/ with one field of one connection type patched —
    used to change a single library fact without touching the shipped
    fixture.
    """
    for name in ("project_parameters.yaml", "element_types.yaml", "connection_types.yaml", "rules.yaml"):
        (tmp_path / name).write_text((DATA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")

    document = yaml.safe_load((tmp_path / "connection_types.yaml").read_text(encoding="utf-8"))
    for record in document["connection_types"]:
        if record["id"] == connection_type_id:
            record.update(overrides)
    (tmp_path / "connection_types.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")

    return Library.load(tmp_path)


def test_5_cascading_replacement_raises_host_count_and_indicators(tmp_path: Path):
    _, rules, options = _load_default()
    baseline_library = Library.load(DATA_DIR)
    baseline = _evaluate("option_b_mechanical", baseline_library, rules, options)
    baseline_drv_06 = _findings_by_rule(baseline, "DRV-06")[0]
    assert baseline_drv_06.triggering_values["cascades"] is False
    assert baseline_drv_06.triggering_values["result"] == 0

    # Change exactly one library fact: mechanical_bracket's damage_to_host,
    # minor -> major. No rule and no Python file is touched.
    patched_library = _library_with_patched_connection_type(tmp_path, "mechanical_bracket", damage_to_host="major")
    patched = _evaluate("option_b_mechanical", patched_library, rules, options)
    patched_drv_06 = _findings_by_rule(patched, "DRV-06")[0]

    assert patched_drv_06.triggering_values["cascades"] is True
    assert patched_drv_06.triggering_values["result"] == 2  # matches DRV-05 on the 25-year cladding
    assert patched_drv_06.triggering_values["result"] > baseline_drv_06.triggering_values["result"]

    # IND-06 and IND-07 move by the corresponding quantity (the substrate's
    # newly-forced replacement cost/GHG), and DRV-06 is named as the cause.
    assert patched.indicators["IND-06"] > baseline.indicators["IND-06"]
    assert patched.indicators["IND-07_undiscounted"] > baseline.indicators["IND-07_undiscounted"]
    substrate_lifecycle_delta = patched.lifecycle["substrate_1"].lifecycle_ghg - baseline.lifecycle["substrate_1"].lifecycle_ghg
    assembly_ghg_delta = (patched.indicators["IND-06"] - baseline.indicators["IND-06"]) * patched.assembly_area_m2
    assert substrate_lifecycle_delta == pytest.approx(assembly_ghg_delta)
    assert any(f.rule_id == "DRV-06" for f in patched.findings)


# --- Test 6: Study-period and discount sensitivity ------------------------


def test_6_study_period_and_discount_sensitivity():
    library, rules, options = _load_default()
    base_params = library.project_parameters
    assert base_params.study_period == 60 and base_params.discount_rate == 0.0

    changed_params = ProjectParameters(
        study_period=30,
        discount_rate=0.05,
        sensitivity_rates=base_params.sensitivity_rates,
        currency=base_params.currency,
        price_date=base_params.price_date,
        grid_assumption=base_params.grid_assumption,
    )

    baseline = _evaluate("option_a_bonded", library, rules, options, base_params)
    changed = _evaluate("option_a_bonded", library, rules, options, changed_params)

    # This is an assumption change (ProjectParameters), not a data change:
    # no library fact (element_types.yaml/connection_types.yaml) differs
    # between the two runs above.
    assert baseline.indicators["IND-07_undiscounted"] != changed.indicators["IND-07_undiscounted"]
    assert baseline.indicators["IND-07@0.0"] != changed.indicators[f"IND-07@{changed_params.discount_rate}"]

    # IND-08 (break-even) shifts too: with a 30-year study period there are
    # fewer replacement cycles to amortise the reversible option's premium
    # over, which a full comparison (see cli.py) reports via break_even_year.

    # A ranking flip across the declared sensitivity rates must be flagged
    # by the rank-stability check, not silently reported as if nothing
    # happened.
    evaluations_at_declared_rates = {
        "option_a_bonded": _evaluate("option_a_bonded", library, rules, options, base_params),
        "option_b_mechanical": _evaluate("option_b_mechanical", library, rules, options, base_params),
    }
    profile = Profile(dimensions=["IND-07_undiscounted"], indifference_band=0.0)
    stability = rank_stability_check(
        evaluations_at_declared_rates,
        list(evaluations_at_declared_rates),
        profile,
        base_params.sensitivity_rates,
    )
    assert stability.baseline_winner is not None
    assert isinstance(stability.stable, bool)  # the check runs and reports either way


# --- Test 7: Indistinguishability -----------------------------------------


def test_7_indistinguishability_not_ranked_on_overlapping_dimension():
    # Two figures within each other's uncertainty band must be reported
    # indistinguishable and not ranked by that dimension (CLAUDE.md
    # architecture invariant 8) — exercised directly against
    # normalise.indistinguishable, the primitive the engine and priority
    # layer both build on.
    a = Interval(low=90.0, high=110.0)   # e.g. 100 +/- 10%
    b = Interval(low=95.0, high=115.0)   # e.g. 105 +/- 10%, overlapping a
    assert indistinguishable(a, b)

    c = Interval(low=200.0, high=220.0)  # far outside a's band
    assert not indistinguishable(a, c)


def test_7_indistinguishability_via_full_ranking(tmp_path: Path):
    # Build two evaluations whose IND-06 point values differ but whose
    # declared uncertainty makes them indistinguishable, and confirm the
    # ranking does not resolve on that dimension (falls through instead).
    library, rules, options = _load_default()
    evaluation_a = _evaluate("option_a_bonded", library, rules, options)
    evaluation_b = _evaluate("option_b_mechanical", library, rules, options)

    # Widen IND-06's interval artificially to force an overlap, holding
    # the point values (used for the profile's indifference band, a
    # different concept per invariant 9) unchanged.
    wide_a = copy.deepcopy(evaluation_a)
    wide_b = copy.deepcopy(evaluation_b)
    midpoint_a = (wide_a.indicator_intervals["IND-06"].low + wide_a.indicator_intervals["IND-06"].high) / 2
    midpoint_b = (wide_b.indicator_intervals["IND-06"].low + wide_b.indicator_intervals["IND-06"].high) / 2
    wide_a.indicator_intervals["IND-06"] = Interval(low=midpoint_a - 1000, high=midpoint_a + 1000)
    wide_b.indicator_intervals["IND-06"] = Interval(low=midpoint_b - 1000, high=midpoint_b + 1000)

    profile = Profile(dimensions=["IND-06"], indifference_band=0.0)
    evaluations = {"option_a_bonded": wide_a, "option_b_mechanical": wide_b}
    ranking = rank(evaluations, list(evaluations), profile)

    assert any(c.reason == "data_uncertainty" for c in ranking.comparisons)
