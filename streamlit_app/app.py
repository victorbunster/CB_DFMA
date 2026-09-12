"""Streamlit interface for the Circular DfMA MVP — a public-hostable
counterpart to ``python -m cdfma.gui`` (the Tkinter desktop GUI).

Deliberately kept out of ``src/cdfma``: CLAUDE.md §4/§8 keep the engine
free of web frameworks and third-party dependencies beyond pydantic/
PyYAML/pytest, and Streamlit pulls in a large dependency tree (pandas,
numpy, pyarrow, …) that has no place there. This app lives in its own
top-level folder and only *imports* ``cdfma`` unchanged — every value on
screen comes from the same schema, library, graph, normalise, rules,
engine, priority and report modules the CLI and Tkinter GUI use. It holds
no domain content and no evaluation logic of its own, same invariant as
gui.py.

Run locally from the repo root:
    streamlit run streamlit_app/app.py

See streamlit_app/README.md for Streamlit Community Cloud deployment.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Import the existing cdfma package directly from src/, rather than
# requiring a separate install step — the one thing that must work
# identically whether run locally or on a cloud host that only installs
# streamlit_app/requirements.txt.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import streamlit as st  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from cdfma.cli import ProjectResult, evaluate_project  # noqa: E402
from cdfma.library import LibraryError, append_connection_type, append_element_type  # noqa: E402
from cdfma.report import render_comparison, render_findings, render_gap_report, render_legend  # noqa: E402
from cdfma.schema import (  # noqa: E402
    CompositionEntry,
    ConnectionType,
    DataQuality,
    ElementCost,
    ElementType,
    EmbodiedGHG,
    Envelope,
)

st.set_page_config(page_title="Circular DfMA — Slice 1", layout="wide")

DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_PROJECT = REPO_ROOT / "data" / "project_wall.yaml"

_LAYERS = ["skin", "structure", "services", "space_plan", "site"]
_TIERS = ["material", "component", "product_assembly", "element"]
_SERVICE_LIFE_BASES = ["warranty", "standard", "observed", "assumed"]
_RECOVERY_PATHWAYS = ["reuse_as_is", "remanufacture", "recycle", "none"]
_PROVENANCES = ["archetype", "product_entry"]
_SHAPE_CLASSES = ["planar", "linear", "point_like", "volumetric", "irregular"]
_ORIENTATIONS = ["none", "keep_flat", "keep_vertical"]
_GEOMETRY_PROVENANCES = ["archetype", "product_entry", "measured"]
_G_LEVELS = ["G0", "G1"]
_DECLARED_UNITS = ["per_element", "per_m2", "per_m", "per_kg"]
_DATA_TYPES = ["product_specific_epd", "industry_average", "generic_database", "estimate"]
_NESTABLE_CHOICES = {"Unspecified": None, "Yes": True, "No": False}
_DAMAGE_LEVELS = ["none", "minor", "major"]


def _optional_float(raw: str) -> float | None:
    raw = raw.strip()
    return float(raw) if raw else None


# --- sidebar: run controls ------------------------------------------------

st.title("Circular DfMA — Slice 1")

with st.sidebar:
    st.header("Assessment")
    data_dir_input = st.text_input("Data dir", value=str(DEFAULT_DATA_DIR))
    project_input = st.text_input("Project file", value=str(DEFAULT_PROJECT))
    run_clicked = st.button("Run assessment", key="run_assessment", type="primary", use_container_width=True)
    st.caption(
        "On a shared/public deployment, anything saved via the Add "
        "tabs below only lasts for this session's container — it is "
        "not committed back to the GitHub repo and can be lost on "
        "redeploy. Run locally for changes you want to keep."
    )

if run_clicked:
    try:
        st.session_state["project_result"] = evaluate_project(Path(data_dir_input), Path(project_input))
        st.session_state["project_result_error"] = None
    except Exception as exc:  # noqa: BLE001 - surfaced below, not swallowed
        st.session_state["project_result"] = None
        st.session_state["project_result_error"] = f"{exc}\n\n{traceback.format_exc()}"

result: ProjectResult | None = st.session_state.get("project_result")
result_error: str | None = st.session_state.get("project_result_error")

tab_legend, tab_findings, tab_comparison, tab_gaps, tab_add_material, tab_add_connection = st.tabs(
    ["Legend", "Findings", "Option comparison", "Gap report", "Add material", "Add connection"]
)

with tab_legend:
    st.code(render_legend(), language=None)

if result_error:
    st.error(result_error)

with tab_findings:
    if result is None:
        st.info("Click **Run assessment** in the sidebar first.")
    else:
        option_ids = sorted(result.evaluations)
        option_id = st.selectbox("Option", option_ids)
        st.code(render_findings(result.evaluations[option_id]), language=None)

with tab_comparison:
    if result is None:
        st.info("Click **Run assessment** in the sidebar first.")
    elif result.priority_error:
        st.info(f"No priority declarations: {result.priority_error}")
    else:
        content = render_comparison(result.evaluations, result.ranking, result.stability, result.break_evens)
        if result.constraint_result and result.constraint_result.excluded:
            content += "\n\nExcluded by constraint:\n"
            for option_id, reasons in sorted(result.constraint_result.excluded.items()):
                content += f"  {option_id}: {'; '.join(reasons)}\n"
        if result.target_report:
            content += "\nTargets:\n"
            for option_id in sorted(result.target_report):
                for indicator_id, met in sorted(result.target_report[option_id].items()):
                    content += f"  {option_id} {indicator_id}: {'met' if met else 'NOT MET'}\n"
        st.code(content, language=None)

with tab_gaps:
    if result is None:
        st.info("Click **Run assessment** in the sidebar first.")
    else:
        st.code(render_gap_report(list(result.evaluations.values())), language=None)


# --- "Add material": manual entry of a new element type -------------------
#
# A form only: every value it collects passes straight into
# schema.ElementType, which is what actually validates it (composition
# summing to 1.0, id format, required DataQuality, …). No rule about what
# makes a valid element type lives here — schema.py already has it.

with tab_add_material:
    st.caption(
        "Saving adds this to element_types.yaml, but it won't appear in a "
        "run until an Instance in your project file references its id."
    )

    if "composition_rows" not in st.session_state:
        st.session_state.composition_rows = [{"material": "", "fraction": ""}]
    if "composition_next_id" not in st.session_state:
        st.session_state.composition_next_id = 1
        st.session_state.composition_ids = [0]

    st.subheader("Identity & lifecycle")
    et_id = st.text_input("id (snake_case)", key="et_id")
    et_name = st.text_input("name", key="et_name")
    col1, col2 = st.columns(2)
    et_layer = col1.selectbox("layer", _LAYERS, key="et_layer")
    et_tier = col2.selectbox("tier", _TIERS, key="et_tier")
    col1, col2 = st.columns(2)
    et_service_life = col1.text_input("service_life (years)", key="et_service_life")
    et_service_life_basis = col2.selectbox("service_life_basis", _SERVICE_LIFE_BASES, key="et_slb")
    et_decomposable = st.checkbox("decomposable", key="et_decomposable")
    et_recovery_pathway = st.selectbox("declared_recovery_pathway", _RECOVERY_PATHWAYS, key="et_recovery_pathway")
    et_recovery_preconditions = st.text_input("recovery_preconditions (comma-sep)", key="et_recovery_preconditions")
    et_provenance = st.selectbox("provenance", _PROVENANCES, key="et_provenance")

    st.subheader("Composition (materials must sum to 1.0)")
    for row_id in list(st.session_state.composition_ids):
        cols = st.columns([3, 2, 1])
        st.session_state.composition_rows[st.session_state.composition_ids.index(row_id)]["material"] = cols[
            0
        ].text_input("material", key=f"material_{row_id}", label_visibility="collapsed", placeholder="material")
        st.session_state.composition_rows[st.session_state.composition_ids.index(row_id)]["fraction"] = cols[
            1
        ].text_input(
            "mass_fraction", key=f"fraction_{row_id}", label_visibility="collapsed", placeholder="mass_fraction"
        )
        if cols[2].button("Remove", key=f"remove_{row_id}") and len(st.session_state.composition_ids) > 1:
            index = st.session_state.composition_ids.index(row_id)
            st.session_state.composition_ids.pop(index)
            st.session_state.composition_rows.pop(index)
            st.rerun()

    if st.button("+ Add material row", key="add_composition_row"):
        st.session_state.composition_ids.append(st.session_state.composition_next_id)
        st.session_state.composition_rows.append({"material": "", "fraction": ""})
        st.session_state.composition_next_id += 1
        st.rerun()

    st.subheader("Geometry (G0/G1)")
    et_shape_class = st.selectbox("shape_class", _SHAPE_CLASSES, key="et_shape_class")
    col1, col2, col3 = st.columns(3)
    et_envelope_length = col1.text_input("envelope length (mm)", key="et_env_l")
    et_envelope_width = col2.text_input("envelope width (mm)", key="et_env_w")
    et_envelope_thickness = col3.text_input("envelope thickness (mm)", key="et_env_t")
    col1, col2 = st.columns(2)
    et_fill_ratio = col1.text_input("envelope_fill_ratio (0-1)", value="1.0", key="et_fill_ratio")
    et_mass = col2.text_input("mass (kg)", key="et_mass")
    et_coordination_module = st.text_input("coordination_module (mm, optional)", key="et_coordination_module")
    et_orientation = st.selectbox("orientation_constraint", _ORIENTATIONS, key="et_orientation")
    et_stackable = st.checkbox("stackable", key="et_stackable")
    et_nestable = st.selectbox("nestable", list(_NESTABLE_CHOICES), key="et_nestable")
    et_geometry_provenance = st.selectbox("geometry_provenance", _GEOMETRY_PROVENANCES, key="et_geo_prov")
    et_g_level = st.selectbox("g_level", _G_LEVELS, key="et_g_level")

    st.subheader("Embodied GHG (spec §2.1 — one record per module)")
    et_declared_unit = st.selectbox("declared_unit", _DECLARED_UNITS, key="et_declared_unit")
    col1, col2, col3 = st.columns(3)
    et_ghg_a1a3 = col1.text_input("ghg_A1A3", key="et_ghg_a1a3")
    et_ghg_a4 = col2.text_input("ghg_A4 (optional)", key="et_ghg_a4")
    et_ghg_a5 = col3.text_input("ghg_A5 (optional)", key="et_ghg_a5")
    col1, col2 = st.columns(2)
    et_ghg_c = col1.text_input("ghg_C", key="et_ghg_c")
    et_ghg_d = col2.text_input("ghg_D (reported separately)", value="0", key="et_ghg_d")
    et_biogenic = st.text_input("biogenic_carbon (optional)", key="et_biogenic")
    col1, col2 = st.columns(2)
    et_ghg_source = col1.text_input("ghg_data.source", key="et_ghg_source")
    et_ghg_data_type = col2.selectbox("ghg_data.data_type", _DATA_TYPES, key="et_ghg_data_type")
    col1, col2, col3 = st.columns(3)
    et_ghg_vintage = col1.text_input("ghg_data.vintage (year)", key="et_ghg_vintage")
    et_ghg_geography = col2.text_input("ghg_data.geography", key="et_ghg_geography")
    et_ghg_uncertainty = col3.text_input("ghg_data.uncertainty (e.g. ±25%)", key="et_ghg_uncertainty")
    et_ghg_basis_note = st.text_input("ghg_data.basis_note", key="et_ghg_basis_note")

    st.subheader("Cost (spec §2.1)")
    col1, col2 = st.columns(2)
    et_currency = col1.text_input("currency", value="AUD", key="et_currency")
    et_price_date = col2.text_input("price_date", key="et_price_date")
    col1, col2, col3 = st.columns(3)
    et_cost_supply = col1.text_input("cost_supply", key="et_cost_supply")
    et_cost_install = col2.text_input("cost_install", key="et_cost_install")
    et_cost_removal = col3.text_input("cost_removal", key="et_cost_removal")
    et_residual_value = st.text_input("residual_value", value="0", key="et_residual_value")
    col1, col2 = st.columns(2)
    et_cost_source = col1.text_input("cost_data.source", key="et_cost_source")
    et_cost_data_type = col2.selectbox("cost_data.data_type", _DATA_TYPES, key="et_cost_data_type")
    col1, col2, col3 = st.columns(3)
    et_cost_vintage = col1.text_input("cost_data.vintage (year)", key="et_cost_vintage")
    et_cost_geography = col2.text_input("cost_data.geography", key="et_cost_geography")
    et_cost_uncertainty = col3.text_input("cost_data.uncertainty (e.g. ±25%)", key="et_cost_uncertainty")
    et_cost_basis_note = st.text_input("cost_data.basis_note", key="et_cost_basis_note")

    if st.button("Save element type", key="save_element_type", type="primary"):
        try:
            composition = []
            for row in st.session_state.composition_rows:
                material = row["material"].strip()
                fraction = row["fraction"].strip()
                if not material and not fraction:
                    continue
                composition.append(CompositionEntry(material=material, mass_fraction=float(fraction)))
            if not composition:
                raise ValueError("at least one composition material is required")

            envelope = Envelope(
                length=float(et_envelope_length), width=float(et_envelope_width), thickness=float(et_envelope_thickness)
            )
            ghg_data = DataQuality(
                source=et_ghg_source,
                data_type=et_ghg_data_type,
                vintage=int(et_ghg_vintage),
                geography=et_ghg_geography,
                uncertainty=et_ghg_uncertainty,
                basis_note=et_ghg_basis_note,
            )
            embodied_ghg = EmbodiedGHG(
                declared_unit=et_declared_unit,
                ghg_A1A3=float(et_ghg_a1a3),
                ghg_A4=_optional_float(et_ghg_a4),
                ghg_A5=_optional_float(et_ghg_a5),
                ghg_C=float(et_ghg_c),
                ghg_D=float(et_ghg_d),
                biogenic_carbon=_optional_float(et_biogenic),
                ghg_data=ghg_data,
            )
            cost_data = DataQuality(
                source=et_cost_source,
                data_type=et_cost_data_type,
                vintage=int(et_cost_vintage),
                geography=et_cost_geography,
                uncertainty=et_cost_uncertainty,
                basis_note=et_cost_basis_note,
            )
            cost = ElementCost(
                currency=et_currency,
                price_date=et_price_date,
                cost_supply=float(et_cost_supply),
                cost_install=float(et_cost_install),
                cost_removal=float(et_cost_removal),
                residual_value=float(et_residual_value),
                cost_data=cost_data,
            )
            recovery_preconditions = [s.strip() for s in et_recovery_preconditions.split(",") if s.strip()]

            element_type = ElementType(
                id=et_id.strip(),
                name=et_name.strip(),
                layer=et_layer,
                tier=et_tier,
                service_life=int(et_service_life),
                service_life_basis=et_service_life_basis,
                composition=composition,
                decomposable=bool(et_decomposable),
                declared_recovery_pathway=et_recovery_pathway,
                recovery_preconditions=recovery_preconditions,
                provenance=et_provenance,
                shape_class=et_shape_class,
                envelope=envelope,
                envelope_fill_ratio=float(et_fill_ratio),
                mass=float(et_mass),
                coordination_module=_optional_float(et_coordination_module),
                orientation_constraint=et_orientation,
                stackable=bool(et_stackable),
                nestable=_NESTABLE_CHOICES[et_nestable],
                geometry_provenance=et_geometry_provenance,
                g_level=et_g_level,
                embodied_ghg=embodied_ghg,
                cost=cost,
            )
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            st.error(f"Invalid element type: {exc}")
        else:
            path = Path(data_dir_input) / "element_types.yaml"
            try:
                append_element_type(path, element_type)
            except LibraryError as exc:
                st.error(f"Could not save: {exc}")
            else:
                st.success(
                    f"Added {element_type.id!r} to {path}. It won't appear in an assessment until an "
                    f"Instance references element_type_id: {element_type.id} — add one, then Run assessment."
                )


# --- "Add connection": manual entry of a new connection type --------------

with tab_add_connection:
    st.caption(
        "Saving adds this to connection_types.yaml, but it won't appear in a "
        "run until a ConnectionInstance in your project file references its id."
    )

    st.subheader("Identity")
    ct_id = st.text_input("id (snake_case)", key="ct_id")
    ct_name = st.text_input("name", key="ct_name")
    ct_removal_method = st.text_input("removal_method", key="ct_removal_method")
    col1, col2 = st.columns(2)
    ct_damage_to_self = col1.selectbox("damage_to_self", _DAMAGE_LEVELS, key="ct_damage_to_self")
    ct_damage_to_host = col2.selectbox("damage_to_host", _DAMAGE_LEVELS, key="ct_damage_to_host")
    ct_re_installable = st.checkbox("re_installable", key="ct_re_installable")
    ct_access_requirement = st.text_input("access_requirement (optional)", key="ct_access_requirement")
    col1, col2 = st.columns(2)
    ct_tolerance_absorbed = col1.text_input("tolerance_absorbed (mm, optional)", key="ct_tolerance_absorbed")
    ct_reuse_cycles = col2.text_input("reuse_cycles", value="0", key="ct_reuse_cycles")

    st.subheader("GHG (spec §2.4 — per connection instance, see Legend)")
    col1, col2 = st.columns(2)
    ct_ghg_a1a3 = col1.text_input("ghg_A1A3", key="ct_ghg_a1a3")
    ct_ghg_a5 = col2.text_input("ghg_A5", key="ct_ghg_a5")
    col1, col2 = st.columns(2)
    ct_ghg_source = col1.text_input("ghg_data.source", key="ct_ghg_source")
    ct_ghg_data_type = col2.selectbox("ghg_data.data_type", _DATA_TYPES, key="ct_ghg_data_type")
    col1, col2, col3 = st.columns(3)
    ct_ghg_vintage = col1.text_input("ghg_data.vintage (year)", key="ct_ghg_vintage")
    ct_ghg_geography = col2.text_input("ghg_data.geography", key="ct_ghg_geography")
    ct_ghg_uncertainty = col3.text_input("ghg_data.uncertainty (e.g. ±25%)", key="ct_ghg_uncertainty")
    ct_ghg_basis_note = st.text_input("ghg_data.basis_note", key="ct_ghg_basis_note")

    st.subheader("Cost (spec §2.4)")
    col1, col2 = st.columns(2)
    ct_cost_install = col1.text_input("cost_install", key="ct_cost_install")
    ct_cost_removal = col2.text_input("cost_removal", key="ct_cost_removal")
    col1, col2 = st.columns(2)
    ct_cost_source = col1.text_input("cost_data.source", key="ct_cost_source")
    ct_cost_data_type = col2.selectbox("cost_data.data_type", _DATA_TYPES, key="ct_cost_data_type")
    col1, col2, col3 = st.columns(3)
    ct_cost_vintage = col1.text_input("cost_data.vintage (year)", key="ct_cost_vintage")
    ct_cost_geography = col2.text_input("cost_data.geography", key="ct_cost_geography")
    ct_cost_uncertainty = col3.text_input("cost_data.uncertainty (e.g. ±25%)", key="ct_cost_uncertainty")
    ct_cost_basis_note = st.text_input("cost_data.basis_note", key="ct_cost_basis_note")

    if st.button("Save connection type", key="save_connection_type", type="primary"):
        try:
            ghg_data = DataQuality(
                source=ct_ghg_source,
                data_type=ct_ghg_data_type,
                vintage=int(ct_ghg_vintage),
                geography=ct_ghg_geography,
                uncertainty=ct_ghg_uncertainty,
                basis_note=ct_ghg_basis_note,
            )
            cost_data = DataQuality(
                source=ct_cost_source,
                data_type=ct_cost_data_type,
                vintage=int(ct_cost_vintage),
                geography=ct_cost_geography,
                uncertainty=ct_cost_uncertainty,
                basis_note=ct_cost_basis_note,
            )
            connection_type = ConnectionType(
                id=ct_id.strip(),
                name=ct_name.strip(),
                removal_method=ct_removal_method.strip(),
                damage_to_self=ct_damage_to_self,
                damage_to_host=ct_damage_to_host,
                re_installable=bool(ct_re_installable),
                access_requirement=ct_access_requirement,
                tolerance_absorbed=_optional_float(ct_tolerance_absorbed),
                reuse_cycles=int(ct_reuse_cycles),
                ghg_A1A3=float(ct_ghg_a1a3),
                ghg_A5=float(ct_ghg_a5),
                ghg_data=ghg_data,
                cost_install=float(ct_cost_install),
                cost_removal=float(ct_cost_removal),
                cost_data=cost_data,
            )
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            st.error(f"Invalid connection type: {exc}")
        else:
            path = Path(data_dir_input) / "connection_types.yaml"
            try:
                append_connection_type(path, connection_type)
            except LibraryError as exc:
                st.error(f"Could not save: {exc}")
            else:
                st.success(
                    f"Added {connection_type.id!r} to {path}. It won't appear in an assessment until a "
                    f"ConnectionInstance references connection_type_id: {connection_type.id} — add one, then Run assessment."
                )
