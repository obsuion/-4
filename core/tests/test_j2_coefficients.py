"""B27 bounded coefficient gates: compatibility is separate from references.

No public endpoint API is exercised here. Potential differentiation and circle
Taylor coefficients are exact rational references; they do not prove universal
interval inclusion. The general inclusion argument belongs to the contract.
"""

import ast
from decimal import (Decimal, DecimalException, Inexact, ROUND_UP, localcontext,
                     ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_EVEN,
                     DivisionByZero, InvalidOperation, Overflow, Underflow,
                     Subnormal)
from fractions import Fraction as Q
from math import factorial, isqrt
from pathlib import Path

import pytest

from ops_sim.v5 import orbit_j2_enclosure as old
from ops_sim.v5 import orbit_j2_zonotope as z
from test_v56f1_j2_gravity_contracts import make_model, forge


CAP = 2**31
CASES = (
    (("2.00", "2.00"), ("-0.000", "0.000"), ("0", "0"),
     ("0", "0"), ("2.0", "2.0"), ("0", "0")),
    (("1", "1"), ("2", "2"), ("2", "2"),
     (".25", ".25"), ("-.5", "-.5"), (".125", ".125")),
    (("1.75", "2.25"), ("-.25", ".25"), ("-.125", ".125"),
     ("-.2", ".1"), ("1.8", "2.2"), ("-.05", ".05")),
)
ERRORS = (old._Unresolved, TypeError, ValueError)


def ledger(precision=50, cap=CAP):
    return z._CoefficientArithmeticV3(precision, cap)


def box(ar, bounds=CASES[0]):
    return tuple(old._I(ar.point(Decimal(a)).lo, ar.point(Decimal(b)).hi)
                 for a, b in bounds)


def representation(series):
    # Decimal tuple comparison retains signs of zero and coefficient exponents.
    return tuple(tuple((Decimal(v.lo).as_tuple(), Decimal(v.hi).as_tuple())
                       for v in coordinate) for coordinate in series)


def bounds_copy(value):
    return tuple((Decimal(a.lo).as_tuple(), Decimal(a.hi).as_tuple()) for a in value)


def invoke(bounds=CASES[0], order=7, j2=0, precision=50):
    ar = ledger(precision)
    incoming = box(ar, bounds)
    answer = z._coefficients_incremental_v1(incoming, order, make_model(j2=j2), ar)
    return incoming, answer, ar


@pytest.mark.parametrize("case", range(len(CASES)))
@pytest.mark.parametrize("j2", [0, 11/32, -11/32])
@pytest.mark.parametrize("precision", [40, 50, 80])
@pytest.mark.parametrize("order", [6, 7])
def test_exact_legacy_endpoint_representations_at_every_prefix(case, j2, precision, order):
    new_ar, legacy_ar = ledger(precision), z._ArithmeticV2(precision, CAP)
    incoming, legacy_box = box(new_ar, CASES[case]), box(legacy_ar, CASES[case])
    before = bounds_copy(incoming)
    model = make_model(j2=j2)
    result = z._coefficients_incremental_v1(incoming, order, model, new_ar)
    expected = old._coefficients(legacy_box, order, model, legacy_ar)
    assert type(result) is list and len(result) == 6
    assert all(type(s) is list and len(s) == order+1 for s in result)
    for degree in range(order+1):
        assert representation([s[:degree+1] for s in result]) == representation(
            [s[:degree+1] for s in expected])
    assert bounds_copy(incoming) == before
    assert new_ar.operations == new_ar.leaf_operations+new_ar.reserved_units
    assert new_ar.operations <= new_ar.limit and not new_ar.rejected
    assert all(type(e) is z._D and e._ar is new_ar
               for s in result for a in s for e in (a.lo, a.hi))


