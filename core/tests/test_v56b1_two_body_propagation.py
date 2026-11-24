"""Independent analytic and Decimal elliptic references for B1 coast endpoints.

Offline reference derivation: from EXACT binary r0,v0,mu (Decimal.from_float)
derive h=r cross v, evec=(v cross h)/mu-r/|r|, a=1/(2/|r|-v.v/mu).
P=evec/e, Q=hhat cross P define the ellipse plane without production helpers.
cos(E0)=(1-|r0|/a)/e; sin(E0)=(r0.v0)/(e*sqrt(mu*a)). Navipedia eq(3)
then gives M=E0-e*sin(E0)+sqrt(mu/a**3)*dt and E-e*sin(E)=M.
r=a*((cosE-e)*P+sqrt(1-e**2)*sinE*Q), with its analytic time derivative.
This reference never calls/copies the universal-variable core. Exact circular
inputs use rhat,vhat as the plane basis. All synthetic element-generated inputs
are rounded FIRST, then the reference rederives the orbit from those binaries.

Decimal sin/cos/atan and Machin pi are reproduced below; no fixtures/downloads
or dependency installation. Ninety-digit references are checked at 110 digits.

Numerical budgets, each an explicit ABSOLUTE Euclidean norm (rel_tol=0):
eta = configured reduced-root tolerance [s]; kappa=1/(1-e), u=2**-53.
phase_s=64*u*kappa*|dt| includes invariant/period rounding and turn count.
Reconstruction allowance=256*u*kappa*(a + vmax*T) [m], or
256*u*kappa*(vmax + amax*T) [m/s], T=sqrt(a**3/mu).
Independent review found that the original vmax*eta / amax*eta root terms
underbounded the actual residual-retaining reconstruction. With signed root
time residual delta and coherent exact coefficients, rhat=rstar(t+delta)-v0*delta.
Also vhat-v0=(Rstar/Rhat)*(vstar(t+delta)-v0), because both changed velocity
coefficients have denominator Rhat. For V0=|v0|, D=rp-V0*eta>0 therefore gives
root_r=(vmax+V0)*eta and root_v=amax*eta+V0*eta*(vmax+V0)/D.
Phase contributes vmax*phase_s and amax*phase_s separately; eta already
includes the accepted residual's evaluation allowance, not that allowance twice.
The exact root theorem does not make rounded invariants a coherent exact orbit.
Constants cover scaled sums/products/norms and
1/(1-e) conditioning in the production derivation; these are conservative
working binary64/libm budgets, not certified intervals or operational accuracy.
Norm/divide/sqrt/scaling receive 8u; three squared velocity terms receive
16u absolute beta allowance. beta>=1-e turns n=beta**1.5/T sensitivity into
<=32u/(1-e) relative error; 64u covers period/tau/reduction too. The 256u
reconstruction allowance reserves four groups of 64u for coefficients,
Stumpff/trigonometric evaluation, vector reconstruction, and norm/derivative
evaluation, with the explicit 1/(1-e) denominator conditioning above.
Reference uncertainty (<1e-60 in tested SI outputs) is separately added.
Original input-rounding error is ZERO between reference and production because
both describe the same binary initial data; synthetic elements are not truth.
Invariants are supplemental: endpoint phase is tested independently first.
The full working budget additionally requires V0*eta/rp<=2^-10 and its
position-reconstruction allowance<D/2. The first predeclared verification
conditioning limit gives rp/D<=1024/1023, away from a singular reconstructed
radius. These checks neither change production acceptance nor select sweep
outcomes. They do not prove the retained 256u policy for arbitrary tolerances.
The exact root-only bound is finite for every D>0, but becomes unhelpfully
large as D tends to zero; for D<=0 it establishes no finite velocity bound.
"""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import math
import random

import pytest

from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit import TwoBodyTrajectory, TwoBodySolverConfig, evaluate_two_body_state
import ops_sim.v5.orbit as orbit
from test_v56b1_two_body_contracts import _trajectory


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _norm(a):
    return _dot(a, a).sqrt()


def _atan(x, eps):
    if x < 0:
        return -_atan(-x, eps)
    # Callers reduce to [0,1]; two half-angle reductions bound Taylor x<0.2.
    for _ in range(2):
        x = x/(1+(1+x*x).sqrt())
    term, total = x, x
    for j in range(1, 512):
        term *= -x*x
        add = term/(2*j+1)
        total += add
        if abs(add) < eps:
            return 4*total
    raise AssertionError("reference atan did not converge")


def _pi(eps):
    return 16*_atan(Decimal(1)/5, eps)-4*_atan(Decimal(1)/239, eps)


def _atan2(y, x, pi, eps):
    if not x:
        return pi/2 if y > 0 else -pi/2
    ratio = abs(y/x)
    angle = _atan(ratio, eps) if ratio <= 1 else pi/2-_atan(1/ratio, eps)
    if x < 0:
        angle = pi-angle
    return angle if y >= 0 else -angle


