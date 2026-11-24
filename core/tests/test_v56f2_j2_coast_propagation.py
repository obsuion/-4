"""Independent endpoint references and scoped F2 refinement diagnostics.

All coordinates are SI: position m, velocity m/s, energy m^2/s^2, hz m^2/s.
Refinement is nominal evidence, not a validated enclosure. On the selected
smooth bounded arcs, the error model is C*h^4 + O(h^5) + binary64 rounding.
The order check permits 12..20 (16 +/-25%) only above the separately stated
reference/arithmetic floor. The circle uses finer h for multi-revolution arcs
because a preliminary independent review observed non-asymptotic coarse steps.
The truncation health envelope 8*(1+n*|T|)^2*(n*h)^4 times the state scale is a
declared test policy for these fixtures, not an analytic global error theorem.
An operation-count reserve 256*u*N*(1+n*|T|)*scale separates ordinary arithmetic
from truncation. B1's independently justified endpoint budget is added only to
the B1 comparison; its Decimal reference also independently checks both solvers.
"""

from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from math import atan2, cos, fsum, hypot, isfinite, pi, sin, sqrt, tau, ulp

import pytest

from ops_sim.v5 import orbit_j2 as coast
from ops_sim.v5.orbit import TwoBodyTrajectory, TwoBodySolverConfig, evaluate_two_body_state
from ops_sim.v5.orbit_j2_gravity import evaluate_j2_gravity
from test_v56b1_two_body_propagation import _reference, _budgets, _errors, _pi, _sincos
from test_v56f2_j2_coast_contracts import at, evaluate, trajectory


def components(state):
    return state.position.components_m, state.velocity.components_m_per_s


def distance(left, right):
    return tuple(hypot(*(a-b for a, b in zip(x, y))) for x, y in zip(components(left), components(right)))


def arithmetic_floor(scale, n, span, h):
    steps = int(abs(span)/h)+1
    return 256*2**-53*steps*(1+n*abs(span))*scale


def assert_fourth_order(errors, uncertainty):
    resolved_pairs = 0
    for i in range(2):
        # Never force an order ratio when reference/roundoff can explain it.
        assert errors[i+1] < errors[i]
        if errors[i+1] <= 10*uncertainty[i+1]:
            continue
        resolved_pairs += 1
        low = (errors[i]-uncertainty[i])/(errors[i+1]+uncertainty[i+1])
        high = (errors[i]+uncertainty[i])/(errors[i+1]-uncertainty[i+1])
        assert low <= 20 and high >= 12, (errors, uncertainty, low, high)
    assert resolved_pairs >= 1, ('no resolved fourth-order evidence', errors, uncertainty)


@pytest.mark.parametrize('velocity', [(0, 2, 0), (0, 1.75, 0.25)], ids=['circle', 'ellipse'])
@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('t0', [0, 32.125])
def test_zero_j2_converges_to_b1_and_independent_decimal_orbit(velocity, sign, t0, record_property):
    t = trajectory(v=velocity, t0=t0)
    request = at(t, t0+sign*2)
    b1 = TwoBodyTrajectory(t.initial_state, t.gravity_model.gravitational_parameter_m3_s2)
    tolerance = 1e-13
    reference = _reference(b1, request, 90)
    tighter = _reference(b1, request, 110)
    for key in ('r', 'v'):
        assert max(abs(x-y) for x, y in zip(reference[key], tighter[key])) < Decimal('1e-60')
    independent = evaluate_two_body_state(b1, request, TwoBodySolverConfig(tolerance, 100))
    b1_budget = _budgets(reference, tolerance)
    assert all(e <= b for e, b in zip(_errors(independent, reference), b1_budget))
    scales = (float(reference['a']), float(reference['vmax']))
    n = 1/float(reference['time'])
    hs = (1/32, 1/64, 1/128)
    errors, floors = [], []
    for h in hs:
        result = coast.evaluate_j2_cartesian_state(t, request, coast.J2RK4SolverConfig(h, 1000))
        error = _errors(result, reference)
        rounding = tuple(arithmetic_floor(s, n, sign*2, h)+1e-60 for s in scales)
        truncation = tuple(8*(1+2*n)**2*(n*h)**4*s for s in scales)
        assert all(e <= b+r for e, b, r in zip(error, truncation, rounding))
        # B1 uncertainty, F2 nominal truncation and binary64 are distinct terms.
        assert all(e <= b+q+r for e, b, q, r in zip(distance(result, independent), b1_budget, truncation, rounding))
        errors.append(error); floors.append(rounding)
    for axis in (0, 1):
        assert_fourth_order([e[axis] for e in errors], [e[axis] for e in floors])
    record_property('zero_j2_errors_m_mps', json.dumps(errors))
    record_property('b1_reference_budget_m_mps', json.dumps(b1_budget))