def circular_coefficients(order):
    # mu=8, radius=2, velocity=2 yields exact angular frequency 1 rad/s.
    cosine = [Q(0) if k % 2 else Q(2*(-1)**(k//2), factorial(k))
              for k in range(order+1)]
    sine = [Q(0) if not k % 2 else Q(2*(-1)**((k-1)//2), factorial(k))
            for k in range(order+1)]
    return cosine, sine, [Q(0)]*(order+1), [-v for v in sine], cosine, [Q(0)]*(order+1)


@pytest.mark.parametrize("precision", [40, 50, 80])
@pytest.mark.parametrize("order", [6, 7])
def test_zero_j2_circle_contains_independent_complete_taylor_reference(precision, order):
    _, answer, _ = invoke(precision=precision, order=order)
    for actual, exact in zip(answer, circular_coefficients(order)):
        for interval, coefficient in zip(actual, exact):
            assert Q(Decimal(interval.lo)) <= coefficient <= Q(Decimal(interval.hi))


class PotentialJet:
    """Exact scalar value, gradient and Hessian; not production force code."""

    def __init__(self, value, gradient=(0, 0, 0), hessian=((0, 0, 0),)*3):
        self.value = Q(value)
        self.gradient = tuple(map(Q, gradient))
        self.hessian = tuple(tuple(map(Q, row)) for row in hessian)

    @classmethod
    def variable(cls, value, axis):
        return cls(value, tuple(int(i == axis) for i in range(3)))

    def __add__(self, other):
        other = other if isinstance(other, PotentialJet) else PotentialJet(other)
        return PotentialJet(self.value+other.value,
            tuple(a+b for a, b in zip(self.gradient, other.gradient)),
            tuple(tuple(self.hessian[i][j]+other.hessian[i][j]
                        for j in range(3)) for i in range(3)))

    __radd__ = __add__

    def __neg__(self):
        return PotentialJet(-self.value, tuple(-v for v in self.gradient),
                            tuple(tuple(-v for v in row) for row in self.hessian))

    def __sub__(self, other):
        return self+-other if isinstance(other, PotentialJet) else self+(-Q(other))

    def __mul__(self, other):
        other = other if isinstance(other, PotentialJet) else PotentialJet(other)
        return PotentialJet(self.value*other.value,
            tuple(self.gradient[i]*other.value+self.value*other.gradient[i]
                  for i in range(3)),
            tuple(tuple(self.hessian[i][j]*other.value+
                        self.gradient[i]*other.gradient[j]+
                        self.gradient[j]*other.gradient[i]+
                        self.value*other.hessian[i][j]
                        for j in range(3)) for i in range(3)))

    __rmul__ = __mul__

    def half_power(self, twice_exponent):
        numerator, denominator = isqrt(self.value.numerator), isqrt(self.value.denominator)
        assert numerator*numerator == self.value.numerator
        assert denominator*denominator == self.value.denominator
        root, alpha = Q(numerator, denominator), Q(twice_exponent, 2)
        value = root**twice_exponent
        first = alpha*value/self.value
        second = alpha*(alpha-1)*value/self.value**2
        return PotentialJet(value, tuple(first*v for v in self.gradient),
            tuple(tuple(first*self.hessian[i][j]+second*self.gradient[i]*self.gradient[j]
                        for j in range(3)) for i in range(3)))


def force_jerk_from_potential(position, velocity, j2):
    x, y, vertical = (PotentialJet.variable(v, i) for i, v in enumerate(position))
    q = x*x+y*y+vertical*vertical
    # Phi=-mu/r + mu J2 Rg^2/2 (3 z^2/r^5 - 1/r^3).
    potential = -8*q.half_power(-1)+(Q(8)*j2/2)*(
        3*vertical*vertical*q.half_power(-5)-q.half_power(-3))
    force = tuple(-v for v in potential.gradient)
    jerk = tuple(-sum((potential.hessian[i][j]*velocity[j] for j in range(3)), Q(0))
                 for i in range(3))
    return force, jerk


@pytest.mark.parametrize("position", [(1, 2, 2), (2, 3, 6)])
@pytest.mark.parametrize("j2", [Q(0), Q(11, 32), Q(-11, 32)])
@pytest.mark.parametrize("precision", [40, 50, 80])
@pytest.mark.parametrize("order", [6, 7])
def test_signed_j2_force_jerk_reference_from_independent_potential(position, j2, precision, order):
    velocity = (Q(1, 4), Q(-1, 2), Q(1, 8))
    values = (*position, *velocity)
    bounds = tuple((str(float(v)), str(float(v))) for v in values)
    _, answer, _ = invoke(bounds, order=order, j2=float(j2), precision=precision)
    force, jerk = force_jerk_from_potential(position, velocity, j2)
    for i in range(3):
        for axis, degree, expected in ((i+3, 1, force[i]), (i, 2, force[i]/2),
                                      (i+3, 2, jerk[i]/2), (i, 3, jerk[i]/6)):
            assert Q(Decimal(answer[axis][degree].lo)) <= expected <= Q(Decimal(answer[axis][degree].hi))


@pytest.mark.parametrize("order", [6, 7])
@pytest.mark.parametrize("j2", [0, 11/32, -11/32])
def test_hostile_ambient_context_cannot_change_success_representations(order, j2):
    expected = representation(invoke(order=order, j2=j2)[1])
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_UP
        ambient.Emax, ambient.Emin = 3, -3
        ambient.traps[Inexact] = True
        actual = representation(invoke(order=order, j2=j2)[1])
    assert actual == expected


@pytest.mark.parametrize("order", [True, False, 0, 5, 8, 7.0, "7", None])
def test_only_exact_orders_six_and_seven_admitted(order):
    ar = ledger()
    incoming = box(ar)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, order, make_model(), ar)


@pytest.mark.parametrize("count", [0, 5, 7])
def test_exactly_six_intervals_required(count):
    ar = ledger()
    incoming = tuple(ar.point(2) for _ in range(count))
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, make_model(), ar)


@pytest.mark.parametrize("kind", ["foreign", "raw", "nonfinite", "reversed", "wrong_interval"])
def test_owned_finite_ordered_intervals_required_before_arithmetic(monkeypatch, kind):
    ar, foreign = ledger(), ledger()
    incoming = list(box(ar))
    if kind == "foreign":
        incoming[0] = foreign.point(2)
    elif kind == "raw":
        incoming[0] = old._I(Decimal(2), Decimal(2))
    elif kind == "nonfinite":
        incoming[0] = old._I(z._D("NaN", ar), z._D("Infinity", ar))
    elif kind == "reversed":
        incoming[0] = old._I(ar.point(3).lo, ar.point(2).hi)
    else:
        incoming[0] = (incoming[0].lo, incoming[0].hi)
    called = []
    def forbidden(*args):
        called.append(args)
        raise AssertionError("field arithmetic ran before interval admission")
    monkeypatch.setattr(ar, "mul", forbidden)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(tuple(incoming), 6, make_model(), ar)
    assert called == []


@pytest.mark.parametrize("owner", [z._Arithmetic, z._ArithmeticV2])
def test_old_accounting_identity_not_accepted(owner):
    ar = owner(50)
    incoming = box(ar)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, make_model(), ar)


@pytest.mark.parametrize("precision", [True, 39, 81, 50.0, "50"])
def test_new_closed_arithmetic_precision_admission(precision):
    with pytest.raises((TypeError, ValueError)):
        ledger(precision)


@pytest.mark.parametrize("cap", [True, 0, -1, 2**31+1, 2.0, "4"])
def test_new_closed_arithmetic_ceiling_admission(cap):
    with pytest.raises((TypeError, ValueError)):
        ledger(cap=cap)


def test_closed_bootstrap_does_not_construct_or_top_up_old_ledgers(monkeypatch):
    def forbidden(*args):
        raise AssertionError("legacy ledger bootstrap was called")
    monkeypatch.setattr(z._Arithmetic, "__init__", forbidden)
    monkeypatch.setattr(z._ArithmeticV2, "__init__", forbidden)
    ar = ledger(80)
    assert ar.limit == CAP
    assert ar.operations == ar.leaf_operations == ar.reserved_units == 0
    assert ar.down._context.prec == ar.up._context.prec == ar.nearest._context.prec == 80
    assert (ar.down._context.rounding, ar.up._context.rounding,
            ar.nearest._context.rounding) == (ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_EVEN)
    for context in (ar.down._context, ar.up._context, ar.nearest._context):
        assert context.Emin == -200 and context.Emax == 200 and context.clamp == 0
        assert all(context.traps[trap] for trap in
                   (InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal))


class ContextSpy:
    def __init__(self, native, ar):
        self.native, self.ar, self.calls = native, ar, []

    def __getattr__(self, name):
        native = getattr(self.native, name)
        if not callable(native):
            return native
        def call(*args, **kwargs):
            self.calls.append((name, self.ar.operations, self.ar.leaf_operations))
            return native(*args, **kwargs)
        return call


def test_context_leaf_charges_precede_native_work_and_exhaustion_latches():
    ar = ledger(cap=128)
    spy = ContextSpy(ar.down._context, ar)
    ar.down._context = spy
    before = ar.operations
    actual = ar.down.add(Decimal(1), Decimal(2))
    assert Decimal(actual) == 3
    assert spy.calls == [("add", before+3, before+3)]
    assert ar.operations-before == 5
    ar.reserve(ar.limit-ar.operations, "synthetic remaining-cap admission")
    frozen = (ar.operations, ar.leaf_operations, ar.reserved_units)
    with pytest.raises(old._Unresolved, match="exhausted"):
        ar.down.add(Decimal(1), Decimal(2))
    assert len(spy.calls) == 1 and ar.rejected
    for action in (lambda: ar.charge(0), lambda: ar.reserve(0, "cannot unlatch"),
                   lambda: ar.point(0)):
        with pytest.raises(old._Unresolved, match="already rejected"):
            action()
    assert frozen == (ar.operations, ar.leaf_operations, ar.reserved_units)


def test_rational_conversion_rejects_before_unbounded_fraction_construction(monkeypatch):
    ar = ledger()
    called = []
    original = z.Fraction
    def fraction_spy(*args):
        called.append(args)
        return original(*args)
    monkeypatch.setattr(z, "Fraction", fraction_spy)
    with pytest.raises(old._Unresolved, match="4096"):
        z._fraction(Decimal("1e1300"), ar)
    assert called == []


def test_sqrt_bracket_is_independently_rational_and_charged():
    ar = ledger()
    incoming = old._I(ar.point(2).lo, ar.point(3).hi)
    before = ar.operations
    result = ar.sqrt(incoming)
    assert Q(Decimal(result.lo))**2 <= 2 and Q(Decimal(result.hi))**2 >= 3
    assert ar.operations-before == 190
    assert ar.operations == ar.leaf_operations+ar.reserved_units


@pytest.mark.parametrize("bounds", [(("0", "0"),)*6,
    (("-1", "1"), ("-1", "1"), ("-1", "1"), ("0", "0"), ("0", "0"), ("0", "0"))])
def test_radius_interval_must_exclude_zero(bounds):
    ar = ledger()
    incoming = box(ar, bounds)
    before = bounds_copy(incoming)
    with pytest.raises(old._Unresolved):
        z._coefficients_incremental_v1(incoming, 7, make_model(), ar)
    assert bounds_copy(incoming) == before


def test_denominator_and_explicit_context_traps_remain_guarded():
    ar = ledger()
    with pytest.raises(old._Unresolved, match="zero"):
        ar.div(ar.point(1), old._I(ar.point(-1).lo, ar.point(1).hi))
    with pytest.raises(DecimalException):
        ar.up.multiply(Decimal("1e200"), Decimal("1e200"))
    with pytest.raises(DecimalException):
        ar.down.multiply(Decimal("1e-200"), Decimal("1e-200"))


def test_discarded_degree_zero_product_precedes_square_override(monkeypatch):
    ar = ledger()
    incoming = box(ar, CASES[1])
    positions = {id(a): i for i, a in enumerate(incoming[:3])}
    events = []
    mul, square = ar.mul, ar.square
    def mul_spy(a, b):
        if id(a) == id(b) and id(a) in positions:
            events.append(("discarded-product", positions[id(a)]))
        return mul(a, b)
    def square_spy(a):
        if id(a) in positions:
            events.append(("square", positions[id(a)]))
        return square(a)
    monkeypatch.setattr(ar, "mul", mul_spy)
    monkeypatch.setattr(ar, "square", square_spy)
    z._coefficients_incremental_v1(incoming, 7, make_model(j2=11/32), ar)
    for axis in range(3):
        assert events.count(("square", axis)) == 1
        assert events.index(("discarded-product", axis)) < events.index(("square", axis))


def test_final_velocity_extension_failure_is_atomic_and_input_unchanged(monkeypatch):
    ar = ledger()
    incoming = box(ar, CASES[1])  # q0=9 avoids other divisors equalling7.
    before = bounds_copy(incoming)
    original, seventh_divisions, published = ar.div, [], []
    def fail_last_axis(a, b):
        if Decimal(b.lo) == Decimal(b.hi) == 7:
            seventh_divisions.append(a)
            if len(seventh_divisions) == 6:
                raise old._Unresolved("synthetic final-axis extension failure")
        return original(a, b)
    monkeypatch.setattr(ar, "div", fail_last_axis)
    with pytest.raises(old._Unresolved, match="synthetic final-axis"):
        published.append(z._coefficients_incremental_v1(incoming, 7, make_model(j2=11/32), ar))
    assert len(seventh_divisions) == 6 and published == []
    assert bounds_copy(incoming) == before
    assert ar.operations == ar.leaf_operations+ar.reserved_units


def test_late_real_work_ceiling_failure_never_publishes_partial_series():
    _, _, complete = invoke(CASES[1], j2=11/32)
    ar = ledger(cap=complete.operations-1)
    incoming = box(ar, CASES[1])
    before, published = bounds_copy(incoming), []
    with pytest.raises(old._Unresolved, match="exhausted"):
        published.append(z._coefficients_incremental_v1(incoming, 7, make_model(j2=11/32), ar))
    assert published == [] and ar.rejected
    assert ar.operations <= ar.limit and ar.leaf_operations > complete.leaf_operations//2
    assert bounds_copy(incoming) == before


def test_invocation_local_state_does_not_cross_reuse_queries_or_different_orders():
    first = representation(invoke(CASES[0], order=6, j2=11/32)[1])
    _, unrelated, other = invoke(CASES[2], order=7, j2=-11/32, precision=80)
    assert all(a.lo._ar is other for s in unrelated for a in s)
    assert representation(invoke(CASES[0], order=6, j2=11/32)[1]) == first
    ar = ledger()
    incoming = box(ar)
    b = ar.operations
    left = z._coefficients_incremental_v1(incoming, 6, make_model(j2=11/32), ar)
    first_cost = ar.operations-b
    b = ar.operations
    right = z._coefficients_incremental_v1(incoming, 6, make_model(j2=11/32), ar)
    assert ar.operations-b == first_cost and representation(left) == representation(right)
    assert all(a is not b for s, t in zip(left, right) for a, b in zip(s[1:], t[1:]))


def test_new_kernel_has_no_global_or_nonlocal_cache_binding():
    tree = ast.parse(Path(z.__file__).read_text(encoding="utf-8"))
    owner = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "_coefficients_incremental_v1")
    assert not any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(owner))


