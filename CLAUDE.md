# CLAUDE.md — Circular DfMA MVP

Guidance for Claude Code working in this repository. Read this before writing any code.

---

## 1. What this is

A deterministic, rule-driven decision-support engine for circular Design for Manufacture and Assembly. It evaluates a declared assembly against a knowledge base of rules and returns findings, indicator values, comparisons and gaps.

**It is not an LCA tool and not a cost estimator.** It consumes figures produced elsewhere, carries their provenance, and reasons about how design decisions change them over time. It ships no factor database and calculates no emission factors of its own.

**Spec authority:** `docs/mvp-scope.md` (Revision 3). Where this file and the spec disagree, the spec wins — flag the conflict rather than resolving it silently. Revisions 1 and 2 are superseded and deliberately absent from this repository; do not reintroduce their field lists.

Supporting context: `docs/core-system-model.md` (the four-part separation), `docs/worked-example.md` (fixture and answer key), `docs/dfma-definition.md` (terminology).

---

## 2. Current slice

This is **Slice 1**. Build only what is listed as in scope.

**In scope**

- Library: element types, connection types, project parameters, data quality records — at G0/G1 geometric definition.
- Graph: element instances, composition edges, connection instances, **manually asserted** dependency edges.
- Normalisation: declared-unit resolution, assembly quantities, interval arithmetic (spec §5.4).
- Derivations: `DRV-01` reversibility, `DRV-04` handling class, `DRV-05` replacement count, `DRV-06` cascading replacement, `DRV-07` lifecycle GHG and cost.
- Criteria: `CON-001`, `CON-003`, `REC-001`, `SEP-001`, `DFM-001`.
- Indicators: `IND-01`, `IND-02`, `IND-05`, `IND-06`, `IND-07`, `IND-08`.
- Priority layer: constraints, dominance elimination, lexicographic ranking, rank-stability check.
- Reports: findings, option comparison, gap report.
- Acceptance tests 1, 2, 5, 6, 7.

**Out of scope — do not implement, do not stub beyond a raised `NotImplementedError`**

- Interface records, interface archetypes, interface signatures, position conventions (spec §2.2–§2.3).
- G2/G3 geometry, derived dependency edges, clearance and access reasoning.
- The compatibility test and substitution lookup (§5.2, §5.3), `DRV-03`, `CON-002`, `IND-03`, `IND-04`.
- Acceptance tests 3 and 4.
- Everything in spec §2.9 and §10.

If a task appears to require out-of-scope material, stop and say so rather than building a partial version of it. Slice 2 adds the geometric layer; a half-built interface model now will have to be discarded.

---

## 3. Architecture invariants

These are not preferences. Code that breaks one of them is wrong even if the tests pass.

1. **The engine holds no domain content.** No element name, threshold, citation or material appears in `engine.py`. Rule logic is registered; rule parameters come from data.
2. **Facts, judgements and preferences stay separate.** `library.py` and `graph.py` hold facts only — no derived values, no assessments. `rules.py` holds judgements. `priority.py` holds preferences. Dependencies run one way: `schema` → `library`/`graph` → `normalise` → `rules` → `engine` → `report`; `priority` depends on indicator results only.
3. **A missing input produces a gap entry, never a default and never a silent pass.** Check every rule's `requires[]` against the subject before evaluating. A rule that cannot run must say which field was absent.
4. **Module D is stored and reported separately and is never summed into any total.** No code path may add `ghg_D` to another module.
5. **No composite score, no weighted aggregate, no single number.** Ranking is lexicographic under a declared profile.
6. **Derived values are never stored on library objects.** Replacement counts, lifecycle totals and present values are computed on each run. If a schema class grows a `lifecycle_ghg` field, that is a defect.
7. **No bare numbers.** Every GHG and cost figure carries a `DataQuality` record: source, data type, vintage, geography, uncertainty, basis note. Loading a figure without one is a validation error.
8. **Uncertainty governs ranking.** Two options whose difference on a dimension falls inside the combined interval are reported *indistinguishable on that dimension* and are not ranked by it. Refusing to rank is correct behaviour, not a failure to produce output.
9. **The profile's indifference band and the data's uncertainty band are different things** and must never be combined or substituted for one another.
10. **Provenance travels with results.** Every finding carries its rule id, the input values that triggered it, its source, and the provenance flags of the data it used. Anything derived from an archetype, generic factor or estimate is flagged provisional.

---

## 4. Layout

