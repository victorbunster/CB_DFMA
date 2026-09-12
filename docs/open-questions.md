# Open questions

Per CLAUDE.md §9: the spec is not silently filled in with invented domain
content. Each entry below is a place the codebase hit a gap; it's
recorded here rather than guessed at.

**Update:** the user has since explicitly chosen (see the conversation
where the MVP engine was built) to fill gaps #1 and #3 below with
clearly-labeled PLACEHOLDER values, so the engine has a full library and
graph to run end to end, rather than leaving them as gaps in the shipped
data. The values themselves are still not real — replace them before
treating any output that depends on them as real. #6, #7 and #8 are new
entries from that same build.

## 1. Connection type DataQuality is unspecified

`docs/mvp-scope.md` §2.4 lists `ghg_A1A3`, `ghg_A5`, `cost_install`,
`cost_removal` on `ConnectionType`, but its field table has no `ghg_data` /
`cost_data` entry, and the worked-example appendix gives `adhesive_bond`
and `mechanical_bracket` figures (e.g. `ghg_A1A3: 1.8`, `cost_install: 18`)
with no source citation behind them.

CLAUDE.md §5 (architecture invariant 7) is unqualified: "No bare numbers.
Every GHG and cost figure carries a `DataQuality` record... Loading a
figure without one is a validation error." `schema.ConnectionType` follows
that and requires `ghg_data`/`cost_data`.

**Needed to close this**: for `adhesive_bond` and `mechanical_bracket` (or
whatever real connection types replace them), a `source` citation,
`data_type`, `vintage`, `geography` and `uncertainty` band for the GHG
figures, and the same for the cost figures. Until supplied,
`data/connection_types.yaml` ships with an empty list — fabricating a
citation would defeat the purpose of the field.

## 2. `ElementType.nestable` not stated for the cladding panel fixture

The worked-example appendix gives `stackable: true` for
`cladding_panel_alu_mw_25` but never mentions `nestable`, even though
spec §2.1 lists both as required booleans ("storage and transport").

Rather than invent a value, `schema.ElementType.nestable` is `bool | None`
(default `None`), and `data/element_types.yaml` declares it `null` for
this record. **Needed to close this**: a real answer for whether the panel
nests with others of its kind, from whoever supplied the archetype.

## 3. `substrate_60` is not fully specified

The worked-example appendix gives `substrate_60` only `layer`,
`service_life`/`service_life_basis`, `shape_class`, `g_level`, and its
GHG/cost figures. Missing: `composition`, `mass`, `envelope`,
`envelope_fill_ratio`, `decomposable`, `declared_recovery_pathway`,
`recovery_preconditions`, `provenance`, `coordination_module`,
`orientation_constraint`, `stackable`/`nestable`, `geometry_provenance`.

**Needed to close this**: those facts about the actual substrate
product/archetype being modeled, so it can be added to
`data/element_types.yaml`. Reproducing `docs/worked-example.md` end to end
(acceptance test 1) needs both sides of the joint, so this blocks that
test.

## 4. `DataQuality.uncertainty` format — RESOLVED (with a caveat)

Spec §2.7 types this field as "± % or range" without a machine format.
`normalise.parse_uncertainty_fraction` now parses a symmetric `"±X%"`
string — the one format the worked example ever uses — and raises rather
than guessing at anything else. Every `uncertainty` value shipped in
`data/*.yaml` uses this format, so this is closed for Slice 1.

**Caveat**: the spec's "or range" alternative (an explicit, possibly
asymmetric `[low, high]` band) is not supported. If a real figure ever
needs an asymmetric band, `normalise.py` will need a second format.

## 5. Open-vocabulary fields

`ConnectionType.removal_method`, `ConnectionType.access_requirement` and
`ElementType.recovery_preconditions` are free strings / a string list, not
closed enums — the spec gives examples (`destructive`, `unbolt`,
`edges_undamaged`, `fixings_removable`) but never an exhaustive value set.
Left open rather than guessing at the full domain. **Needed to close
this**: a decision on whether these should become closed enums once more
real data is authored, to keep values consistent across records.

## 6. `DRV-04` handling-class thresholds are placeholders

The mass/dimension breakpoints for one-person / two-person / mechanical
handling in `data/rules.yaml`'s `DRV-04` logic (25kg/1200mm, 50kg/2400mm)
are not given anywhere in the spec or its worked example — there is no
real manual-handling guidance behind them. **Needed to close this**: real
thresholds (e.g. from AS 1418, HSE guidance, or whatever standard the
project wants to cite), and a `source` to put in the rule's citation.

## 7. `CON-003`'s cost margin is a placeholder

Spec §3.2 says recovery "is not worth doing" when `cost_removal` exceeds
`residual_value` "by more than a declared margin" — a number the spec
never gives. `data/rules.yaml`'s `CON-003.logic.cost_removal_margin: 10.0`
is a placeholder. **Needed to close this**: the real declared margin (a
currency amount, or possibly a percentage — the spec doesn't say which).

## 8. Modelling decisions made to build the engine (not domain content, but worth recording)

A few implementation choices had no single spec answer and were decided
rather than left undone, documented where they live in code:

- **Assembly reference area** for the "per m²" indicators (IND-05/06/07)
  is the summed face area of skin-layer instances
  (`engine.assembly_reference_area_m2`). Spec §5.4 defines per-m²
  resolution for one element's own figure, not an assembly-wide area for
  a multi-instance graph.
- **Connection GHG/cost figures are treated as flat per-connection
  totals**, never per-metre (`engine.py` module docstring) — the "or per
  metre" half of spec §2.4 needs an interface's extent, which doesn't
  exist without the interface layer (out of scope, §2).
- **Every instance contributes its own full lifecycle** (capital,
  replacements, final removal), summed across the graph
  (`engine.py` module docstring), rather than trying to reproduce
  `mvp-scope.md`'s illustrative appendix table figure-for-figure — that
  appendix is not the fixture/answer key CLAUDE.md §1 names (that's
  `docs/worked-example.md`, which carries no numeric table), and is
  marked "All figures illustrative".
- **Uncertainty propagation** for indistinguishability (CLAUDE.md
  invariant 8) treats each instance's total GHG/cost contribution as one
  banded figure using that element/connection type's own `DataQuality.
  uncertainty`, rather than a separate band per elementary figure.
- **The priority layer's declarations** (constraints/targets/profile)
  are not one of CLAUDE.md §4's five named data files. They're folded
  into a `priority:` section of `data/project_wall.yaml` — the one
  remaining per-project file — rather than hardcoded in `priority.py` or
  given a sixth data file outside that list.