@pytest.mark.parametrize("field,value", [
    ("gravitational_parameter_m3_s2", 0.0),
    ("gravitational_parameter_m3_s2", float("nan")),
    ("reference_radius_m", -1.0),
    ("j2", float("inf")),
])
def test_forged_model_numeric_authority_is_rejected_before_field_work(monkeypatch, field, value):
    ar = ledger()
    incoming = box(ar)
    model = make_model()
    forged_parameter = forge(getattr(model, field), value=value)
    model = forge(model, **{field: forged_parameter})
    calls = []
    def forbidden(*args):
        calls.append(args)
        raise AssertionError("field arithmetic preceded model admission")
    monkeypatch.setattr(ar, "mul", forbidden)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, model, ar)
    assert calls == []


@pytest.mark.parametrize("mutator", [
    lambda ar: setattr(ar.down._context, "prec", 39),
    lambda ar: setattr(ar.up._context, "rounding", ROUND_UP),
    lambda ar: setattr(ar.nearest._context, "Emax", 201),
    lambda ar: setattr(ar.down._context, "Emin", -201),
    lambda ar: ar.up._context.traps.__setitem__(InvalidOperation, False),
    lambda ar: setattr(ar.nearest, "_ar", ledger()),
])
def test_forged_context_or_context_ownership_is_rejected_before_field_work(monkeypatch, mutator):
    ar = ledger()
    incoming = box(ar)
    mutator(ar)
    calls = []
    def forbidden(*args):
        calls.append(args)
        raise AssertionError("field arithmetic preceded context admission")
    monkeypatch.setattr(ar, "mul", forbidden)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, make_model(), ar)
    assert calls == []