```
docs/                       spec and context (read-only; do not edit to fit the code)
src/cdfma/
  schema.py                 ElementType, ConnectionType, DataQuality, ProjectParameters,
                            Instance, ConnectionInstance, Interval, Finding, Gap, TradeOff
  library.py                YAML load, validation, id resolution
  graph.py                  instances and edges; traversal helpers
  normalise.py              declared-unit resolution, assembly quantities, interval arithmetic
  rules.py                  rule registry; one pure function per rule id
  engine.py                 evaluation cycle (spec §5.1)
  priority.py               constraints, dominance, ranking, rank stability
  report.py                 findings / comparison / gap renderers
  cli.py                    entry point
data/
  project_parameters.yaml   element_types.yaml   connection_types.yaml
  project_wall.yaml         rules.yaml
tests/
  test_acceptance.py        fixtures/
```

Nine modules. Do not add a tenth without saying why. Do not add a database, a web framework, an ORM or a package layer.

---

## 5. Data and units

- `data/*.yaml` is the store and the source of truth. No hardcoded fixtures in `src/`.
- Units: mm, kg, years, kgCO₂e, currency per `project_parameters.yaml`. Never mix; never convert outside `normalise.py`.
- Declared-unit resolution happens only in `normalise.py`: per m² uses envelope face area × `envelope_fill_ratio`; per kg uses `mass`; per m uses the governing envelope dimension. This is where silent errors enter — every branch needs a unit test.
- Ids are lowercase snake_case and stable. Rules and data reference ids, never names.
- Impact and cost quantities are `Interval`, not `float`. Arithmetic on them is interval arithmetic. Do not unwrap to a midpoint for convenience.

---

## 6. Rule authoring

`data/rules.yaml` carries, per rule: `id`, `kind`, `scope`, `requires[]`, `logic` parameters (thresholds, margins), `output` template, `source`, `opposes[]`.

`rules.py` registers one pure function per rule id:

```
(subject, context) -> Finding | Gap | None
```

- Thresholds and citations live in YAML, never in the function body.
- Functions do not mutate the graph, the library or the context.
- A rule that fires must return the input values that triggered it, for the report.
- `opposes[]` is honoured by the engine, not by the rules: the engine detects two opposing rules firing on the same subject and emits a `TradeOff` holding both positions, the deciding conditions and the crossover point where one exists. It does not resolve the trade-off.

Register rule metadata loading before authoring any rule content. Retrofitting it means rewriting every rule.

---

## 7. Tests

`tests/test_acceptance.py` implements the spec's numbered tests. Names must carry the numbers.

| Test | Requirement |
|---|---|
| 1 Reproduction | Reproduces `docs/worked-example.md` end to end, figures matching the hand-checked answer key exactly. |
| 2 Propagation | Changing one library fact (adhesive bond → mechanical fixing) propagates to derived reversibility, findings, indicators and ranking **with no edit to any rule or any Python file**. |
| 5 Cascading replacement | Setting `damage_to_host` minor → major raises the host's derived replacement count and moves `IND-06` and `IND-07` by the corresponding quantity, naming `DRV-06` as the cause. |
| 6 Study-period and discount sensitivity | Changing `study_period` 60 → 30 and the rate 0% → 5% changes `IND-07` and `IND-08`, is reported as an assumption change rather than a data change, and any ranking flip is flagged by the rank-stability check. |
| 7 Indistinguishability | Two options differing by less than the combined uncertainty band are reported indistinguishable on that dimension and are not ranked by it. |

Tests 5 and 7 are decisive. Test 2 is the structural test of the facts/judgements/preferences separation — if it requires a code change, the separation is broken.

Run `pytest` before reporting any task complete.

---

## 8. Environment

- Python 3.11+. Dependencies: `pydantic` v2, `PyYAML`, `pytest`. Nothing else — no pandas, no numpy, no network calls, no AI or ML libraries.
- Full type hints. `pydantic` models for anything loaded from YAML.
- Deterministic output: sort before iterating, never depend on dict insertion order for reported sequence, no randomness, no wall-clock in results.
- `python -m cdfma.cli --project data/project_wall.yaml` runs the assessment and prints the three reports.

---

## 9. When the spec is silent

Do not invent domain content — thresholds, service lives, damage expectations, emission factors or cost rates. Record the question in `docs/open-questions.md` and ask. A gap in the data is a research finding the platform is designed to surface; a plausible invented number destroys that.