def _sincos(x, pi, eps):
    x %= 2*pi
    if x > pi:
        x -= 2*pi
    if x < -pi:
        x += 2*pi
    st, ct = x, Decimal(1)
    s, c = st, ct
    for j in range(1, 512):
        st *= -x*x/((2*j)*(2*j+1))
        ct *= -x*x/((2*j-1)*(2*j))
        s += st
        c += ct
        if max(abs(st), abs(ct)) < eps:
            return s, c
    raise AssertionError("reference trigonometric series did not converge")


def _reference(trajectory, instant, precision=90):
    with localcontext() as ctx:
        ctx.prec = precision
        eps = Decimal(10)**(-precision+8)
        pi = _pi(eps/100)
        r0 = tuple(Decimal.from_float(x) for x in trajectory.initial_state.position.components_m)
        v0 = tuple(Decimal.from_float(x) for x in trajectory.initial_state.velocity.components_m_per_s)
        mu = Decimal.from_float(trajectory.gravitational_parameter_m3_s2.value)
        dt = Decimal.from_float(instant.elapsed_seconds)-Decimal.from_float(
            trajectory.initial_state.position.instant.elapsed_seconds)
        radius = _norm(r0)
        h = _cross(r0, v0)
        hhat = tuple(x/_norm(h) for x in h)
        evec = tuple(x/mu-y/radius for x, y in zip(_cross(v0, h), r0))
        e = _norm(evec)
        a = 1/(2/radius-_dot(v0, v0)/mu)
        n = (mu/a**3).sqrt()
        if e == 0:
            p = tuple(x/radius for x in r0)
            q = _cross(hhat, p)
            mean0 = Decimal(0)
        else:
            p = tuple(x/e for x in evec)
            q = _cross(hhat, p)
            cos0 = (1-radius/a)/e
            sin0 = _dot(r0, v0)/(e*(mu*a).sqrt())
            e0 = _atan2(sin0, cos0, pi, eps/100)
            mean0 = e0-e*_sincos(e0, pi, eps/100)[0]
        mean = (mean0+n*dt) % (2*pi)
        if mean > pi:
            mean -= 2*pi
        if mean < -pi:
            mean += 2*pi
        lo, hi, anomaly = -pi, pi, mean
        for _ in range(512):
            s, c = _sincos(anomaly, pi, eps/100)
            residual = anomaly-e*s-mean
            if abs(residual) < eps:
                break
            if residual < 0:
                lo = anomaly
            else:
                hi = anomaly
            candidate = anomaly-residual/(1-e*c)
            anomaly = candidate if lo < candidate < hi else (lo+hi)/2
        else:
            raise AssertionError("independent elliptic Kepler reference did not converge")
        w = (1-e*e).sqrt()
        r = tuple(a*((c-e)*x+w*s*y) for x, y in zip(p, q))
        v = tuple((mu/a).sqrt()/(1-e*c)*(-s*x+w*c*y) for x, y in zip(p, q))
        rp = a*(1-e)
        return {"r": r, "v": v, "a": a, "e": e, "dt": dt,
                "vmax": (mu*(1+e)/rp).sqrt(), "amax": mu/rp**2, "time": 1/n,
                "period": 2*pi/n, "initial_speed": _norm(v0), "pericentre": rp}


def _legacy_budgets(reference, tolerance):
    """Original, disproved endpoint budget retained only as review evidence."""
    a, e, dt = (float(reference[k]) for k in ("a", "e", "dt"))
    vmax, amax, time = (float(reference[k]) for k in ("vmax", "amax", "time"))
    u, condition = 2.0**-53, 1/(1-e)
    phase = 64*u*condition*abs(dt)
    position = vmax*(tolerance+phase) + 256*u*condition*(a+vmax*time) + 1e-60
    velocity = amax*(tolerance+phase) + 256*u*condition*(vmax+amax*time) + 1e-60
    return position, velocity


def _root_budget(vmax, amax, initial_speed, pericentre, eta):
    """Decimal exact-arithmetic root contribution; eta seconds, lengths metres.

    From |Rhat-Rstar|<=V0*eta and Rstar>=rp, Rhat>=D=rp-V0*eta.
    The extra velocity term is |Rstar/Rhat-1|*|vstar-v0|.
    No finite velocity conclusion follows from this argument when D<=0.
    """
    with localcontext() as ctx:
        ctx.prec = 90
        if not eta.is_finite() or eta < 0:
            raise ValueError("root residual allowance must be finite and nonnegative")
        displacement = initial_speed*eta
        denominator = pericentre-displacement
        if denominator <= 0:
            raise ValueError("root velocity bound requires pericentre - initial_speed*eta > 0")
        return ((vmax+initial_speed)*eta,
                amax*eta+displacement*(vmax+initial_speed)/denominator,
                denominator)


