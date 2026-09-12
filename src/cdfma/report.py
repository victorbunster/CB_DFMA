"""Findings, option-comparison and gap report renderers (spec §5.1 step 7,
§6), plus a shared reference legend. Plain text, deterministic (sorted,
no dict-order or wall-clock dependence — CLAUDE.md §8), no logic beyond
formatting what the engine and priority layer already computed.
"""

from __future__ import annotations

from cdfma.engine import EvaluationResult
from cdfma.priority import RankingResult, RankStabilityResult
from cdfma.schema import Finding, Gap, TradeOff

# Static reference text only — no computation, no domain content beyond
# what data/rules.yaml and mvp-scope.md §3.2 already declare. Shared by
# every interface (gui.py, streamlit_app/) so it's defined once here
# rather than duplicated per UI — and so a UI that must not depend on
# tkinter (e.g. a web deployment) doesn't need to import gui.py to get it.
LEGEND = """\
INDICATORS (spec §3.2)

IND-01  Mass fraction recoverable at component tier.
        This build: decomposable-mass proxy (DRV-02, the full
        highest-recoverable-tier test, is out of scope for Slice 1).
IND-02  Fraction of connections reversible (per DRV-01).
IND-05  Upfront embodied GHG, A1-A5, per m² of assembly.
IND-06  Lifecycle embodied GHG over the study period, including
        replacement cycles and end-of-life (C). Module D (benefits
        beyond the system boundary) is reported separately
        ("IND-06_ghg_D") and never summed in.
IND-07  Lifecycle cost over the study period: capital, replacement,
        removal, less residual value. Shown undiscounted
        ("IND-07_undiscounted") and at each declared rate
        ("IND-07@<rate>").
IND-08  Break-even of reversibility: the year a reversible option's
        higher upfront cost/GHG is repaid by avoided replacement.
        Carbon and cost break-even are reported separately — they
        frequently disagree, and that disagreement is the finding.

Not implemented (out of scope, need the interface layer): IND-03
(interface diversity), IND-04 (transport density).

An indicator shown as "indistinguishable" on a ranking dimension means
two options' values overlap within their combined data uncertainty
band — a fact about the data, not a preference (kept separate from the
priority profile's own indifference band).

RULES (spec §3.2) — the rule id shown on each finding

Derivations (always report a value):
  DRV-01  Reversibility, from removal method + damage expectation.
  DRV-04  Handling class: one-person / two-person / mechanical.
  DRV-05  Replacement count over the study period.
  DRV-06  Cascading replacement: a host forced to replace on its
          element's shorter cycle.
  DRV-07  Lifecycle GHG and cost.

Criteria (fire only when their condition is met):
  CON-001  Irreversible joint across a service-life differential
           above threshold.
  CON-003  Recovery not worth doing (removal cost/GHG exceeds credit).
  REC-001  Declared recovery pathway contradicted by the installed
           connection.
  SEP-001  Not decomposable with multiple materials — not separable
           at end of life.
  DFM-001  DfMA part-count saving opposing a circularity criterion —
           produces a TRADE-OFF where it opposes CON-001.

[PROVISIONAL] on a finding means it derives from an archetype, a
generic factor, or an estimate, per the data's own DataQuality record.

Several logic thresholds and some library facts are PLACEHOLDER values,
not real data — see docs/open-questions.md.

Use "Add material" / "Add connection" to enter a new element type or
connection type by hand (spec §6). Saving adds it to element_types.yaml /
connection_types.yaml, but it won't appear in a run until an Instance or
ConnectionInstance in your project file also references its id.
"""


def render_legend() -> str:
    return LEGEND


def _finding_line(finding: Finding) -> str:
    provisional = " [PROVISIONAL]" if finding.provisional else ""
    action = f" -> {finding.recommended_action}" if finding.recommended_action else ""
    return (
        f"  [{finding.rule_id}] {finding.subject_kind}:{finding.subject_id} "
        f"({finding.severity}){provisional}: {finding.text}{action}\n"
        f"      source: {finding.source}"
    )


def _trade_off_block(trade_off: TradeOff) -> str:
    lines = [
        f"  TRADE-OFF on {trade_off.subject_kind}:{trade_off.subject_id} "
        f"[{trade_off.finding_a.rule_id} vs {trade_off.finding_b.rule_id}]",
        f"    {trade_off.deciding_conditions}",
    ]
    if trade_off.crossover:
        lines.append(f"    crossover: {trade_off.crossover}")
    return "\n".join(lines)