def test_shared_arithmetic_identity_cannot_be_substituted_by_v3_subclass():
    derived = type("DerivedCoefficientLedger", (z._CoefficientArithmeticV3,), {})
    ar = derived(50, CAP)
    incoming = box(ar)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, make_model(), ar)


def test_interval_subclass_cannot_substitute_declared_box_authority():
    derived = type("DerivedInterval", (old._I,), {})
    ar = ledger()
    incoming = list(box(ar))
    incoming[0] = derived(incoming[0].lo, incoming[0].hi)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(tuple(incoming), 6, make_model(), ar)


@pytest.mark.parametrize("value", [1, True, Decimal("1"), Q(1)])
def test_gravity_authority_requires_normalized_float_not_coercible_numeric(value):
    ar = ledger()
    incoming = box(ar)
    model = make_model()
    model = forge(model, gravitational_parameter_m3_s2=forge(
        model.gravitational_parameter_m3_s2, value=value))
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, model, ar)


def test_hostile_numeric_hook_never_runs_during_gravity_admission():
    class Hostile(float):
        def __float__(self):
            raise AssertionError("numeric coercion hook ran")
    ar = ledger()
    incoming = box(ar)
    model = make_model()
    model = forge(model, j2=forge(model.j2, value=Hostile(0.25)))
    with pytest.raises(TypeError):
        z._coefficients_incremental_v1(incoming, 6, model, ar)


