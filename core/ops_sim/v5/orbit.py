"""Pure bound two-body Cartesian coast queries in fixed model-inertial axes.

Model: r'' = -mu*r/|r|**3 (S008 / D304); no perturbations or runtime binding.
Only the initial Cartesian state and explicit mu are authoritative. TT elapsed
seconds are subtracted from the initial instant, never from a large Julian date.

Scaled universal-variable derivation (not classical orbital elements):
R0=|r0|, V=sqrt(mu/R0), T=R0/V, u=v0/V, beta=2-u.u=alpha*R0,
b=(rhat.u)*sqrt(beta), k=1-beta, q=sqrt(alpha)*chi, n=beta**1.5/T.
Putting z=q*q into C(z)=(1-cos(q))/q**2 and S(z)=(q-sin(q))/q**3
reduces F(chi)/sqrt(mu) to H(q)/n, where
H=beta*q+b*(1-cos(q))+k*(q-sin(q))-n*dt.
H'=1+b*sin(q)-k*cos(q)=alpha*R lies in [1-e,1+e], e=hypot(k,b).
Thus signed M/(1+e), M/(1-e), and M-b +/- e enclose the root, M=n*dt.
The latter follows by bounding b*cos(q)+k*sin(q) by e. This derivation
supplies the equations not printed in NAIF prop2b_c's API description.

Reconstruction uses the same q and conventional Lagrange f/g and derivatives.
The root identity gives n*g=b*(1-cos(q))+beta*sin(q)-H, avoiding the
subtraction of elapsed time and a many-revolution anomaly. H is retained:
we do not silently replace the requested time with the solved time.

Numerical domain (implementation choices, not mission or accuracy approval):
e <= 1-2**-8; R0, V and T each in [2**-128,2**128] in m, m/s, s;
|dt| <= 2**40 s and |dt/P| <= 2**20. Additional derived arithmetic must
be finite/representable. Pericentre p/(1+e), p=R0*|rhat cross u|**2,
must clear the ellipsoid's equatorial-radius sphere. Ambiguous clearance
within 64*u_machine/(1-e) relative arithmetic allowance rejects; this is
an explicit numerical uncertainty guard, not a physical altitude margin.

Period reduction subtracts an integer multiple of the *rounded* binary64
period using exact rational arithmetic, then rounds once. The root tolerance
is a time-residual target for that reduced problem, not an orbit error bound.
A separate working phase-time allowance is 64*u_machine*|dt|/(1-e), plus
subtraction/reduction roundoff; it includes period error times turn count.
Reconstruction and input-invariant roundoff require additional scale-aware
budgets (independent Decimal reference tests). Purity is not phase accuracy.
Independent review corrected the verification's residual-to-endpoint conversion;
the executable propagator is unchanged. For coherent exact coefficients and
signed time residual delta, the retained -H term gives
r_hat=r_star(t+delta)-v0*delta, not simply a time-shifted state. Furthermore
v_hat-v0=(R_star/R_hat)*(v_star(t+delta)-v0), since the velocity coefficients
use the reconstructed radius. For |delta|<=eta, V0=|v0|, rp=pericentre and
D=rp-V0*eta>0, sufficient root contributions are (vmax+V0)*eta metres and
amax*eta+V0*eta*(vmax+V0)/D metres/second. D<=0 establishes no finite velocity
bound by this argument. Phase, rounded coefficients/vector arithmetic and
reference uncertainty remain separate; these identities do not turn rounded
invariants into one exact orbit or make the residual tolerance operational
accuracy. The test helpers document their additional working-budget domain.
These working allowances assume ordinary binary64/libm accuracy; they are
conservative numerical policies, not formally certified interval arithmetic.
For scale: norm/divide/sqrt/scaling contribute about 8u relative error; the
three squared velocity terms give an absolute beta allowance about 16u.
Since beta>=1-e and n=beta**1.5/T, its relative allowance is below
32u/(1-e); 64u leaves room for rounded tau, period and reduction operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import cos, fsum, hypot, inf, isfinite, nextafter, sin, sqrt, tau, ulp

from .frames import CartesianPosition, CartesianState, CartesianVelocity
from .orbit_config import (
    FrameKind, GeometryInstant, _exact, _instant, _nga_parameter, _parameter, _real,
)
from .parameters import ScalarParameter


_U = 2.0**-53
_MAX_ECCENTRICITY = 1.0 - 2.0**-8
_MIN_SCALE = 2.0**-128
_MAX_SCALE = 2.0**128
_MAX_SPAN_SECONDS = 2**40
_MAX_REVOLUTIONS = 2**20
_MU_ID = "orbit.gravity.gravitational-parameter"


def _cross(a, b):
    return (fsum((a[1]*b[2], -a[2]*b[1])),
            fsum((a[2]*b[0], -a[0]*b[2])),
            fsum((a[0]*b[1], -a[1]*b[0])))


@dataclass(frozen=True, slots=True)
class _Scales:
    radius_m: float
    speed_m_per_s: float
    time_seconds: float
    rhat: tuple[float, float, float]
    scaled_velocity: tuple[float, float, float]
    beta: float
    b: float
    eccentricity: float
    pericentre_m: float
    mean_motion_per_s: float
    period_seconds: float


def _scales(state: CartesianState, mu: float) -> _Scales:
    r0, v0 = state.position.components_m, state.velocity.components_m_per_s
    radius = hypot(*r0)
    if not isfinite(radius) or not _MIN_SCALE <= radius <= _MAX_SCALE:
        raise ValueError("initial radius must be nonzero and within [2**-128, 2**128] m")
    speed = sqrt(mu / radius)
    if not isfinite(speed) or not _MIN_SCALE <= speed <= _MAX_SCALE:
        raise ValueError("gravitational speed scale outside supported arithmetic")
    time = radius / speed
    if not _MIN_SCALE <= time <= _MAX_SCALE:
        raise ValueError("orbital time scale outside supported arithmetic")
    rhat = tuple(x/radius for x in r0)
    velocity = tuple(x/speed for x in v0)
    # Bound before squaring; a bound ellipse necessarily has |v/V| < sqrt(2).
    if not all(isfinite(x) for x in velocity) or hypot(*velocity) >= 2.0:
        raise ValueError("nonelliptic or unsupported scaled velocity")
    hbar = _cross(rhat, velocity)
    h2 = fsum(x*x for x in hbar)
    if h2 == 0.0:
        raise ValueError("radial or degenerate motion has zero angular momentum")
    beta = fsum((2.0, *(-x*x for x in velocity)))
    if beta <= 0.0:
        raise ValueError("nonelliptic energy: reciprocal semimajor axis must be positive")
    b = fsum(x*y for x, y in zip(rhat, velocity)) * sqrt(beta)
    eccentricity = hypot(1.0-beta, b)
    if not isfinite(eccentricity) or eccentricity > _MAX_ECCENTRICITY:
        raise ValueError("unsupported near-parabolic conditioning: e must be <= 1-2**-8")
    pericentre = radius * (h2 / (1.0+eccentricity))
    clearance_roundoff = 64.0*_U/(1.0-eccentricity) * pericentre
    earth_radius = state.position.frame.ellipsoid.equatorial_radius_m.value
    if pericentre - clearance_roundoff <= earth_radius:
        raise ValueError("pericentre must be resolvably strictly outside equatorial-radius sphere")
    n = beta * sqrt(beta) / time
    period = tau/n
    # These checks include quantities used for conditioning and error budgets.
    derived = (pericentre, n, period, beta/radius, radius/beta,
               speed*speed*beta/2.0, radius*speed*sqrt(h2))
    if not all(isfinite(x) and x > 0.0 for x in derived):
        raise ValueError("nonfinite or unsupported derived orbital arithmetic")
    return _Scales(radius, speed, time, rhat, velocity, beta, b, eccentricity,
                   pericentre, n, period)


@dataclass(frozen=True, slots=True)
class TwoBodyTrajectory:
    """One authoritative initial state and provenance-bearing central mu."""

    initial_state: CartesianState
    gravitational_parameter_m3_s2: ScalarParameter

    def __post_init__(self) -> None:
        _exact(self.initial_state, CartesianState, "initial_state")
        state = CartesianState(self.initial_state.position, self.initial_state.velocity)
        mu = _parameter(self.gravitational_parameter_m3_s2, _MU_ID, "m^3/s^2")
        if self.gravitational_parameter_m3_s2.value <= 0 or mu.value <= 0:
            raise ValueError("gravitational parameter must be strictly positive")
        if state.position.frame.kind is not FrameKind.MODEL_INERTIAL:
            raise ValueError("initial state must use MODEL_INERTIAL axes")
        _scales(state, mu.value)
        object.__setattr__(self, "initial_state", state)
        object.__setattr__(self, "gravitational_parameter_m3_s2", mu)


@dataclass(frozen=True, slots=True)
class TwoBodySolverConfig:
    """Reduced root time-residual target in seconds and bounded iteration work."""

    time_tolerance_seconds: float
    max_iterations: int

    def __post_init__(self) -> None:
        tolerance = _real("time_tolerance_seconds", self.time_tolerance_seconds)
        if self.time_tolerance_seconds <= 0 or tolerance <= 0:
            raise ValueError("time_tolerance_seconds must be strictly positive")
        _exact(self.max_iterations, int, "max_iterations")
        if self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        object.__setattr__(self, "time_tolerance_seconds", tolerance)


def nominal_earth_gravitational_parameter() -> ScalarParameter:
    """NGA general geocentric GM, including atmosphere; not its GPS footnote GM."""
    return _nga_parameter(_MU_ID, "m^3/s^2", 398_600_441_800_000.0)


@dataclass(frozen=True, slots=True)
class _ReducedTime:
    seconds: float
    revolutions: int
    reduction_roundoff_seconds: float
    phase_time_allowance_seconds: float


def _reduce_time(initial: GeometryInstant, requested: GeometryInstant, scales: _Scales) -> _ReducedTime:
    # Exact difference prevents two valid A timestamps hiding an invalid span.
    span = Fraction(requested.elapsed_seconds) - Fraction(initial.elapsed_seconds)
    if abs(span) > _MAX_SPAN_SECONDS:
        raise ValueError("propagation span exceeds 2**40 s")
    period = Fraction(scales.period_seconds)
    if abs(span) > _MAX_REVOLUTIONS*period:
        raise ValueError("propagation span exceeds 2**20 orbital periods")
    # Exact quotient/remainder selects the nearest integer turn count (ties to
    # even). This does not round/snap an endpoint; the remainder is retained.
    # V5's existing numeric guard prohibits a generic rounding call in physics.
    revolutions, remainder = divmod(span, period)
    if 2*remainder > period or (2*remainder == period and revolutions % 2):
        revolutions += 1
    exact_reduced = span - revolutions*period
    reduced = float(exact_reduced)
    if reduced == 0.0 and exact_reduced:
        raise ValueError("reduced propagation duration underflows binary64")
    reduction_error = float(abs(Fraction(reduced)-exact_reduced))
    phase_allowance = 64.0*_U*float(abs(span))/(1.0-scales.eccentricity) + reduction_error
    return _ReducedTime(reduced, revolutions, reduction_error, phase_allowance)


def _stumpff(z: float) -> tuple[float, float]:
    """Elliptic C,S; exact limits and bounded Taylor recurrence for 0<=z<=1.

    C=sum (-z)^j/(2j+2)!, S=sum (-z)^j/(2j+3)!. At z<=1, 18
    terms leave <1/38! (<2e-45), well below binary64 roundoff. Larger z
    uses a half-angle identity for C; q-sin(q) is well conditioned at q>1.
    The admitted reduced root/bracket has |q|<6, hence z<36.
    """
    if not isfinite(z) or not 0.0 <= z <= 36.0:
        raise ValueError("Stumpff argument outside supported elliptic bracket")
    if z <= 1.0:
        ct, st = 0.5, 1.0/6.0
        cs, ss = [ct], [st]
        for j in range(1, 18):
            ct *= -z/((2*j+1)*(2*j+2))
            st *= -z/((2*j+2)*(2*j+3))
            cs.append(ct)
            ss.append(st)
        return fsum(cs), fsum(ss)
    q = sqrt(z)
    return 2.0*(sin(q/2.0)/q)**2, (1.0-sin(q)/q)/z


def _root_terms(q: float, scales: _Scales, mean: float):
    z = q*q
    c, s = _stumpff(z)
    one_minus_cos = z*c
    q_minus_sin = q*z*s
    terms = (scales.beta*q, scales.b*one_minus_cos,
             (1.0-scales.beta)*q_minus_sin, -mean)
    residual = fsum(terms)
    # Term-scaled allowance also works for tiny dt; there is no epsilon*P floor.
    allowance = 64.0*_U*fsum(abs(x) for x in terms) + 8.0*ulp(residual)
    derivative = fsum((1.0, scales.b*sin(q), -(1.0-scales.beta)*cos(q)))
    return residual, allowance, derivative, one_minus_cos


@dataclass(frozen=True, slots=True)
class _Root:
    q: float
    residual_seconds: float
    roundoff_seconds: float
    iterations: int
    bracket_q: tuple[float, float]


def _solve_universal(scales: _Scales, seconds: float, config: TwoBodySolverConfig) -> _Root:
    n = scales.mean_motion_per_s
    mean = n*seconds
    if not isfinite(mean) or (mean == 0.0 and seconds != 0.0):
        raise ValueError("scaled propagation duration is outside supported arithmetic")
    if seconds == 0.0:
        return _Root(0.0, 0.0, 0.0, 0, (0.0, 0.0))
    # Inflate only the numerical enclosure, never the admitted orbital values.
    enclosure_e = scales.eccentricity + 64.0*_U
    ends = sorted((mean/(1.0+enclosure_e), mean/(1.0-enclosure_e)))
    lo = nextafter(max(ends[0], mean-scales.b-enclosure_e), -inf)
    hi = nextafter(min(ends[1], mean-scales.b+enclosure_e), inf)
    q = mean if lo < mean < hi else lo+(hi-lo)/2.0
    for iteration in range(1, config.max_iterations+1):
        residual, allowance, derivative, _ = _root_terms(q, scales, mean)
        residual_seconds, roundoff_seconds = residual/n, allowance/n
        if not all(isfinite(x) for x in (residual_seconds, roundoff_seconds, derivative)) or derivative <= 0.0:
            raise ValueError("unsupported universal-variable residual arithmetic")
        if abs(residual_seconds)+roundoff_seconds <= config.time_tolerance_seconds:
            return _Root(q, residual_seconds, roundoff_seconds, iteration, (lo, hi))
        if abs(residual) <= allowance:
            raise ValueError("requested residual accuracy cannot be resolved by binary64 evaluation")
        # Update a bracket endpoint only when residual sign exceeds its allowance.
        if residual < 0.0:
            lo = q
        else:
            hi = q
        candidate = q-residual/derivative
        if not lo < candidate < hi:
            candidate = lo+(hi-lo)/2.0
        if candidate == q or candidate == lo or candidate == hi:
            raise ValueError("universal-variable solver stagnation before residual acceptance")
        q = candidate
    raise ValueError("universal-variable solver iteration limit exceeded")


def evaluate_two_body_state(
    trajectory: TwoBodyTrajectory,
    instant: GeometryInstant,
    solver_config: TwoBodySolverConfig,
) -> CartesianState:
    """Evaluate original initial evidence at a signed TT instant; no state mutation."""
    _exact(trajectory, TwoBodyTrajectory, "trajectory")
    trajectory = TwoBodyTrajectory(trajectory.initial_state, trajectory.gravitational_parameter_m3_s2)
    _exact(solver_config, TwoBodySolverConfig, "solver_config")
    solver_config = TwoBodySolverConfig(solver_config.time_tolerance_seconds, solver_config.max_iterations)
    instant = _instant(instant)
    initial = trajectory.initial_state
    if instant.epoch != initial.position.instant.epoch:
        raise ValueError("requested instant must use the initial reference TT epoch")
    scales = _scales(initial, trajectory.gravitational_parameter_m3_s2.value)
    reduced = _reduce_time(initial.position.instant, instant, scales)
    if instant == initial.position.instant:
        return initial
    root = _solve_universal(scales, reduced.seconds, solver_config)
    q, beta = root.q, scales.beta
    _, _, _, one_minus_cos = _root_terms(q, scales, scales.mean_motion_per_s*reduced.seconds)
    f_lagrange = 1.0-one_minus_cos/beta
    g_over_time = fsum((scales.b*one_minus_cos, beta*sin(q),
                       -root.residual_seconds*scales.mean_motion_per_s)) / (beta*sqrt(beta))
    rscaled = tuple(fsum((f_lagrange*x, g_over_time*y))
                    for x, y in zip(scales.rhat, scales.scaled_velocity))
    radius_ratio = hypot(*rscaled)
    if not isfinite(radius_ratio) or radius_ratio <= 0.0:
        raise ValueError("unsupported reconstructed radius")
    fdot_times_time = -sin(q)/(sqrt(beta)*radius_ratio)
    gdot_lagrange = 1.0-one_minus_cos/(beta*radius_ratio)
    position = tuple(_real("propagated position", scales.radius_m*x) for x in rscaled)
    velocity = tuple(_real("propagated velocity", scales.speed_m_per_s*
                          fsum((fdot_times_time*x, gdot_lagrange*y)))
                     for x, y in zip(scales.rhat, scales.scaled_velocity))
    frame = initial.position.frame
    return CartesianState(CartesianPosition(frame, instant, position),
                          CartesianVelocity(frame, instant, velocity))


__all__ = (
    "TwoBodyTrajectory", "TwoBodySolverConfig", "evaluate_two_body_state",
    "nominal_earth_gravitational_parameter",
)