def circle_reference(span, precision):
    # Exact binary authorities: mu8,r2,Rg1,J2=11/32 give n=17/16,v=17/8.
    # No rounded initial-speed mismatch is hidden in the analytic reference.
    with localcontext() as ctx:
        ctx.prec = precision
        eps = Decimal(10)**(-precision+10)
        angle = Decimal(17)/16*(Decimal(span.numerator)/Decimal(span.denominator))
        s, c = _sincos(angle, _pi(eps), eps)
        return ((2*c, 2*s, Decimal(0)), (-Decimal(17)/8*s, Decimal(17)/8*c, Decimal(0)))


@pytest.mark.parametrize('turns', [0.125, 1, 3])
@pytest.mark.parametrize('sign', [1, -1])
def test_exact_nonzero_j2_circle_signed_multiple_arcs(turns, sign, record_property):
    t = trajectory(v=(0, 17/8, 0), j2=11/32)
    request = at(t, 32.125+sign*turns*tau/(17/16))
    span = Fraction(request.elapsed_seconds)-Fraction(32.125)
    ref, tighter = circle_reference(span, 90), circle_reference(span, 110)
    assert all(abs(x-y) < Decimal('1e-60') for a, b in zip(ref, tighter) for x, y in zip(a, b))
    hs = (1/32, 1/64, 1/128)
    errors, floors = [], []
    for h in hs:
        result = coast.evaluate_j2_cartesian_state(t, request, coast.J2RK4SolverConfig(h, 3000))
        error = tuple(hypot(*(float(abs(Decimal.from_float(x)-y)) for x, y in zip(a, b))) for a, b in zip(components(result), ref))
        rounding = tuple(arithmetic_floor(scale, 17/16, float(span), h)+1e-60 for scale in (2, 17/8))
        truncation = tuple(8*(1+17/16*abs(float(span)))**2*(17/16*h)**4*scale for scale in (2, 17/8))
        assert all(e <= q+r for e, q, r in zip(error, truncation, rounding))
        assert result.position.components_m[2] == result.velocity.components_m_per_s[2] == 0
        errors.append(error); floors.append(rounding)
    for axis in (0, 1):
        assert_fourth_order([e[axis] for e in errors], [e[axis] for e in floors])
    record_property('circle_errors_m_mps', json.dumps(errors))


def invariants(state, model):
    (x, y, _), (vx, vy, vz) = components(state)
    potential = evaluate_j2_gravity(model, state.position).specific_potential_m2_per_s2
    return fsum((vx*vx/2, vy*vy/2, vz*vz/2, potential)), fsum((x*vy, -y*vx))


@pytest.mark.parametrize('sign', [1, -1])
def test_energy_and_axial_momentum_refine_without_exact_conservation(sign, record_property):
    t = trajectory(v=(0, 1.5, 1), j2=1/128)
    initial = invariants(t.initial_state, t.gravity_model)
    errors = []
    for h in (1/8, 1/16, 1/32):
        result = evaluate(t, 32.125+sign*4, h)
        errors.append(tuple(abs(x-y) for x, y in zip(invariants(result, t.gravity_model), initial)))
    for axis in (0, 1):
        # Symmetry can improve RK4 invariant drift to fifth order; allow both
        # fourth/fifth-order behavior and finite-h corrections, never exactness.
        assert errors[2][axis] > 256*2**-53*max(1, abs(initial[axis]))
        assert all(8 < a[axis]/b[axis] < 64 for a, b in zip(errors, errors[1:]))
    record_property('invariant_errors_energy_hz', json.dumps(errors))


@pytest.mark.parametrize('sign', [1, -1])
def test_test_only_reanchoring_time_reversal_refines(sign, record_property):
    t = trajectory(v=(0, 1.5, 1), j2=1/128)
    errors = []
    for h in (1/8, 1/16, 1/32):
        endpoint = evaluate(t, 32.125+sign*4, h)
        test_only = coast.J2CartesianTrajectory(endpoint, t.gravity_model)
        back = evaluate(test_only, 32.125, h)
        errors.append(distance(back, t.initial_state))
    for axis in (0, 1):
        assert errors[2][axis] > arithmetic_floor(3, 1, 8, 1/32)
        assert all(8 < a[axis]/b[axis] < 64 for a, b in zip(errors, errors[1:]))
    record_property('reversal_errors_m_mps', json.dumps(errors))


def test_repeat_queries_reversed_order_and_reconstructed_authority_are_exact():
    t = trajectory(v=(0, 1.5, 1), j2=1/128)
    times = (32.625, 31.5, 34.25, 32.625)
    before = (t.initial_state, t.gravity_model)
    forward = tuple(evaluate(t, time) for time in times)
    reverse = tuple(evaluate(t, time) for time in reversed(times))
    assert forward == tuple(reversed(reverse)) and forward[0] == forward[-1]
    assert forward == tuple(evaluate(replace(t), time) for time in times)
    assert before == (t.initial_state, t.gravity_model)


