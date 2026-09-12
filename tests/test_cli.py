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


def _copy_data(tmp_path: Path) -> Path:
    for name in ("project_parameters.yaml", "element_types.yaml", "connection_types.yaml", "rules.yaml", "project_wall.yaml"):
        (tmp_path / name).write_text((DATA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_list_option_ids() -> None:
    assert list_option_ids(DATA_DIR / "project_wall.yaml") == ["option_a_bonded", "option_b_mechanical"]


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