def _budget_terms(reference, tolerance):
    """Separate SI contributions; Decimal avoids downward binary64 input casts.

    eta is the configured root-residual ceiling (already including evaluation
    allowance); it is not a position request. The final sum rounds outward.
    Reference metadata has the same <1e-60 tested uncertainty as the reference.
    """
    with localcontext() as ctx:
        ctx.prec = 90
        eta = Decimal.from_float(tolerance)
        a, e, dt = (reference[k] for k in ("a", "e", "dt"))
        vmax, amax, time = (reference[k] for k in ("vmax", "amax", "time"))
        v0, rp = reference["initial_speed"], reference["pericentre"]
        root_r, root_v, denominator = _root_budget(vmax, amax, v0, rp, eta)
        u, condition = Decimal(2)**-53, 1/(1-e)
        phase = 64*u*condition*abs(dt)
        reconstruction = (256*u*condition*(a+vmax*time),
                          256*u*condition*(vmax+amax*time))
        if v0*eta/rp > Decimal(2)**-10:
            raise ValueError("working reconstruction budget requires initial_speed*eta/pericentre <= 2**-10")
        if reconstruction[0] >= denominator/2:
            raise ValueError("working reconstruction allowance must be below half the radius lower bound")
        return {"root": (root_r, root_v), "phase": (vmax*phase, amax*phase),
                "reconstruction": reconstruction,
                "reference": (Decimal("1e-60"), Decimal("1e-60")),
                "radius_lower_m": denominator, "root_radius_fraction": v0*eta/rp}


def _budgets(reference, tolerance):
    terms = _budget_terms(reference, tolerance)
    with localcontext() as ctx:
        ctx.prec = 90
        totals = tuple(math.nextafter(float(sum(terms[key][i] for key in
                       ("root", "phase", "reconstruction", "reference"))), math.inf)
                       for i in range(2))
    if not all(math.isfinite(x) for x in totals):
        raise ValueError("endpoint working budget is outside finite binary64 reporting")
    return totals


def _errors(state, reference):
    return tuple(math.hypot(*(float(abs(Decimal.from_float(x)-y)) for x, y in zip(actual, reference[key])))
                 for actual, key in ((state.position.components_m, "r"), (state.velocity.components_m_per_s, "v")))


def _checked(trajectory, seconds, tolerance=1e-8):
    instant = GeometryInstant(trajectory.initial_state.position.instant.epoch, seconds)
    config = TwoBodySolverConfig(tolerance, 100)
    state = evaluate_two_body_state(trajectory, instant, config)
    reference = _reference(trajectory, instant)
    errors, budgets = _errors(state, reference), _budgets(reference, tolerance)
    assert errors[0] <= budgets[0], ("position m", errors, budgets)
    assert errors[1] <= budgets[1], ("velocity m/s", errors, budgets)
    assert state.position.instant == state.velocity.instant == instant
    assert state.position.frame == state.velocity.frame == trajectory.initial_state.position.frame
    return state, reference, errors, budgets


def _ellipse(e, a, eccentric_anomaly, *, t0=0.0, retrograde=False):
    """Synthetic double-precision starting points only; reference rederives binaries."""
    mu = 398_600_441_800_000.0
    s, c = math.sin(eccentric_anomaly), math.cos(eccentric_anomaly)
    w = math.sqrt(1-e*e)
    factor = math.sqrt(mu/a)/(1-e*c)
    r = (a*(c-e), a*w*s, 0.0)
    v = (-factor*s, factor*w*c, 0.0)
    # A fixed nontrivial rotated/inclined plane, not a coordinate-axis case.
    def rotate(vector):
        x, y, z = vector
        x, y = math.cos(.37)*x-math.sin(.37)*y, math.sin(.37)*x+math.cos(.37)*y
        y, z = math.cos(.81)*y-math.sin(.81)*z, math.sin(.81)*y+math.cos(.81)*z
        x, y = math.cos(-.63)*x-math.sin(-.63)*y, math.sin(-.63)*x+math.cos(-.63)*y
        return x, y, z
    return _trajectory(rotate(r), tuple(-x for x in rotate(v)) if retrograde else rotate(v),
                       mu, earth=6_378_137.0, t0=t0)


