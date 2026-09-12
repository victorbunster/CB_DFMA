# Circular DfMA — Slice 1

A deterministic, rule-driven decision-support engine for circular Design
for Manufacture and Assembly. See [CLAUDE.md](CLAUDE.md) for the full
architecture and scope, and [docs/mvp-scope.md](docs/mvp-scope.md) for the
spec it implements (Slice 1 only — see CLAUDE.md §2).

**Data quality note**: several values in `data/*.yaml` and
`data/rules.yaml` are clearly-labeled `PLACEHOLDER`s, not real figures —
see [docs/open-questions.md](docs/open-questions.md) for exactly which,
and why.

## Setup

```
python -m pip install -e ".[dev]"
```

## Run

```
python -m cdfma.cli --project data/project_wall.yaml
```

or, once installed:

```
cdfma --project data/project_wall.yaml
```

Prints the three reports (findings, option comparison, gap report) for
both options declared in `data/project_wall.yaml`.

## GUI

```
python -m cdfma.gui
```

or `cdfma-gui`. A thin Tkinter desktop wrapper (see CLAUDE.md §4) around
the same `evaluate_project` function the CLI uses — pick a data directory
and a project file, click **Run assessment**, and browse the three
reports across tabs.

## Tests

```
python -m pytest
```

`tests/test_acceptance.py` implements the spec's numbered acceptance
tests in scope for Slice 1 (1, 2, 5, 6, 7 — see CLAUDE.md §7).
`tests/test_library.py` covers the library layer's loading and
validation directly.
