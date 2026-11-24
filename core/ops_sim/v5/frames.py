"""Pure timestamped geometry in two explicitly defined model frames.

Active Rz(theta) = ((c,-s,0),(s,c,0),(0,0,1)). The derivative is
Rdot*rF = Omega cross rI: vI=R*vF+Omega cross rI, while the inverse is
vF=R.T*(vI-Omega cross rI). A velocity alone is never transformed.
Directions receive rotation only, with no automatic unit normalization.

One phase evaluator uses remainder(theta0+omega*t, tau). |omega*t| <= 2**20
rad bounds accumulated binary64 phase/reduction error, not model fidelity or
a mission horizon. With u=2**-53 a conservative tested phase budget is
8*u*(abs(theta0)+abs(omega*t)+1) rad, allowing multiplication, addition and
binary-tau reduction. Component budgets must additionally scale with vector
size and operation count. No universal metre bound is claimed for all shapes.
See S008 and the independent high-precision tests for scoped numerical bounds.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, isfinite, remainder, sin, tau

from .orbit_config import (
    FrameDefinition, FrameKind, GeodeticLocation, GeometryInstant,
    UniformRotationDefinition, _exact, _frame, _instant, _real, _rotation,
)


def _vector(value: object, name: str) -> tuple[float, float, float]:
    _exact(value, tuple, name)
    if len(value) != 3:
        raise ValueError(f"{name} must have exactly three components")
    return tuple(_real(name, x) for x in value)


def _evidence(frame: object, instant: object) -> tuple[FrameDefinition, GeometryInstant]:
    frame, instant = _frame(frame), _instant(instant)
    if frame.rotation.epoch != instant.epoch:
        raise ValueError("instant epoch differs from frame epoch")
    return frame, instant


@dataclass(frozen=True, slots=True)
class CartesianPosition:
    frame: FrameDefinition
    instant: GeometryInstant
    components_m: tuple[float, float, float]

    def __post_init__(self) -> None:
        frame, instant = _evidence(self.frame, self.instant)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "instant", instant)
        object.__setattr__(self, "components_m", _vector(self.components_m, "position"))


@dataclass(frozen=True, slots=True)
class CartesianVelocity:
    """Derivative of position components in this frame; transform only in a state."""

    frame: FrameDefinition
    instant: GeometryInstant
    components_m_per_s: tuple[float, float, float]

    def __post_init__(self) -> None:
        frame, instant = _evidence(self.frame, self.instant)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "instant", instant)
        object.__setattr__(self, "components_m_per_s", _vector(self.components_m_per_s, "velocity"))


@dataclass(frozen=True, slots=True)
class CartesianDirection:
    """Nonzero dimensionless vector; its magnitude is preserved, not normalized."""

    frame: FrameDefinition
    instant: GeometryInstant
    components: tuple[float, float, float]

    def __post_init__(self) -> None:
        frame, instant = _evidence(self.frame, self.instant)
        components = _vector(self.components, "direction")
        if not any(components):
            raise ValueError("direction must be nonzero")
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "instant", instant)
        object.__setattr__(self, "components", components)


def _position(value: object) -> CartesianPosition:
    _exact(value, CartesianPosition, "position")
    return CartesianPosition(value.frame, value.instant, value.components_m)


def _velocity(value: object) -> CartesianVelocity:
    _exact(value, CartesianVelocity, "velocity")
    return CartesianVelocity(value.frame, value.instant, value.components_m_per_s)


@dataclass(frozen=True, slots=True)
class CartesianState:
    """Corresponding position and derivative, with identical frame and instant."""

    position: CartesianPosition
    velocity: CartesianVelocity

    def __post_init__(self) -> None:
        position, velocity = _position(self.position), _velocity(self.velocity)
        if position.frame != velocity.frame or position.instant != velocity.instant:
            raise ValueError("state position/velocity frame and instant must match")
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "velocity", velocity)


def rotation_angle(rotation: UniformRotationDefinition, instant: GeometryInstant) -> float:
    """Return active angle reduced to [-pi, pi], retaining fractional time."""
    rotation, instant = _rotation(rotation), _instant(instant)
    if rotation.epoch != instant.epoch:
        raise ValueError("instant epoch differs from rotation epoch")
    product = rotation.angular_velocity_rad_per_s.value * instant.elapsed_seconds
    if not isfinite(product) or abs(product) > 2**20:
        raise ValueError("rotation exceeds 2**20 rad accumulated-phase envelope")
    return remainder(rotation.initial_phase_rad.value + product, tau)


def _transform_setup(source: FrameDefinition, target: FrameDefinition, instant: GeometryInstant):
    source, instant = _evidence(source, instant)
    target = _frame(target)
    if source.kind is target.kind:
        raise ValueError("transform requires opposite model frame kinds")
    if source.ellipsoid != target.ellipsoid or source.rotation != target.rotation:
        raise ValueError("incompatible complete frame definitions")
    angle = rotation_angle(source.rotation, instant)
    if source.kind is FrameKind.MODEL_INERTIAL:
        angle = -angle
    return target, cos(angle), sin(angle)


def _rotate(vector: tuple[float, float, float], c: float, s: float):
    x, y, z = vector
    return _vector((c*x - s*y, s*x + c*y, z), "rotated components")


def transform_position(position: CartesianPosition, target_frame: FrameDefinition) -> CartesianPosition:
    position = _position(position)
    target, c, s = _transform_setup(position.frame, target_frame, position.instant)
    return CartesianPosition(target, position.instant, _rotate(position.components_m, c, s))


def transform_direction(direction: CartesianDirection, target_frame: FrameDefinition) -> CartesianDirection:
    _exact(direction, CartesianDirection, "direction")
    direction = CartesianDirection(direction.frame, direction.instant, direction.components)
    target, c, s = _transform_setup(direction.frame, target_frame, direction.instant)
    return CartesianDirection(target, direction.instant, _rotate(direction.components, c, s))


def transform_state(state: CartesianState, target_frame: FrameDefinition) -> CartesianState:
    _exact(state, CartesianState, "state")
    state = CartesianState(state.position, state.velocity)
    position, velocity = state.position, state.velocity
    target, c, s = _transform_setup(position.frame, target_frame, position.instant)
    omega = position.frame.rotation.angular_velocity_rad_per_s.value
    transformed_position = _rotate(position.components_m, c, s)
    if position.frame.kind is FrameKind.EARTH_FIXED:
        vx, vy, vz = _rotate(velocity.components_m_per_s, c, s)
        x, y, _ = transformed_position
        transformed_velocity = (vx - omega*y, vy + omega*x, vz)
    else:
        x, y, _ = position.components_m
        vx, vy, vz = velocity.components_m_per_s
        compensated = _vector((vx + omega*y, vy - omega*x, vz), "compensated velocity")
        transformed_velocity = _rotate(compensated, c, s)
    return CartesianState(
        CartesianPosition(target, position.instant, transformed_position),
        CartesianVelocity(target, position.instant, transformed_velocity),
    )


def _geodetic_setup(location: GeodeticLocation, frame: FrameDefinition, instant: GeometryInstant):
    _exact(location, GeodeticLocation, "location")
    location = GeodeticLocation(location.ellipsoid, location.latitude_rad,
                                location.longitude_rad, location.ellipsoidal_height_m)
    frame, instant = _evidence(frame, instant)
    if frame.kind is not FrameKind.EARTH_FIXED:
        raise ValueError("geodetic conversion requires EARTH_FIXED frame")
    if location.ellipsoid != frame.ellipsoid:
        raise ValueError("geographic and frame ellipsoids differ")
    return location, frame, instant


def geodetic_position(location: GeodeticLocation, frame: FrameDefinition, instant: GeometryInstant) -> CartesianPosition:
    """Return ellipsoid normal-offset position in metres; no inverse geodesy.

    q=(1-f)**2 and hypot(cos(phi),(1-f)*sin(phi)) evaluate 1-e2 stably.
    They are algebraically equivalent to N=a/sqrt(1-e2*sin(phi)**2).
    """
    location, frame, instant = _geodetic_setup(location, frame, instant)
    ratio = 1.0 - location.ellipsoid.flattening.value
    cp, sp = cos(location.latitude_rad), sin(location.latitude_rad)
    n = location.ellipsoid.equatorial_radius_m.value / hypot(cp, ratio*sp)
    h = location.ellipsoidal_height_m
    horizontal = _real("N + h", n + h) * cp
    xyz = (horizontal*cos(location.longitude_rad), horizontal*sin(location.longitude_rad),
           _real("N*q + h", n*(ratio*ratio) + h)*sp)
    return CartesianPosition(frame, instant, xyz)


def geodetic_normal(location: GeodeticLocation, frame: FrameDefinition, instant: GeometryInstant) -> CartesianDirection:
    """Outward reference-surface normal, generally distinct from radial position."""
    location, frame, instant = _geodetic_setup(location, frame, instant)
    cp = cos(location.latitude_rad)
    return CartesianDirection(frame, instant, (
        cp*cos(location.longitude_rad), cp*sin(location.longitude_rad), sin(location.latitude_rad),
    ))


__all__ = [
    "CartesianPosition", "CartesianVelocity", "CartesianDirection", "CartesianState",
    "rotation_angle", "transform_position", "transform_direction", "transform_state",
    "geodetic_position", "geodetic_normal",
]