@pytest.mark.parametrize("quarter_turns", [0, 1, 2, 4, -1, -2, -4, 7])
@pytest.mark.parametrize("plane", ["xy", "inclined", "retrograde"])
@pytest.mark.parametrize("t0", [0.0, 123.25])
def test_hand_circular_fractions_signed_planes_and_nonzero_initial_time(quarter_turns, plane, t0):
    # Exact binary circle: R=2m, V=1m/s, mu=2m³/s², n=1/2 s^-1.
    # Inclined basis (0,0,1) is a 90-degree inclination, exact in binary.
    direction = (0, 0, 1) if plane == "inclined" else (0, -1, 0) if plane == "retrograde" else (0, 1, 0)
    t = _trajectory(v=direction, t0=t0)
    seconds = t0+quarter_turns*math.pi
    state, _, _, _ = _checked(t, seconds, 1e-12)
    # Analytic rotation evaluated at the actual supplied binary timestamp.
    with localcontext() as ctx:
        ctx.prec = 90
        eps = Decimal("1e-82")
        phase = (Decimal.from_float(seconds)-Decimal.from_float(t0))/2
        s, c = _sincos(phase, _pi(eps/100), eps/100)
        hand = {"r": (2*c, 2*s*direction[1], 2*s*direction[2]),
                "v": (-s, c*direction[1], c*direction[2])}
    rerr, verr = _errors(state, hand)
    assert rerr <= 2e-12, ("m: fixture-specific exact-circle analytic allowance", rerr)
    assert verr <= 1e-12, ("m/s: fixture-specific exact-circle analytic allowance", verr)
    if quarter_turns == 0:
        assert state == t.initial_state


@pytest.mark.parametrize("e,a,anomaly,seconds", [
    (1e-9, 7e6, 0.7, 1321.125),
    (.25, 1.1e7, 1.1, 2300.75),
    (.65, 2.2e7, -1.6, -6800.125),
    (.9, 7e7, 0.13, 66000.5),
    (.99, 7e8, 1.4, -12000000.25),
    (1-2**-8-1e-12, 7e6/(2**-8+1e-12), 2.4, -500000.25),
    (.35, 1.2e7, .8, 17*13082.123+73.25),
    (1e-8, 7e6, 1.2, 1e9+.125),
    (.72, 2.5e7, -0.9, -1e9+.25),
])
def test_independent_decimal_elliptic_endpoints(e, a, anomaly, seconds):
    t = _ellipse(e, a, anomaly, t0=41.125)
    _, reference, errors, budgets = _checked(t, seconds, 1e-7)
    assert abs(_dot(t.initial_state.position.components_m, t.initial_state.velocity.components_m_per_s)) > 0
    print(f"elliptic e={e:g} a={a:g}m query={seconds:g}s errors={errors} budgets={budgets}")
    assert float(reference["e"]) > 0


def test_reference_precision_and_zero_time_reproduction():
    t = _ellipse(.99, 7e8, 1.4)
    for seconds in (0.0, 1e9+.125):
        instant = GeometryInstant(t.initial_state.position.instant.epoch, seconds)
        ref90, ref110 = _reference(t, instant), _reference(t, instant, precision=110)
        for key in ("r", "v"):
            assert max(abs(x-y) for x, y in zip(ref90[key], ref110[key])) < Decimal("1e-60")
        for key in ("pericentre", "initial_speed"):
            assert abs(ref90[key]-ref110[key]) < Decimal("1e-60")  # m and m/s.
        if seconds == 0:
            assert max(_errors(t.initial_state, ref90)) < 1e-60


def test_stumpff_zero_small_and_branch_boundary_against_decimal():
    assert orbit._stumpff(0.0) == (0.5, 1/6)
    with localcontext() as ctx:
        ctx.prec = 90
        pi, eps = _pi(Decimal("1e-84")), Decimal("1e-82")
        for z in (1e-24, 1e-12, .3, math.nextafter(1.0, 0), 1.0, math.nextafter(1.0, math.inf), 25.0):
            dz = Decimal.from_float(z)
            q = dz.sqrt()
            s, c = _sincos(q, pi, eps)
            expected = ((1-c)/dz, (q-s)/(q*dz))
            actual = orbit._stumpff(z)
            for x, y in zip(actual, expected):
                # Absolute dimensionless allowance: <= 8 binary64 ulps at O(1).
                assert abs(Decimal.from_float(x)-y) <= Decimal.from_float(8*2**-53)


def test_residual_bracket_iterations_and_unattainable_request():
    t = _ellipse(.65, 2.2e7, .7)
    scales = orbit._scales(t.initial_state, t.gravitational_parameter_m3_s2.value)
    config = TwoBodySolverConfig(1e-8, 100)
    root = orbit._solve_universal(scales, 1900.25, config)
    assert root.bracket_q[0] <= root.q <= root.bracket_q[1]
    assert 1 < root.iterations <= config.max_iterations
    assert abs(root.residual_seconds)+root.roundoff_seconds <= config.time_tolerance_seconds
    # Independent high precision evaluation of the dimensional residual for the
    # SAME rounded solver coefficients, distinct from endpoint/reference error.
    with localcontext() as ctx:
        ctx.prec = 90
        d = Decimal.from_float
        eps = Decimal("1e-82")
        s, c = _sincos(d(root.q), _pi(eps/100), eps/100)
        residual = (d(root.q)+d(scales.b)*(1-c)-(1-d(scales.beta))*s)/d(scales.mean_motion_per_s)-d(1900.25)
        assert abs(residual-d(root.residual_seconds)) <= d(root.roundoff_seconds)
        assert abs(residual) <= d(config.time_tolerance_seconds)
    with pytest.raises(ValueError, match="iteration limit"):
        evaluate_two_body_state(t, GeometryInstant(t.initial_state.position.instant.epoch, 1900.25), TwoBodySolverConfig(1e-8, 1))
    with pytest.raises(ValueError, match="accuracy cannot be resolved"):
        evaluate_two_body_state(t, GeometryInstant(t.initial_state.position.instant.epoch, 1900.25), TwoBodySolverConfig(1e-30, 100))