@pytest.mark.parametrize('delta', [0.25, -0.25])
def test_rk4_against_independent_oscillator_stability_polynomial(monkeypatch, delta):
    # For y'=Ay, A^2=-I, classical RK4 has the exact polynomial
    # I+dA+d^2*A^2/2+d^3*A^3/6+d^4*A^4/24. No copied stepper.
    t = trajectory()
    monkeypatch.setattr(coast, '_force', lambda model, anchor, r: tuple(-x for x in r))
    r, v = (2., -1., .5), (.25, 2., -.5)
    result = coast._rk4_step(t.gravity_model, t.initial_state.position, r, v, delta)
    d = Fraction(delta)
    even, odd = 1-d*d/2+d**4/24, d-d**3/6
    expected = (tuple(even*Fraction(x)+odd*Fraction(y) for x, y in zip(r, v)),
                tuple(even*Fraction(y)-odd*Fraction(x) for x, y in zip(r, v)))
    for actual, exact in zip(result, expected):
        for x, y in zip(actual, exact):
            assert abs(Fraction(x)-y) <= 8*Fraction(ulp(float(y)))


@pytest.mark.parametrize('case', ['half-underflow', 'increment-underflow', 'sum-overflow', 'swallowed', 'public-small-step', 'public-overflow'])
def test_unsupported_arithmetic_is_deliberate_value_error(case):
    with pytest.raises(ValueError):
        if case == 'half-underflow': coast._product(2**-1074, .5)
        elif case == 'increment-underflow': coast._advance((0.,), (2**-1074,), .5)
        elif case == 'sum-overflow': coast._sum((2.0**1023, 2.0**1023))
        elif case == 'swallowed': coast._advance((2.0**100,), (1.,), 1.)
        elif case == 'public-small-step': evaluate(trajectory(t0=0), 2**-60, 2**-60)
        else: evaluate(trajectory(v=(2.0**1000, 0, 0), t0=0), 2**40, 2**40)


def test_true_cancellation_and_nonzero_subnormals_are_distinguished():
    assert coast._sum((1., -1.)) == 0
    assert coast._advance((1.,), (-1.,), 1.) == (0.,)
    assert coast._product(2**-1074, 1.) == 2**-1074
    assert coast._advance((0.,), (2**-1074,), 1.) == (2**-1074,)
    t = trajectory(v=(2**-1074, 0, 0))
    assert evaluate(t, 32.125) == t.initial_state


def node_angle(state):
    (x, y, z), (vx, vy, vz) = components(state)
    hx, hy = y*vz-z*vy, z*vx-x*vz
    return atan2(hx, -hy)


def test_small_j2_nodal_sign_and_scaling_are_approximation_diagnostics(record_property):
    # Predeclared BEFORE probes: mu1,r1,Rg.5,v=(0,.6,.8), epsilon<=2^-19,
    # nT<=64*pi. NASA Rickman slides105-106: dOmega/dt=-1.5*epsilon*n*cos(i).
    # Direct circular torque integration adds sin(2*nT)/2 to the secular term,
    # relative envelope<=1/(2*nT). A declared 20*epsilon*nT higher-order reserve
    # plus that periodic envelope is <2%. This reserve is NOT a proved bound.
    # Test policy: 2% approximation allowance, separately .1% integration
    # allowance assessed with h=.05,.025,.0125. No orbital coefficient default.
    reports = []
    for j2 in (2**-18, 2**-17):
        for turns in (16, 32):
            t = trajectory(r=(1, 0, 0), v=(0, .6, .8), t0=0, mu=1, rg=.5, j2=j2)
            span = turns*tau
            epsilon = j2/4
            cosi = .6/hypot(.6, .8)
            prediction = -1.5*epsilon*cosi*span
            assert 1/(2*span)+20*epsilon*span < .02
            drifts = [node_angle(evaluate(t, span, h, 20000)) for h in (.05, .025, .0125)]
            # Central RK4 preserves a plane; the nodal integration residual is
            # measured directly. No enforced ratio at the roundoff floor.
            integration = abs(drifts[2]-drifts[1])
            assert integration <= .001*abs(prediction)
            assert integration <= abs(drifts[1]-drifts[0])+256*2**-53*int(span/.0125)
            assert drifts[2] < 0
            assert abs(drifts[2]-prediction) <= .02*abs(prediction)+integration
            reports.append(dict(j2=j2, turns=turns, prediction_rad=prediction,
                                measured_rad=drifts[2], refinement_rad=integration))
    for a, b in ((reports[0], reports[1]), (reports[0], reports[2]), (reports[1], reports[3])):
        # Doubling span or J2 doubles the first-order prediction; allowance is
        # propagated from each approximation/numerical term, not a tuned ratio.
        budget = .02*(abs(b['prediction_rad'])+2*abs(a['prediction_rad']))
        budget += b['refinement_rad']+2*a['refinement_rad']
        assert abs(b['measured_rad']-2*a['measured_rad']) <= budget
    record_property('secular_diagnostic', json.dumps(reports))
