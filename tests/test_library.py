"""Unit tests for the library layer: YAML loading, validation, id
resolution, and manual entry (src/cdfma/library.py). These exercise code
mechanics with synthetic fixture data; they are not the spec's numbered
acceptance tests (see tests/test_acceptance.py) and do not stand in for
docs/worked-example.md's answer key.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cdfma.library import (
    Library,
    LibraryError,
    append_connection_type,
    append_element_type,
    load_connection_types,
    load_element_types,
    load_project_parameters,
)
from cdfma.schema import (
    CompositionEntry,
    ConnectionType,
    DataQuality,
    ElementCost,
    ElementType,
    EmbodiedGHG,
    Envelope,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

_VALID_DATA_QUALITY = """
        source: "test fixture"
        data_type: estimate
        vintage: 2026
        geography: AU
        uncertainty: "±10%"
"""

_MINIMAL_ELEMENT_TYPE = """
element_types:
  - id: {id}
    name: "Test element"
    layer: skin
    tier: material
    service_life: 20
    service_life_basis: assumed
    composition:
      - material: steel
        mass_fraction: 1.0
    decomposable: true
    declared_recovery_pathway: recycle
    provenance: archetype
    shape_class: planar
    envelope: {{length: 100, width: 100, thickness: 10}}
    envelope_fill_ratio: 1.0
    mass: 5
    orientation_constraint: none
    stackable: true
    geometry_provenance: archetype
    g_level: G0
    embodied_ghg:
      declared_unit: per_kg
      ghg_A1A3: 1.0
      ghg_C: 0.5
      ghg_D: 0.0
      ghg_data:
{data_quality}
    cost:
      currency: AUD
      price_date: "2026-01"
      cost_supply: 1.0
      cost_install: 1.0
      cost_removal: 1.0
      residual_value: 0.0
      cost_data:
{data_quality}
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- real, shipped data ------------------------------------------------


def test_loads_shipped_project_parameters() -> None:
    params = load_project_parameters(DATA_DIR / "project_parameters.yaml")
    assert params.study_period == 60
    assert params.discount_rate == 0.0
    assert params.sensitivity_rates == [0.05]
    assert params.currency == "AUD"


def test_loads_shipped_element_types() -> None:
    element_types = load_element_types(DATA_DIR / "element_types.yaml")
    panel = element_types["cladding_panel_alu_mw_25"]
    assert panel.service_life == 25
    assert panel.layer == "skin"
    assert panel.mass == 78
    assert panel.nestable is None  # honestly unstated, not invented
    assert panel.embodied_ghg.ghg_D == -9.0
    assert panel.cost.residual_value == 0


def test_loads_shipped_connection_types() -> None:
    # adhesive_bond / mechanical_bracket carry PLACEHOLDER DataQuality
    # (docs/open-questions.md #1) but are otherwise real, from the
    # worked-example appendix.
    connection_types = load_connection_types(DATA_DIR / "connection_types.yaml")
    assert set(connection_types) == {"adhesive_bond", "mechanical_bracket"}
    assert connection_types["adhesive_bond"].damage_to_host == "major"
    assert connection_types["mechanical_bracket"].re_installable is True


def test_library_load_bundles_all_three(tmp_path: Path) -> None:
    library = Library.load(DATA_DIR)
    assert "cladding_panel_alu_mw_25" in library.element_types
    assert library.get_element_type("cladding_panel_alu_mw_25").id == "cladding_panel_alu_mw_25"
    assert library.project_parameters.study_period == 60


def test_get_element_type_missing_raises() -> None:
    library = Library.load(DATA_DIR)
    with pytest.raises(LibraryError, match="no element type"):
        library.get_element_type("does_not_exist")


def test_get_connection_type_missing_raises() -> None:
    library = Library.load(DATA_DIR)
    with pytest.raises(LibraryError, match="no connection type"):
        library.get_connection_type("does_not_exist")


# --- validation failures, via synthetic fixtures -----------------------


def test_duplicate_id_raises(tmp_path: Path) -> None:
    text = _MINIMAL_ELEMENT_TYPE.format(id="dup_id", data_quality=_VALID_DATA_QUALITY)
    # append the same record again under the same top-level key
    doubled = text.replace("element_types:\n", "element_types:\n", 1)
    doubled = doubled + text.split("element_types:\n", 1)[1]
    path = _write(tmp_path / "element_types.yaml", doubled)
    with pytest.raises(LibraryError, match="duplicate id"):
        load_element_types(path)


def test_bad_id_format_raises(tmp_path: Path) -> None:
    text = _MINIMAL_ELEMENT_TYPE.format(id="Not-Snake-Case", data_quality=_VALID_DATA_QUALITY)
    path = _write(tmp_path / "element_types.yaml", text)
    with pytest.raises(LibraryError, match="snake_case"):
        load_element_types(path)


def test_missing_data_quality_raises(tmp_path: Path) -> None:
    # No bare numbers: ghg_data is required (CLAUDE.md architecture invariant 7).
    text = _MINIMAL_ELEMENT_TYPE.format(id="valid_id", data_quality=_VALID_DATA_QUALITY)
    broken = text.replace("    ghg_data:\n" + _VALID_DATA_QUALITY, "    ghg_data: null\n", 1)
    path = _write(tmp_path / "element_types.yaml", broken)
    with pytest.raises(LibraryError, match="failed validation"):
        load_element_types(path)


