# Open questions

Per CLAUDE.md §9: the spec is not silently filled in with invented domain
content. Each entry below is a place the base library (`schema.py`,
`library.py`, `data/*.yaml`) hit a gap; it's recorded here rather than
guessed at.

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

## 4. `DataQuality.uncertainty` format

Spec §2.7 types this field as "± % or range" without a machine format.
`schema.DataQuality.uncertainty` is currently a required free-text string.
Interval arithmetic that consumes it (turning a declared figure plus its
uncertainty band into an `Interval`) belongs to `normalise.py` (spec §5.4),
which doesn't exist yet.

**Needed to close this**: agree the exact format (e.g. always a symmetric
percentage, vs. sometimes an explicit `[low, high]` range) before
`normalise.py` is written, so it has one shape to parse rather than two.

## 5. Open-vocabulary fields

`ConnectionType.removal_method`, `ConnectionType.access_requirement` and
`ElementType.recovery_preconditions` are free strings / a string list, not
closed enums — the spec gives examples (`destructive`, `unbolt`,
`edges_undamaged`, `fixings_removable`) but never an exhaustive value set.
Left open rather than guessing at the full domain. **Needed to close
this**: a decision on whether these should become closed enums once more
real data is authored, to keep values consistent across records.
