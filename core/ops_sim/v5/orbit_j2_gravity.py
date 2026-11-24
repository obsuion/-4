"""Instantaneous static-axis gravity in the existing MODEL_INERTIAL frame.

The negative specific potential is
Phi = -mu/r + mu*J2*Rg**2/(2*r**3)*(3*z**2/r**2-1).
Acceleration is -grad(Phi), including the central term exactly once. The
unnormalized J2 coefficient and its gravity reference radius are explicit
physical parameters, independent of the frame's reference ellipsoid shape.
The symmetry axis is MODEL_INERTIAL +z; rotation metadata does not rotate it.

Products use binary mantissas/exponents rather than forming radius powers.
Every evaluated nonzero term must remain representable: overflow or rounding
of a nonzero term to zero raises ValueError. Subnormal nonzero results are
admitted with their ordinary absolute binary64 resolution. No universal
relative accuracy is claimed near cancellation or at subnormal scales.
Zero J2 bypasses all correction arithmetic. S008 records the convention and
the independently justified, scoped arithmetic checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import frexp, fsum, hypot, isfinite, ldexp

from .frames import CartesianPosition, _position
from .ids import ParameterId, SourceRecordId
from .orbit_config import (
    FrameDefinition, FrameKind, ReferenceEllipsoid, UniformRotationDefinition,
    _exact, _parameter,
)
from .parameters import ScalarParameter
from .provenance import ParameterProvenance, ProvenanceClass, ProvenanceStatus


def _text(value: object) -> None:
    """Preserve exact Unicode scalar text without invoking caller text hooks."""
    _exact(value, str, "scientific metadata text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("scientific metadata must contain Unicode scalar values") from error


def _parameter_text(value: object) -> None:
    # Preflight BEFORE A's owner reconstructs IDs or compares/hashes metadata.
    _exact(value, ScalarParameter, "parameter")
    p = value.provenance
    _exact(p, ParameterProvenance, "provenance")
    _exact(p.parameter_id, ParameterId, "parameter_id")
    _exact(p.classification, ProvenanceClass, "classification")
    _exact(p.status, ProvenanceStatus, "status")
    _text(p.parameter_id.value)
    _text(p.classification.value)
    _text(p.status.value)
    _text(p.units)
    _exact(p.source_ids, tuple, "source_ids")
    for source in p.source_ids:
        _exact(source, SourceRecordId, "source_id")
        _text(source.value)
    for optional in (p.rationale, p.derivation):
        if optional is not None:
            _text(optional)


def _frame_text(value: object) -> None:
    _exact(value, FrameDefinition, "frame")
    _exact(value.kind, FrameKind, "frame kind")
    _text(value.kind.value)
    _exact(value.ellipsoid, ReferenceEllipsoid, "ellipsoid")
    _text(value.ellipsoid.name)
    _exact(value.rotation, UniformRotationDefinition, "rotation")
    for parameter in (
        value.ellipsoid.equatorial_radius_m, value.ellipsoid.flattening,
        value.rotation.initial_phase_rad, value.rotation.angular_velocity_rad_per_s,
    ):
        _parameter_text(parameter)


@dataclass(frozen=True, slots=True)
class J2GravityModel:
    """Three separately sourced, default-free gravity parameters."""

    gravitational_parameter_m3_s2: ScalarParameter
    j2: ScalarParameter
    reference_radius_m: ScalarParameter

    __hash__ = None

    def __post_init__(self) -> None:
        parameters = (
            ("gravitational_parameter_m3_s2", "orbit.gravity.gravitational-parameter", "m^3/s^2"),
            ("j2", "orbit.gravity.j2", "1"),
            ("reference_radius_m", "orbit.gravity.reference-radius", "m"),
        )
        for name, identifier, units in parameters:
            original = getattr(self, name)
            _parameter_text(original)
            parameter = _parameter(original, identifier, units)
            _parameter_text(parameter)
            if name != "j2" and parameter.value <= 0:
                raise ValueError("gravitational parameter and gravity radius must be positive")
            object.__setattr__(self, name, parameter)


def _quotient_product(factors: tuple[float, ...], radius: float, power: int) -> float:
    """Bounded-factor product divided by r**power without forming that power."""
    if any(value == 0 for value in factors):
        return 0.0
    mantissa, exponent = 1.0, 0
    for value in factors:
        part, shift = frexp(value)
        mantissa *= part
        exponent += shift
    part, shift = frexp(radius)
    mantissa /= part**power
    exponent -= shift*power
    try:
        result = ldexp(mantissa, exponent)
    except OverflowError as error:
        raise ValueError("gravity term exceeds finite binary64 arithmetic") from error
    if not isfinite(result) or result == 0:
        raise ValueError("nonzero gravity term is outside binary64 representation")
    return result


def _sum_terms(first: float, second: float) -> float:
    try:
        result = fsum((first, second))
    except OverflowError as error:
        raise ValueError("gravity output exceeds finite binary64 arithmetic") from error
    if not isfinite(result):
        raise ValueError("gravity output must be finite")
    return result


def _gravity(model: J2GravityModel, position: CartesianPosition) -> tuple[float, float, float, float]:
    x, y, z = position.components_m
    radius = hypot(x, y, z)
    if radius == 0 or not isfinite(radius):
        raise ValueError("gravity requires a finite nonzero position norm")
    mu = model.gravitational_parameter_m3_s2.value
    j2 = model.j2.value
    central = tuple(_quotient_product((-mu, component), radius, 3)
                    for component in (x, y, z))
    potential = _quotient_product((-mu,), radius, 1)
    if j2 == 0:
        return (*central, potential)
    rg = model.reference_radius_m.value
    q = _quotient_product((z, z), radius, 2)
    correction = tuple(_quotient_product((1.5, mu, j2, rg, rg, component, 5*q-offset), radius, 5)
                       for component, offset in ((x, 1), (y, 1), (z, 3)))
    potential_correction = _quotient_product((0.5, mu, j2, rg, rg, 3*q-1), radius, 3)
    return (*(_sum_terms(a, b) for a, b in zip(central, correction)),
            _sum_terms(potential, potential_correction))


@dataclass(frozen=True, slots=True)
class J2GravityEvaluation:
    """Reconstructed source evidence and internally derived SI gravity values."""

    model: J2GravityModel
    position: CartesianPosition
    acceleration_x_m_per_s2: float = field(init=False)
    acceleration_y_m_per_s2: float = field(init=False)
    acceleration_z_m_per_s2: float = field(init=False)
    specific_potential_m2_per_s2: float = field(init=False)

    __hash__ = None

    def __post_init__(self) -> None:
        _exact(self.model, J2GravityModel, "model")
        model = J2GravityModel(self.model.gravitational_parameter_m3_s2,
                               self.model.j2, self.model.reference_radius_m)
        _exact(self.position, CartesianPosition, "position")
        _frame_text(self.position.frame)
        position = _position(self.position)
        _frame_text(position.frame)
        if position.frame.kind is not FrameKind.MODEL_INERTIAL:
            raise ValueError("gravity position must use MODEL_INERTIAL")
        values = _gravity(model, position)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "position", position)
        for name, value in zip((
            "acceleration_x_m_per_s2", "acceleration_y_m_per_s2",
            "acceleration_z_m_per_s2", "specific_potential_m2_per_s2",
        ), values):
            object.__setattr__(self, name, value)


def evaluate_j2_gravity(model: J2GravityModel, position: CartesianPosition) -> J2GravityEvaluation:
    return J2GravityEvaluation(model, position)


__all__ = ["J2GravityEvaluation", "J2GravityModel", "evaluate_j2_gravity"]