def test_stagnation_guard_is_explicit(monkeypatch):
    # Controlled residual-evaluator seam isolates equal-iterate protection. The
    # public trajectory is valid; no invalid pericentre masks this failure.
    t = _trajectory()
    scales = orbit._scales(t.initial_state, 2.0)
    original = orbit._root_terms
    def unresolved(q, values, mean):
        result = original(q, values, mean)
        return 1e-100, 0.0, 1e100, result[3]
    monkeypatch.setattr(orbit, "_root_terms", unresolved)
    with pytest.raises(ValueError, match="stagnation"):
        orbit._solve_universal(scales, 1, TwoBodySolverConfig(1e-200, 1000))


def test_tiny_duration_and_near_period_queries_do_not_snap():
    t = _trajectory()
    _, _, errors, _ = _checked(t, 1e-20, 1e-30)
    assert errors[0] <= 1e-30
    period = 4*math.pi
    for seconds in (period, math.nextafter(period, -math.inf), math.nextafter(period, math.inf), period+1e-8,
                    100000*period+.123, -100000*period-.123):
        state, _, _, _ = _checked(t, seconds, 1e-12)
        assert state.position.instant.elapsed_seconds == seconds
        if seconds != period:
            assert state.position.components_m != t.initial_state.position.components_m
    before = _checked(t, period-1e-8, 1e-12)[0]
    after = _checked(t, period+1e-8, 1e-12)[0]
    assert before.position.components_m[1] < 0 < after.position.components_m[1]


def test_fraction_time_reduction_is_exact_before_final_rounding():
    t = _trajectory(t0=-123.25)
    scales = orbit._scales(t.initial_state, 2.0)
    request = GeometryInstant(t.initial_state.position.instant.epoch, 1e6+.125)
    reduced = orbit._reduce_time(t.initial_state.position.instant, request, scales)
    span = Fraction(request.elapsed_seconds)-Fraction(-123.25)
    exact = span-reduced.revolutions*Fraction(scales.period_seconds)
    assert reduced.seconds == float(exact)
    assert reduced.reduction_roundoff_seconds == float(abs(Fraction(reduced.seconds)-exact))
    assert reduced.phase_time_allowance_seconds >= reduced.reduction_roundoff_seconds
    assert abs(reduced.seconds) <= scales.period_seconds/2


@pytest.mark.parametrize("seconds,turns,remaining", [(4, 0, 4), (12, 2, -4), (20, 2, 4),
                                                     (-4, 0, -4), (-12, -2, 4), (-20, -2, -4)])
def test_exact_nearest_turn_selection_at_half_period_ties(seconds, turns, remaining):
    t = _trajectory()
    # Isolate rational reduction with an exact synthetic period; no propagation.
    scales = replace(orbit._scales(t.initial_state, 2.0), period_seconds=8.0)
    reduced = orbit._reduce_time(t.initial_state.position.instant,
        GeometryInstant(t.initial_state.position.instant.epoch, seconds), scales)
    assert reduced.revolutions == turns
    assert reduced.seconds == remaining
    assert reduced.reduction_roundoff_seconds == 0


def _invariants(state, mu):
    r, v = state.position.components_m, state.velocity.components_m_per_s
    radius = math.hypot(*r)
    h = _cross(r, v)
    return (_dot(v, v)/2-mu/radius, h,
            tuple(x/mu-y/radius for x, y in zip(_cross(v, h), r)))


