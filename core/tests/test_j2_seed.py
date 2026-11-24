"""B12 bounded search contract; analytic references are exact rational bounds."""
from dataclasses import replace
from decimal import Decimal, DivisionByZero, Inexact, ROUND_UP, localcontext
from fractions import Fraction
import json
from pathlib import Path

import pytest

from examples.v5_j2_enclosure_pilot import inputs
from ops_sim.v5 import orbit_j2_enclosure as enc
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_j2 import J2RK4SolverConfig
from ops_sim.v5.orbit_sun_local_document import local_request_from_json

RADIUS_REASON = "continuous tube cannot establish the radius floor"


def b11():
    fixture = json.loads((Path(__file__).parent / "fixtures/m2_b11_incoming_box.json").read_text(encoding="utf-8"))
    q = local_request_from_json(json.dumps(fixture["h5_input_document"], ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    box = [enc._I(Decimal(lo), Decimal(hi)) for lo, hi in fixture["boundary"]["state_bounds"]]
    return fixture, box, q.coast.trajectory.gravity_model, q.coast.enclosure_policy


def synthetic(floor=1.8, budget=12):
    ar = enc._Arithmetic(50)
    box = [enc._I(Decimal("1.91"), Decimal("2.91"))] + [
        ar.point(x) for x in (0, 0, 0, 17/8, 0)]
    return box, inputs(True).gravity_model, enc.J2EnclosurePolicy(1/1024, 1, floor, 50, budget), ar


def contains(outer, inner):
    return len(outer) == len(inner) and all(b.lo <= a.lo and a.hi <= b.hi for a, b in zip(inner, outer))


def forbidden(*args, **kwargs):
    pytest.fail("forbidden fallback/RHS invocation")


def test_fixture_is_exact_local_set_not_checkpoint():
    f, box, _, p = b11()
    assert f["archive_sha256"] == "516c70384dd94c0eeb322f06d93fd9768c0938418fc1114471ac57aff48786bb"
    assert f["result_sha256"] == "a0ac2a8c910e886c8f75223e31e0ebd83861bf3d801742acf6e0419db398055f"
    assert f["boundary"]["id"] == 3450 and f["local_absolute_span_seconds"] == [17378, 17383]
    t = f["boundary"]["elapsed_seconds"]
    assert Fraction(int(t["numerator_hex"], 16), int(t["denominator_hex"], 16)) == 17378
    assert len(box) == 6 and p == enc.J2EnclosurePolicy(5, 4096, 6000000, 50, 12)
    assert "NOT a checkpoint" in f["purpose"]


def test_b11_original_rejection_and_alternative_full_set_admission():
    _, box, _, p = b11()
    ar = enc._Arithmetic(p.precision_digits)
    enc._domain(box, p, ar)
    with pytest.raises(enc._Unresolved, match=RADIUS_REASON):
        enc._domain(enc._inflate(box, ar), p, ar)
    seed = enc._alternative_seed(box, ar)
    assert contains(seed, box)
    enc._domain(seed, p, ar)


@pytest.mark.parametrize("budget", [2, 12, 16])
def test_b11_actual_step_includes_original_rejection_in_budget(budget):
    _, box, model, p = b11()
    p = replace(p, max_picard_iterations=budget)
    ar = enc._Arithmetic(50)
    endpoint, tube, attempts = enc._step_with_tube(box, ar.point(5), model, p, ar)
    assert attempts == ar.picard_attempts == 2
    assert tube == enc._alternative_seed(box, ar)
    enc._domain(endpoint, p, ar)
    field = enc._field([[a] for a in tube], model, ar)
    time = enc._I(Decimal(0), Decimal(5))
    image = [ar.add(a, ar.mul(time, field[i][0])) for i, a in enumerate(box)]
    assert all(b.lo < a.lo and a.hi < b.hi for a, b in zip(image, tube))


def test_budget_one_has_no_alternative_or_rhs(monkeypatch):
    _, box, model, p = b11()
    ar = enc._Arithmetic(50)
    monkeypatch.setattr(enc, "_alternative_seed", forbidden)
    monkeypatch.setattr(enc, "_field", forbidden)
    with pytest.raises(enc._Unresolved, match=RADIUS_REASON):
        enc._tube(box, ar.point(5), model, replace(p, max_picard_iterations=1), ar)
    assert ar.picard_attempts == 1


def test_attempt_counter_does_not_reset_prior_steps():
    _, box, model, p = b11()
    ar = enc._Arithmetic(50)
    ar.picard_attempts = 23
    _, attempts = enc._tube(box, ar.point(5), model, p, ar)
    assert attempts == 2 and ar.picard_attempts == 25


def test_invalid_incoming_has_no_alternative_or_rhs(monkeypatch):
    box, model, p, ar = synthetic(floor=2)
    monkeypatch.setattr(enc, "_alternative_seed", forbidden)
    monkeypatch.setattr(enc, "_field", forbidden)
    with pytest.raises(enc._Unresolved, match=RADIUS_REASON):
        enc._tube(box, ar.point(1/1024), model, p, ar)
    assert ar.picard_attempts == 1


def test_inadmissible_alternative_is_charged_once_without_second_seed(monkeypatch):
    box, model, p, ar = synthetic(floor=1.87)
    original = enc._alternative_seed
    calls = []
    def alternative(b, a):
        calls.append(b)
        return original(b, a)
    monkeypatch.setattr(enc, "_alternative_seed", alternative)
    monkeypatch.setattr(enc, "_field", forbidden)
    enc._domain(box, p, ar)
    with pytest.raises(enc._Unresolved, match=RADIUS_REASON):
        enc._tube(box, ar.point(1/1024), model, p, ar)
    assert calls == [box] and ar.picard_attempts == 2


@pytest.mark.parametrize("invalid", ["shrunk", "short"])
def test_noncontaining_alternative_rejected_before_domain_trial(monkeypatch, invalid):
    box, model, p, ar = synthetic()
    seed = enc._alternative_seed(box, ar)
    if invalid == "short":
        seed = seed[:-1]
    else:
        seed[0] = enc._I(Decimal(2), Decimal("2.5"))
    monkeypatch.setattr(enc, "_alternative_seed", lambda b, a: seed)
    monkeypatch.setattr(enc, "_field", forbidden)
    with pytest.raises(enc._Unresolved, match="does not contain incoming box"):
        enc._tube(box, ar.point(1/1024), model, p, ar)
    assert ar.picard_attempts == 1


@pytest.mark.parametrize("lo,hi", [("0", "0"), ("-7", "-3"), ("1.91", "2.91"),
                                 ("1e40", "1.0000000000000000000000000000000000000000000000001e40")])
def test_alternative_padding_brackets_independent_exact_rational_formula(lo, hi):
    a = enc._I(Decimal(lo), Decimal(hi))
    seed = enc._alternative_seed([a], enc._Arithmetic(50))[0]
    scale = max(Fraction(1), abs(Fraction(a.lo)), abs(Fraction(a.hi)))
    pad = (Fraction(a.hi) - Fraction(a.lo))/16 + scale/Fraction(10**30)
    assert Fraction(seed.lo) <= Fraction(a.lo)-pad
    assert Fraction(seed.hi) >= Fraction(a.hi)+pad
    assert contains([seed], [a])


@pytest.mark.parametrize("sign", [1, -1])
def test_alternative_encloses_independent_exact_circle_whole_arc_and_endpoint(sign):
    box, model, p, ar = synthetic()
    assert model.gravitational_parameter_m3_s2.value == 8
    assert model.j2.value == 11/32 and model.reference_radius_m.value == 1
    h = Fraction(sign, 1024)
    endpoint, tube, attempts = enc._step_with_tube(box, ar.point(float(h)), model, p, ar)
    assert attempts == ar.picard_attempts and 2 <= attempts <= p.max_picard_iterations
    # At z=0,r=2: n^2=mu/r^3*(1+3*J2*Rg^2/(2*r^2))=289/256.
    # For |tau|<=H and nH<1: 1-theta^2/2<=cos(theta)<=1, 0<=sin(theta)<=theta.
    # These exact inequalities cover the WHOLE arc, not a sampled orbit.
    n, H = Fraction(17, 16), abs(h)
    theta = n*H
    assert theta < 1
    whole = [(2-theta**2, Fraction(2)), (Fraction(0), 2*n*H),
             (Fraction(0), Fraction(0)), (-2*n*n*H, Fraction(0)),
             (2*n-n**3*H**2, 2*n), (Fraction(0), Fraction(0))]
    if sign < 0:
        for i in (1, 3):
            lo, hi = whole[i]
            whole[i] = (-hi, -lo)
    for interval, (lo, hi) in zip(tube, whole):
        assert Fraction(interval.lo) <= lo <= hi <= Fraction(interval.hi)
    # Independent endpoint oracle: Taylor polynomials + exact Lagrange bound.
    # Use degree 19; sin/cos twentieth derivatives have magnitude <=1.
    angle = n*h
    def trig(cosine):
        total = Fraction(0)
        fact = 1
        for k in range(20):
            if k:
                fact *= k
            if k % 2 == (0 if cosine else 1):
                total += (-1)**(k//2)*angle**k/fact
        fact *= 20
        error = abs(angle)**20/fact
        return total-error, total+error
    c, s = trig(True), trig(False)
    reference = [(2*c[0], 2*c[1]), (2*s[0], 2*s[1]), (Fraction(0), Fraction(0)),
                 (-2*n*s[1], -2*n*s[0]), (2*n*c[0], 2*n*c[1]), (Fraction(0), Fraction(0))]
    for interval, (lo, hi) in zip(endpoint, reference):
        assert Fraction(interval.lo) <= lo <= hi <= Fraction(interval.hi)


def test_alternative_and_negative_step_ignore_hostile_ambient_context():
    def evaluate():
        box, model, p, ar = synthetic()
        return enc._step_with_tube(box, ar.point(-1/1024), model, p, ar), ar.picard_attempts
    expected = evaluate()
    with localcontext() as c:
        c.prec = 3
        c.rounding = ROUND_UP
        c.traps[Inexact] = True
        assert evaluate() == expected


def test_strict_inclusion_equality_does_not_accept_or_reset_budget(monkeypatch):
    box, model, p, ar = synthetic(budget=2)
    seed = enc._alternative_seed(box, ar)
    # Image reaches upper seed face exactly at h=1. Non-strict containment is insufficient.
    def field(series, m, a):
        rhs = [[a.point(a.up.subtract(b.hi, x.hi))] for b, x in zip(seed, box)]
        time = enc._I(Decimal(0), Decimal(1))
        image = [a.add(x, a.mul(time, f[0])) for x, f in zip(box, rhs)]
        assert all(x.hi == b.hi and b.lo < x.lo for x, b in zip(image, seed))
        return rhs
    monkeypatch.setattr(enc, "_field", field)
    with pytest.raises(enc._Unresolved, match="Picard inclusion work exhausted"):
        enc._tube(box, ar.point(1), model, p, ar)
    assert ar.picard_attempts == 2


@pytest.mark.parametrize("error", [enc._Unresolved("other guard"), DivisionByZero("arithmetic guard")])
def test_unrelated_first_domain_failures_have_no_fallback(monkeypatch, error):
    box, model, p, ar = synthetic()
    def domain(*args):
        raise error
    monkeypatch.setattr(enc, "_domain", domain)
    monkeypatch.setattr(enc, "_alternative_seed", forbidden)
    with pytest.raises(type(error), match=str(error)):
        enc._tube(box, ar.point(1/1024), model, p, ar)
    assert ar.picard_attempts == 1


def test_later_radius_failure_has_no_fallback(monkeypatch):
    tr = inputs(True)
    ar = enc._Arithmetic(50)
    box = [ar.point(x) for x in (*tr.initial_state.position.components_m, *tr.initial_state.velocity.components_m_per_s)]
    p = enc.J2EnclosurePolicy(1/32, 1, .5, 50, 12)
    original = enc._domain
    calls = 0
    def domain(b, p, a):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise enc._Unresolved(RADIUS_REASON)
        return original(b, p, a)
    monkeypatch.setattr(enc, "_domain", domain)
    monkeypatch.setattr(enc, "_alternative_seed", forbidden)
    with pytest.raises(enc._Unresolved, match=RADIUS_REASON):
        enc._tube(box, ar.point(1/32), tr.gravity_model, p, ar)
    assert calls == ar.picard_attempts == 2


@pytest.mark.parametrize("stage", ["seed", "rhs", "taylor", "endpoint"])
def test_later_arithmetic_or_endpoint_failure_never_restarts(monkeypatch, stage):
    _, box, model, p = b11()
    ar = enc._Arithmetic(50)
    alt = enc._alternative_seed
    calls = 0
    def seed(b, a):
        nonlocal calls
        calls += 1
        if stage == "seed":
            raise DivisionByZero("seed arithmetic")
        return alt(b, a)
    monkeypatch.setattr(enc, "_alternative_seed", seed)
    if stage == "rhs":
        def field(*args):
            raise DivisionByZero("RHS arithmetic")
        monkeypatch.setattr(enc, "_field", field)
    if stage == "taylor":
        def coefficients(*args):
            raise DivisionByZero("Taylor arithmetic")
        monkeypatch.setattr(enc, "_coefficients", coefficients)
    if stage == "endpoint":
        original = enc._domain
        domain_calls = 0
        def domain(b, p, a):
            nonlocal domain_calls
            domain_calls += 1
            if domain_calls == 4:  # rejected initial, incoming, alternative, endpoint
                raise enc._Unresolved(RADIUS_REASON)
            return original(b, p, a)
        monkeypatch.setattr(enc, "_domain", domain)
    with pytest.raises(enc._Unresolved if stage == "endpoint" else DivisionByZero):
        enc._step_with_tube(box, ar.point(5), model, p, ar)
    assert calls == 1 and ar.picard_attempts == (1 if stage == "seed" else 2)


@pytest.mark.parametrize("failure", [enc._Unresolved(RADIUS_REASON), DivisionByZero("arithmetic")])
def test_public_failure_after_partial_work_publishes_no_success(monkeypatch, failure):
    tr = inputs(True)
    instant = GeometryInstant(tr.initial_state.position.instant.epoch, 128+1/32)
    def step(*args):
        args[-1].picard_attempts += 2
        raise failure
    monkeypatch.setattr(enc, "_step", step)
    result = enc.evaluate_j2_enclosure(tr, instant, J2RK4SolverConfig(1/32, 1),
                                       enc.J2EnclosurePolicy(1/32, 1, .5, 50, 12))
    assert result.status == "unresolved" and result.reason == str(failure)
    assert result.picard_attempts == 2 and result.enclosure_steps == result.nominal_steps == 0
    assert result.nominal_state is result.endpoint_intervals is None
    assert result.position_error_bound_m is result.velocity_error_bound_m_per_s is None

