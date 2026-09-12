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

from cdfma.cli import ProjectResult, evaluate_project
from cdfma.report import render_comparison, render_findings, render_gap_report


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


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