@pytest.mark.parametrize("value", [1, True, Decimal("1"), Q(1), float("nan")])
def test_sensitivity_numeric_authority_must_already_be_normalized(value):
    from ops_sim.v5.provenance import SensitivityRange
    ar = ledger()
    incoming = box(ar)
    model = make_model()
    ranges = forge(SensitivityRange(0.0, 2.0), lower=value)
    p = forge(model.j2.provenance, sensitivity_range=ranges)
    model = forge(model, j2=forge(model.j2, provenance=p))
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, model, ar)


@pytest.mark.parametrize("kind", ["signed_zero", "source_order"])
def test_canonical_zero_and_declared_source_order_authority_contract(kind):
    ar = ledger()
    incoming = box(ar)
    model = make_model(j2=0)
    if kind == "signed_zero":
        model = forge(model, j2=forge(model.j2, value=-0.0))
    else:
        p = forge(model.j2.provenance, source_ids=model.j2.provenance.source_ids[::-1])
        model = forge(model, j2=forge(model.j2, provenance=p))
    if kind == "signed_zero":
        with pytest.raises(ERRORS):
            z._coefficients_incremental_v1(incoming, 6, model, ar)
    else:
        # The existing owner preserves declared source-ID order; reversal is
        # valid metadata, not a normalization defect.
        declared = model.j2.provenance.source_ids
        result = z._coefficients_incremental_v1(incoming, 6, model, ar)
        old_ar = z._ArithmeticV2(50, CAP)
        expected = old._coefficients(box(old_ar), 6, model, old_ar)
        assert representation(result) == representation(expected)
        assert model.j2.provenance.source_ids == declared