def test_invariants_forward_backward_and_separately_reanchored_evaluation():
    t = _ellipse(.72, 2.5e7, .9, t0=13.125)
    state, reference, _, budgets = _checked(t, 43.125)
    mu = t.gravitational_parameter_m3_s2.value
    initial = t.initial_state
    energy0, h0, e0 = _invariants(initial, mu)
    energy1, h1, e1 = _invariants(state, mu)
    dr, dv = budgets
    r, v = math.hypot(*state.position.components_m), math.hypot(*state.velocity.components_m_per_s)
    u = 2**-53
    energy_budget = v*dv+mu/r**2*dr + 64*u*(v*v+mu/r)  # m²/s²
    h_budget = r*dv+v*dr+64*u*r*v  # m²/s
    e_budget = (dv*math.hypot(*h0)+v*h_budget)/mu+2*dr/r+128*u  # dimensionless
    assert abs(energy1-energy0) <= energy_budget
    assert math.dist(h1, h0) <= h_budget
    assert math.dist(e1, e0) <= e_budget
    reanchored = TwoBodyTrajectory(state, t.gravitational_parameter_m3_s2)
    recovered, _, _, recovered_budget = _checked(reanchored, 13.125)
    later, _, _, later_budget = _checked(reanchored, 73.125)
    direct, _, _, direct_budget = _checked(t, 73.125)
    # Reanchoring admits a slightly different binary orbit. A conservative
    # variational growth bound exp(L*dt), L=max(1/T,2*mu*T/rmin³), in the
    # norm |dr|+T|dv| follows the two-body Jacobian (scaled velocity T*v).
    # rmin=rp/2 leaves room for the segment between the two nearby solutions;
    # the resulting bound is checked to remain well inside that room. With
    # T=sqrt(rmin³/(2mu)), L=1/T. This is a short, 30-second recovery/coast,
    # avoiding the useless exponential bound over many orbital periods.
    rmin = float(reference["a"]*(1-reference["e"]))/2
    time = math.sqrt(rmin**3/(2*mu))
    growth = math.exp(30.0/time)
    initial_error = dr+time*dv
    assert growth*initial_error < rmin/2
    for result, target, endpoint_budget in ((recovered, initial, recovered_budget),
                                           (later, direct, tuple(x+y for x, y in zip(later_budget, direct_budget)))):
        assert math.dist(result.position.components_m, target.position.components_m) <= growth*initial_error+endpoint_budget[0]
        assert math.dist(result.velocity.components_m_per_s, target.velocity.components_m_per_s) <= growth*initial_error/time+endpoint_budget[1]


def test_deterministic_query_order_input_preservation_and_parameter_sensitivity():
    t, cfg = _ellipse(.4, 1.3e7, .8), TwoBodySolverConfig(1e-8, 100)
    before = deepcopy((t, cfg))
    epoch = t.initial_state.position.instant.epoch
    at = lambda value, seconds: evaluate_two_body_state(value, GeometryInstant(epoch, seconds), cfg)
    first = at(t, 1000)
    at(t, 100)
    assert at(t, 1000) == first == at(deepcopy(t), 1000)
    assert (t, cfg) == before
    changed_mu = replace(t, gravitational_parameter_m3_s2=replace(t.gravitational_parameter_m3_s2,
                         value=t.gravitational_parameter_m3_s2.value*1.0001))
    changed_velocity = replace(t, initial_state=replace(t.initial_state, velocity=replace(t.initial_state.velocity,
        components_m_per_s=tuple(x*1.0001 for x in t.initial_state.velocity.components_m_per_s))))
    assert at(changed_mu, 1000) != first
    assert at(changed_velocity, 1000) != first


def test_seeded_independent_endpoint_sweep():
    rng = random.Random(5601)
    maxima = [0.0, 0.0]
    ratios = [0.0, 0.0]
    for index in range(64):
        e = rng.uniform(1e-7, .99)
        pericentre = rng.uniform(6.5e6, 2.0e7)
        a = pericentre/(1-e)
        t = _ellipse(e, a, rng.uniform(-math.pi, math.pi), t0=17.125,
                     retrograde=bool(index%2))
        seconds = rng.uniform(-1e9, 1e9) if index%8 == 0 else rng.uniform(-200000, 200000)
        _, _, errors, budgets = _checked(t, seconds, 1e-6)
        maxima = [max(a, b) for a, b in zip(maxima, errors)]
        ratios = [max(a, b/c) for a, b, c in zip(ratios, errors, budgets)]
    print(f"B1 seeded=5601 cases=64 e=(1e-7,.99) rp=[6.5e6,2e7]m |query|<=1e9s "
          f"max_position_m={maxima[0]:.17g} max_velocity_m_per_s={maxima[1]:.17g} "
          f"max_budget_ratios={ratios}")


_REVIEW_CASES = {
    "P": ((7000000.0, 0.0, 0.0), (0.000003, 7546.053290107542, 0.0),
          2914.2583188430076, 1e-6),
    "V": ((-6475134.267426118, -4689882.013371683, -7988023.400237308),
          (-4225.895425039322, 4003.5505883152605, 782.9198366353096),
          2976.052644955996, 3.133415127246218e-8),
}


