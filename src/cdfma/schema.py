"""Typed data model for the library layer (facts).

Scope note (Slice 1, see CLAUDE.md §2): only the types needed by
``library.py`` are defined here so far — ``DataQuality``, ``Interval``,
``ElementType``, ``ConnectionType`` and ``ProjectParameters``. ``Instance``,
``ConnectionInstance``, ``Finding``, ``Gap`` and ``TradeOff`` belong to the
graph, rules, engine and report modules respectively and will be added here
when those modules are built — adding them now would be building ahead of
scope.

Everything in this module is a fact: no derived values, no judgements, no
thresholds. Models are frozen (immutable) and reject unknown fields, so a
loaded object is exactly what was declared in YAML — nothing silently
defaulted, nothing added later by mistake (see CLAUDE.md architecture
invariant 6: derived values are never stored on library objects).

Out of scope for Slice 1 (CLAUDE.md §2) and deliberately absent from these
models: interface records, interface archetypes, interface signatures,
position conventions, and any geometry beyond G0/G1 (envelope, mass,
orientation, shape class). A ``mates[]``-style field on ``ConnectionType``
that references interface roles is likewise omitted, since it only has
meaning once interface matching (§5.2, out of scope) exists.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Ids are lowercase snake_case and stable (CLAUDE.md §5).
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_id(value: str) -> str:
    if not _ID_PATTERN.match(value):
        raise ValueError(
            f"id {value!r} is not lowercase snake_case (must match {_ID_PATTERN.pattern!r})"
        )
    return value


class _Fact(BaseModel):
    """Base for all library models: frozen, no stray fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Interval(_Fact):
    """A closed interval [low, high]. See CLAUDE.md §5: impact and cost
    quantities are intervals, not floats, once arithmetic is done on them.

    This type is the shared representation for that later arithmetic
    (normalise.py and onward). Library figures themselves are stored as
    plain declared-unit numbers alongside a ``DataQuality`` record; nothing
    in this Slice constructs an ``Interval`` yet, since declared-unit
    resolution and uncertainty banding are normalise.py's job (§5.4), not
    the library's.
    """

    low: float
    high: float

    @model_validator(mode="after")
    def _low_le_high(self) -> Interval:
        if self.low > self.high:
            raise ValueError(f"Interval low ({self.low}) exceeds high ({self.high})")
        return self


class DataQuality(_Fact):
    """Attached to every GHG and cost figure (or block of figures).
    No bare numbers — a figure loaded without one is a validation error
    (CLAUDE.md §5 architecture invariant 7).
    """

    source: str = Field(min_length=1)
    data_type: Literal["product_specific_epd", "industry_average", "generic_database", "estimate"]
    vintage: int = Field(ge=1900, le=2100)
    geography: str = Field(min_length=1)
    # "± % or range" (spec §2.7). The spec does not define a machine format
    # for this, and normalise.py's interval arithmetic (§5.4) is not part of
    # this Slice, so it is kept as a required free-text band rather than a
    # parsed number. See docs/open-questions.md.
    uncertainty: str = Field(min_length=1)
    basis_note: str = ""


class CompositionEntry(_Fact):
    """One material fraction within an element type's composition."""

    material: str = Field(min_length=1)
    mass_fraction: float = Field(gt=0, le=1)


class Envelope(_Fact):
    """Oriented bounding box, in mm (G0)."""

    length: float = Field(gt=0)
    width: float = Field(gt=0)
    thickness: float = Field(gt=0)


class EmbodiedGHG(_Fact):
    """One record per module, never a single number (spec §2.1)."""

    declared_unit: Literal["per_element", "per_m2", "per_m", "per_kg"]
    ghg_A1A3: float
    ghg_A4: float | None = None
    ghg_A5: float | None = None
    ghg_C: float
    # Reported and stored separately; never summed into any other figure
    # (CLAUDE.md architecture invariant 4).
    ghg_D: float
    biogenic_carbon: float | None = None
    ghg_data: DataQuality


class ElementCost(_Fact):
    """Three figures — the circular argument lives in the second and third
    (spec §2.1)."""

    currency: str = Field(min_length=1)
    price_date: str = Field(min_length=1)
    cost_supply: float
    cost_install: float
    cost_removal: float
    residual_value: float
    cost_data: DataQuality