def test_composition_must_sum_to_one(tmp_path: Path) -> None:
    text = _MINIMAL_ELEMENT_TYPE.format(id="valid_id", data_quality=_VALID_DATA_QUALITY)
    broken = text.replace("mass_fraction: 1.0", "mass_fraction: 0.5", 1)
    path = _write(tmp_path / "element_types.yaml", broken)
    with pytest.raises(LibraryError, match="sum to"):
        load_element_types(path)


def test_missing_top_level_key_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "element_types.yaml", "not_the_right_key: []\n")
    with pytest.raises(LibraryError, match="expected a top-level"):
        load_element_types(path)


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "element_types.yaml", "element_types: [this is not: valid yaml\n")
    with pytest.raises(LibraryError, match="invalid YAML"):
        load_element_types(path)


# --- append_element_type: manual entry (gui.py's "Add material" tab) ---


def _sample_element_type(element_type_id: str = "test_brick") -> ElementType:
    dq = DataQuality(source="test", data_type="estimate", vintage=2026, geography="AU", uncertainty="±20%")
    return ElementType(
        id=element_type_id,
        name="Test brick",
        layer="structure",
        tier="material",
        service_life=50,
        service_life_basis="assumed",
        composition=[CompositionEntry(material="clay", mass_fraction=1.0)],
        decomposable=True,
        declared_recovery_pathway="recycle",
        provenance="archetype",
        shape_class="volumetric",
        envelope=Envelope(length=230, width=110, thickness=76),
        envelope_fill_ratio=1.0,
        mass=3.0,
        orientation_constraint="none",
        stackable=True,
        geometry_provenance="archetype",
        g_level="G0",
        embodied_ghg=EmbodiedGHG(declared_unit="per_kg", ghg_A1A3=0.24, ghg_C=0.01, ghg_D=0.0, ghg_data=dq),
        cost=ElementCost(
            currency="AUD", price_date="2026-06", cost_supply=0.8, cost_install=0.3, cost_removal=0.1,
            residual_value=0.0, cost_data=dq,
        ),
    )


def test_append_element_type_preserves_existing_content_and_reloads(tmp_path: Path) -> None:
    target = tmp_path / "element_types.yaml"
    target.write_text((DATA_DIR / "element_types.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    append_element_type(target, _sample_element_type())

    after = target.read_text(encoding="utf-8")
    assert before in after, "existing content (including comments) must survive untouched"

    reloaded = load_element_types(target)
    assert "cladding_panel_alu_mw_25" in reloaded  # original record still loads
    assert reloaded["test_brick"].mass == 3.0


def test_append_element_type_rejects_duplicate_id(tmp_path: Path) -> None:
    target = tmp_path / "element_types.yaml"
    target.write_text((DATA_DIR / "element_types.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(LibraryError, match="already exists"):
        append_element_type(target, _sample_element_type("cladding_panel_alu_mw_25"))


def test_append_element_type_writes_valid_yaml(tmp_path: Path) -> None:
    target = tmp_path / "element_types.yaml"
    target.write_text("element_types: []\n", encoding="utf-8")

    append_element_type(target, _sample_element_type())

    # The file is still well-formed YAML, not just text concatenation.
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert document["element_types"][0]["id"] == "test_brick"


# --- append_connection_type: manual entry (gui.py's "Add connection" tab) -


def _sample_connection_type(connection_type_id: str = "test_clip") -> ConnectionType:
    dq = DataQuality(source="test", data_type="estimate", vintage=2026, geography="AU", uncertainty="±20%")
    return ConnectionType(
        id=connection_type_id,
        name="Test clip fixing",
        removal_method="unclip",
        damage_to_self="none",
        damage_to_host="minor",
        re_installable=True,
        tolerance_absorbed=4,
        reuse_cycles=5,
        ghg_A1A3=2.0,
        ghg_A5=0.3,
        ghg_data=dq,
        cost_install=15,
        cost_removal=10,
        cost_data=dq,
    )


def test_append_connection_type_preserves_existing_content_and_reloads(tmp_path: Path) -> None:
    target = tmp_path / "connection_types.yaml"
    target.write_text((DATA_DIR / "connection_types.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    append_connection_type(target, _sample_connection_type())

    after = target.read_text(encoding="utf-8")
    assert before in after, "existing content (including comments) must survive untouched"

    reloaded = load_connection_types(target)
    assert "adhesive_bond" in reloaded  # original records still load
    assert reloaded["test_clip"].reuse_cycles == 5


def test_append_connection_type_rejects_duplicate_id(tmp_path: Path) -> None:
    target = tmp_path / "connection_types.yaml"
    target.write_text((DATA_DIR / "connection_types.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(LibraryError, match="already exists"):
        append_connection_type(target, _sample_connection_type("adhesive_bond"))


def test_append_connection_type_handles_empty_flow_list(tmp_path: Path) -> None:
    # connection_types.yaml briefly shipped as "connection_types: []";
    # appending the first real record to that shape must still produce
    # valid YAML (see append_element_type's equivalent test/fix).
    target = tmp_path / "connection_types.yaml"
    target.write_text("connection_types: []\n", encoding="utf-8")

    append_connection_type(target, _sample_connection_type())

    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert document["connection_types"][0]["id"] == "test_clip"