def _accepted_root(trajectory, seconds, tolerance):
    instant = GeometryInstant(trajectory.initial_state.position.instant.epoch, seconds)
    scales = orbit._scales(trajectory.initial_state, trajectory.gravitational_parameter_m3_s2.value)
    reduced = orbit._reduce_time(trajectory.initial_state.position.instant, instant, scales)
    root = orbit._solve_universal(scales, reduced.seconds, TwoBodySolverConfig(tolerance, 100))
    # Independent high-precision residual for the same rounded coefficients.
    # This checks root evaluation, not the exact-binary-input orbit's phase.
    with localcontext() as ctx:
        ctx.prec = 90
        d, eps = Decimal.from_float, Decimal("1e-82")
        s, c = _sincos(d(root.q), _pi(eps/100), eps/100)
        delta = (d(root.q)+d(scales.b)*(1-c)-(1-d(scales.beta))*s)/d(scales.mean_motion_per_s)-d(reduced.seconds)
        assert abs(delta-d(root.residual_seconds)) <= d(root.roundoff_seconds)
        assert abs(delta) <= d(tolerance)
    assert abs(root.residual_seconds)+root.roundoff_seconds <= tolerance
    return root


def _counterexample(label, component):
    r, v, seconds, tolerance = _REVIEW_CASES[label]
    trajectory = _trajectory(r, v, 398600441800000.0, earth=6378137.0, t0=0.0)
    instant = GeometryInstant(trajectory.initial_state.position.instant.epoch, seconds)
    state = evaluate_two_body_state(trajectory, instant, TwoBodySolverConfig(tolerance, 100))
    reference = _reference(trajectory, instant)
    errors, old, corrected = _errors(state, reference), _legacy_budgets(reference, tolerance), _budgets(reference, tolerance)
    # Component-specific first assertion prevents position masking the V finding.
    assert errors[component] > old[component]
    assert errors[component] <= corrected[component]
    assert all(error <= budget for error, budget in zip(errors, corrected))
    root = _accepted_root(trajectory, seconds, tolerance)
    assert abs(root.residual_seconds) > tolerance/4  # Material residual, no extra iterations.
    print(f"review {label}: errors={errors} old={old} corrected={corrected} "
          f"residual_s={root.residual_seconds:.17g} allowance_s={root.roundoff_seconds:.17g}")


def test_review_position_counterexample():
    _counterexample("P", 0)


def test_review_velocity_counterexample():
    _counterexample("V", 1)


@pytest.mark.parametrize("radial_sign", [-1, 1])
@pytest.mark.parametrize("time_sign", [-1, 1])
def test_near_circular_off_periapsis_material_residual_both_time_directions(radial_sign, time_sign):
    r, v, seconds, tolerance = _REVIEW_CASES["P"]
    trajectory = _trajectory(r, (radial_sign*v[0], v[1], v[2]),
                             398600441800000.0, earth=6378137.0, t0=0.0)
    _checked(trajectory, time_sign*seconds, tolerance)
    root = _accepted_root(trajectory, time_sign*seconds, tolerance)
    assert abs(root.residual_seconds) > tolerance/4
    assert root.residual_seconds*radial_sign > 0


@pytest.mark.parametrize("quarter_turns", [-2, -1, 1, 2])
@pytest.mark.parametrize("delta_text", ["-0.000001", "0.000001"])
def test_exact_circle_distinguishes_time_shift_from_residual_retaining_reconstruction(quarter_turns, delta_text):
    # Exact-arithmetic mechanism test, not a changed production endpoint:
    # R=2m, V=1m/s, mu=2m³/s², n=1/2 s^-1 and an explicit approximate q.
    with localcontext() as ctx:
        ctx.prec = 90
        eps = Decimal("1e-82")
        pi = _pi(eps/100)
        radius, speed, n = Decimal(2), Decimal(1), Decimal("0.5")
        delta = Decimal(delta_text)
        t = quarter_turns*pi/(2*n)
        q = n*(t+delta)
        s, c = _sincos(q, pi, eps/100)
        s0, c0 = _sincos(n*t, pi, eps/100)
        v0 = (Decimal(0), speed)
        rstar, vstar = (radius*c, radius*s), (-speed*s, speed*c)
        # Actual f,g,fdot,gdot relationships, in Decimal for this exact circle.
        f, g = c, t-(q-s)/n
        rhat = (radius*f, speed*g)
        rhat_norm = _norm(rhat)
        fdot, gdot = -speed*s/rhat_norm, 1-radius*(1-c)/rhat_norm
        vhat = (radius*fdot, speed*gdot)
        predicted_r = tuple(x-y*delta for x, y in zip(rstar, v0))
        predicted_v = tuple(y+radius/rhat_norm*(x-y) for x, y in zip(vstar, v0))
        assert _norm(tuple(x-y for x, y in zip(rhat, predicted_r))) < Decimal("1e-75")  # m
        assert _norm(tuple(x-y for x, y in zip(vhat, predicted_v))) < Decimal("1e-75")  # m/s
        er = _norm((rhat[0]-radius*c0, rhat[1]-radius*s0))
        ev = _norm((vhat[0]+speed*s0, vhat[1]-speed*c0))
        root_r, root_v, denominator = _root_budget(speed, speed*n, speed, radius, abs(delta))
        assert er <= root_r and ev <= root_v and denominator > 0
        if abs(quarter_turns) == 2:
            assert er > speed*abs(delta)  # Half-period: leading error is 2V|delta|.
        else:
            assert ev > speed*n*abs(delta)  # Quarter-period: leading error is sqrt(2)A|delta|.