_FINDINGS_NOTE = (
    "Every rule that fired on this option's graph, one line each: which rule\n"
    "(see the Legend), what subject it fired on, and why. [PROVISIONAL] means\n"
    "an input came from an archetype, a generic factor, or an estimate.\n"
    "Trade-offs below are two opposing rules firing on the same subject —\n"
    "held side by side, not resolved."
)

_GAP_REPORT_NOTE = (
    "Rules that could NOT run because a required field was absent — a gap in\n"
    "the data, never a default or a silent pass. Absence here is itself a\n"
    "finding about what the data doesn't yet support."
)

_COMPARISON_NOTE = (
    "Every indicator (see the Legend) for each option, side by side; then, if\n"
    "a priority profile is declared, the ranking it produces, the rank-\n"
    "stability check across dimension reordering and discount rates, and the\n"
    "IND-08 break-even between the two options."
)


def render_findings(result: EvaluationResult) -> str:
    lines = [f"=== Findings — option {result.option_id!r} ===", _FINDINGS_NOTE, ""]
    findings = sorted(result.findings, key=lambda f: (f.rule_id, f.subject_kind, f.subject_id))
    if not findings:
        lines.append("  (no findings)")
    for finding in findings:
        lines.append(_finding_line(finding))

    if result.trade_offs:
        lines.append("")
        lines.append("--- Trade-offs ---")
        for trade_off in sorted(result.trade_offs, key=lambda t: (t.subject_kind, t.subject_id)):
            lines.append(_trade_off_block(trade_off))

    return "\n".join(lines)


def render_gap_report(results: list[EvaluationResult]) -> str:
    lines = ["=== Gap report ===", _GAP_REPORT_NOTE, ""]
    any_gaps = False
    for result in results:
        gaps = sorted(result.gaps, key=lambda g: (g.rule_id, g.subject_kind, g.subject_id))
        for gap in gaps:
            any_gaps = True
            lines.append(
                f"  option {result.option_id!r}: [{gap.rule_id}] {gap.subject_kind}:{gap.subject_id} "
                f"— {gap.reason}"
            )
    if not any_gaps:
        lines.append("  (no gaps)")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3g}"


def render_comparison(
    evaluations: dict[str, EvaluationResult],
    ranking: RankingResult | None = None,
    stability: RankStabilityResult | None = None,
    break_evens: dict[str, int | None] | None = None,
) -> str:
    lines = ["=== Option comparison ===", _COMPARISON_NOTE, ""]
    option_ids = sorted(evaluations)
    indicator_ids = sorted({key for e in evaluations.values() for key in e.indicators})

    header = "  indicator".ljust(24) + "".join(option_id.ljust(20) for option_id in option_ids)
    lines.append(header)
    for indicator_id in indicator_ids:
        row = f"  {indicator_id}".ljust(24)
        row += "".join(_fmt(evaluations[o].indicators.get(indicator_id)).ljust(20) for o in option_ids)
        lines.append(row)

    if ranking is not None:
        lines.append("")
        lines.append(f"--- Ranking under profile {ranking.profile_dimensions} ---")
        lines.append("  order (best first): " + " > ".join(ranking.order))
        for comparison in ranking.comparisons:
            if comparison.winner is not None:
                lines.append(f"    {comparison.indicator_id}: {comparison.winner} wins")
            else:
                lines.append(f"    {comparison.indicator_id}: indistinguishable ({comparison.reason})")

    if stability is not None:
        lines.append("")
        lines.append("--- Rank-stability check ---")
        lines.append(f"  baseline winner: {stability.baseline_winner}")
        lines.append(f"  stable: {stability.stable}")
        for reordering, winner in stability.reordering_flips:
            lines.append(f"    reordering {reordering} flips winner to {winner}")
        for rate, winner in stability.rate_flips:
            lines.append(f"    at discount rate {rate:.0%} flips winner to {winner}")

    if break_evens:
        lines.append("")
        lines.append("--- IND-08: break-even of reversibility ---")
        for metric, year in sorted(break_evens.items()):
            lines.append(f"  {metric} break-even: {'year ' + str(year) if year is not None else 'none within study period'}")

    return "\n".join(lines)
