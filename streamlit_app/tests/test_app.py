"""Headless tests for streamlit_app/app.py, using Streamlit's own
AppTest framework (no browser needed). These check the Streamlit-specific
wiring only — that widgets map to the right cdfma calls — not the
underlying logic, which is already covered by the main test suite
(tests/test_acceptance.py, tests/test_library.py) against the same
cdfma package this app imports unchanged.

Run from the repo root:
    python -m pytest streamlit_app/tests
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = REPO_ROOT / "streamlit_app" / "app.py"


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(REPO_ROOT / "data", data_dir)
    return data_dir


def _set(at: AppTest, key: str, value) -> None:
    for collection in (at.text_input, at.selectbox, at.checkbox):
        for widget in collection:
            if widget.key == key:
                widget.set_value(value)
                return
    raise KeyError(key)


def _by_label(at: AppTest, label: str):
    return next(w for w in at.text_input if w.label == label)


def test_app_loads_without_exception() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not at.exception
    assert len(at.tabs) == 6


def test_run_assessment_against_temp_data(temp_data_dir: Path) -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _by_label(at, "Data dir").set_value(str(temp_data_dir))
    _by_label(at, "Project file").set_value(str(temp_data_dir / "project_wall.yaml"))

    at.button(key="run_assessment").click().run()

    assert not at.exception
    full_text = "\n".join(el.value for el in at.get("code"))
    assert "=== Findings" in full_text
    assert "=== Option comparison" in full_text
    assert "=== Gap report" in full_text
    assert "IND-01" in full_text


def test_add_material_saves_and_reloads(temp_data_dir: Path) -> None:
    from cdfma.library import load_element_types  # local import: needs src/ on sys.path, set by app.py

    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _by_label(at, "Data dir").set_value(str(temp_data_dir))

    fields = {
        "et_id": "test_gypsum_board", "et_name": "Test gypsum board",
        "et_layer": "space_plan", "et_tier": "material",
        "et_service_life": "30", "et_slb": "assumed",
        "et_recovery_pathway": "recycle", "et_recovery_preconditions": "",
        "et_provenance": "archetype",
        "material_0": "gypsum", "fraction_0": "1.0",
        "et_shape_class": "planar",
        "et_env_l": "1200", "et_env_w": "2400", "et_env_t": "12.5",
        "et_fill_ratio": "1.0", "et_mass": "20",
        "et_orientation": "keep_flat",
        "et_nestable": "Unspecified", "et_geo_prov": "archetype", "et_g_level": "G1",
        "et_declared_unit": "per_m2", "et_ghg_a1a3": "5.0", "et_ghg_c": "0.5", "et_ghg_d": "0",
        "et_ghg_source": "test", "et_ghg_data_type": "estimate", "et_ghg_vintage": "2026",
        "et_ghg_geography": "AU", "et_ghg_uncertainty": "±20%",
        "et_currency": "AUD", "et_price_date": "2026-06",
        "et_cost_supply": "10", "et_cost_install": "5", "et_cost_removal": "3", "et_residual_value": "0",
        "et_cost_source": "test", "et_cost_data_type": "estimate", "et_cost_vintage": "2026",
        "et_cost_geography": "AU", "et_cost_uncertainty": "±20%",
    }
    for key, value in fields.items():
        _set(at, key, value)
    _set(at, "et_decomposable", True)
    _set(at, "et_stackable", True)

    at.button(key="save_element_type").click().run()

    assert not at.exception
    assert not at.error
    assert at.success

    reloaded = load_element_types(temp_data_dir / "element_types.yaml")
    assert "test_gypsum_board" in reloaded
    assert reloaded["test_gypsum_board"].mass == 20.0
    # existing shipped content must survive untouched alongside it
    assert "cladding_panel_alu_mw_25" in reloaded


def test_add_material_rejects_invalid_id(temp_data_dir: Path) -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _by_label(at, "Data dir").set_value(str(temp_data_dir))
    _set(at, "et_id", "Not Snake Case")
    _set(at, "material_0", "x")
    _set(at, "fraction_0", "1.0")

    at.button(key="save_element_type").click().run()

    assert not at.exception  # a bad form must surface st.error, never crash the app
    assert at.error


def test_add_connection_saves_and_reloads(temp_data_dir: Path) -> None:
    from cdfma.library import load_connection_types

    at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    _by_label(at, "Data dir").set_value(str(temp_data_dir))

    fields = {
        "ct_id": "test_clip", "ct_name": "Test clip fixing", "ct_removal_method": "unclip",
        "ct_damage_to_self": "none", "ct_damage_to_host": "minor",
        "ct_access_requirement": "", "ct_tolerance_absorbed": "4", "ct_reuse_cycles": "5",
        "ct_ghg_a1a3": "2.0", "ct_ghg_a5": "0.3",
        "ct_ghg_source": "test", "ct_ghg_data_type": "estimate", "ct_ghg_vintage": "2026",
        "ct_ghg_geography": "AU", "ct_ghg_uncertainty": "±20%",
        "ct_cost_install": "15", "ct_cost_removal": "10",
        "ct_cost_source": "test", "ct_cost_data_type": "estimate", "ct_cost_vintage": "2026",
        "ct_cost_geography": "AU", "ct_cost_uncertainty": "±20%",
    }
    for key, value in fields.items():
        _set(at, key, value)
    _set(at, "ct_re_installable", True)

    at.button(key="save_connection_type").click().run()

    assert not at.exception
    assert not at.error
    assert at.success

    reloaded = load_connection_types(temp_data_dir / "connection_types.yaml")
    assert "test_clip" in reloaded
    assert reloaded["test_clip"].reuse_cycles == 5
    assert "adhesive_bond" in reloaded
