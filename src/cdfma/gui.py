"""A tenth module, justified: a small Tkinter desktop GUI, so the MVP can
be exercised meaningfully without reading CLI text output. Tkinter is
Python's standard library, so this adds no dependency beyond CLAUDE.md
§8's pydantic/PyYAML/pytest, and no web framework, database or ORM is
introduced.

Thin wrapper only: it holds no domain content and no evaluation logic of
its own. Every button here calls straight into ``cli.evaluate_project``
(the same function ``python -m cdfma.cli`` uses) and renders the results
with ``report.py``'s existing renderers — this file only arranges widgets
and text.
"""

from __future__ import annotations

import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pydantic import ValidationError

from cdfma.cli import ProjectResult, evaluate_project
from cdfma.graph import GraphError
from cdfma.graph import Graph as ProjectGraph
from cdfma.graph import append_option
from cdfma.library import Library, LibraryError, append_connection_type, append_element_type
from cdfma.report import LEGEND, render_comparison, render_findings, render_gap_report
from cdfma.schema import (
    CompositionEntry,
    ConnectionInstance,
    ConnectionType,
    DataQuality,
    ElementCost,
    ElementType,
    EmbodiedGHG,
    Envelope,
    Instance,
)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Circular DfMA — Slice 1")
        self.geometry("980x680")

        self.data_dir_var = tk.StringVar(value="data")
        self.project_var = tk.StringVar(value="data/project_wall.yaml")
        self.option_var = tk.StringVar()
        self._result: ProjectResult | None = None

        self._build_top_bar()
        self._build_notebook()

    def _build_top_bar(self) -> None:
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")

        ttk.Label(bar, text="Data dir:").grid(row=0, column=0, sticky="w")
        ttk.Entry(bar, textvariable=self.data_dir_var, width=40).grid(row=0, column=1, padx=4)
        ttk.Button(bar, text="Browse…", command=self._browse_data_dir).grid(row=0, column=2)

        ttk.Label(bar, text="Project file:").grid(row=1, column=0, sticky="w")
        ttk.Entry(bar, textvariable=self.project_var, width=40).grid(row=1, column=1, padx=4)
        ttk.Button(bar, text="Browse…", command=self._browse_project).grid(row=1, column=2)

        ttk.Button(bar, text="Run assessment", command=self._run).grid(row=0, column=3, rowspan=2, padx=12)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self.status_var, foreground="#555").grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        legend_tab = ttk.Frame(self.notebook)
        self.notebook.add(legend_tab, text="Legend")
        legend_text = self._make_text(legend_tab)
        self._set_text(legend_text, LEGEND)

        findings_tab = ttk.Frame(self.notebook)
        self.notebook.add(findings_tab, text="Findings")
        option_bar = ttk.Frame(findings_tab, padding=(4, 4))
        option_bar.pack(fill="x")
        ttk.Label(option_bar, text="Option:").pack(side="left")
        self.option_menu = ttk.Combobox(option_bar, textvariable=self.option_var, state="readonly", width=30)
        self.option_menu.pack(side="left", padx=6)
        self.option_menu.bind("<<ComboboxSelected>>", lambda _e: self._render_findings())
        self.findings_text = self._make_text(findings_tab)

        comparison_tab = ttk.Frame(self.notebook)
        self.notebook.add(comparison_tab, text="Option comparison")
        self.comparison_text = self._make_text(comparison_tab)

        gap_tab = ttk.Frame(self.notebook)
        self.notebook.add(gap_tab, text="Gap report")
        self.gap_text = self._make_text(gap_tab)

        add_tab = ttk.Frame(self.notebook)
        self.notebook.add(add_tab, text="Add material")
        self._build_add_element_type_tab(add_tab)

        add_connection_tab = ttk.Frame(self.notebook)
        self.notebook.add(add_connection_tab, text="Add connection")
        self._build_add_connection_type_tab(add_connection_tab)

        build_wall_tab = ttk.Frame(self.notebook)
        self.notebook.add(build_wall_tab, text="Build wall")
        self._build_wall_tab(build_wall_tab)

    def _make_text(self, parent: ttk.Frame) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=4, pady=4)
        text = tk.Text(frame, wrap="word", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text.configure(state="disabled")
        return text

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _browse_data_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.data_dir_var.get() or ".")
        if chosen:
            self.data_dir_var.set(chosen)

    def _browse_project(self) -> None:
        chosen = filedialog.askopenfilename(
            initialdir=str(Path(self.project_var.get()).parent), filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if chosen:
            self.project_var.set(chosen)

    def _run(self) -> None:
        try:
            self._result = evaluate_project(Path(self.data_dir_var.get()), Path(self.project_var.get()))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            messagebox.showerror("Assessment failed", f"{exc}\n\n{traceback.format_exc()}")
            self.status_var.set(f"Failed: {exc}")
            return

        option_ids = sorted(self._result.evaluations)
        self.option_menu["values"] = option_ids
        if option_ids:
            self.option_var.set(option_ids[0])
        self._render_findings()
        self._render_gap_report()
        self._render_comparison()
        self.status_var.set(f"Ran {len(option_ids)} option(s) from {self.project_var.get()!r}.")

    def _render_findings(self) -> None:
        if self._result is None or not self.option_var.get():
            return
        evaluation = self._result.evaluations[self.option_var.get()]
        self._set_text(self.findings_text, render_findings(evaluation))

    def _render_gap_report(self) -> None:
        if self._result is None:
            return
        self._set_text(self.gap_text, render_gap_report(list(self._result.evaluations.values())))

    def _render_comparison(self) -> None:
        if self._result is None:
            return
        if self._result.priority_error:
            content = f"(no priority declarations: {self._result.priority_error})"
        else:
            content = render_comparison(
                self._result.evaluations, self._result.ranking, self._result.stability, self._result.break_evens
            )
            if self._result.constraint_result and self._result.constraint_result.excluded:
                content += "\n\nExcluded by constraint:\n"
                for option_id, reasons in sorted(self._result.constraint_result.excluded.items()):
                    content += f"  {option_id}: {'; '.join(reasons)}\n"
            if self._result.target_report:
                content += "\nTargets:\n"
                for option_id in sorted(self._result.target_report):
                    for indicator_id, met in sorted(self._result.target_report[option_id].items()):
                        content += f"  {option_id} {indicator_id}: {'met' if met else 'NOT MET'}\n"
        self._set_text(self.comparison_text, content)

    # --- "Add material" tab: manual entry of a new element type ---------
    #
    # A form only: every value it collects passes straight into
    # schema.ElementType, which is what actually validates it (composition
    # summing to 1.0, id format, required DataQuality, …). This method
    # holds no rule about what makes a valid element type — schema.py
    # already does, and duplicating that here would be exactly the kind
    # of domain content CLAUDE.md keeps out of a thin wrapper.

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

    def _make_scrollable_form(self, parent: ttk.Frame) -> ttk.Frame:
        """A vertically-scrolling form area — shared by every "Add ..."
        tab, since each has more fields than fit in the window at once.
        """
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas, padding=10)
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind(
            "<Enter>",
            lambda _e: canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")),
        )
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return form

    @staticmethod
    def _form_section(form: ttk.Frame, title: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(form, text=title, padding=8)
        frame.pack(fill="x", pady=(0, 10))
        return frame

    @staticmethod
    def _form_row(
        frame: ttk.Frame, store: dict[str, tk.Variable], label: str, key: str, kind: str = "entry", values=None, default=""
    ) -> None:
        r = frame.grid_size()[1]
        ttk.Label(frame, text=label, width=26, anchor="w").grid(row=r, column=0, sticky="w", pady=2)
        if kind == "combo":
            var = tk.StringVar(value=default or values[0])
            ttk.Combobox(frame, textvariable=var, values=values, state="readonly", width=28).grid(
                row=r, column=1, sticky="w"
            )
        elif kind == "check":
            var = tk.BooleanVar(value=bool(default))
            ttk.Checkbutton(frame, variable=var).grid(row=r, column=1, sticky="w")
        else:
            var = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=var, width=30).grid(row=r, column=1, sticky="w")
        store[key] = var

    def _build_add_element_type_tab(self, parent: ttk.Frame) -> None:
        form = self._make_scrollable_form(parent)
        v: dict[str, tk.Variable] = {}
        self._et_vars = v
        section, row = self._form_section, lambda *a, **k: self._form_row(*a, **k)

        identity = section(form, "Identity & lifecycle")
        row(identity, v, "id (snake_case)", "id")
        row(identity, v, "name", "name")
        row(identity, v, "layer", "layer", "combo", self._LAYERS)
        row(identity, v, "tier", "tier", "combo", self._TIERS)
        row(identity, v, "service_life (years)", "service_life")
        row(identity, v, "service_life_basis", "service_life_basis", "combo", self._SERVICE_LIFE_BASES)
        row(identity, v, "decomposable", "decomposable", "check")
        row(identity, v, "declared_recovery_pathway", "declared_recovery_pathway", "combo", self._RECOVERY_PATHWAYS)
        row(identity, v, "recovery_preconditions (comma-sep)", "recovery_preconditions")
        row(identity, v, "provenance", "provenance", "combo", self._PROVENANCES)

        composition_section = section(form, "Composition (materials must sum to 1.0)")
        self._composition_rows_frame = ttk.Frame(composition_section)
        self._composition_rows_frame.pack(fill="x")
        self._composition_rows: list[dict] = []
        self._add_composition_row()
        ttk.Button(composition_section, text="+ Add material row", command=self._add_composition_row).pack(
            anchor="w", pady=(4, 0)
        )

        geometry = section(form, "Geometry (G0/G1)")
        row(geometry, v, "shape_class", "shape_class", "combo", self._SHAPE_CLASSES)
        row(geometry, v, "envelope length (mm)", "envelope_length")
        row(geometry, v, "envelope width (mm)", "envelope_width")
        row(geometry, v, "envelope thickness (mm)", "envelope_thickness")
        row(geometry, v, "envelope_fill_ratio (0-1)", "envelope_fill_ratio", default="1.0")
        row(geometry, v, "mass (kg)", "mass")
        row(geometry, v, "coordination_module (mm, optional)", "coordination_module")
        row(geometry, v, "orientation_constraint", "orientation_constraint", "combo", self._ORIENTATIONS)
        row(geometry, v, "stackable", "stackable", "check")
        row(geometry, v, "nestable", "nestable", "combo", list(self._NESTABLE_CHOICES), default="Unspecified")
        row(geometry, v, "geometry_provenance", "geometry_provenance", "combo", self._GEOMETRY_PROVENANCES)
        row(geometry, v, "g_level", "g_level", "combo", self._G_LEVELS)

        ghg = section(form, "Embodied GHG (spec §2.1 — one record per module)")
        row(ghg, v, "declared_unit", "declared_unit", "combo", self._DECLARED_UNITS)
        row(ghg, v, "ghg_A1A3", "ghg_A1A3")
        row(ghg, v, "ghg_A4 (optional)", "ghg_A4")
        row(ghg, v, "ghg_A5 (optional)", "ghg_A5")
        row(ghg, v, "ghg_C", "ghg_C")
        row(ghg, v, "ghg_D (reported separately)", "ghg_D", default="0")
        row(ghg, v, "biogenic_carbon (optional)", "biogenic_carbon")
        row(ghg, v, "ghg_data.source", "ghg_source")
        row(ghg, v, "ghg_data.data_type", "ghg_data_type", "combo", self._DATA_TYPES)
        row(ghg, v, "ghg_data.vintage (year)", "ghg_vintage")
        row(ghg, v, "ghg_data.geography", "ghg_geography")
        row(ghg, v, "ghg_data.uncertainty (e.g. ±25%)", "ghg_uncertainty")
        row(ghg, v, "ghg_data.basis_note", "ghg_basis_note")

        cost = section(form, "Cost (spec §2.1)")
        row(cost, v, "currency", "currency", default="AUD")
        row(cost, v, "price_date", "price_date")
        row(cost, v, "cost_supply", "cost_supply")
        row(cost, v, "cost_install", "cost_install")
        row(cost, v, "cost_removal", "cost_removal")
        row(cost, v, "residual_value", "residual_value", default="0")
        row(cost, v, "cost_data.source", "cost_source")
        row(cost, v, "cost_data.data_type", "cost_data_type", "combo", self._DATA_TYPES)
        row(cost, v, "cost_data.vintage (year)", "cost_vintage")
        row(cost, v, "cost_data.geography", "cost_geography")
        row(cost, v, "cost_data.uncertainty (e.g. ±25%)", "cost_uncertainty")
        row(cost, v, "cost_data.basis_note", "cost_basis_note")

        button_bar = ttk.Frame(form)
        button_bar.pack(fill="x", pady=(4, 0))
        ttk.Button(button_bar, text="Save element type", command=self._save_element_type).pack(side="left")
        self.add_status_var = tk.StringVar(value="")
        ttk.Label(button_bar, textvariable=self.add_status_var, foreground="#555").pack(side="left", padx=10)

    def _add_composition_row(self) -> None:
        record: dict = {}
        r = len(self._composition_rows)
        frame = ttk.Frame(self._composition_rows_frame)
        frame.grid(row=r, column=0, sticky="w", pady=2)
        material_var = tk.StringVar()
        fraction_var = tk.StringVar()
        ttk.Entry(frame, textvariable=material_var, width=20).grid(row=0, column=0, padx=(0, 4))
        ttk.Label(frame, text="mass_fraction:").grid(row=0, column=1, padx=(0, 4))
        ttk.Entry(frame, textvariable=fraction_var, width=8).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(frame, text="Remove", command=lambda: self._remove_composition_row(record)).grid(row=0, column=3)
        record.update(frame=frame, material_var=material_var, fraction_var=fraction_var)
        self._composition_rows.append(record)

    def _remove_composition_row(self, record: dict) -> None:
        if len(self._composition_rows) <= 1:
            return
        record["frame"].destroy()
        self._composition_rows.remove(record)
        for index, remaining in enumerate(self._composition_rows):
            remaining["frame"].grid(row=index, column=0, sticky="w", pady=2)

    def _save_element_type(self) -> None:
        v = self._et_vars

        def text(key: str) -> str:
            return v[key].get().strip()

        def optional_float(key: str) -> float | None:
            raw = text(key)
            return float(raw) if raw else None

        try:
            composition = []
            for record in self._composition_rows:
                material = record["material_var"].get().strip()
                fraction = record["fraction_var"].get().strip()
                if not material and not fraction:
                    continue
                composition.append(CompositionEntry(material=material, mass_fraction=float(fraction)))
            if not composition:
                raise ValueError("at least one composition material is required")

            envelope = Envelope(
                length=float(text("envelope_length")),
                width=float(text("envelope_width")),
                thickness=float(text("envelope_thickness")),
            )
            ghg_data = DataQuality(
                source=text("ghg_source"),
                data_type=v["ghg_data_type"].get(),
                vintage=int(text("ghg_vintage")),
                geography=text("ghg_geography"),
                uncertainty=text("ghg_uncertainty"),
                basis_note=text("ghg_basis_note"),
            )
            embodied_ghg = EmbodiedGHG(
                declared_unit=v["declared_unit"].get(),
                ghg_A1A3=float(text("ghg_A1A3")),
                ghg_A4=optional_float("ghg_A4"),
                ghg_A5=optional_float("ghg_A5"),
                ghg_C=float(text("ghg_C")),
                ghg_D=float(text("ghg_D")),
                biogenic_carbon=optional_float("biogenic_carbon"),
                ghg_data=ghg_data,
            )
            cost_data = DataQuality(
                source=text("cost_source"),
                data_type=v["cost_data_type"].get(),
                vintage=int(text("cost_vintage")),
                geography=text("cost_geography"),
                uncertainty=text("cost_uncertainty"),
                basis_note=text("cost_basis_note"),
            )
            cost = ElementCost(
                currency=text("currency"),
                price_date=text("price_date"),
                cost_supply=float(text("cost_supply")),
                cost_install=float(text("cost_install")),
                cost_removal=float(text("cost_removal")),
                residual_value=float(text("residual_value")),
                cost_data=cost_data,
            )
            recovery_preconditions = [s.strip() for s in text("recovery_preconditions").split(",") if s.strip()]

            element_type = ElementType(
                id=text("id"),
                name=text("name"),
                layer=v["layer"].get(),
                tier=v["tier"].get(),
                service_life=int(text("service_life")),
                service_life_basis=v["service_life_basis"].get(),
                composition=composition,
                decomposable=bool(v["decomposable"].get()),
                declared_recovery_pathway=v["declared_recovery_pathway"].get(),
                recovery_preconditions=recovery_preconditions,
                provenance=v["provenance"].get(),
                shape_class=v["shape_class"].get(),
                envelope=envelope,
                envelope_fill_ratio=float(text("envelope_fill_ratio")),
                mass=float(text("mass")),
                coordination_module=optional_float("coordination_module"),
                orientation_constraint=v["orientation_constraint"].get(),
                stackable=bool(v["stackable"].get()),
                nestable=self._NESTABLE_CHOICES[v["nestable"].get()],
                geometry_provenance=v["geometry_provenance"].get(),
                g_level=v["g_level"].get(),
                embodied_ghg=embodied_ghg,
                cost=cost,
            )
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Invalid element type", str(exc))
            return

        path = Path(self.data_dir_var.get()) / "element_types.yaml"
        try:
            append_element_type(path, element_type)
        except LibraryError as exc:
            messagebox.showerror("Could not save", str(exc))
            return

        messagebox.showinfo(
            "Saved",
            f"Added {element_type.id!r} to {path}.\n\n"
            "It won't appear in an assessment until an Instance in your "
            f"project file references element_type_id: {element_type.id} "
            "— add one, then click Run assessment.",
        )
        self.add_status_var.set(f"Saved {element_type.id!r} to {path}.")

    # --- "Add connection" tab: manual entry of a new connection type ----
    #
    # Same shape as "Add material" above: a form collecting values that
    # pass straight into schema.ConnectionType, which does the actual
    # validation (id format, the required DataQuality records, …).

    def _build_add_connection_type_tab(self, parent: ttk.Frame) -> None:
        form = self._make_scrollable_form(parent)
        v: dict[str, tk.Variable] = {}
        self._ct_vars = v
        section, row = self._form_section, lambda *a, **k: self._form_row(*a, **k)

        identity = section(form, "Identity")
        row(identity, v, "id (snake_case)", "id")
        row(identity, v, "name", "name")
        row(identity, v, "removal_method", "removal_method")
        row(identity, v, "damage_to_self", "damage_to_self", "combo", self._DAMAGE_LEVELS)
        row(identity, v, "damage_to_host", "damage_to_host", "combo", self._DAMAGE_LEVELS)
        row(identity, v, "re_installable", "re_installable", "check")
        row(identity, v, "access_requirement (optional)", "access_requirement")
        row(identity, v, "tolerance_absorbed (mm, optional)", "tolerance_absorbed")
        row(identity, v, "reuse_cycles", "reuse_cycles", default="0")

        ghg = section(form, "GHG (spec §2.4 — per connection instance, see Legend)")
        row(ghg, v, "ghg_A1A3", "ghg_A1A3")
        row(ghg, v, "ghg_A5", "ghg_A5")
        row(ghg, v, "ghg_data.source", "ghg_source")
        row(ghg, v, "ghg_data.data_type", "ghg_data_type", "combo", self._DATA_TYPES)
        row(ghg, v, "ghg_data.vintage (year)", "ghg_vintage")
        row(ghg, v, "ghg_data.geography", "ghg_geography")
        row(ghg, v, "ghg_data.uncertainty (e.g. ±25%)", "ghg_uncertainty")
        row(ghg, v, "ghg_data.basis_note", "ghg_basis_note")

        cost = section(form, "Cost (spec §2.4)")
        row(cost, v, "cost_install", "cost_install")
        row(cost, v, "cost_removal", "cost_removal")
        row(cost, v, "cost_data.source", "cost_source")
        row(cost, v, "cost_data.data_type", "cost_data_type", "combo", self._DATA_TYPES)
        row(cost, v, "cost_data.vintage (year)", "cost_vintage")
        row(cost, v, "cost_data.geography", "cost_geography")
        row(cost, v, "cost_data.uncertainty (e.g. ±25%)", "cost_uncertainty")
        row(cost, v, "cost_data.basis_note", "cost_basis_note")

        button_bar = ttk.Frame(form)
        button_bar.pack(fill="x", pady=(4, 0))
        ttk.Button(button_bar, text="Save connection type", command=self._save_connection_type).pack(side="left")
        self.add_connection_status_var = tk.StringVar(value="")
        ttk.Label(button_bar, textvariable=self.add_connection_status_var, foreground="#555").pack(side="left", padx=10)

    def _save_connection_type(self) -> None:
        v = self._ct_vars

        def text(key: str) -> str:
            return v[key].get().strip()

        def optional_float(key: str) -> float | None:
            raw = text(key)
            return float(raw) if raw else None

        try:
            ghg_data = DataQuality(
                source=text("ghg_source"),
                data_type=v["ghg_data_type"].get(),
                vintage=int(text("ghg_vintage")),
                geography=text("ghg_geography"),
                uncertainty=text("ghg_uncertainty"),
                basis_note=text("ghg_basis_note"),
            )
            cost_data = DataQuality(
                source=text("cost_source"),
                data_type=v["cost_data_type"].get(),
                vintage=int(text("cost_vintage")),
                geography=text("cost_geography"),
                uncertainty=text("cost_uncertainty"),
                basis_note=text("cost_basis_note"),
            )
            connection_type = ConnectionType(
                id=text("id"),
                name=text("name"),
                removal_method=text("removal_method"),
                damage_to_self=v["damage_to_self"].get(),
                damage_to_host=v["damage_to_host"].get(),
                re_installable=bool(v["re_installable"].get()),
                access_requirement=text("access_requirement"),
                tolerance_absorbed=optional_float("tolerance_absorbed"),
                reuse_cycles=int(text("reuse_cycles")),
                ghg_A1A3=float(text("ghg_A1A3")),
                ghg_A5=float(text("ghg_A5")),
                ghg_data=ghg_data,
                cost_install=float(text("cost_install")),
                cost_removal=float(text("cost_removal")),
                cost_data=cost_data,
            )
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Invalid connection type", str(exc))
            return

        path = Path(self.data_dir_var.get()) / "connection_types.yaml"
        try:
            append_connection_type(path, connection_type)
        except LibraryError as exc:
            messagebox.showerror("Could not save", str(exc))
            return

        messagebox.showinfo(
            "Saved",
            f"Added {connection_type.id!r} to {path}.\n\n"
            "It won't appear in an assessment until a ConnectionInstance "
            f"in your project file references connection_type_id: "
            f"{connection_type.id} — add one, then click Run assessment.",
        )
        self.add_connection_status_var.set(f"Saved {connection_type.id!r} to {path}.")

    # --- "Build wall" tab: manual entry of a new option (project graph) -
    #
    # A form only, same invariant as the two tabs above: it collects
    # instance and connection rows, constructs real schema.Instance /
    # ConnectionInstance / graph.Graph objects (which do the actual
    # validation — id format, no dangling references, no self-referential
    # connection), and hands the result to graph.append_option.

    def _build_wall_tab(self, parent: ttk.Frame) -> None:
        form = self._make_scrollable_form(parent)

        target_frame = self._form_section(form, "Target")
        wv: dict[str, tk.Variable] = {}
        self._form_row(target_frame, wv, "project file", "wall_target", default=self.project_var.get())
        self._form_row(target_frame, wv, "new option id (snake_case)", "wall_option_id")
        self._wall_vars = wv

        library_bar = ttk.Frame(form)
        library_bar.pack(fill="x", pady=(0, 10))
        ttk.Button(library_bar, text="Reload element/connection type ids", command=self._reload_wall_library_ids).pack(
            side="left"
        )
        self.wall_library_status_var = tk.StringVar(value="")
        ttk.Label(library_bar, textvariable=self.wall_library_status_var, foreground="#555").pack(
            side="left", padx=10
        )

        instances_section = self._form_section(form, "Instances (each is one occurrence of an element type)")
        self._wall_instances_frame = ttk.Frame(instances_section)
        self._wall_instances_frame.pack(fill="x")
        self._wall_instance_rows: list[dict] = []
        header = ttk.Frame(instances_section)
        header.pack(fill="x")
        for text, width in (("instance id", 16), ("element_type_id", 30), ("label (optional)", 20)):
            ttk.Label(header, text=text, width=width, anchor="w").pack(side="left", padx=(0, 4))
        self._add_wall_instance_row()
        ttk.Button(instances_section, text="+ Add instance row", command=self._add_wall_instance_row).pack(
            anchor="w", pady=(4, 0)
        )

        connections_section = self._form_section(
            form, "Connections (element_instance_id / host_instance_id must match instance ids above)"
        )
        self._wall_connections_frame = ttk.Frame(connections_section)
        self._wall_connections_frame.pack(fill="x")
        self._wall_connection_rows: list[dict] = []
        header = ttk.Frame(connections_section)
        header.pack(fill="x")
        for text, width in (
            ("connection id", 14),
            ("connection_type_id", 24),
            ("element_instance_id", 16),
            ("host_instance_id", 16),
        ):
            ttk.Label(header, text=text, width=width, anchor="w").pack(side="left", padx=(0, 4))
        ttk.Button(
            connections_section, text="+ Add connection row", command=self._add_wall_connection_row
        ).pack(anchor="w", pady=(4, 0))

        button_bar = ttk.Frame(form)
        button_bar.pack(fill="x", pady=(4, 0))
        ttk.Button(button_bar, text="Save wall", command=self._save_wall).pack(side="left")
        self.wall_status_var = tk.StringVar(value="")
        ttk.Label(button_bar, textvariable=self.wall_status_var, foreground="#555").pack(side="left", padx=10)

        self._wall_element_type_ids: list[str] = []
        self._wall_connection_type_ids: list[str] = []
        self._reload_wall_library_ids()

    def _reload_wall_library_ids(self) -> None:
        try:
            library = Library.load(Path(self.data_dir_var.get()))
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            self.wall_library_status_var.set(f"Could not load library: {exc}")
            return
        self._wall_element_type_ids = sorted(library.element_types)
        self._wall_connection_type_ids = sorted(library.connection_types)
        for row in self._wall_instance_rows:
            row["element_type_combo"].configure(values=self._wall_element_type_ids)
        for row in self._wall_connection_rows:
            row["connection_type_combo"].configure(values=self._wall_connection_type_ids)
        self.wall_library_status_var.set(
            f"{len(self._wall_element_type_ids)} element type(s), {len(self._wall_connection_type_ids)} connection type(s) loaded."
        )

    def _add_wall_instance_row(self) -> None:
        record: dict = {}
        frame = ttk.Frame(self._wall_instances_frame)
        frame.pack(fill="x", pady=2)
        id_var = tk.StringVar()
        element_type_var = tk.StringVar()
        label_var = tk.StringVar()
        ttk.Entry(frame, textvariable=id_var, width=16).pack(side="left", padx=(0, 4))
        combo = ttk.Combobox(frame, textvariable=element_type_var, values=getattr(self, "_wall_element_type_ids", []), width=28)
        combo.pack(side="left", padx=(0, 4))
        ttk.Entry(frame, textvariable=label_var, width=20).pack(side="left", padx=(0, 4))
        ttk.Button(frame, text="Remove", command=lambda: self._remove_wall_instance_row(record)).pack(side="left")
        record.update(frame=frame, id_var=id_var, element_type_var=element_type_var, label_var=label_var, element_type_combo=combo)
        self._wall_instance_rows.append(record)

    def _remove_wall_instance_row(self, record: dict) -> None:
        if len(self._wall_instance_rows) <= 1:
            return
        record["frame"].destroy()
        self._wall_instance_rows.remove(record)

    def _add_wall_connection_row(self) -> None:
        record: dict = {}
        frame = ttk.Frame(self._wall_connections_frame)
        frame.pack(fill="x", pady=2)
        id_var = tk.StringVar()
        connection_type_var = tk.StringVar()
        element_instance_var = tk.StringVar()
        host_instance_var = tk.StringVar()
        ttk.Entry(frame, textvariable=id_var, width=14).pack(side="left", padx=(0, 4))
        combo = ttk.Combobox(
            frame, textvariable=connection_type_var, values=getattr(self, "_wall_connection_type_ids", []), width=22
        )
        combo.pack(side="left", padx=(0, 4))
        ttk.Entry(frame, textvariable=element_instance_var, width=16).pack(side="left", padx=(0, 4))
        ttk.Entry(frame, textvariable=host_instance_var, width=16).pack(side="left", padx=(0, 4))
        ttk.Button(frame, text="Remove", command=lambda: self._remove_wall_connection_row(record)).pack(side="left")
        record.update(
            frame=frame,
            id_var=id_var,
            connection_type_var=connection_type_var,
            element_instance_var=element_instance_var,
            host_instance_var=host_instance_var,
            connection_type_combo=combo,
        )
        self._wall_connection_rows.append(record)

    def _remove_wall_connection_row(self, record: dict) -> None:
        record["frame"].destroy()
        self._wall_connection_rows.remove(record)

    def _save_wall(self) -> None:
        wv = self._wall_vars
        target_path = Path(wv["wall_target"].get().strip())
        option_id = wv["wall_option_id"].get().strip()

        try:
            if not option_id:
                raise ValueError("a new option id is required")

            instances: dict[str, Instance] = {}
            for row in self._wall_instance_rows:
                instance_id = row["id_var"].get().strip()
                element_type_id = row["element_type_var"].get().strip()
                if not instance_id and not element_type_id:
                    continue
                instance = Instance(id=instance_id, element_type_id=element_type_id, label=row["label_var"].get())
                if instance.id in instances:
                    raise ValueError(f"duplicate instance id {instance.id!r}")
                instances[instance.id] = instance
            if not instances:
                raise ValueError("at least one instance is required")

            connection_instances: dict[str, ConnectionInstance] = {}
            for row in self._wall_connection_rows:
                connection_id = row["id_var"].get().strip()
                connection_type_id = row["connection_type_var"].get().strip()
                if not connection_id and not connection_type_id:
                    continue
                connection = ConnectionInstance(
                    id=connection_id,
                    connection_type_id=connection_type_id,
                    element_instance_id=row["element_instance_var"].get().strip(),
                    host_instance_id=row["host_instance_var"].get().strip(),
                )
                if connection.id in connection_instances:
                    raise ValueError(f"duplicate connection instance id {connection.id!r}")
                connection_instances[connection.id] = connection

            graph = ProjectGraph(
                instances=instances,
                connection_instances=connection_instances,
                composition_edges=[],
                dependency_edges=[],
            )
            library = Library.load(Path(self.data_dir_var.get()))
            graph.validate_against_library(library)
        except (ValidationError, ValueError, TypeError, GraphError, LibraryError) as exc:
            messagebox.showerror("Invalid wall", str(exc))
            return

        try:
            append_option(target_path, option_id, graph)
        except GraphError as exc:
            messagebox.showerror("Could not save", str(exc))
            return

        messagebox.showinfo(
            "Saved",
            f"Added option {option_id!r} ({len(instances)} instance(s), {len(connection_instances)} "
            f"connection(s)) to {target_path}.\n\nSet Project file to this path and click Run assessment to see it.",
        )
        self.wall_status_var.set(f"Saved {option_id!r} to {target_path}.")


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
