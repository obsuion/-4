"""Bounded temporal model visibility, composed from B2, B1 and C2a.

The run-zero grid seeds a breadth-first search; samples never certify cells.
Strict whole-cell bounds certify a conjunction, otherwise uncertainty remains.
All times are run-relative TT seconds; intervals are [start,end). No context,
engine, persistence, serviceability or physical event-time accuracy is implied.

Numerical policy: exact rational invariant/variation arithmetic, outward
binary64 allowances, and the reviewed B1 working position-error budget. The
latter and C2a's geodesy allowances assume ordinary binary64/libm accuracy;
this is not formal interval arithmetic or an ephemeris error certificate.
See D308 and S008 for the derivation, conditioning domain and exclusions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from math import asin, inf, isfinite, ldexp, nextafter, pi, sqrt

from .context import SimulationInputs, _validate_inputs
from .frames import rotation_angle
from .orbit import _reduce_time, _scales, evaluate_two_body_state
from .orbit_binding import CoastOrbitInputs, _validated_coast
from .orbit_config import GeometryInstant, _exact, _real
from .orbit_geometry import GroundPointDefinition, _point
from .orbit_visibility import (
    GroundVisibilityPolicy, GroundVisibilityResult, _policy, _setup,
    evaluate_ground_visibility,
)


_U = Fraction(1, 2**53)
_PI_UP = Fraction(nextafter(pi, inf))


class TemporalVisibilityStatus(str, Enum):
    VISIBLE = "VISIBLE"
    NOT_VISIBLE = "NOT_VISIBLE"
    UNRESOLVED = "UNRESOLVED"


class TemporalUnresolvedReason(str, Enum):
    BOUNDARY_TOLERANCE = "BOUNDARY_TOLERANCE"
    EVALUATION_LIMIT = "EVALUATION_LIMIT"
    TIME_RESOLUTION = "TIME_RESOLUTION"


@dataclass(frozen=True, slots=True)
class GroundVisibilitySearchConfig:
    """Unresolved-cell width target (s), and expensive representative budget."""

    boundary_tolerance_seconds: float
    max_evaluations: int

    def __post_init__(self) -> None:
        value = _real("boundary_tolerance_seconds", self.boundary_tolerance_seconds)
        if self.boundary_tolerance_seconds <= 0 or value <= 0:
            raise ValueError("boundary tolerance must be strictly positive")
        _exact(self.max_evaluations, int, "max_evaluations")
        if self.max_evaluations <= 0:
            raise ValueError("max_evaluations must be positive")
        object.__setattr__(self, "boundary_tolerance_seconds", value)


def _interval(start, end):
    lo, hi = _real("start_seconds", start), _real("end_seconds", end)
    if not 0 <= start < end or not 0 <= lo < hi:
        raise ValueError("interval must have nonnegative start and positive duration")
    return lo, hi


@dataclass(frozen=True, slots=True)
class TemporalVisibilityCell:
    """One final cell. Allowances include temporal AND numerical anchor reserves.

    LOS allowance is dimensionless (zero for the authoritative h<0 branch);
    elevation allowance is radians. Add the applicable C2a instantaneous
    allowance as well. None means no representative was evaluated. A cell
    is evidence from a search, not an independently authorizing operation.
    """

    start_seconds: float
    end_seconds: float
    status: TemporalVisibilityStatus
    representative_seconds: float | None
    representative: GroundVisibilityResult | None
    line_of_sight_temporal_allowance: float | None
    elevation_temporal_allowance_rad: float | None
    unresolved_reason: TemporalUnresolvedReason | None

    def __post_init__(self) -> None:
        lo, hi = _interval(self.start_seconds, self.end_seconds)
        _exact(self.status, TemporalVisibilityStatus, "status")
        if self.status not in tuple(TemporalVisibilityStatus):
            raise ValueError("unknown temporal status")
        if self.status is TemporalVisibilityStatus.UNRESOLVED:
            _exact(self.unresolved_reason, TemporalUnresolvedReason, "unresolved_reason")
            if self.unresolved_reason not in tuple(TemporalUnresolvedReason):
                raise ValueError("unknown unresolved reason")
        elif self.unresolved_reason is not None:
            raise ValueError("resolved cell cannot carry an unresolved reason")
        if self.representative is None:
            if self.status is not TemporalVisibilityStatus.UNRESOLVED or any(x is not None for x in (
                self.representative_seconds, self.line_of_sight_temporal_allowance,
                self.elevation_temporal_allowance_rad,
            )):
                raise ValueError("unevaluated cell must retain uncertainty and no numerical evidence")
        else:
            _exact(self.representative, GroundVisibilityResult, "representative")
            t = _real("representative_seconds", self.representative_seconds)
            if not lo < t < hi or t != self.representative.spacecraft_state.position.instant.elapsed_seconds:
                raise ValueError("representative instant must be strictly inside its cell")
            for name in ("line_of_sight_temporal_allowance", "elevation_temporal_allowance_rad"):
                value = _real(name, getattr(self, name))
                if value < 0:
                    raise ValueError("allowances must be nonnegative")
                object.__setattr__(self, name, value)
            object.__setattr__(self, "representative_seconds", t)
        object.__setattr__(self, "start_seconds", lo)
        object.__setattr__(self, "end_seconds", hi)


@dataclass(frozen=True, slots=True)
class GroundVisibilityWindow:
    """Union of directly adjacent certified cells; no estimated event roots."""

    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        lo, hi = _interval(self.start_seconds, self.end_seconds)
        object.__setattr__(self, "start_seconds", lo)
        object.__setattr__(self, "end_seconds", hi)


def _up(value: Fraction) -> float:
    if value < 0:
        raise ValueError("negative enclosure")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError("unsupported enclosure arithmetic") from error
    if not isfinite(result):
        raise ValueError("nonfinite enclosure")
    if Fraction(result) < value:
        result = nextafter(result, inf)
    if not isfinite(result):
        raise ValueError("nonfinite outward enclosure")
    return result


def _sqrt_up(value: Fraction) -> Fraction:
    """Scale before sqrt, then verify the enclosure against the exact square."""
    if value < 0:
        raise ValueError("negative squared invariant")
    if value == 0:
        return Fraction(0)
    exponent = (value.numerator.bit_length()-value.denominator.bit_length())//2
    scale = Fraction(2)**exponent
    try:
        candidate = ldexp(sqrt(float(value/(scale*scale))), exponent)
    except OverflowError as error:
        raise ValueError("unsupported square-root enclosure") from error
    for _ in range(4):
        if not isfinite(candidate):
            break
        if Fraction(candidate)**2 >= value:
            return Fraction(candidate)
        candidate = nextafter(candidate, inf)
    raise ValueError("unsupported square-root enclosure")


def _dot(a, b):
    return sum((x*y for x, y in zip(a, b)), Fraction(0))


@dataclass(frozen=True, slots=True)
class _Envelope:
    radius_s: Fraction
    rate_s: Fraction
    radius_g: Fraction
    rate_g: Fraction
    relative_speed: Fraction
    omega: Fraction
    polar_axis: Fraction
    position_error: Fraction


def _envelope(inputs, point, start, end):
    coast = _validated_coast(inputs.coast_orbit)
    trajectory, solver = coast.trajectory, coast.solver_config
    state = trajectory.initial_state
    mu = Fraction(trajectory.gravitational_parameter_m3_s2.value)
    # B1 owns admission, including endpoint span/revolution limits. No solves.
    scales = _scales(state, float(mu))
    for endpoint in (start, end):
        _reduce_time(state.position.instant, endpoint, scales)
        rotation_angle(state.position.frame.rotation, endpoint)
    r = tuple(map(Fraction, state.position.components_m))
    v = tuple(map(Fraction, state.velocity.components_m_per_s))
    radius_hi, speed_hi = _sqrt_up(_dot(r, r)), _sqrt_up(_dot(v, v))
    angular = (r[1]*v[2]-r[2]*v[1], r[2]*v[0]-r[0]*v[2], r[0]*v[1]-r[1]*v[0])
    h2 = _dot(angular, angular)
    alpha_lo = 2/radius_hi-_dot(v, v)/mu
    if alpha_lo <= 0 or h2 <= 0:
        raise ValueError("unsupported exact invariant enclosure")
    semi_hi = 1/alpha_lo
    eccentricity_hi = _sqrt_up(max(Fraction(0), 1-h2/(mu*semi_hi)))
    if eccentricity_hi >= 1:
        raise ValueError("unsupported eccentricity enclosure")
    peri_lo = h2/(mu*(1+eccentricity_hi))
    apo_hi = semi_hi*(1+eccentricity_hi)
    vmax = _sqrt_up(mu*(1+eccentricity_hi)/peri_lo)
    condition = 1/(1-eccentricity_hi)
    time_hi = _sqrt_up(semi_hi**3/mu)
    eta = Fraction(solver.time_tolerance_seconds)
    reconstruction = 256*_U*condition*(semi_hi+vmax*time_hi)
    if speed_hi*eta/peri_lo > Fraction(1, 2**10) or reconstruction >= (peri_lo-speed_hi*eta)/2:
        raise ValueError("B1 working position-error budget outside supported conditioning")
    span = max(abs(Fraction(t.elapsed_seconds)-Fraction(state.position.instant.elapsed_seconds))
               for t in (start, end))
    # Corrected residual-to-position term includes initial speed, because B1's
    # f/g reconstruction retains requested time. 2u*P encloses remainder
    # conversion; 64u*k*span separately covers the reviewed phase policy.
    position_error = ((vmax+speed_hi)*eta
                      + vmax*(64*_U*condition*span+2*_U*Fraction(scales.period_seconds))
                      + reconstruction)
    a = Fraction(point.ellipsoid.equatorial_radius_m.value)
    f = Fraction(point.ellipsoid.flattening.value)
    height = Fraction(point.ellipsoidal_height_m.value)
    if not Fraction(1, 2**900) <= a <= 2**900 or f > Fraction(1, 2):
        raise ValueError("C2a ellipsoid conditioning is unsupported")
    if max(abs(height), apo_hi+position_error)/a > 2**40:
        raise ValueError("global C2a coordinate scale is unsupported")
    b = a*(1-f)
    omega = abs(Fraction(state.position.frame.rotation.angular_velocity_rad_per_s.value))
    rs, ls, rg = apo_hi/b, vmax/b, 1+abs(height)/b
    envelope = _Envelope(rs, ls, rg, omega*rg, vmax+omega*a*rg,
                         omega, b, position_error)
    for value in (peri_lo, eccentricity_hi, semi_hi, apo_hi, vmax, time_hi,
                  rs, ls, rg, envelope.rate_g, envelope.relative_speed, position_error):
        _up(value)  # Explicitly reject unsupported/nonfinite derived outputs.
    return envelope


def _sign(value, allowance):
    return 1 if value > allowance else -1 if value < -allowance else 0


def _classify(representative, envelope, reach):
    """Strict component tests with rational time and arithmetic reserves."""
    e = envelope
    a, height, p0, p1, delta, c1_error, _, _ = _setup(representative.geometry)
    anchor = e.position_error/e.polar_axis
    ds = e.rate_s*reach+anchor
    endpoint_time = 2*e.radius_s*ds+ds*ds
    endpoint = _sign(representative.spacecraft_level, endpoint_time)
    if height < 0:
        los, los_time = -1, Fraction(0)
    elif endpoint < 0:
        los, los_time = -1, endpoint_time
    elif height == 0:
        # A surface departure is used only with a whole-cell exterior endpoint.
        los_time = (e.rate_g*e.radius_s+e.radius_g*e.rate_s)*reach+e.radius_g*anchor
        los = (_sign(_dot(p0, p1)-1, delta*sum(map(abs, p1))+los_time)
               if endpoint > 0 else 0)
        if endpoint == 0:
            los_time = max(los_time, endpoint_time)
    else:
        # Including delta here as well as the instantaneous C2a minimum reserve
        # is deliberately conservative. It covers mixed ground/B1 anchor error
        # without treating a derivative diagnostic as a minimum-level allowance.
        displacement = max(e.rate_g*reach+delta, e.rate_s*reach+anchor)
        radius = max(e.radius_g, e.radius_s)
        los_time = 2*radius*displacement+displacement*displacement
        closest = tuple(x+representative.minimum_parameter*(y-x) for x, y in zip(p0, p1))
        instant = 2*sum(map(abs, closest))*delta+delta*delta
        los = _sign(representative.minimum_level, instant+los_time)

    geometry = representative.geometry
    rho = Fraction(geometry.slant_range_m)
    # E0 is an angle allowance, not a lower bound on range. Reserve C1 range
    # construction error too, including the rounded a+h exact-axis case.
    length_error = a*c1_error+8*_U*(rho
        + sum(map(abs, map(Fraction, geometry.spacecraft_state.position.components_m)))
        + sum(map(abs, map(Fraction, geometry.ground_state.position.components_m))))
    displacement = e.relative_speed*reach+e.position_error+length_error
    elevation_time = _PI_UP
    if displacement < rho:
        ratio = displacement/(rho-displacement)
        if ratio < 1:
            ratio_hi = _up(ratio)
            # <=2u absolute asin error is the declared libm policy. Outward
            # rational addition protects the sum; pi-up is an enclosure cap.
            ray = 2*Fraction(asin(ratio_hi))+4*_U
            normal = min(_PI_UP, e.omega*reach)
            elevation_time = min(_PI_UP, ray+normal)
    elevation = _sign(Fraction(representative.elevation_margin_rad),
                      Fraction(representative.elevation_allowance_rad)+elevation_time)
    S = TemporalVisibilityStatus
    status = S.NOT_VISIBLE if los < 0 or elevation < 0 else S.VISIBLE if los > 0 and elevation > 0 else S.UNRESOLVED
    return status, _up(los_time), _up(elevation_time)


def _seeds(start, end, sample):
    # Sample is an exact positive integer, and admitted times <=2**40. Grid
    # multiples therefore convert exactly, without a floating accumulator.
    lo, stop = start, Fraction(end)
    multiple = Fraction(start)//sample+1
    while multiple*sample < stop:
        hi = float(multiple*sample)
        yield lo, hi
        lo, multiple = hi, multiple+1
    yield lo, end


def _search(inputs, point, policy, start, end, config, envelope):
    S, R = TemporalVisibilityStatus, TemporalUnresolvedReason
    tolerance = Fraction(config.boundary_tolerance_seconds)
    initial = iter(_seeds(start, end, inputs.numerical_config.geometry_sample_seconds))
    children, finished, cache = deque(), [], {}
    initial_done = False
    while True:
        if not initial_done:
            pair = next(initial, None)
            if pair is None:
                initial_done = True
                continue
        elif children:
            pair = children.popleft()
        else:
            break
        lo, hi = pair
        left, right = Fraction(lo), Fraction(hi)
        width = right-left
        midpoint = float((left+right)/2)
        evidence, los_time, angle_time = None, None, None
        status = S.UNRESOLVED
        if not lo < midpoint < hi:
            reason = R.BOUNDARY_TOLERANCE if width <= tolerance else R.TIME_RESOLUTION
        elif midpoint not in cache and len(cache) >= config.max_evaluations:
            reason = R.BOUNDARY_TOLERANCE if width <= tolerance else R.EVALUATION_LIMIT
            if not initial_done:
                # A compact *unevaluated* seed tail avoids allocation proportional
                # to a potentially trillion-cell grid after budget exhaustion.
                # This union is uncertainty only; no certification crosses it.
                hi, initial_done = end, True
                reason = (R.BOUNDARY_TOLERANCE if Fraction(hi)-left <= tolerance
                          else R.EVALUATION_LIMIT)
        else:
            if midpoint not in cache:
                coast = inputs.coast_orbit
                instant = GeometryInstant(coast.trajectory.initial_state.position.instant.epoch, midpoint)
                state = evaluate_two_body_state(coast.trajectory, instant, coast.solver_config)
                cache[midpoint] = evaluate_ground_visibility(point, state, policy)
            evidence = cache[midpoint]
            # A rounded midpoint may be asymmetric: half the nominal width
            # would underbound one edge. Use its actual larger exact reach.
            reach = max(Fraction(midpoint)-left, right-Fraction(midpoint))
            status, los_time, angle_time = _classify(evidence, envelope, reach)
            if status is not S.UNRESOLVED:
                reason = None
            elif width <= tolerance:
                reason = R.BOUNDARY_TOLERANCE
            elif len(cache) >= config.max_evaluations:
                reason = R.EVALUATION_LIMIT
            else:
                children.extend(((lo, midpoint), (midpoint, hi)))
                continue
        finished.append(TemporalVisibilityCell(lo, hi, status,
            midpoint if evidence is not None else None, evidence, los_time, angle_time, reason))
    cells = tuple(sorted(finished, key=lambda cell: cell.start_seconds))
    windows = []
    for cell in cells:
        if cell.status is S.VISIBLE:
            if windows and windows[-1].end_seconds == cell.start_seconds:
                windows[-1] = GroundVisibilityWindow(windows[-1].start_seconds, cell.end_seconds)
            else:
                windows.append(GroundVisibilityWindow(cell.start_seconds, cell.end_seconds))
    complete = not any(cell.unresolved_reason in (R.EVALUATION_LIMIT, R.TIME_RESOLUTION)
                       and Fraction(cell.end_seconds)-Fraction(cell.start_seconds) > tolerance for cell in cells)
    return cells, tuple(windows), len(cache), complete


@dataclass(frozen=True, slots=True)
class GroundVisibilitySearchResult:
    """Recomputed immutable evidence; point/policy remain external to B2 binding."""

    inputs: SimulationInputs
    point: GroundPointDefinition
    policy: GroundVisibilityPolicy
    start_seconds: float
    end_seconds: float
    config: GroundVisibilitySearchConfig
    cells: tuple[TemporalVisibilityCell, ...] = field(init=False)
    visible_windows: tuple[GroundVisibilityWindow, ...] = field(init=False)
    evaluation_count: int = field(init=False)
    complete_to_tolerance: bool = field(init=False)

    def __post_init__(self) -> None:
        _validate_inputs(self.inputs)
        if self.inputs.coast_orbit is None:
            raise ValueError("temporal search requires B2-bound coast inputs")
        if type(self.inputs.coast_orbit) is not CoastOrbitInputs:
            raise TypeError("two-body temporal search requires CoastOrbitInputs")
        point, policy = _point(self.point), _policy(self.policy)
        _exact(self.config, GroundVisibilitySearchConfig, "config")
        config = GroundVisibilitySearchConfig(self.config.boundary_tolerance_seconds, self.config.max_evaluations)
        lo, hi = _interval(self.start_seconds, self.end_seconds)
        horizon = self.inputs.common_world.horizon_seconds
        if self.end_seconds > horizon or hi > horizon:
            raise ValueError("confinement exceeds common-world horizon")
        state = self.inputs.coast_orbit.trajectory.initial_state
        if point.ellipsoid != state.position.frame.ellipsoid:
            raise ValueError("point ellipsoid differs from bound trajectory frame")
        # Check originals too, before float rounding can hide A's endpoint cap.
        start = GeometryInstant(state.position.instant.epoch, self.start_seconds)
        end = GeometryInstant(state.position.instant.epoch, self.end_seconds)
        envelope = _envelope(self.inputs, point, start, end)
        cells, windows, count, complete = _search(self.inputs, point, policy, lo, hi, config, envelope)
        for name, value in (("point", point), ("policy", policy), ("config", config),
                            ("start_seconds", lo), ("end_seconds", hi), ("cells", cells),
                            ("visible_windows", windows), ("evaluation_count", count),
                            ("complete_to_tolerance", complete)):
            object.__setattr__(self, name, value)


def find_ground_visibility_windows(
    inputs: SimulationInputs, point: GroundPointDefinition, policy: GroundVisibilityPolicy,
    start_seconds: float, end_seconds: float, config: GroundVisibilitySearchConfig,
) -> GroundVisibilitySearchResult:
    return GroundVisibilitySearchResult(inputs, point, policy, start_seconds, end_seconds, config)


__all__ = ["GroundVisibilitySearchConfig", "TemporalVisibilityStatus", "TemporalUnresolvedReason",
           "TemporalVisibilityCell", "GroundVisibilityWindow", "GroundVisibilitySearchResult",
           "find_ground_visibility_windows"]
