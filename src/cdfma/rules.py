"""Rule registry: rule metadata loaded from ``data/rules.yaml``, and one
pure function per rule id (CLAUDE.md §6).

Thresholds and citations live in YAML, never in a function body — every
function below reads its numbers from ``RuleDef.logic``, supplied by the
caller (``engine.py``), not hardcoded here. Functions do not mutate the
graph, the library or the context; each returns a fresh ``Finding`` (or
``None`` if it does not fire).

Scope (CLAUDE.md §2): only ``DRV-01``, ``DRV-04``, ``DRV-05``, ``DRV-06``,
``DRV-07``, ``CON-001``, ``CON-003``, ``REC-001``, ``SEP-001`` and
``DFM-001`` are registered. ``DRV-02``, ``DRV-03``, ``CON-002`` and the
compatibility/substitution machinery are out of scope and have no entry
here.

Several ``logic`` values in ``data/rules.yaml`` are placeholders (per the
user's explicit choice, see docs/open-questions.md): ``CON-003``'s cost
margin and ``DRV-04``'s handling-class thresholds are not given anywhere
in the spec or its worked example, unlike ``CON-001``'s 15-year threshold,
which the worked example states directly and which is therefore real, not
invented.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from cdfma.graph import Graph
from cdfma.library import Library
from cdfma.normalise import replacement_count
from cdfma.schema import (
    ConnectionInstance,
    ConnectionType,
    DataQualityFlags,
    ElementType,
    Finding,
    Instance,
    ProjectParameters,
)

_MISSING = object()


class RulesError(Exception):
    """Raised for malformed rule metadata, an unknown declared unit, or a
    ``requires[]`` path that names no known root."""


class RuleScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_kind: Literal["instance", "connection_instance"]
    layer: list[str] | None = None
    """Restricts an ``instance``-scoped rule to element types on these
    layers; ``None`` means any layer."""


class RuleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    severity: str
    recommended_action: str | None = None


class RuleDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["derivation", "criterion", "indicator"]
    scope: RuleScope
    requires: list[str] = []
    logic: dict[str, Any] = {}
    output: RuleOutput
    source: str
    opposes: list[str] = []


def load_rules(path: Path) -> dict[str, RuleDef]:
    """Load and validate ``data/rules.yaml``, keyed by id."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RulesError(f"could not read {path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulesError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(document, dict) or "rules" not in document:
        raise RulesError(f"{path}: expected a top-level 'rules' list")

    rules: dict[str, RuleDef] = {}
    for index, raw in enumerate(document["rules"]):
        try:
            rule = RuleDef.model_validate(raw)
        except ValidationError as exc:
            raise RulesError(f"{path}: rules[{index}] failed validation:\n{exc}") from exc
        if rule.id in rules:
            raise RulesError(f"{path}: duplicate rule id {rule.id!r}")
        rules[rule.id] = rule
    return rules


@dataclass
class RuleContext:
    """Everything a rule function may read. Never mutated by a rule."""

    library: Library
    graph: Graph
    project_parameters: ProjectParameters
    rule: RuleDef
    env: dict[str, Any] = field(default_factory=dict)


def resolve_path(env: dict[str, Any], path: str) -> Any:
    """Resolve a dotted ``requires[]`` path (e.g. ``"element_type.
    embodied_ghg.ghg_A4"``) against ``env``. Returns ``_MISSING`` if any
    segment is absent or ``None`` along the way — the engine turns that
    into a ``Gap`` before ever calling the rule function (CLAUDE.md
    architecture invariant 3).
    """
    parts = path.split(".")
    if parts[0] not in env:
        raise RulesError(f"requires path {path!r} has unknown root {parts[0]!r}")
    value: Any = env[parts[0]]
    for part in parts[1:]:
        if value is None:
            return _MISSING
        value = getattr(value, part, _MISSING)
        if value is _MISSING:
            return _MISSING
    return value


def missing_requirements(env: dict[str, Any], requires: list[str]) -> list[str]:
    """Which of ``requires[]`` are absent (or ``None``) in ``env``. The
    engine calls this before invoking a rule function, and turns a
    non-empty result into a ``Gap`` rather than calling the rule
    (CLAUDE.md architecture invariant 3).
    """
    return [path for path in requires if resolve_path(env, path) in (_MISSING, None)]


RuleFunction = Callable[[Any, RuleContext], Finding | None]

_REGISTRY: dict[str, RuleFunction] = {}


def register_rule(rule_id: str) -> Callable[[RuleFunction], RuleFunction]:
    def decorator(fn: RuleFunction) -> RuleFunction:
        _REGISTRY[rule_id] = fn
        return fn

    return decorator


def get_rule_function(rule_id: str) -> RuleFunction | None:
    return _REGISTRY.get(rule_id)


def registered_rule_ids() -> list[str]:
    return sorted(_REGISTRY)


# --- shared helpers -----------------------------------------------------


def _data_quality(*sources: str) -> DataQualityFlags:
    return DataQualityFlags(provenance=list(sources))


def _finding(
    context: RuleContext,
    subject_id: str,
    subject_kind: Literal["instance", "connection_instance"],
    triggering_values: dict[str, Any],
    data_quality: DataQualityFlags,
) -> Finding:
    rule = context.rule
    text = rule.output.text.format(**triggering_values)
    action = rule.output.recommended_action
    if action is not None:
        action = action.format(**triggering_values)
    return Finding(
        rule_id=rule.id,
        subject_id=subject_id,
        subject_kind=subject_kind,
        text=text,
        severity=rule.output.severity,
        recommended_action=action,
        triggering_values=triggering_values,
        source=rule.source,
        data_quality=data_quality,
    )


def is_reversible(connection_type: ConnectionType) -> bool:
    """The reversibility test shared by DRV-01 and (for the same
    condition, inverted) DFM-001/CON-001: re-installable, and no more
    than minor damage on either side.
    """
    return (
        connection_type.re_installable
        and connection_type.damage_to_self in ("none", "minor")
        and connection_type.damage_to_host in ("none", "minor")
    )


def _element_and_host(
    connection: ConnectionInstance, context: RuleContext
) -> tuple[ElementType, ElementType]:
    element_instance = context.graph.element_of(connection)
    host_instance = context.graph.host_of(connection)
    element_type = context.library.get_element_type(element_instance.element_type_id)
    host_type = context.library.get_element_type(host_instance.element_type_id)
    return element_type, host_type


# --- derivations ----------------------------------------------------------


@register_rule("DRV-01")
def drv_01_reversibility(subject: ConnectionInstance, context: RuleContext) -> Finding:
    connection_type = context.library.get_connection_type(subject.connection_type_id)
    reversible = is_reversible(connection_type)
    return _finding(
        context,
        subject.id,
        "connection_instance",
        {
            "connection_type_id": connection_type.id,
            "removal_method": connection_type.removal_method,
            "damage_to_self": connection_type.damage_to_self,
            "damage_to_host": connection_type.damage_to_host,
            "re_installable": connection_type.re_installable,
            "result": "reversible" if reversible else "irreversible",
        },
        _data_quality(),
    )


@register_rule("DRV-04")
def drv_04_handling_class(subject: Instance, context: RuleContext) -> Finding:
    element_type = context.library.get_element_type(subject.element_type_id)
    logic = context.rule.logic
    max_dim_mm = max(
        element_type.envelope.length, element_type.envelope.width, element_type.envelope.thickness
    )
    if (
        element_type.mass <= logic["one_person_max_mass_kg"]
        and max_dim_mm <= logic["one_person_max_dimension_mm"]
    ):
        handling_class = "one_person"
    elif (
        element_type.mass <= logic["two_person_max_mass_kg"]
        and max_dim_mm <= logic["two_person_max_dimension_mm"]
    ):
        handling_class = "two_person"
    else:
        handling_class = "mechanical"
    return _finding(
        context,
        subject.id,
        "instance",
        {
            "element_type_id": element_type.id,
            "mass": element_type.mass,
            "max_dimension_mm": max_dim_mm,
            "result": handling_class,
        },
        _data_quality(element_type.geometry_provenance),
    )


@register_rule("DRV-05")
def drv_05_replacement_count(subject: Instance, context: RuleContext) -> Finding:
    element_type = context.library.get_element_type(subject.element_type_id)
    count = replacement_count(element_type.service_life, context.project_parameters.study_period)
    return _finding(
        context,
        subject.id,
        "instance",
        {
            "element_type_id": element_type.id,
            "service_life": element_type.service_life,
            "study_period": context.project_parameters.study_period,
            "result": count,
        },
        _data_quality(element_type.provenance),
    )


@register_rule("DRV-06")
def drv_06_cascading_replacement(subject: ConnectionInstance, context: RuleContext) -> Finding:
    connection_type = context.library.get_connection_type(subject.connection_type_id)
    element_type, host_type = _element_and_host(subject, context)
    study_period = context.project_parameters.study_period

    host_own_count = replacement_count(host_type.service_life, study_period)
    cascades = connection_type.damage_to_host == "major"
    if cascades:
        element_count = replacement_count(element_type.service_life, study_period)
        effective_host_count = max(host_own_count, element_count)
    else:
        effective_host_count = host_own_count

    return _finding(
        context,
        subject.id,
        "connection_instance",
        {
            "connection_type_id": connection_type.id,
            "host_element_type_id": host_type.id,
            "element_element_type_id": element_type.id,
            "damage_to_host": connection_type.damage_to_host,
            "host_own_replacement_count": host_own_count,
            "cascades": cascades,
            "result": effective_host_count,
        },
        _data_quality(host_type.provenance, element_type.provenance),
    )


@register_rule("DRV-07")
def drv_07_lifecycle_ghg_and_cost(subject: Instance, context: RuleContext) -> Finding:
    from cdfma.engine import instance_lifecycle  # local import: avoids a cycle

    result = instance_lifecycle(subject, context.library, context.graph, context.project_parameters)
    element_type = context.library.get_element_type(subject.element_type_id)
    discount_rate = context.project_parameters.discount_rate
    return _finding(
        context,
        subject.id,
        "instance",
        {
            "element_type_id": element_type.id,
            "upfront_ghg": round(result.upfront_ghg, 3),
            "lifecycle_ghg": round(result.lifecycle_ghg, 3),
            "ghg_d": round(result.ghg_d, 3),
            "upfront_cost": round(result.upfront_cost, 2),
            "lifecycle_cost_undiscounted": round(result.lifecycle_cost_undiscounted, 2),
            "lifecycle_cost_discounted": round(result.lifecycle_cost_at_rate[discount_rate], 2),
            "discount_rate": discount_rate,
        },
        _data_quality(
            element_type.embodied_ghg.ghg_data.data_type, element_type.cost.cost_data.data_type
        ),
    )


# --- criteria ---------------------------------------------------------


@register_rule("CON-001")
def con_001_irreversible_across_differential(
    subject: ConnectionInstance, context: RuleContext
) -> Finding | None:
    connection_type = context.library.get_connection_type(subject.connection_type_id)
    element_type, host_type = _element_and_host(subject, context)
    threshold = context.rule.logic["service_life_differential_threshold_years"]
    differential = abs(host_type.service_life - element_type.service_life)

    if is_reversible(connection_type) or differential <= threshold:
        return None

    shorter, longer = sorted([element_type, host_type], key=lambda et: et.service_life)
    return _finding(
        context,
        subject.id,
        "connection_instance",
        {
            "differential": differential,
            "threshold": threshold,
            "shorter_service_life": shorter.service_life,
            "shorter_element_type_id": shorter.id,
            "longer_service_life": longer.service_life,
            "longer_element_type_id": longer.id,
        },
        _data_quality(element_type.provenance, host_type.provenance),
    )


@register_rule("CON-003")
def con_003_recovery_not_worth_doing(subject: Instance, context: RuleContext) -> Finding | None:
    element_type = context.library.get_element_type(subject.element_type_id)
    margin = context.rule.logic["cost_removal_margin"]
    cost_excess = element_type.cost.cost_removal - element_type.cost.residual_value
    ghg_excess = element_type.embodied_ghg.ghg_C - abs(element_type.embodied_ghg.ghg_D)

    fails_on_cost = cost_excess > margin
    fails_on_ghg = ghg_excess > 0
    if not (fails_on_cost or fails_on_ghg):
        return None

    return _finding(
        context,
        subject.id,
        "instance",
        {
            "element_type_id": element_type.id,
            "declared_recovery_pathway": element_type.declared_recovery_pathway,
            "cost_removal": element_type.cost.cost_removal,
            "residual_value": element_type.cost.residual_value,
            "cost_margin": margin,
            "fails_on_cost": fails_on_cost,
            "ghg_c": element_type.embodied_ghg.ghg_C,
            "ghg_d": element_type.embodied_ghg.ghg_D,
            "fails_on_ghg": fails_on_ghg,
        },
        _data_quality(element_type.cost.cost_data.data_type, element_type.embodied_ghg.ghg_data.data_type),
    )


@register_rule("REC-001")
def rec_001_pathway_contradicted(subject: ConnectionInstance, context: RuleContext) -> Finding | None:
    connection_type = context.library.get_connection_type(subject.connection_type_id)
    element_type, _host_type = _element_and_host(subject, context)

    # Checks the element side only (the side being recovered) — see
    # module docstring: a symmetric host-side check is a possible future
    # extension, not built for Slice 1.
    if element_type.declared_recovery_pathway not in ("reuse_as_is", "remanufacture"):
        return None
    if connection_type.damage_to_self != "major":
        return None

    return _finding(
        context,
        subject.id,
        "connection_instance",
        {
            "element_type_id": element_type.id,
            "declared_recovery_pathway": element_type.declared_recovery_pathway,
            "connection_type_id": connection_type.id,
            "damage_to_self": connection_type.damage_to_self,
        },
        _data_quality(element_type.provenance),
    )


@register_rule("SEP-001")
def sep_001_material_separability(subject: Instance, context: RuleContext) -> Finding | None:
    element_type = context.library.get_element_type(subject.element_type_id)
    if element_type.decomposable or len(element_type.composition) <= 1:
        return None

    return _finding(
        context,
        subject.id,
        "instance",
        {
            "element_type_id": element_type.id,
            "materials": ", ".join(entry.material for entry in element_type.composition),
        },
        _data_quality(element_type.provenance),
    )


@register_rule("DFM-001")
def dfm_001_dfma_opposes_circularity(
    subject: ConnectionInstance, context: RuleContext
) -> Finding | None:
    connection_type = context.library.get_connection_type(subject.connection_type_id)
    element_type, host_type = _element_and_host(subject, context)
    threshold = context.rule.logic["service_life_differential_threshold_years"]
    differential = abs(host_type.service_life - element_type.service_life)

    # Same triggering condition as CON-001 (see module docstring): with no
    # substitution lookup in Slice 1, DFM-001 reports the connection's own
    # A1-A3/capital figures as the DfMA saving it is trading against
    # DRV-07's replacement burden, rather than a computed alternative.
    if is_reversible(connection_type) or differential <= threshold:
        return None

    capital_saving = connection_type.ghg_A1A3 + connection_type.ghg_A5
    return _finding(
        context,
        subject.id,
        "connection_instance",
        {
            "connection_type_id": connection_type.id,
            "connection_ghg_upfront": capital_saving,
            "connection_cost_install": connection_type.cost_install,
            "differential": differential,
        },
        _data_quality(),
    )