def test_root_velocity_denominator_and_distinct_working_budget_domain():
    d = Decimal
    args = (d(2), d(1), d(2), d(4))
    assert _root_budget(*args, d(0)) == (0, 0, 4)
    small = _root_budget(*args, d(1))
    near = _root_budget(*args, d("1.999"))
    assert small == (4, 5, 2)
    assert near[2] == d("0.002") and near[1] > small[1]
    for eta in (d(2), d(3)):
        with pytest.raises(ValueError, match="pericentre - initial_speed"):
            _root_budget(*args, eta)
    trajectory = _trajectory()
    reference = _reference(trajectory, trajectory.initial_state.position.instant)
    edge = float(reference["pericentre"]/reference["initial_speed"]/1024)
    _budget_terms(reference, edge)
    with pytest.raises(ValueError, match=r"initial_speed\*eta/pericentre"):
        _budget_terms(reference, math.nextafter(edge, math.inf))
    # Positive mathematical D alone does not certify the floating reconstruction.
    assert _root_budget(reference["vmax"], reference["amax"], reference["initial_speed"],
                        reference["pericentre"], d("0.1"))[2] > 0
    with pytest.raises(ValueError, match="working reconstruction budget"):
        _budgets(reference, .1)
    with pytest.raises(ValueError, match="half the radius lower bound"):
        _budget_terms(dict(reference, a=d("1e100")), 1e-6)


def test_root_phase_reconstruction_and_reference_terms_remain_separate():
    trajectory = _trajectory()
    reference = _reference(trajectory, GeometryInstant(trajectory.initial_state.position.instant.epoch, 1.0))
    first, second = _budget_terms(reference, 1e-6), _budget_terms(reference, 2e-6)
    assert second["root"][0] > first["root"][0]
    assert second["root"][1] > first["root"][1]
    assert all(first[key] == second[key] for key in ("phase", "reconstruction", "reference"))
    changed_time = _budget_terms(dict(reference, dt=2*reference["dt"]), 1e-6)
    with localcontext() as ctx:
        ctx.prec = 90
        assert changed_time["phase"] == tuple(2*x for x in first["phase"])
    assert all(first[key] == changed_time[key] for key in ("root", "reconstruction", "reference"))


def test_supplementary_review_sweep():
    rng = random.Random(20260914)
    accepted = rejected = old_outside = material = 0
    maxima, ratios, max_rho = [0.0, 0.0], [0.0, 0.0], Decimal(0)
    rejection_indices = []
    for index in range(1000):
        e = rng.uniform(1e-6, .9959)
        rp = rng.uniform(6.5e6, 2e7)
        a = rp/(1-e)
        anomaly = rng.uniform(-math.pi, math.pi)
        trajectory = _ellipse(e, a, anomaly, t0=0.0, retrograde=bool(index % 2))
        period = math.tau*math.sqrt(a**3/398600441800000.0)
        seconds = rng.uniform(-1.5, 1.5)*period
        tolerance = 10**rng.uniform(-9, -3)
        instant = GeometryInstant(trajectory.initial_state.position.instant.epoch, seconds)
        try:
            state = evaluate_two_body_state(trajectory, instant, TwoBodySolverConfig(tolerance, 100))
        except ValueError as error:
            # Only the known explicit production accuracy rejection is counted.
            # Other ValueErrors and all unrelated exceptions remain test failures.
            if str(error) != "requested residual accuracy cannot be resolved by binary64 evaluation":
                raise
            rejected += 1
            rejection_indices.append(index)
            continue
        accepted += 1
        reference = _reference(trajectory, instant)
        errors, budgets = _errors(state, reference), _budgets(reference, tolerance)
        old = _legacy_budgets(reference, tolerance)
        old_outside += any(x > y for x, y in zip(errors, old))
        assert errors[0] <= budgets[0], (index, "m", errors, budgets)
        assert errors[1] <= budgets[1], (index, "m/s", errors, budgets)
        root = _accepted_root(trajectory, seconds, tolerance)
        material += abs(root.residual_seconds) >= tolerance/4
        maxima = [max(x, y) for x, y in zip(maxima, errors)]
        ratios = [max(x, y/z) for x, y, z in zip(ratios, errors, budgets)]
        max_rho = max(max_rho, _budget_terms(reference, tolerance)["root_radius_fraction"])
    assert accepted+rejected == 1000 and accepted > 0 and material > 0
    print(f"review sweep seed=20260914 count=1000 accepted={accepted} accuracy_rejections={rejected} "
          f"old_budget_exceedances={old_outside} material_residuals={material} "
          f"max_errors={maxima} max_corrected_ratios={ratios} max_V0_eta_over_rp={max_rho} "
          f"rejection_indices={rejection_indices}")
