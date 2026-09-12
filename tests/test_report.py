"""Unit tests for report.py's renderers, beyond what's exercised
incidentally by the other test files. Focused on render_composition,
which has no other direct coverage.
"""

from __future__ import annotations

from pathlib import Path

from cdfma.graph import load_options
from cdfma.library import Library
from cdfma.report import render_composition

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_render_composition_lists_instances_and_connections() -> None:
    library = Library.load(DATA_DIR)
    options = load_options(DATA_DIR / "project_wall.yaml")

    text = render_composition(options, library)

    assert "=== Composition ===" in text
    assert "--- option_a_bonded ---" in text
    assert "--- option_b_mechanical ---" in text
    # facts from the library appear, not a re-derivation of them
    assert "cladding_panel_alu_mw_25" in text
    assert "aluminium 35%" in text
    assert "mineral_wool 60%" in text
    # the differing joint is visible in each option's own section
    assert "adhesive_bond" in text
    assert "mechanical_bracket" in text
    # element -> host direction is shown
    assert "cladding_1 -> substrate_1" in text


def test_render_composition_respects_the_options_given() -> None:
    library = Library.load(DATA_DIR)
    options = load_options(DATA_DIR / "project_wall.yaml")
    only_one = {"option_a_bonded": options["option_a_bonded"]}

    text = render_composition(only_one, library)

    assert "option_a_bonded" in text
    assert "option_b_mechanical" not in text


def test_render_composition_handles_empty_graph() -> None:
    from cdfma.graph import Graph

    library = Library.load(DATA_DIR)
    empty = {"nothing_yet": Graph(instances={}, connection_instances={}, composition_edges=[], dependency_edges=[])}

    text = render_composition(empty, library)

    assert "(none)" in text