@pytest.mark.parametrize("name,value", [
    ("kernel_id", "different"), ("resource_policy_version", 2),
    ("resource_policy_version", True), ("operations", -1),
    ("leaf_operations", 1), ("limit", 2**31+1),
])
def test_closed_kernel_identity_and_ledger_balance_are_admitted(name, value):
    ar = ledger()
    incoming = box(ar)
    setattr(ar, name, value)
    with pytest.raises(ERRORS):
        z._coefficients_incremental_v1(incoming, 6, make_model(), ar)


@pytest.mark.parametrize("order", [6, 7])
@pytest.mark.parametrize("j2", [0, 11/32, -11/32])
def test_incremental_arithmetic_schedule_is_truthful_and_does_not_repeat_prefixes(
        monkeypatch, order, j2):
    ar = ledger()
    incoming = box(ar)
    counts = {name: 0 for name in ("mul", "add", "neg", "div", "square", "sqrt", "total")}
    for name in counts:
        original = getattr(ar, name)
        def spy(*args, _original=original, _name=name):
            counts[_name] += 1
            return _original(*args)
        monkeypatch.setattr(ar, name, spy)
    result = z._coefficients_incremental_v1(incoming, order, make_model(j2=j2), ar)
    n, terms, recurrence = order, order*(order+1)//2, order*(order-1)//2
    graph = 8 if j2 == 0 else 14
    top_mul = graph*terms+2*recurrence+(n-1)+3*n
    if j2 != 0:
        top_mul += 9*n+3
    # Each interval divide invokes one accounted interval multiply internally.
    assert counts["mul"] == top_mul+7*n
    assert counts["add"] == graph*terms+recurrence+(3 if j2 == 0 else 9)*n
    assert counts["neg"] == (3 if j2 == 0 else 6)*n
    assert counts["div"] == 7*n
    assert counts["square"] == (3 if j2 == 0 else 4)
    assert counts["sqrt"] == 1
    assert counts["total"] == (graph+2)*n-1
    assert len(result) == 6 and all(len(row) == n+1 for row in result)
    assert ar.operations == ar.leaf_operations+ar.reserved_units
    assert ar.reserved_units >= 512+8*(28*n+70)+1024*n*(n+1)//2


