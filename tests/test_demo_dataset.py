"""Regression coverage for the demo dataset (docs/open-questions.md #9):
the extra element/connection types in data/element_types.yaml and
data/connection_types.yaml, exercised through data/project_wall_demo.yaml
— a six-instance wall build-up, not one of the spec's numbered acceptance
tests (see tests/test_acceptance.py for those), but a real end-to-end run
worth locking in so the richer dataset doesn't quietly break.
"""

from __future__ import annotations

from pathlib import Path

from cdfma.engine import run_engine
from cdfma.graph import load_options
from cdfma.library import Library
from cdfma.rules import load_rules

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEMO_PROJECT = DATA_DIR / "project_wall_demo.yaml"


def _evaluate(option_id: str):
    library = Library.load(DATA_DIR)
    rules = load_rules(DATA_DIR / "rules.yaml")
    options = load_options(DEMO_PROJECT)
    graph = options[option_id]
    return run_engine(option_id, library, graph, rules, library.project_parameters)


def test_demo_dataset_runs_without_gaps() -> None:
    for option_id in ("option_full_buildup_bonded", "option_full_buildup_mechanical"):
        evaluation = _evaluate(option_id)
        assert evaluation.gaps == [], f"{option_id}: no field should be missing across the demo dataset"
        assert evaluation.findings, f"{option_id}: expected findings to fire"


def test_demo_dataset_has_six_instances_and_five_connections() -> None:
    evaluation = _evaluate("option_full_buildup_bonded")
    assert len(evaluation.lifecycle) == 6
    drv_01_findings = [f for f in evaluation.findings if f.rule_id == "DRV-01"]
    assert len(drv_01_findings) == 5


def test_demo_dataset_cascades_only_in_bonded_option() -> None:
    # Same story as the original cladding/substrate pair, against a
    # different host: cladding-to-battens is adhesive_bond (damage_to_host
    # major) in one option and mechanical_bracket (minor) in the other.
    bonded = _evaluate("option_full_buildup_bonded")
    mechanical = _evaluate("option_full_buildup_mechanical")

    def cascades_for(evaluation, connection_id: str) -> bool:
        (finding,) = [
            f for f in evaluation.findings if f.rule_id == "DRV-06" and f.subject_id == connection_id
        ]
        return finding.triggering_values["cascades"]

    assert cascades_for(bonded, "cladding_to_battens") is True
    assert cascades_for(mechanical, "cladding_to_battens") is False

    # The cascade must actually raise the battens' own lifecycle burden,
    # not just be reported (this is DRV-06's whole point, per CLAUDE.md
    # §7 acceptance test 5). Compared at the instance level, not via the
    # assembly-wide IND-06/07, since those also mix in each option's
    # differing connection-type GHG/cost, which is a separate effect.
    assert bonded.lifecycle["battens_1"].lifecycle_ghg > mechanical.lifecycle["battens_1"].lifecycle_ghg
    assert bonded.lifecycle["battens_1"].lifecycle_cost_undiscounted > mechanical.lifecycle["battens_1"].lifecycle_cost_undiscounted


def test_demo_dataset_membrane_frame_differential_fires_trade_off() -> None:
    # A second CON-001/DFM-001 trade-off, independent of the cladding
    # joint, on a differential the two-instance fixture never exercised
    # (20-year membrane on a 60-year frame, common to both options).
    for option_id in ("option_full_buildup_bonded", "option_full_buildup_mechanical"):
        evaluation = _evaluate(option_id)
        con_001 = [f for f in evaluation.findings if f.rule_id == "CON-001" and f.subject_id == "membrane_to_frame"]
        dfm_001 = [f for f in evaluation.findings if f.rule_id == "DFM-001" and f.subject_id == "membrane_to_frame"]
        assert len(con_001) == 1
        assert con_001[0].triggering_values["differential"] == 40
        assert len(dfm_001) == 1
        trade_offs = [
            t
            for t in evaluation.trade_offs
            if t.subject_id == "membrane_to_frame" and {t.finding_a.rule_id, t.finding_b.rule_id} == {"CON-001", "DFM-001"}
        ]
        assert len(trade_offs) == 1
