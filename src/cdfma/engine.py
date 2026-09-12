"""The evaluation cycle (spec §5.1). Holds no domain content of its own —
every threshold and citation comes from ``data/rules.yaml`` via
``rules.py``; this module only binds rules to subjects, checks
``requires[]``, normalises quantities, evaluates, detects trade-offs, and
computes indicators.

Cost/GHG lifecycle modelling notes (design decisions, not spec text —
documented here since the spec leaves the exact mechanics of §5.4 and
DRV-07 to be worked out):

* Every instance contributes its own **full** lifecycle — initial
  capital, replacements at its own (or cascaded-effective) schedule, and
  a final removal at the end of the study period — summed across every
  instance in the graph. This is a general, self-consistent rule that
  works for any graph, rather than a special case tuned to reproduce
  mvp-scope.md's illustrative appendix table figure-for-figure. Per
  CLAUDE.md §1, ``docs/worked-example.md`` (not that appendix) is the
  designated fixture/answer key, and it carries no such numeric table —
  only the qualitative findings (DRV-01, CON-001, REC-001, DFM-001,
  and the resulting trade-off), which this engine does reproduce exactly.
* Connection GHG/cost figures are treated as flat per-connection-instance
  totals, not per-metre: interfaces (which would supply a length) are out
  of scope for Slice 1, so the "or per metre" half of spec §2.4 has
  nothing to resolve against.
* A connection's figures are attributed to its ``element_instance_id``
  side only (never double-counted on the host side), and reapplied
  whenever that side is naturally replaced — matching spec §5.4:
  "replacement events reapply the element figure and its connection
  figures."
* Module D is never included in a lifecycle total or a cash-flow event —
  only ever reported as its own separate figure (CLAUDE.md architecture
  invariant 4).
* Uncertainty propagation (for indistinguishability, CLAUDE.md invariant
  8) treats each instance's total GHG/cost contribution as one banded
  figure, using that element or connection type's own ``DataQuality.
  uncertainty`` — not a separate band per elementary figure (A1-A3, A4,
  …). A coarser but tractable propagation for Slice 1.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from cdfma.graph import Graph
from cdfma.library import Library
from cdfma.normalise import (
    present_value,
    replacement_years,
    resolve_per_element,
    scale,
    sum_intervals,
    to_interval,
)
from cdfma.rules import RuleContext, RuleDef, get_rule_function, missing_requirements
from cdfma.schema import (
    ConnectionType,
    Finding,
    Gap,
    Instance,
    Interval,
    ProjectParameters,
    TradeOff,
)


class EngineError(Exception):
    pass


@dataclass
class LifecycleResult:
    instance_id: str
    element_type_id: str
    upfront_ghg: float
    lifecycle_ghg: float
    ghg_d: float
    ghg_events: list[tuple[int, float]]
    upfront_cost: float
    lifecycle_cost_undiscounted: float
    lifecycle_cost_at_rate: dict[float, float]
    cost_events: list[tuple[int, float]]
    own_years: list[int]
    effective_years: list[int]
    cascades: bool


@dataclass
class EvaluationResult:
    option_id: str
    findings: list[Finding]
    gaps: list[Gap]
    trade_offs: list[TradeOff]
    lifecycle: dict[str, LifecycleResult]
    assembly_area_m2: float
    indicators: dict[str, float] = field(default_factory=dict)
    indicator_intervals: dict[str, Interval] = field(default_factory=dict)


def _connection_ghg_total(connection_type: ConnectionType) -> float:
    return connection_type.ghg_A1A3 + connection_type.ghg_A5


def instance_lifecycle(
    instance: Instance, library: Library, graph: Graph, project_parameters: ProjectParameters
) -> LifecycleResult:
    element_type = library.get_element_type(instance.element_type_id)
    study_period = project_parameters.study_period
    ghg, cost = element_type.embodied_ghg, element_type.cost

    own_years = replacement_years(element_type.service_life, study_period)

    effective_years_set = set(own_years)
    cascades = False
    for connection in graph.connections_of_instance(instance.id):
        if connection.host_instance_id != instance.id:
            continue
        connection_type = library.get_connection_type(connection.connection_type_id)
        if connection_type.damage_to_host == "major":
            cascades = True
            driving_element = library.get_element_type(graph.element_of(connection).element_type_id)
            effective_years_set |= set(replacement_years(driving_element.service_life, study_period))
    effective_years = sorted(effective_years_set)

    a_stage = resolve_per_element(ghg.ghg_A1A3, ghg.declared_unit, element_type)
    if ghg.ghg_A4 is not None:
        a_stage += resolve_per_element(ghg.ghg_A4, ghg.declared_unit, element_type)
    if ghg.ghg_A5 is not None:
        a_stage += resolve_per_element(ghg.ghg_A5, ghg.declared_unit, element_type)
    c_stage = resolve_per_element(ghg.ghg_C, ghg.declared_unit, element_type)
    d_stage = resolve_per_element(ghg.ghg_D, ghg.declared_unit, element_type)

    connections_as_element = [
        c for c in graph.connections_of_instance(instance.id) if c.element_instance_id == instance.id
    ]
    connection_ghg = sum(
        _connection_ghg_total(library.get_connection_type(c.connection_type_id))
        for c in connections_as_element
    )
    connection_install_cost = sum(
        library.get_connection_type(c.connection_type_id).cost_install for c in connections_as_element
    )
    connection_removal_cost = sum(
        library.get_connection_type(c.connection_type_id).cost_removal for c in connections_as_element
    )

    upfront_ghg = a_stage + connection_ghg
    # Own replacements reapply the element's A-stage *and* its connections
    # (spec §5.4); a cascaded host's *extra* forced replacements reapply
    # only its own material — the connection belongs to the element side.
    ghg_events: list[tuple[int, float]] = [(0, upfront_ghg)]
    for year in own_years:
        ghg_events.append((year, a_stage + connection_ghg))
    for year in effective_years:
        if year not in own_years:
            ghg_events.append((year, a_stage))
    ghg_events.append((study_period, c_stage))
    lifecycle_ghg = sum(amount for _, amount in ghg_events)

    upfront_cost = cost.cost_supply + cost.cost_install + connection_install_cost
    cost_events: list[tuple[int, float]] = [(0, upfront_cost)]
    for year in own_years:
        cost_events.append(
            (
                year,
                cost.cost_removal
                + cost.cost_supply
                + cost.cost_install
                + connection_removal_cost
                + connection_install_cost,
            )
        )
    for year in effective_years:
        if year not in own_years:
            cost_events.append((year, cost.cost_removal + cost.cost_supply + cost.cost_install))
    cost_events.append((study_period, cost.cost_removal - cost.residual_value))

    lifecycle_cost_undiscounted = sum(amount for _, amount in cost_events)
    # Always includes the project's own declared rate, plus 0.0 and every
    # sensitivity rate, so a lookup by any of those never misses.
    rates = sorted({0.0, project_parameters.discount_rate, *project_parameters.sensitivity_rates})
    lifecycle_cost_at_rate = {
        rate: sum(present_value(amount, rate, year) for year, amount in cost_events) for rate in rates
    }

    return LifecycleResult(
        instance_id=instance.id,
        element_type_id=element_type.id,
        upfront_ghg=upfront_ghg,
        lifecycle_ghg=lifecycle_ghg,
        ghg_d=d_stage,
        ghg_events=ghg_events,
        upfront_cost=upfront_cost,
        lifecycle_cost_undiscounted=lifecycle_cost_undiscounted,
        lifecycle_cost_at_rate=lifecycle_cost_at_rate,
        cost_events=cost_events,
        own_years=own_years,
        effective_years=effective_years,
        cascades=cascades,
    )


def assembly_reference_area_m2(library: Library, graph: Graph) -> float:
    """The assembly's reference area for "per m²" indicators (IND-05/06/07):
    the largest face area among the graph's skin-layer instances. Spec
    §5.4 defines per-m² resolution for a single element's own figure but
    not an assembly-wide reference area for multi-instance graphs; the
    skin layer is used here since it is what "per m² of assembly"
    conventionally means for a wall build-up (spec §1).

    Uses ``max``, not a sum, deliberately: a real wall's skin is usually
    several layers (cladding, membrane, insulation, …) covering the same
    footprint, not additional area stacked on top of each other — so
    summing every skin-layer instance's own face area would inflate the
    denominator once a graph has more than one. For a graph with exactly
    one skin-layer instance (as in Slice 1's original two-option fixture)
    this is identical to summing, so existing figures are unaffected.
    Documented design decision, not spec text.
    """
    from cdfma.normalise import face_area_m2

    areas = [
        face_area_m2(library.get_element_type(instance.element_type_id))
        for instance in graph.instances.values()
        if library.get_element_type(instance.element_type_id).layer == "skin"
    ]
    return max(areas, default=0.0)


def _bind_env(rule: RuleDef, subject, library: Library, graph: Graph) -> dict:
    if rule.scope.subject_kind == "instance":
        return {"element_type": library.get_element_type(subject.element_type_id)}
    connection_type = library.get_connection_type(subject.connection_type_id)
    element_type = library.get_element_type(graph.element_of(subject).element_type_id)
    host_type = library.get_element_type(graph.host_of(subject).element_type_id)
    return {"connection_type": connection_type, "element_type": element_type, "host_element_type": host_type}


def _subjects_for(rule: RuleDef, graph: Graph, library: Library):
    if rule.scope.subject_kind == "instance":
        for instance in sorted(graph.instances.values(), key=lambda i: i.id):
            element_type = library.get_element_type(instance.element_type_id)
            if rule.scope.layer is not None and element_type.layer not in rule.scope.layer:
                continue
            yield instance
    else:
        yield from sorted(graph.connection_instances.values(), key=lambda c: c.id)


def _detect_trade_offs(findings: list[Finding], rules: dict[str, RuleDef]) -> list[TradeOff]:
    by_subject: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        by_subject[(finding.subject_id, finding.subject_kind)].append(finding)

    trade_offs: list[TradeOff] = []
    seen: set[tuple[str, str, tuple[str, str]]] = set()
    for (subject_id, subject_kind), subject_findings in by_subject.items():
        for finding_a in subject_findings:
            rule_a = rules[finding_a.rule_id]
            for finding_b in subject_findings:
                if finding_b.rule_id not in rule_a.opposes:
                    continue
                pair = tuple(sorted((finding_a.rule_id, finding_b.rule_id)))
                key = (subject_id, subject_kind, pair)
                if key in seen:
                    continue
                seen.add(key)
                trade_offs.append(
                    TradeOff(
                        subject_id=subject_id,
                        subject_kind=subject_kind,
                        finding_a=finding_a,
                        finding_b=finding_b,
                        deciding_conditions=(
                            f"{finding_a.rule_id}: {finding_a.text} | {finding_b.rule_id}: {finding_b.text}"
                        ),
                    )
                )
    return trade_offs


def _instance_ghg_interval(library: Library, instance: Instance, point_value: float) -> Interval:
    element_type = library.get_element_type(instance.element_type_id)
    return to_interval(point_value, element_type.embodied_ghg.ghg_data.uncertainty)


def _instance_cost_interval(library: Library, instance: Instance, point_value: float) -> Interval:
    element_type = library.get_element_type(instance.element_type_id)
    return to_interval(point_value, element_type.cost.cost_data.uncertainty)


def _compute_indicators(
    library: Library,
    graph: Graph,
    lifecycle: dict[str, LifecycleResult],
    findings: list[Finding],
    assembly_area_m2: float,
    project_parameters: ProjectParameters,
) -> tuple[dict[str, float], dict[str, Interval]]:
    if assembly_area_m2 <= 0:
        raise EngineError("assembly reference area is zero: no skin-layer instance in the graph")

    total_mass = sum(library.get_element_type(i.element_type_id).mass for i in graph.instances.values())
    decomposable_mass = sum(
        library.get_element_type(i.element_type_id).mass
        for i in graph.instances.values()
        if library.get_element_type(i.element_type_id).decomposable
    )
    ind_01 = decomposable_mass / total_mass if total_mass else 0.0

    reversibility_findings = [f for f in findings if f.rule_id == "DRV-01"]
    reversible_count = sum(1 for f in reversibility_findings if f.triggering_values.get("result") == "reversible")
    ind_02 = reversible_count / len(reversibility_findings) if reversibility_findings else None

    indicators: dict[str, float] = {"IND-01": ind_01}
    if ind_02 is not None:
        indicators["IND-02"] = ind_02

    upfront_total = sum(l.upfront_ghg for l in lifecycle.values())
    lifecycle_total = sum(l.lifecycle_ghg for l in lifecycle.values())
    ghg_d_total = sum(l.ghg_d for l in lifecycle.values())
    indicators["IND-05"] = upfront_total / assembly_area_m2
    indicators["IND-06"] = lifecycle_total / assembly_area_m2
    indicators["IND-06_ghg_D"] = ghg_d_total / assembly_area_m2  # reported separately, never summed in

    indicators["IND-07_undiscounted"] = (
        sum(l.lifecycle_cost_undiscounted for l in lifecycle.values()) / assembly_area_m2
    )
    rates = sorted({0.0, project_parameters.discount_rate, *project_parameters.sensitivity_rates})
    for rate in rates:
        total_at_rate = sum(l.lifecycle_cost_at_rate[rate] for l in lifecycle.values())
        indicators[f"IND-07@{rate}"] = total_at_rate / assembly_area_m2

    intervals: dict[str, Interval] = {}
    intervals["IND-05"] = scale(
        sum_intervals([_instance_ghg_interval(library, i, l.upfront_ghg) for i, l in _pairs(graph, lifecycle)]),
        1.0 / assembly_area_m2,
    )
    intervals["IND-06"] = scale(
        sum_intervals([_instance_ghg_interval(library, i, l.lifecycle_ghg) for i, l in _pairs(graph, lifecycle)]),
        1.0 / assembly_area_m2,
    )
    for rate in rates:
        intervals[f"IND-07@{rate}"] = scale(
            sum_intervals(
                [
                    _instance_cost_interval(library, i, l.lifecycle_cost_at_rate[rate])
                    for i, l in _pairs(graph, lifecycle)
                ]
            ),
            1.0 / assembly_area_m2,
        )

    return indicators, intervals


def _pairs(graph: Graph, lifecycle: dict[str, LifecycleResult]):
    for instance_id, result in lifecycle.items():
        yield graph.instances[instance_id], result


def run_engine(
    option_id: str,
    library: Library,
    graph: Graph,
    rules: dict[str, RuleDef],
    project_parameters: ProjectParameters,
) -> EvaluationResult:
    graph.validate_against_library(library)

    findings: list[Finding] = []
    gaps: list[Gap] = []

    for rule in sorted(rules.values(), key=lambda r: r.id):
        fn = get_rule_function(rule.id)
        if fn is None:
            continue  # declared in data but not registered — not in Slice 1's scope
        for subject in _subjects_for(rule, graph, library):
            env = _bind_env(rule, subject, library, graph)
            missing = missing_requirements(env, rule.requires)
            if missing:
                gaps.append(
                    Gap(
                        rule_id=rule.id,
                        subject_id=subject.id,
                        subject_kind=rule.scope.subject_kind,
                        missing_fields=missing,
                        reason=f"required field(s) absent: {', '.join(missing)}",
                    )
                )
                continue
            context = RuleContext(
                library=library, graph=graph, project_parameters=project_parameters, rule=rule, env=env
            )
            result = fn(subject, context)
            if result is not None:
                findings.append(result)

    trade_offs = _detect_trade_offs(findings, rules)
    lifecycle = {
        instance_id: instance_lifecycle(instance, library, graph, project_parameters)
        for instance_id, instance in graph.instances.items()
    }
    assembly_area = assembly_reference_area_m2(library, graph)
    indicators, indicator_intervals = _compute_indicators(
        library, graph, lifecycle, findings, assembly_area, project_parameters
    )

    return EvaluationResult(
        option_id=option_id,
        findings=findings,
        gaps=gaps,
        trade_offs=trade_offs,
        lifecycle=lifecycle,
        assembly_area_m2=assembly_area,
        indicators=indicators,
        indicator_intervals=indicator_intervals,
    )


def break_even_year(
    series_a: dict[str, LifecycleResult], series_b: dict[str, LifecycleResult], study_period: int, metric: str
) -> int | None:
    """IND-08: the year cumulative GHG or cost trajectories cross, if any
    (spec §3.2's "reported as two numbers... which frequently disagree").
    ``metric`` is ``"ghg"`` or ``"cost"``.
    """

    def cumulative(series: dict[str, LifecycleResult]) -> list[float]:
        events: list[tuple[int, float]] = []
        for result in series.values():
            events.extend(result.ghg_events if metric == "ghg" else result.cost_events)
        by_year = defaultdict(float)
        for year, amount in events:
            by_year[year] += amount
        cumulative_values = []
        running = 0.0
        for year in range(study_period + 1):
            running += by_year.get(year, 0.0)
            cumulative_values.append(running)
        return cumulative_values

    cum_a, cum_b = cumulative(series_a), cumulative(series_b)
    initial_sign = cum_a[0] - cum_b[0]
    for year in range(1, study_period + 1):
        current_sign = cum_a[year] - cum_b[year]
        if initial_sign == 0:
            initial_sign = current_sign
            continue
        if current_sign == 0 or (current_sign > 0) != (initial_sign > 0):
            return year
    return None
