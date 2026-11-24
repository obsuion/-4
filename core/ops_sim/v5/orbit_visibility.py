"""Instantaneous reference-solid occultation AND an explicit elevation mask.

No temporal search, propagation, service, attitude or persistent binding.
All inputs are reconstructed through C1/A/B2 validators. See D307/S008 for
the finite-segment derivation, numerical envelope and conditional allowances.
Fractions describe exact predicates on binary authoritative a/f and Cartesian
inputs, NOT exact geodesy, caller orbit accuracy or physical visibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from math import nextafter, pi

from .frames import CartesianState
from .orbit_binding import _parameter_text
from .orbit_config import _exact, _parameter
from .orbit_geometry import GroundPointDefinition, GroundPointGeometry, evaluate_ground_point_geometry
from .parameters import ScalarParameter


_U = Fraction(1, 2**53)


class GroundVisibilityStatus(str, Enum):
    VISIBLE = "VISIBLE"
    NOT_VISIBLE = "NOT_VISIBLE"
    BOUNDARY = "BOUNDARY"
    UNRESOLVED = "UNRESOLVED"


class LineOfSightStatus(str, Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"
    BOUNDARY = "BOUNDARY"
    UNRESOLVED = "UNRESOLVED"


class ElevationStatus(str, Enum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    BOUNDARY = "BOUNDARY"
    UNRESOLVED = "UNRESOLVED"


class LineOfSightReason(str, Enum):
    GROUND_INSIDE_REFERENCE_BODY = "GROUND_INSIDE_REFERENCE_BODY"
    SPACECRAFT_INSIDE_REFERENCE_BODY = "SPACECRAFT_INSIDE_REFERENCE_BODY"
    SURFACE_OUTWARD = "SURFACE_OUTWARD"
    SURFACE_ENTRY = "SURFACE_ENTRY"
    SURFACE_TANGENT = "SURFACE_TANGENT"
    SEGMENT_CLEAR = "SEGMENT_CLEAR"
    INTERIOR_PENETRATION = "INTERIOR_PENETRATION"
    INTERIOR_TANGENCY = "INTERIOR_TANGENCY"
    SPACECRAFT_SURFACE = "SPACECRAFT_SURFACE"
    NUMERICAL_UNCERTAINTY = "NUMERICAL_UNCERTAINTY"


class BodyLocation(str, Enum):
    INSIDE = "INSIDE"
    SURFACE = "SURFACE"
    OUTSIDE = "OUTSIDE"


class SegmentMinimumLocation(str, Enum):
    GROUND_ENDPOINT = "GROUND_ENDPOINT"
    SPACECRAFT_ENDPOINT = "SPACECRAFT_ENDPOINT"
    INTERIOR = "INTERIOR"


@dataclass(frozen=True, slots=True)
class GroundVisibilityPolicy:
    """Explicit threshold in radians; no operational default or station claim."""

    minimum_elevation_rad: ScalarParameter

    def __post_init__(self) -> None:
        original = self.minimum_elevation_rad
        parameter = _parameter(original, "orbit.visibility.minimum-elevation", "rad")
        _parameter_text(parameter)
        if not -pi/2 <= original.value <= pi/2 or not -pi/2 <= parameter.value <= pi/2:
            raise ValueError("minimum elevation must be in [-pi/2, pi/2]")
        object.__setattr__(self, "minimum_elevation_rad", parameter)


def _policy(value: object) -> GroundVisibilityPolicy:
    _exact(value, GroundVisibilityPolicy, "policy")
    return GroundVisibilityPolicy(value.minimum_elevation_rad)


def _dot(a, b):
    return sum((x*y for x, y in zip(a, b)), Fraction(0))


def _l1(vector):
    return sum(map(abs, vector), Fraction(0))


def _location(level):
    return BodyLocation.INSIDE if level < 0 else BodyLocation.OUTSIDE if level > 0 else BodyLocation.SURFACE


@dataclass(frozen=True, slots=True)
class _SegmentMinimum:
    """Exact dimensionless nominal arithmetic; private, already scaled inputs."""

    a: Fraction
    b: Fraction
    c: Fraction
    end_level: Fraction
    parameter: Fraction
    location: SegmentMinimumLocation
    level: Fraction
    closest_l1: Fraction


def _segment_minimum(p0, p1):
    # Inputs are exact rational x/a,y/a,z/[a*(1-f)]. F=A*s²+2B*s+C.
    d = tuple(y-x for x, y in zip(p0, p1))
    a, b, c = _dot(d, d), _dot(p0, d), _dot(p0, p0)-1
    if a <= 0:
        raise ValueError("scaled segment must be nonzero")
    if b >= 0:
        s, where = Fraction(0), SegmentMinimumLocation.GROUND_ENDPOINT
    elif b <= -a:
        s, where = Fraction(1), SegmentMinimumLocation.SPACECRAFT_ENDPOINT
    else:
        s, where = -b/a, SegmentMinimumLocation.INTERIOR
    closest = tuple(x+s*v for x, v in zip(p0, d))
    return _SegmentMinimum(a, b, c, _dot(p1, p1)-1, s, where,
                           _dot(closest, closest)-1, _l1(closest))


def _upward(value: Fraction) -> float:
    """Round a nonnegative allowance outward, including subnormal conversion."""
    result = float(value)
    return nextafter(result, float("inf")) if Fraction(result) < value else result


def _setup(geometry):
    p, state = geometry.point, geometry.spacecraft_state
    a, f, h = map(Fraction, (p.ellipsoid.equatorial_radius_m.value,
                             p.ellipsoid.flattening.value, p.ellipsoidal_height_m.value))
    r = tuple(map(Fraction, state.position.components_m))
    g = tuple(map(Fraction, geometry.ground_state.position.components_m))
    if not Fraction(1, 2**900) <= a <= 2**900 or f > Fraction(1, 2):
        raise ValueError("C2a requires 2^-900 <= a <= 2^900 m and flattening <= 1/2")
    if max(abs(h), *map(abs, r))/a > 2**40:
        raise ValueError("C2a height/spacecraft coordinate scale exceeds 2^40 times a")
    rotation = state.position.frame.rotation
    phase, rate, t = map(Fraction, (rotation.initial_phase_rad.value,
                                   rotation.angular_velocity_rad_per_s.value,
                                   state.position.instant.elapsed_seconds))
    exact_axis = (p.latitude_rad.value == p.longitude_rad.value == 0 and
                  phase == 0 and (rate == 0 or t == 0))
    phase_error = 8*_U*(abs(phase)+abs(rate*t)+1)
    # For f<=1/2 the geodetic denominator >=1/2. The 256u reserve covers
    # A's trig, ratio/hypot/N, normal-offset and rotation operations in L2,
    # including second-order products (see D307). It assumes <=2u absolute
    # sin/cos error. Phase reduction has its separate A accumulation budget.
    arithmetic = 256*_U*(1+abs(h)/a)
    position_error = arithmetic+(_l1(g)/a+arithmetic)*phase_error
    if exact_axis:
        # This is an identity of the geographic inputs, NOT a replacement for
        # C1's returned coordinate: the exact sum a+h need not be binary64.
        nominal = (a+h, Fraction(0), Fraction(0))
        c1_position_error = _l1(tuple(x-y for x, y in zip(g, nominal)))/a
        position_error, phase_error = Fraction(0), Fraction(0)
    else:
        nominal, c1_position_error = g, position_error
    axes = (a, a, a*(1-f))  # Never round b independently of authoritative a/f.
    p0, p1 = (tuple(x/axis for x, axis in zip(v, axes)) for v in (nominal, r))
    return a, h, p0, p1, position_error/(1-f), c1_position_error, phase_error, exact_axis


def _occultation(h, p0, p1, delta, segment):
    """Return status/reason and the selected signed predicate/allowance."""
    S, R = LineOfSightStatus, LineOfSightReason
    if h < 0:
        return S.BLOCKED, R.GROUND_INSIDE_REFERENCE_BODY, "ground_height_m", h, Fraction(0)
    if segment.end_level < 0:
        return S.BLOCKED, R.SPACECRAFT_INSIDE_REFERENCE_BODY, "spacecraft_level", segment.end_level, Fraction(0)
    if segment.end_level == 0:
        # Half derivative at s=1. Positive => penetration immediately before
        # arrival; negative => minimum at endpoint and exterior approach.
        derivative = _dot(p1, tuple(y-x for x, y in zip(p0, p1)))
        allowance = delta*_l1(p1)
        if derivative > allowance:
            status, reason = S.BLOCKED, R.INTERIOR_PENETRATION
        elif derivative < -allowance or derivative == allowance == 0:
            status, reason = S.BOUNDARY, R.SPACECRAFT_SURFACE
        else:
            status, reason = S.UNRESOLVED, R.NUMERICAL_UNCERTAINTY
        return status, reason, "spacecraft_half_derivative", derivative, allowance
    if h == 0:
        # Exact surface identity: true C=0 and B=p0^T Q p1-1. This avoids
        # declaring a rounded h=0 geographic point buried. Rz^T Q Rz=Q:
        # x²+y² is invariant, z unchanged, with equal equatorial semi-axes.
        departure = _dot(p0, p1)-1
        allowance = delta*_l1(p1)
        if departure > allowance:
            status, reason = S.CLEAR, R.SURFACE_OUTWARD
        elif departure < -allowance:
            status, reason = S.BLOCKED, R.SURFACE_ENTRY
        elif departure == allowance == 0:
            status, reason = S.BOUNDARY, R.SURFACE_TANGENT
        else:
            status, reason = S.UNRESOLVED, R.NUMERICAL_UNCERTAINTY
        return status, reason, "surface_departure", departure, allowance
    # Segment distance is 1-Lipschitz in endpoint displacement. Hence the
    # minimum squared norm varies by <=2*r_min*delta+delta². L1 >= L2
    # avoids a rounded square root and is independent of segment length.
    allowance = 2*segment.closest_l1*delta+delta*delta
    if segment.level > allowance:
        status, reason = S.CLEAR, R.SEGMENT_CLEAR
    elif segment.level < -allowance:
        status, reason = S.BLOCKED, R.INTERIOR_PENETRATION
    elif segment.level == allowance == 0:
        status, reason = S.BOUNDARY, R.INTERIOR_TANGENCY
    else:
        status, reason = S.UNRESOLVED, R.NUMERICAL_UNCERTAINTY
    return status, reason, "minimum_level", segment.level, allowance


def _elevation(geometry, policy, a, h, c1_error, phase_error, exact_axis):
    threshold = policy.minimum_elevation_rad.value
    margin = geometry.elevation_rad-threshold
    rho = Fraction(geometry.slant_range_m)/a
    r = tuple(Fraction(x)/a for x in geometry.spacecraft_state.position.components_m)
    g = tuple(Fraction(x)/a for x in geometry.ground_state.position.components_m)
    # Component subtraction/hypot reserve; grows when subtracting large nearby
    # positions. Exact Fraction operations here add no hidden float tolerance.
    d_error = c1_error+8*_U*(rho+_l1(r)+_l1(g))
    if rho <= d_error:
        allowance = pi
    else:
        ray_error = 2*d_error/(rho-d_error)+32*_U
        projection_error = ray_error+phase_error+64*_U+8*_U
        # Three ENU projections: <=sqrt(3)*epsilon norm perturbation. hypot is
        # 1-Lipschitz, and atan2 gradient is 1/radius. For epsilon<1/8,
        # sqrt(3)*epsilon/(1-sqrt(3)*epsilon)<4*epsilon.
        allowance = (_upward(4*projection_error+8*_U*(1+abs(Fraction(threshold))))
                     if projection_error < Fraction(1, 8) else pi)
    # Only a proven zero-angle identity is a policy boundary. In particular,
    # copying a rounded atan2 result into the mask is not an equality proof.
    equality = exact_axis and threshold == 0 and r[0] == 1+h/a
    if equality:
        status = ElevationStatus.BOUNDARY
    elif margin > allowance:
        status = ElevationStatus.ABOVE
    elif margin < -allowance:
        status = ElevationStatus.BELOW
    else:
        status = ElevationStatus.UNRESOLVED
    return status, margin, allowance


def _combine(los, elevation):
    if los is LineOfSightStatus.BLOCKED or elevation is ElevationStatus.BELOW:
        return GroundVisibilityStatus.NOT_VISIBLE
    if los is LineOfSightStatus.CLEAR and elevation is ElevationStatus.ABOVE:
        return GroundVisibilityStatus.VISIBLE
    if los is LineOfSightStatus.UNRESOLVED or elevation is ElevationStatus.UNRESOLVED:
        return GroundVisibilityStatus.UNRESOLVED
    return GroundVisibilityStatus.BOUNDARY


@dataclass(frozen=True, slots=True)
class GroundVisibilityResult:
    """Complete immutable evidence at one instant; no boolean/window coercion.

    Occultation levels, coefficients, allowances and segment parameters are
    exact dimensionless Fractions, except the ground_height_m predicate (m).
    Elevation margin/allowance are binary64 radians. Locations
    and minimum refer to the nominal segment; ground_location uses actual h.
    The predicate name selects the interpretation of its signed diagnostic.
    C1 geometry retains the exact instant and both complete frames.
    """

    point: GroundPointDefinition
    spacecraft_state: CartesianState
    policy: GroundVisibilityPolicy
    geometry: GroundPointGeometry = field(init=False)
    line_of_sight_status: LineOfSightStatus = field(init=False)
    line_of_sight_reason: LineOfSightReason = field(init=False)
    elevation_status: ElevationStatus = field(init=False)
    elevation_margin_rad: float = field(init=False)
    elevation_allowance_rad: float = field(init=False)
    status: GroundVisibilityStatus = field(init=False)
    ground_location: BodyLocation = field(init=False)
    spacecraft_location: BodyLocation = field(init=False)
    ground_level: Fraction = field(init=False)
    spacecraft_level: Fraction = field(init=False)
    quadratic_a: Fraction = field(init=False)
    quadratic_b: Fraction = field(init=False)
    minimum_parameter: Fraction = field(init=False)
    minimum_location: SegmentMinimumLocation = field(init=False)
    minimum_level: Fraction = field(init=False)
    ground_position_allowance_scaled: Fraction = field(init=False)
    exact_axis_definition: bool = field(init=False)
    occultation_predicate: str = field(init=False)
    occultation_signed_value: Fraction = field(init=False)
    occultation_allowance: Fraction = field(init=False)

    def __post_init__(self) -> None:
        policy = _policy(self.policy)
        geometry = evaluate_ground_point_geometry(self.point, self.spacecraft_state)
        a, h, p0, p1, delta, c1_error, phase_error, exact_axis = _setup(geometry)
        segment = _segment_minimum(p0, p1)
        los, reason, predicate, signed, allowance = _occultation(h, p0, p1, delta, segment)
        elevation, margin, angle_allowance = _elevation(geometry, policy, a, h, c1_error, phase_error, exact_axis)
        values = {
            "point": geometry.point, "spacecraft_state": geometry.spacecraft_state,
            "policy": policy, "geometry": geometry, "line_of_sight_status": los,
            "line_of_sight_reason": reason, "elevation_status": elevation,
            "elevation_margin_rad": margin, "elevation_allowance_rad": angle_allowance,
            "status": _combine(los, elevation), "ground_location": _location(h),
            "spacecraft_location": _location(segment.end_level), "ground_level": segment.c,
            "spacecraft_level": segment.end_level, "quadratic_a": segment.a,
            "quadratic_b": segment.b, "minimum_parameter": segment.parameter,
            "minimum_location": segment.location, "minimum_level": segment.level,
            "ground_position_allowance_scaled": delta, "exact_axis_definition": exact_axis,
            "occultation_predicate": predicate, "occultation_signed_value": signed,
            "occultation_allowance": allowance,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)


def evaluate_ground_visibility(
    point: GroundPointDefinition, spacecraft_state: CartesianState, policy: GroundVisibilityPolicy,
) -> GroundVisibilityResult:
    """Evaluate the supplied simultaneous geometry only; no hidden orbit query."""
    return GroundVisibilityResult(point, spacecraft_state, policy)


__all__ = ["GroundVisibilityPolicy", "GroundVisibilityResult", "GroundVisibilityStatus",
           "LineOfSightStatus", "LineOfSightReason", "ElevationStatus", "BodyLocation",
           "SegmentMinimumLocation", "evaluate_ground_visibility"]
