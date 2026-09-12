"""Unit tests for the graph layer: YAML loading, validation, and manual
entry of a new option (src/cdfma/graph.py). These exercise code mechanics
with synthetic fixture data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cdfma.graph import Graph, GraphError, append_option, load_options
from cdfma.library import Library
from cdfma.schema import ConnectionInstance, Instance

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# A self-contained two-option project graph, independent of the real
# data/project_wall.yaml's current content — that file is meant to be
# extended by the app itself (the "Build wall" tab), so a test asserting
# "exactly these options exist" against it would break every time someone
# used the feature this test is exercising.
_TWO_OPTION_PROJECT_WALL = """
options:
  option_a_bonded:
    instances:
      - id: cladding_1
        element_type_id: cladding_panel_alu_mw_25
    connection_instances: []
    composition_edges: []
    dependency_edges: []
  option_b_mechanical:
    instances:
      - id: cladding_1
        element_type_id: cladding_panel_alu_mw_25
    connection_instances: []
    composition_edges: []
    dependency_edges: []

priority:
  constraints: []
  targets: []
  profile:
    dimensions: [IND-01]
    indifference_band: 0.05
"""


def _copy_project_wall(tmp_path: Path) -> Path:
    for name in ("project_parameters.yaml", "element_types.yaml", "connection_types.yaml"):
        (tmp_path / name).write_text((DATA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    target = tmp_path / "project_wall.yaml"
    target.write_text(_TWO_OPTION_PROJECT_WALL, encoding="utf-8")
    return target


def _sample_graph() -> Graph:
    return Graph(
        instances={
            "frame_x": Instance(id="frame_x", element_type_id="timber_stud_frame_60", label="Test frame"),
            "lining_x": Instance(id="lining_x", element_type_id="plasterboard_lining_30"),
        },
        connection_instances={
            "joint_x": ConnectionInstance(
                id="joint_x",
                connection_type_id="screw_fixing_metal",
                element_instance_id="lining_x",
                host_instance_id="frame_x",
            ),
        },
        composition_edges=[],
        dependency_edges=[],
    )


def test_append_option_preserves_existing_options_and_reloads(tmp_path: Path) -> None:
    target = _copy_project_wall(tmp_path)
    library = Library.load(tmp_path)
    graph = _sample_graph()
    graph.validate_against_library(library)

    append_option(target, "my_new_wall", graph)

    text = target.read_text(encoding="utf-8")
    assert "option_a_bonded:" in text and "option_b_mechanical:" in text
    assert "priority:" in text  # the file's other top-level section survives

    reloaded = load_options(target)
    assert set(reloaded) == {"option_a_bonded", "option_b_mechanical", "my_new_wall"}
    assert reloaded["my_new_wall"].instances["frame_x"].element_type_id == "timber_stud_frame_60"
    assert reloaded["my_new_wall"].connection_instances["joint_x"].host_instance_id == "frame_x"


def test_append_option_rejects_duplicate_id(tmp_path: Path) -> None:
    target = _copy_project_wall(tmp_path)
    graph = _sample_graph()

    with pytest.raises(GraphError, match="already exists"):
        append_option(target, "option_a_bonded", graph)


def test_append_option_creates_new_file(tmp_path: Path) -> None:
    target = tmp_path / "brand_new_project.yaml"
    assert not target.exists()

    append_option(target, "opt1", _sample_graph())

    reloaded = load_options(target)
    assert set(reloaded) == {"opt1"}


def test_append_option_second_call_appends_alongside_first(tmp_path: Path) -> None:
    target = tmp_path / "brand_new_project.yaml"
    append_option(target, "opt1", _sample_graph())
    append_option(
        target,
        "opt2",
        Graph(
            instances={"solo": Instance(id="solo", element_type_id="substrate_60")},
            connection_instances={},
            composition_edges=[],
            dependency_edges=[],
        ),
    )

    reloaded = load_options(target)
    assert set(reloaded) == {"opt1", "opt2"}
    assert reloaded["opt2"].instances["solo"].element_type_id == "substrate_60"
