# Example application of core system logic

A single wall build-up. Figures are illustrative.

## 1 — The library supplies the facts

The designer selects two archetypes and the joint between them:

- **Cladding panel**: aluminium sheet / mineral wool / PU adhesive, `decomposable: false`, service life 25 years (basis: warranty), layer skin, declared recovery pathway `reuse_as_is` with preconditions `[edges_undamaged, fixings_removable]`.
- **Substrate**: service life 60 years, layer structure.
- **Connection type `adhesive_bond`**: removal method destroys the joint, damage to self major, no re-installation.

Nothing here is a judgement — it is what the panel is and how it is fixed.

## 2 — The knowledge base says what follows

- `DRV-01` derives reversibility from the removal method and damage expectation: **irreversible**.
- `DRV-02` derives the highest recoverable tier: the adhesive contaminates both streams, so recovery stops at **material**, not component.
- `CON-001` fires: irreversible joint across a 35-year service-life differential, above its 15-year threshold. Finding: the 25-year skin cannot be replaced without damaging the 60-year substrate. Recommendation: `substitute_joint_type(mechanical)`.
- `REC-001` fires: the declared `reuse_as_is` pathway requires `fixings_removable`, which the installed joint contradicts. The claim is not credible.
- `DFM-001` fires on the same subject: the bonded build-up reduces part count and site fixings. It opposes `CON-001`, so the two produce a **trade-off** — both positions, the deciding conditions (35-year differential, skin over structure), no resolution.

Because the panel values came from an archetype rather than a product entry, all of the above are flagged **provisional**.

## 3 — The priority layer decides what happens with it

The project declares a hard capital-cost cap, a target of 80% mass recoverable at component tier, and a profile ordering cost, then feasibility, then recovery potential, with a 5% indifference band on cost.

Two options are compared: **A** the bonded panel, **B** a mechanically-fixed equivalent.

- The constraint excludes neither.
- Dominance eliminates nothing: B is better on recovery, reversibility and information quality, worse on capital cost. The choice is a real trade-off.
- Under the declared profile, A ranks first — but only while B's cost premium exceeds 5%. Rank stability reports that the order reverses if recovery is placed above cost.

## Output

Two conflicts, one trade-off, the recovery target reported against as unmet, a ranking labelled with the profile that produced it, the cost premium at which the ranking flips, and a gap report noting that the adhesive's damage-on-removal value rests on one observation.