def test_successful_kernel_releases_intermediate_endpoint_graph(monkeypatch):
    import gc
    import weakref
    ar = ledger()
    refs = []
    original = ar.wrap
    def wrap(value):
        answer = original(value)
        refs.append(weakref.ref(answer))
        return answer
    monkeypatch.setattr(ar, "wrap", wrap)
    incoming = box(ar, CASES[2])
    keys = set(ar.__dict__)
    result = z._coefficients_incremental_v1(incoming, 7, make_model(j2=11/32), ar)
    gc.collect()
    reachable = {id(e) for row in result for interval in row for e in (interval.lo, interval.hi)}
    reachable.update(id(e) for interval in incoming for e in (interval.lo, interval.hi))
    assert all(id(ref()) in reachable for ref in refs if ref() is not None)
    assert set(ar.__dict__) == keys
    assert all(len(row) == 8 for row in result)
    del result, incoming
    gc.collect()
    assert all(ref() is None for ref in refs)


def test_valid_sensitivity_metadata_is_admitted_and_preserved():
    from ops_sim.v5.provenance import SensitivityRange
    ar = ledger()
    incoming = box(ar)
    model = make_model(j2=11/32)
    provenance = forge(model.j2.provenance, sensitivity_range=SensitivityRange(-1.0, 1.0))
    model = forge(model, j2=forge(model.j2, provenance=provenance))
    declared = model.j2.provenance
    result = z._coefficients_incremental_v1(incoming, 7, model, ar)
    old_ar = z._ArithmeticV2(50, CAP)
    expected = old._coefficients(box(old_ar), 7, model, old_ar)
    assert representation(result) == representation(expected)
    assert model.j2.provenance is declared


def test_hostile_sensitivity_numeric_hook_is_rejected_before_coercion():
    from ops_sim.v5.provenance import SensitivityRange
    class Hostile(float):
        def __float__(self):
            raise AssertionError("sensitivity coercion hook ran")
    ar = ledger()
    incoming = box(ar)
    model = make_model()
    ranges = forge(SensitivityRange(0.0, 1.0), lower=Hostile(0))
    provenance = forge(model.j2.provenance, sensitivity_range=ranges)
    model = forge(model, j2=forge(model.j2, provenance=provenance))
    with pytest.raises(TypeError):
        z._coefficients_incremental_v1(incoming, 6, model, ar)


def test_noncanonical_sensitivity_zero_is_rejected_by_represented_roundtrip():
    from ops_sim.v5.provenance import SensitivityRange
    ar = ledger()
    incoming = box(ar)
    model = make_model()
    ranges = forge(SensitivityRange(0.0, 1.0), lower=-0.0)
    provenance = forge(model.j2.provenance, sensitivity_range=ranges)
    model = forge(model, j2=forge(model.j2, provenance=provenance))
    with pytest.raises(ValueError, match="sensitivity.*normalized"):
        z._coefficients_incremental_v1(incoming, 6, model, ar)


@pytest.mark.parametrize("magnitude", ["1e150", "1e-150"])
def test_native_trap_inside_kernel_raises_atomic_explicit_failure(magnitude):
    ar = ledger()
    values = ((magnitude, magnitude),) + (("0", "0"),)*5
    incoming = box(ar, values)
    before, published = bounds_copy(incoming), []
    with pytest.raises(old._Unresolved, match="incremental coefficient arithmetic failed"):
        published.append(z._coefficients_incremental_v1(incoming, 7, make_model(), ar))
    assert not published and bounds_copy(incoming) == before
    assert ar.operations == ar.leaf_operations+ar.reserved_units