class ElementType(_Fact):
    """A fact about what an element is (spec §2.1), at G0/G1 geometric
    definition (CLAUDE.md §2). No interfaces[] — out of scope for Slice 1.
    """

    id: str
    name: str = Field(min_length=1)
    layer: Literal["skin", "structure", "services", "space_plan", "site"]
    tier: Literal["material", "component", "product_assembly", "element"]

    service_life: int = Field(gt=0)
    service_life_basis: Literal["warranty", "standard", "observed", "assumed"]
    composition: list[CompositionEntry] = Field(min_length=1)
    decomposable: bool
    declared_recovery_pathway: Literal["reuse_as_is", "remanufacture", "recycle", "none"]
    recovery_preconditions: list[str] = Field(default_factory=list)
    provenance: Literal["archetype", "product_entry"]

    # Geometry — G0 (envelope, mass, orientation, stackability) and G1
    # (shape class only; interfaces excluded, see module docstring).
    shape_class: Literal["planar", "linear", "point_like", "volumetric", "irregular"]
    envelope: Envelope
    envelope_fill_ratio: float = Field(gt=0, le=1)
    mass: float = Field(gt=0)
    coordination_module: float | None = Field(default=None, gt=0)
    orientation_constraint: Literal["none", "keep_flat", "keep_vertical"]
    stackable: bool
    # Optional rather than required: the spec's own worked example (§2.1
    # appendix) never states it for the cladding panel fixture. Rather than
    # invent a fact the source material doesn't give, an absent value is
    # represented honestly as None. See docs/open-questions.md.
    nestable: bool | None = None
    geometry_provenance: Literal["archetype", "product_entry", "measured"]
    g_level: Literal["G0", "G1"]

    embodied_ghg: EmbodiedGHG
    cost: ElementCost

    @field_validator("id")
    @classmethod
    def _id_format(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _composition_sums_to_one(self) -> ElementType:
        total = sum(entry.mass_fraction for entry in self.composition)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"element type {self.id!r}: composition mass fractions sum to "
                f"{total}, expected 1.0"
            )
        return self


class ConnectionType(_Fact):
    """A fact about how two elements are joined (spec §2.4). ``mates[]`` is
    omitted — it references interface roles and geometry types, which are
    out of scope for Slice 1 (see module docstring).
    """

    id: str
    name: str = Field(min_length=1)
    removal_method: str = Field(min_length=1)
    damage_to_self: Literal["none", "minor", "major"]
    damage_to_host: Literal["none", "minor", "major"]
    re_installable: bool
    access_requirement: str = ""
    tolerance_absorbed: float | None = Field(default=None, ge=0)
    reuse_cycles: int = Field(ge=0)

    ghg_A1A3: float
    ghg_A5: float
    # Not itemised in the spec's §2.4 table, but required by CLAUDE.md's
    # blanket invariant that no GHG or cost figure enters the library
    # without a DataQuality record (§5, architecture invariant 7). See
    # docs/open-questions.md.
    ghg_data: DataQuality

    cost_install: float
    cost_removal: float
    cost_data: DataQuality

    @field_validator("id")
    @classmethod
    def _id_format(cls, value: str) -> str:
        return _validate_id(value)


class ProjectParameters(_Fact):
    """Facts about the assessment, not preferences (spec §2.8). Declared
    once per project and reported on every output.
    """

    study_period: int = Field(gt=0)
    discount_rate: float = Field(ge=0, le=1)
    sensitivity_rates: list[float] = Field(default_factory=list)
    currency: str = Field(min_length=1)
    price_date: str = Field(min_length=1)
    transport_distance: float | None = Field(default=None, ge=0)
    grid_assumption: Literal["static"] = "static"

    @field_validator("sensitivity_rates")
    @classmethod
    def _rates_in_range(cls, value: list[float]) -> list[float]:
        for rate in value:
            if not (0 <= rate <= 1):
                raise ValueError(f"sensitivity rate {rate} out of range [0, 1]")
        return value
