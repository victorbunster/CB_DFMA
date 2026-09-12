"""Unit tests for cli.py's reusable core: evaluate_project's optional
option_ids selection, and list_option_ids — the pieces gui.py's "Compare"
selectors are built on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cdfma.cli import evaluate_project, list_option_ids
from cdfma.graph import Graph, append_option
from cdfma.schema import Instance

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# A self-contained two-option project graph, independent of the real
# data/project_wall.yaml's current content — that file is meant to be
# extended by the app itself (the "Build wall" tab, or CLAUDE.md's own
# worked-example pair), so a test asserting "exactly these options exist"
# against it would break every time someone used the feature it's testing.
_TWO_OPTION_PROJECT_WALL = """
options:
  option_a_bonded:
    instances:
      - id: cladding_1
        element_type_id: cladding_panel_alu_mw_25
      - id: substrate_1
        element_type_id: substrate_60
    connection_instances:
      - id: joint_1
        connection_type_id: adhesive_bond
        element_instance_id: cladding_1
        host_instance_id: substrate_1
    composition_edges: []
    dependency_edges: []
  option_b_mechanical:
    instances:
      - id: cladding_1
        element_type_id: cladding_panel_alu_mw_25
      - id: substrate_1
        element_type_id: substrate_60
    connection_instances:
      - id: joint_1
        connection_type_id: mechanical_bracket
        element_instance_id: cladding_1
        host_instance_id: substrate_1
    composition_edges: []
    dependency_edges: []

priority:
  constraints: []
  targets: []
  profile:
    dimensions: [IND-07_undiscounted]
    indifference_band: 0.05
"""


def _copy_data(tmp_path: Path) -> Path:
    for name in ("project_parameters.yaml", "element_types.yaml", "connection_types.yaml", "rules.yaml"):
        (tmp_path / name).write_text((DATA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "project_wall.yaml").write_text(_TWO_OPTION_PROJECT_WALL, encoding="utf-8")
    return tmp_path


def test_list_option_ids(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    assert list_option_ids(data_dir / "project_wall.yaml") == ["option_a_bonded", "option_b_mechanical"]


def test_evaluate_project_default_runs_every_option(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    result = evaluate_project(data_dir, data_dir / "project_wall.yaml")
    assert set(result.evaluations) == {"option_a_bonded", "option_b_mechanical"}
    assert result.break_evens is not None  # exactly two options: pairwise machinery still runs


def test_evaluate_project_selects_a_subset(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    project_path = data_dir / "project_wall.yaml"
    # add a third option so selecting matters
    append_option(
        project_path,
        "option_c_extra",
        Graph(
            instances={
                "x": Instance(id="x", element_type_id="timber_stud_frame_60"),
                "y": Instance(id="y", element_type_id="cladding_panel_alu_mw_25"),
            },
            connection_instances={},
            composition_edges=[],
            dependency_edges=[],
        ),
    )
    assert list_option_ids(project_path) == ["option_a_bonded", "option_b_mechanical", "option_c_extra"]

    all_options = evaluate_project(data_dir, project_path)
    assert set(all_options.evaluations) == {"option_a_bonded", "option_b_mechanical", "option_c_extra"}
    assert all_options.break_evens is None  # three options: the pairwise machinery correctly stays off

    pair = evaluate_project(data_dir, project_path, option_ids=["option_a_bonded", "option_b_mechanical"])
    assert set(pair.evaluations) == {"option_a_bonded", "option_b_mechanical"}
    assert pair.break_evens is not None  # narrowing to two restores it


def test_evaluate_project_rejects_unknown_option_id(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    with pytest.raises(ValueError, match="no such option"):
        evaluate_project(data_dir, data_dir / "project_wall.yaml", option_ids=["does_not_exist"])
