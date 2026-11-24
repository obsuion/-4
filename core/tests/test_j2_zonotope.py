"""Independent exact references for the opt-in centered J2 owner.

Potential Hessians use a rational second-order jet, not the acceleration
formula. Circle ranges use rational sine/cosine series with a proved
Lagrange remainder and monotonicity on |angle| <= 17/32. All inclusion
comparisons are rational; no fitted numerical tolerances are used.
Test-owned history records do not become production state/checkpoints.
"""

from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal, Inexact, ROUND_UP, localcontext
from fractions import Fraction as Q
from itertools import product
from math import factorial, isqrt

import pytest

from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_enclosure as old
from ops_sim.v5 import orbit_j2_zonotope as z
from test_v56f2_j2_coast_contracts import at, trajectory


ZERO = (0, 0, 0, 0, 0, 0)


def base(**changes):
    return replace(old.J2EnclosurePolicy(1/32, 4096, .5, 50, 12), **changes)


def policy(**changes):
    return replace(z.J2ZonotopePolicy(base(), ZERO, 2**24), **changes)


def circle():
    # Exact supplied model gate; these are not Earth constants.
    return trajectory(r=(2, 0, 0), v=(0, 17/8, 0), mu=8,
                      rg=1, j2=11/32, t0=128)


def run(span=.5, *, t=None, p=None, solver=None, version=1):
    t = circle() if t is None else t
    evaluator = (z.evaluate_j2_zonotope_enclosure if version == 1
                 else z.evaluate_j2_zonotope_enclosure_v2)
    default = policy if version == 1 else policy_v2
    return evaluator(
        t, at(t, t.initial_state.position.instant.elapsed_seconds+span),
        solver or f2.J2RK4SolverConfig(1/32, 4096), p or default())


def interval(lo, hi=None):
    return z._I(Decimal(lo), Decimal(lo if hi is None else hi))


def matrix(entries):
    return tuple(tuple(interval(str(value)) for value in row) for row in entries)


def identity():
    return [[int(i == j) for j in range(6)] for i in range(6)]


def point(value):
    return tuple(Decimal(str(x)) for x in value)


def state(center=ZERO, generators=(), births=None, time=Q(0)):
    return z._Zonotope(point(center), tuple(point(g) for g in generators),
                       tuple(range(len(generators))) if births is None else births,
                       time)


def assert_box_contains(box, reference):
    assert len(box) == len(reference) == 6
    for actual, expected in zip(box, reference):
        lo, hi = ((actual.lo, actual.hi) if hasattr(actual, 'lo') else actual)
        assert Q(lo) <= expected[0] <= expected[1] <= Q(hi)


def assert_atomic(result):
    assert result.status == 'unresolved' and result.reason
    assert result.nominal_state is result.endpoint_intervals is None
    assert result.position_error_bound_m is result.velocity_error_bound_m_per_s is None
    assert result.diagnostic_state is None


class _Jet:
    """Exact value/gradient/Hessian for a scalar expression in three variables."""

    def __init__(self, value, gradient=None, hessian=None):
        self.value = Q(value)
        self.gradient = tuple(map(Q, gradient or (0, 0, 0)))
        self.hessian = tuple(tuple(map(Q, row)) for row in
                             (hessian or ((0, 0, 0),)*3))

    @classmethod
    def variable(cls, value, axis):
        return cls(value, tuple(int(i == axis) for i in range(3)))

    def __add__(self, other):
        other = other if isinstance(other, _Jet) else _Jet(other)
        return _Jet(self.value+other.value,
                    tuple(a+b for a, b in zip(self.gradient, other.gradient)),
                    tuple(tuple(self.hessian[i][j]+other.hessian[i][j]
                                for j in range(3)) for i in range(3)))

    __radd__ = __add__

    def __neg__(self):
        return _Jet(-self.value, tuple(-a for a in self.gradient),
                    tuple(tuple(-a for a in row) for row in self.hessian))

    def __sub__(self, other):
        return self+-other if isinstance(other, _Jet) else self+(-Q(other))

    def __mul__(self, other):
        other = other if isinstance(other, _Jet) else _Jet(other)
        return _Jet(self.value*other.value,
                    tuple(self.gradient[i]*other.value+self.value*other.gradient[i]
                          for i in range(3)),
                    tuple(tuple(self.hessian[i][j]*other.value+
                                self.gradient[i]*other.gradient[j]+
                                self.gradient[j]*other.gradient[i]+
                                self.value*other.hessian[i][j]
                                for j in range(3)) for i in range(3)))

    __rmul__ = __mul__

    def half_power(self, twice_exponent):
        # Only a perfect-square rational radius is admitted by this oracle.
        numerator, denominator = isqrt(self.value.numerator), isqrt(self.value.denominator)
        assert numerator*numerator == self.value.numerator
        assert denominator*denominator == self.value.denominator
        root = Q(numerator, denominator)
        alpha = Q(twice_exponent, 2)
        value = root**twice_exponent
        first = alpha*value/self.value
        second = alpha*(alpha-1)*value/self.value**2
        return _Jet(value, tuple(first*a for a in self.gradient),
                    tuple(tuple(first*self.hessian[i][j]+
                                second*self.gradient[i]*self.gradient[j]
                                for j in range(3)) for i in range(3)))


def potential_hessian(position, mu=Q(8), j2=Q(11, 32), rg=Q(1)):
    """Differentiate Phi, independently of F1's acceleration/Jacobian code."""
    x, y, vertical = (_Jet.variable(value, i) for i, value in enumerate(position))
    q = x*x+y*y+vertical*vertical
    potential = -mu*q.half_power(-1)+(mu*j2*rg*rg/2)*(
        3*vertical*vertical*q.half_power(-5)-q.half_power(-3))
    return tuple(tuple(-v for v in row) for row in potential.hessian)


@pytest.mark.parametrize('position', [(2, 0, 0), (0, 0, 2), (1, 2, 2),
                                      (2, 3, 6), (Q(3, 2), 2, 0)])
@pytest.mark.parametrize('j2', [Q(0), Q(11, 32), Q(-11, 32)])
def test_real_jacobian_contains_independent_potential_hessian(position, j2):
    t = trajectory(r=tuple(map(float, position)), j2=float(j2), t0=128)
    ar = z._Arithmetic(50, 2**24)
    tube = tuple(ar.point(v) for v in (*t.initial_state.position.components_m,
                                      *t.initial_state.velocity.components_m_per_s))
    scales = (2, 1, -1, -2, 3, 0)
    actual = z._jacobian_box(tube, t.gravity_model, scales, ar)
    independent = potential_hessian(position, j2=j2)
    for i, j in product(range(6), repeat=2):
        if i < 3:
            reference = Q(10)**(scales[j]-scales[i]) if j == i+3 else Q(0)
        else:
            reference = (independent[i-3][j]*Q(10)**(scales[j]-scales[i])
                         if j < 3 else Q(0))
        assert Q(actual[i][j].lo) <= reference <= Q(actual[i][j].hi)
    assert actual[0][3].lo == actual[0][3].hi == Decimal('0.0001')
    assert all(independent[i][j] == independent[j][i] for i, j in product(range(3), repeat=2))


@pytest.mark.parametrize('j2', [Q(0), Q(11, 32)])
def test_jacobian_closed_axis_box_contains_independent_complete_range(j2):
    # For every x in [2,3], y=z=0 the differentiated potential gives:
    # Kxx=2mu/x^3+6muJ2Rg^2/x^5,
    # Kyy=-mu/x^3-3muJ2Rg^2/(2x^5),
    # Kzz=-mu/x^3-9muJ2Rg^2/(2x^5), all cross entries zero.
    # Positive supplied mu and nonnegative J2 make each diagonal monotone.
    # Thus endpoint rational Hessians bound the ENTIRE closed interval.
    t = trajectory(j2=float(j2), t0=128)
    ar = z._Arithmetic(50, 2**24)
    tube = (interval('2', '3'), interval('0'), interval('0'),
            interval('-1', '1'), interval('-1', '1'), interval('-1', '1'))
    actual = z._jacobian_box(tube, t.gravity_model, ZERO, ar)
    left = potential_hessian((2, 0, 0), j2=j2)
    right = potential_hessian((3, 0, 0), j2=j2)
    for i, j in product(range(3), repeat=2):
        lo, hi = sorted((left[i][j], right[i][j]))
        assert Q(actual[i+3][j].lo) <= lo <= hi <= Q(actual[i+3][j].hi)


def trig_at(angle, sine):
    order = 100
    total = sum(((-1)**(k//2)*angle**k/Q(factorial(k))
                 for k in range(1 if sine else 0, order+1, 2)), Q(0))
    error = abs(angle)**(order+1)/factorial(order+1)
    return total-error, total+error


def trig_range(lo, hi, sine):
    assert -Q(17, 32) <= lo <= hi <= Q(17, 32)
    # cos(x) >= 1-x^2/2 > 0 proves sin monotone on this entire interval.
    # sin's sign follows from monotonicity and sin(0)=0, proving cosine
    # decreases on positive and increases on negative angles.
    assert 1-max(abs(lo), abs(hi))**2/2 > 0
    left, right = trig_at(lo, sine), trig_at(hi, sine)
    if sine:
        return left[0], right[1]
    lower = min(left[0], right[0])
    upper = Q(1) if lo <= 0 <= hi else max(left[1], right[1])
    return lower, upper


def times(pair, value):
    return tuple(sorted(value*v for v in pair))


def circle_range(start, end):
    lo, hi = sorted((Q(17, 16)*start, Q(17, 16)*end))
    sine, cosine = trig_range(lo, hi, True), trig_range(lo, hi, False)
    return (times(cosine, 2), times(sine, 2), (Q(0), Q(0)),
            times(sine, -Q(17, 8)), times(cosine, Q(17, 8)), (Q(0), Q(0)))


@pytest.mark.parametrize('sign', [-1, 1])
@pytest.mark.parametrize('version', [1, 2])
def test_original_anchor_signed_circle_every_closed_tube_and_endpoint(monkeypatch, sign, version):
    history = []
    actual_step = z._transport_step

    def record(current, h, model, p, ar, step_index, next_time=None):
        following, tube = actual_step(current, h, model, p, ar, step_index, next_time)
        # Exact test-owned copies avoid retaining budget-bearing endpoints or
        # invoking a second production projection in the running query.
        copied_tube = tuple(old._I(Decimal(a.lo), Decimal(a.hi)) for a in tube)
        center = tuple(Q(Decimal(c)) for c in following.center)
        generators = tuple(tuple(Q(Decimal(v)) for v in column)
                           for column in following.generators)
        endpoint = tuple((c-sum((abs(g[i]) for g in generators), Q(0)),
                          c+sum((abs(g[i]) for g in generators), Q(0)))
                         for i, c in enumerate(center))
        history.append((current.time, following.time, copied_tube, endpoint))
        return following, tube

    monkeypatch.setattr(z, '_transport_step', record)
    result = run(sign*.5, version=version)
    assert result.status == 'enclosed', result.reason
    assert len(history) == result.completed_steps == result.attempted_steps == 16
    for start, end, tube, endpoint in history:
        # Private time uses the original elapsed TT anchor, not a shifted
        # diagnostic boundary or a propagated nominal state.
        assert_box_contains(tube, circle_range(start-Q(128), end-Q(128)))
        assert_box_contains(endpoint, circle_range(end-Q(128), end-Q(128)))
    assert_box_contains(result.endpoint_intervals, circle_range(Q(sign, 2), Q(sign, 2)))
    nominal = (*result.nominal_state.position.components_m,
               *result.nominal_state.velocity.components_m_per_s)
    limits = (result.position_error_bound_m,)*3+(result.velocity_error_bound_m_per_s,)*3
    for (lo, hi), n, bound in zip(result.endpoint_intervals, nominal, limits):
        assert max(abs(Q(lo)-Q(n)), abs(Q(hi)-Q(n))) <= Q(bound)


def test_noncommuting_time_ordered_exact_affine_map_is_enclosed():
    ar = z._Arithmetic(50, 2**24)
    jacobian = [[interval('0') for _ in range(6)] for _ in range(6)]
    jacobian[0][1] = jacobian[1][0] = interval('0', '1')
    result = z._flow_derivative_box(tuple(map(tuple, jacobian)), interval('1'), ar)
    # exp(A2/2) exp(A1/2) for nilpotent A1=e01,A2=e10. The two
    # diagonals differ, disproving the frozen-average exponential reference.
    exact = identity()
    exact[0][1] = exact[1][0] = Q(1, 2)
    exact[1][1] = Q(5, 4)
    for i, j in product(range(6), repeat=2):
        assert Q(result[i][j].lo) <= exact[i][j] <= Q(result[i][j].hi)


def test_exact_rotation_reverse_carries_nonpoint_generators():
    ar = z._Arithmetic(50, 2**24)
    incoming = state(generators=((1, 0, 0, 0, 0, 0), (0, 1, 0, 0, 0, 0)))
    forward, reverse = identity(), identity()
    forward[0][:2], forward[1][:2] = ('.6', '-.8'), ('.8', '.6')
    reverse[0][:2], reverse[1][:2] = ('.6', '.8'), ('-.8', '.6')
    zero_center = tuple(ar.point(0) for _ in range(6))
    middle = z._transport_generators(incoming, zero_center, matrix(forward), ar, 1)
    following = z._transport_generators(middle, zero_center, matrix(reverse), ar, 2)
    actual = dict(zip(following.births, following.generators))
    for birth, g in zip(incoming.births, incoming.generators):
        assert tuple(map(Q, actual[birth])) == tuple(map(Q, g))
    assert_box_contains(z._project_box(following, ZERO, ar),
                        ((Q(-1), Q(1)), (Q(-1), Q(1)), *((Q(0), Q(0)),)*4))


def test_uncertain_affine_transport_contains_entire_inherited_nonpoint_set():
    ar = z._Arithmetic(50, 2**24)
    incoming = state(center=(1, 2, 3, 0, 0, 0), generators=(
        ('.3', '.2', 0, 0, 0, 0), ('-.1', '.4', 0, 0, 0, 0)))
    m = [list(row) for row in matrix(identity())]
    m[0][0], m[0][1] = interval('.5', '.7'), interval('-.4', '-.2')
    m[1][0], m[1][1] = interval('.1', '.3'), interval('.8', '1.1')
    center_bounds = tuple(interval(str(c)) for c in incoming.center)
    following = z._transport_generators(incoming, center_bounds, tuple(map(tuple, m)), ar, 1)
    carried = dict(zip(following.births, following.generators))
    assert all(birth in carried for birth in incoming.births)
    new_axes = [g for birth, g in carried.items() if birth not in incoming.births]
    assert all(sum(value != 0 for value in g) <= 1 for g in new_axes)
    axis_radius = [sum((abs(Q(g[i])) for g in new_axes), Q(0)) for i in range(6)]
    # A multiaffine residual attains coordinate extrema on these vertices.
    # Checking all vertices therefore covers the complete matrix interval
    # and complete inherited generator cube, not sampled physical points.
    for parameters in product((0, 1), repeat=4):
        selected = [list(map(Q, row)) for row in identity()]
        for (i, j), endpoint in zip(((0, 0), (0, 1), (1, 0), (1, 1)), parameters):
            selected[i][j] = Q((m[i][j].lo, m[i][j].hi)[endpoint])
        for latent in product((-1, 1), repeat=2):
            displacement = [sum((Q(g[i])*coefficient for g, coefficient in
                                  zip(incoming.generators, latent)), Q(0)) for i in range(6)]
            exact = [Q(incoming.center[i])+sum((selected[i][j]*displacement[j]
                                               for j in range(6)), Q(0)) for i in range(6)]
            retained = [Q(following.center[i])+sum((Q(carried[birth][i])*coefficient
                        for birth, coefficient in zip(incoming.births, latent)), Q(0))
                        for i in range(6)]
            assert all(abs(a-b) <= radius for a, b, radius in zip(exact, retained, axis_radius))


def test_reduction_beyond_twelve_columns_proves_discarded_cube_inclusion():
    ar = z._Arithmetic(50, 2**24)
    generators = [tuple((i+1)/10 if j == i % 6 else 0 for j in range(6)) for i in range(18)]
    # Decimal strings above are the actual input authority; independent exact
    # norms are derived from those represented values, not original floats.
    incoming = state(center=(1, 2, 3, 4, 5, 6), generators=generators)
    output = z._reduce_generators(incoming, ar, 3)
    assert output.center == incoming.center and len(output.generators) <= 12
    ranking = sorted(range(18), key=lambda k: (-sum((Q(v)**2 for v in incoming.generators[k]), Q()), k))
    keep = set(ranking[:6])
    carried = dict(zip(output.births, output.generators))
    assert all(carried[k] == incoming.generators[k] for k in keep)
    discarded = [g for k, g in enumerate(incoming.generators) if k not in keep]
    independent_radius = [sum((abs(Q(g[i])) for g in discarded), Q(0)) for i in range(6)]
    replacement = [g for birth, g in carried.items() if birth not in keep]
    assert all(sum(value != 0 for value in g) <= 1 for g in replacement)
    radius = [sum((abs(Q(g[i])) for g in replacement), Q(0)) for i in range(6)]
    assert all(a <= b for a, b in zip(independent_radius, radius))
    # For every old latent vector, |discarded_i| <= independent_radius_i,
    # so the replacement axis coefficient lies in [-1,1]. This is the
    # independent full-set proof, without enumerating 2^18 sample vertices.


def test_policy_immutable_strict_and_no_old_dispatch():
    p = policy()
    assert [f.name for f in fields(p) if f.init] == [
        'base_policy', 'scale_exponents', 'max_scalar_operations']
    assert not hasattr(p, '__dict__')
    with pytest.raises(FrozenInstanceError):
        p.scale_exponents = ZERO
    with pytest.raises(TypeError):
        old.evaluate_j2_enclosure(circle(), at(circle(), 128),
                                  f2.J2RK4SolverConfig(1/32, 4096), p)


@pytest.mark.parametrize('name,value', [
    ('base_policy', None), ('base_policy', {}), ('scale_exponents', [0]*6),
    ('scale_exponents', (0,)*5), ('scale_exponents', (0,)*7),
    ('scale_exponents', (True, 0, 0, 0, 0, 0)),
    ('scale_exponents', (0., 0, 0, 0, 0, 0)),
    ('scale_exponents', (33, 0, 0, 0, 0, 0)),
    ('scale_exponents', (-33, 0, 0, 0, 0, 0)),
    ('max_scalar_operations', True), ('max_scalar_operations', 0),
    ('max_scalar_operations', 2**24+1), ('max_scalar_operations', 1.0),
])
def test_policy_invalid_inputs_rejected(name, value):
    with pytest.raises((TypeError, ValueError)):
        policy(**{name: value})


def test_exact_initialization_and_tuple_scale_under_hostile_ambient():
    values = (float.fromhex('0x1.123456789abcdp+1'), -3.75, .125, 1e-20, 0., 2.5)
    scales = (32, -32, 1, -1, 3, -3)
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.traps[Inexact] = True
        ar = z._Arithmetic(50, 2**24)
        initial = z._initial_set(values, scales, ar, Q(128))
        assert not initial.generators
        assert all(Q(c) == Q(value)*Q(10)**(-k)
                   for c, value, k in zip(initial.center, values, scales))
        assert_box_contains(z._project_box(initial, scales, ar),
                            tuple((Q(v), Q(v)) for v in values))


def test_hostile_ambient_does_not_change_complete_scientific_result():
    ordinary = run(.0625)
    assert ordinary.status == 'enclosed', ordinary.reason
    exported = [value for pair in ordinary.endpoint_intervals for value in pair]
    exported.extend(ordinary.diagnostic_state.center)
    exported.extend(value for column in ordinary.diagnostic_state.generators for value in column)
    assert exported and all(type(value) is Decimal and not hasattr(value, '_ar')
                            for value in exported)
    with pytest.raises(FrozenInstanceError):
        ordinary.status = 'unresolved'
    with pytest.raises(FrozenInstanceError):
        ordinary.diagnostic_state.center = point(ZERO)
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_UP
        ambient.traps[Inexact] = True
        assert run(.0625) == ordinary


@pytest.mark.parametrize('signed', ['1', '-1'])
def test_pb_signed_nilpotent_reference(signed):
    ar = z._Arithmetic(50, 2**24)
    a = [[interval('0') for _ in range(6)] for _ in range(6)]
    a[0][1] = interval('1')
    result = z._flow_derivative_box(tuple(map(tuple, a)), interval(signed), ar)
    expected = identity()
    expected[0][1] = Q(signed)
    for i, j in product(range(6), repeat=2):
        assert Q(result[i][j].lo) <= expected[i][j] <= Q(result[i][j].hi)


def test_pb_tail_rejects_equality_z_eight_without_result():
    ar = z._Arithmetic(50, 2**24)
    a = [[interval('0') for _ in range(6)] for _ in range(6)]
    a[0][0] = interval('8')
    with pytest.raises(old._Unresolved, match='tail|Peano|z|eight|8'):
        z._flow_derivative_box(tuple(map(tuple, a)), interval('1'), ar)


def test_rank_intermediate_bit_cap_rejects_before_unbounded_rank():
    ar = z._Arithmetic(50, 2**24)
    generators = ((Decimal('1e1300'), Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(0)),)+(
        (Decimal(1), Decimal(1), Decimal(0), Decimal(0), Decimal(0), Decimal(0)),)*12
    incoming = z._Zonotope(point(ZERO), generators, tuple(range(13)), Q(0))
    with pytest.raises(old._Unresolved, match='bit|rank'):
        z._reduce_generators(incoming, ar, 1)


class _ContextSpy:
    def __init__(self, context):
        self.context, self.calls = context, []

    def __getattr__(self, name):
        actual = getattr(self.context, name)
        if not callable(actual):
            return actual

        def call(*arguments, **keywords):
            self.calls.append(name)
            return actual(*arguments, **keywords)
        return call


def test_direct_context_calls_are_charged_and_rejected_before_protected_work():
    ar = z._Arithmetic(50, 128)
    spy = _ContextSpy(ar.down._context)
    ar.down._context = spy
    # Independently frozen leaf weights: operation + each scalar argument
    # conversion + finite guard + endpoint wrap. Binary=5, unary=4 units.
    for name, arguments, expected in (
        ('add', (Decimal(1), Decimal(2)), 5),
        ('subtract', (Decimal(3), Decimal(2)), 5),
        ('multiply', (Decimal(2), Decimal(3)), 5),
        ('divide', (Decimal(3), Decimal(2)), 5),
        ('sqrt', (Decimal(2),), 4),
        ('next_minus', (Decimal(2),), 4),
        ('next_plus', (Decimal(2),), 4),
    ):
        before = ar.operations
        getattr(ar.down, name)(*arguments)
        assert ar.operations-before == expected
        assert spy.calls[-1] == name
    assert ar.reserved_units == 0 and ar.operations == ar.leaf_operations
    ar = z._Arithmetic(50, 1)
    spy = _ContextSpy(ar.up._context)
    ar.up._context = spy
    ar.charge(1)
    with pytest.raises(old._Unresolved):
        ar.up.multiply(Decimal(2), Decimal(3))
    assert spy.calls == [] and ar.operations == 1
    with pytest.raises(old._Unresolved):
        ar.up.add(Decimal(1), Decimal(1))
    assert spy.calls == [] and ar.operations == 1


def test_sqrt_rational_bracket_checks_are_charged_and_exact(monkeypatch):
    ar = z._Arithmetic(50, 2**24)
    original = z._fraction
    charges = []

    def capture(value, owner):
        before = owner.operations
        answer = original(value, owner)
        charges.append(owner.operations-before)
        return answer

    monkeypatch.setattr(z, '_fraction', capture)
    before = ar.operations
    result = ar.sqrt(interval('2', '3'))
    # Six Decimal rational conversions cost14 each; two checked rational
    # products cost21 each; two comparisons cost20 each. Points/guards and
    # sqrt/neighbor context operations cost24: 84+42+40+24=190.
    assert charges == [14]*6 and ar.operations-before == 190
    assert Q(result.lo)**2 <= 2 and Q(result.hi)**2 >= 3


def test_fraction_conversion_never_executes_after_rejected_charge(monkeypatch):
    ar = z._Arithmetic(50, 1)
    ar.charge(1)
    executed = []
    real = z.Fraction

    def forbidden(*arguments, **keywords):
        executed.append(arguments)
        return real(*arguments, **keywords)

    monkeypatch.setattr(z, 'Fraction', forbidden)
    with pytest.raises(old._Unresolved):
        z._fraction(Decimal('2'), ar)
    assert executed == [] and ar.operations == 1


def test_explicit_conversion_rank_and_composite_reservation_weights():
    ar = z._Arithmetic(50, 4096)
    before = ar.operations
    value = ar.point(Decimal(2)).lo
    assert ar.operations-before == 3
    for operation, expected in (
        (lambda: value.copy_abs(), 3),
        (lambda: value.copy_negate(), 3),
        (lambda: value < Decimal(3), 1),
        (lambda: z._fraction(Decimal(2), ar), 14),
        (lambda: z._radd(Q(1), Q(2), ar), 21),
        (lambda: z._rmul(Q(1), Q(2), ar), 21),
        (lambda: z._rcompare(Q(1), Q(2), ar), 20),
        (lambda: z._shift(Decimal(2), 3, ar), 7),
    ):
        before = ar.operations
        operation()
        assert ar.operations-before == expected
    leaves = ar.leaf_operations
    ar.reserve(17, 'independent finite control reservation')
    assert ar.leaf_operations == leaves and ar.reserved_units == 17
    assert ar.operations == leaves+17


def test_missing_context_accounting_method_cannot_call_raw_context():
    ar = z._Arithmetic(50, 4096)
    spy = _ContextSpy(ar.up._context)
    ar.up._context = spy
    for name in ('power', 'fma', 'quantize', 'create_decimal'):
        with pytest.raises(AttributeError):
            getattr(ar.up, name)
    assert spy.calls == [] and ar.operations == 0


@pytest.mark.parametrize('name,arguments', [
    ('power', (Decimal(2), Decimal(5))),
    ('fma', (Decimal(1), Decimal(2), Decimal(3))),
    ('quantize', (Decimal(1), Decimal('.1'))),
    ('create_decimal', (Decimal(1),)),
    ('not_a_context_operation', ()),
    ('add', (Decimal(1),)),
    ('multiply', (Decimal(1), Decimal(2), Decimal(3))),
    ('sqrt', (Decimal(1), Decimal(2))),
    ('next_plus', ()),
])
def test_direct_context_dispatch_rejects_missing_charge_schedule_before_native_call(name, arguments):
    ar = z._Arithmetic(50, 4096)
    spy = _ContextSpy(ar.up._context)
    ar.up._context = spy
    before = ar.operations
    with pytest.raises(old._Unresolved):
        ar.up._call(name, *arguments)
    assert spy.calls == [] and ar.operations == before


@pytest.mark.parametrize('operation', [
    lambda v: v+Decimal(1), lambda v: Decimal(1)+v,
    lambda v: v-Decimal(1), lambda v: Decimal(1)-v,
    lambda v: v*Decimal(3), lambda v: Decimal(3)*v,
    lambda v: v/Decimal(3), lambda v: Decimal(3)/v,
    lambda v: v**Decimal(2), lambda v: Decimal(2)**v,
    lambda v: v//Decimal(3), lambda v: Decimal(3)//v,
    lambda v: v % Decimal(3), lambda v: Decimal(3) % v,
    lambda v: divmod(v, Decimal(3)), lambda v: divmod(Decimal(3), v),
    lambda v: +v, lambda v: -v, lambda v: abs(v),
], ids=['add', 'radd', 'sub', 'rsub', 'mul', 'rmul', 'div', 'rdiv',
        'pow', 'rpow', 'floordiv', 'rfloordiv', 'mod', 'rmod', 'divmod',
        'rdivmod', 'plus', 'minus', 'abs'])
def test_implicit_decimal_arithmetic_cannot_escape_query_accounting(operation):
    ar = z._Arithmetic(50, 4096)
    value = ar.point(Decimal('2.000123456789')).lo
    before = ar.operations
    # Native arithmetic would consult this hostile ambient context. An
    # explicit unsupported-path rejection must happen before that operation
    # can execute or return a plain, unbound Decimal result.
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.traps[Inexact] = True
        with pytest.raises(old._Unresolved):
            operation(value)
    assert ar.operations == before


def test_tiny_budget_rejects_before_numeric_policy_reconstruction(monkeypatch):
    t, request, p = circle(), at(circle(), 128), policy(max_scalar_operations=1)

    def forbidden_policy_reconstruction(self):
        raise AssertionError('numeric policy reconstructed before admission reservation')

    def forbidden_nominal(*arguments):
        raise AssertionError('nominal evaluation before failed admission')

    monkeypatch.setattr(z.J2ZonotopePolicy, '__post_init__', forbidden_policy_reconstruction)
    monkeypatch.setattr(z, '_nominal_evaluator', forbidden_nominal)
    result = z.evaluate_j2_zonotope_enclosure(t, request, f2.J2RK4SolverConfig(1/32, 4096), p)
    assert_atomic(result)
    assert result.nominal_evaluations == result.scalar_operations == 0


def test_nominal_exactly_once_and_success_counts_are_derived(monkeypatch):
    calls = []
    actual = z._nominal_evaluator

    def record(*arguments):
        calls.append(arguments)
        return actual(*arguments)

    monkeypatch.setattr(z, '_nominal_evaluator', record)
    result = run(.0625)
    assert result.status == 'enclosed', result.reason
    assert len(calls) == result.nominal_evaluations == 1
    assert result.planned_nominal_steps == result.nominal_completed_steps == 2
    assert result.planned_nominal_force_calls == result.nominal_force_calls == 9
    assert result.scalar_operations >= result.charged_leaf_operations > 0
    assert result.scalar_operations == result.charged_leaf_operations+result.reserved_control_operations


@pytest.mark.parametrize('version', [1, 2])
def test_partial_nominal_failure_counts_unknown_and_no_enclosure(monkeypatch, version):
    calls = []

    def nominal(*arguments):
        calls.append(arguments)
        raise ValueError('synthetic F2 partial arithmetic failure; no public work counters')

    def enclosure_forbidden(*arguments, **keywords):
        raise AssertionError('enclosure after nominal failure')

    monkeypatch.setattr(z, '_nominal_evaluator', nominal)
    monkeypatch.setattr(z, '_transport_step', enclosure_forbidden)
    result = run(.0625, version=version)
    assert_atomic(result)
    assert len(calls) == result.nominal_evaluations == 1
    assert result.nominal_completed_steps is result.nominal_force_calls is None
    assert result.planned_nominal_steps == 2 and result.planned_nominal_force_calls == 9
    assert result.attempted_steps == result.completed_steps == result.picard_attempts == 0
    assert 'nominal' in result.reason.lower() or 'F2' in result.reason


@pytest.mark.parametrize('case', ['steps', 'nominal-steps', 'work', 'radius', 'picard'])
@pytest.mark.parametrize('version', [1, 2])
def test_failure_atomicity_and_static_admission(case, monkeypatch, version):
    p = policy() if version == 1 else policy_v2()
    solver = f2.J2RK4SolverConfig(1/32, 4096)
    if case == 'steps':
        p = replace(p, base_policy=base(max_steps=1))
    if case == 'nominal-steps':
        solver = f2.J2RK4SolverConfig(1/32, 1)
    if case == 'work':
        p = replace(p, max_scalar_operations=1)
    if case == 'radius':
        p = replace(p, base_policy=base(min_radius_m=3))
    if case == 'picard':
        p = replace(p, base_policy=base(max_picard_iterations=1))
    calls = []
    actual = z._nominal_evaluator

    def record(*arguments):
        calls.append(arguments)
        return actual(*arguments)

    monkeypatch.setattr(z, '_nominal_evaluator', record)
    result = run(.5, p=p, solver=solver, version=version)
    assert_atomic(result)
    assert result.scalar_operations <= p.max_scalar_operations
    if case in ('steps', 'nominal-steps', 'work'):
        assert calls == [] and result.nominal_evaluations == 0
        assert result.attempted_steps == result.completed_steps == result.picard_attempts == 0
    else:
        assert len(calls) == 1
        assert result.nominal_completed_steps == 16 and result.nominal_force_calls == 65
    if case == 'picard':
        assert result.attempted_steps == result.picard_attempts == 1
        assert result.completed_steps == 0


@pytest.mark.parametrize('version', [1, 2])
def test_late_enclosure_failure_clears_all_success_fields(monkeypatch, version):
    original = z._jacobian_box
    calls = []

    def fail_second(*arguments, **keywords):
        calls.append(arguments)
        if len(calls) == 2:
            raise old._Unresolved('injected second enclosure leg rejection')
        return original(*arguments, **keywords)

    monkeypatch.setattr(z, '_jacobian_box', fail_second)
    result = run(.0625, version=version)
    assert_atomic(result)
    assert result.attempted_steps == 2 and result.completed_steps == 1
    assert result.nominal_evaluations == 1 and result.nominal_completed_steps == 2


@pytest.mark.parametrize('version', [1, 2])
def test_zero_span_still_nominal_once_exact_original_authority(monkeypatch, version):
    calls = []
    actual = z._nominal_evaluator

    def record(*arguments):
        calls.append(arguments)
        return actual(*arguments)

    monkeypatch.setattr(z, '_nominal_evaluator', record)
    result = run(0, version=version)
    assert result.status == 'enclosed', result.reason
    assert len(calls) == result.nominal_evaluations == 1
    assert result.attempted_steps == result.completed_steps == result.picard_attempts == 0
    assert result.planned_nominal_steps == result.nominal_completed_steps == 0
    assert result.planned_nominal_force_calls == result.nominal_force_calls == 1
    assert result.position_error_bound_m == result.velocity_error_bound_m_per_s == 0
    components = (*circle().initial_state.position.components_m,
                  *circle().initial_state.velocity.components_m_per_s)
    assert all(Q(lo) == Q(hi) == Q(value)
               for (lo, hi), value in zip(result.endpoint_intervals, components))


# B19: resource v2 uses the same independently checked physical owners.
class _IntSubclass(int):
    pass


class _TupleSubclass(tuple):
    pass


class _TextSubclass(str):
    pass


def policy_v2(**changes):
    return replace(z.J2ZonotopePolicyV2(base(), ZERO, 2**31), **changes)


def scientific_record(value):
    """Exact test-only projection: retain every field, except explicit v2 identity."""
    from dataclasses import is_dataclass
    if is_dataclass(value):
        is_v2 = type(value) in (z.J2ZonotopePolicyV2, z.J2ZonotopeResultV2)
        return {f.name: scientific_record(getattr(value, f.name))
                for f in fields(value)
                if not (is_v2 and f.name == 'resource_policy_version')}
    if isinstance(value, Decimal):
        return ('Decimal', str(value))
    if isinstance(value, Q):
        return ('Fraction', value.numerator, value.denominator)
    if type(value) is float:
        return ('float', value.hex())
    if type(value) is tuple:
        return tuple(scientific_record(v) for v in value)
    return value


def test_v1_record_shapes_frozen_and_v2_identity_is_additive():
    p = policy()
    assert [f.name for f in fields(p)] == [
        'base_policy', 'scale_exponents', 'max_scalar_operations', 'method_id',
        'method_version', 'pb_order', 'max_generators', 'retained_generators',
        'rank_bit_cap']
    expected = [
        'trajectory', 'instant', 'solver_config', 'policy', 'status', 'reason',
        'nominal_state', 'endpoint_intervals', 'position_error_bound_m',
        'velocity_error_bound_m_per_s', 'diagnostic_state', 'attempted_steps',
        'completed_steps', 'picard_attempts', 'reductions', 'scalar_operations',
        'charged_leaf_operations', 'reserved_control_operations',
        'nominal_evaluations', 'planned_nominal_steps', 'planned_nominal_force_calls',
        'nominal_completed_steps', 'nominal_force_calls',
        'nominal_counter_provenance', 'method_id', 'method_version']
    assert [f.name for f in fields(z.J2ZonotopeResult)] == expected
    assert [f.name for f in fields(z.J2ZonotopeResultV2)] == expected+['resource_policy_version']
    p2 = policy_v2(max_scalar_operations=2**24)
    assert type(p2) is z.J2ZonotopePolicyV2
    assert p2.method_id == p.method_id == 'm2-centered-zonotope-pb6-v1'
    assert p2.method_version == p.method_version == 1
    assert type(p2.resource_policy_version) is int and p2.resource_policy_version == 2
    assert not hasattr(p, 'resource_policy_version')
    assert scientific_record(p2) == scientific_record(p)
    assert not hasattr(p2, '__dict__')
    with pytest.raises(FrozenInstanceError):
        p2.resource_policy_version = 1


@pytest.mark.parametrize('cap', [1, 2**24, 2**24+1, 2**31])
def test_v2_cap_valid_boundaries(cap):
    assert policy_v2(max_scalar_operations=cap).max_scalar_operations == cap
    assert z._ArithmeticV2(50, cap).limit == cap


@pytest.mark.parametrize('cap', [True, 1., _IntSubclass(1), 0, -1, 2**31+1])
def test_v2_cap_invalid_boundaries(cap):
    with pytest.raises((TypeError, ValueError)):
        policy_v2(max_scalar_operations=cap)
    with pytest.raises((TypeError, ValueError)):
        z._ArithmeticV2(50, cap)


@pytest.mark.parametrize('cap', [2**24+1, 2**31])
def test_v1_large_cap_still_rejected(cap):
    with pytest.raises(ValueError):
        policy(max_scalar_operations=cap)
    with pytest.raises(ValueError):
        z._Arithmetic(50, cap)
    assert z._Arithmetic(50).limit == 2**24


@pytest.mark.parametrize('precision', [True, 50., _IntSubclass(50), 39, 81])
def test_v2_ledger_precision_domain_is_unchanged(precision):
    with pytest.raises((TypeError, ValueError)):
        z._ArithmeticV2(precision, 2**31)


@pytest.mark.parametrize('name,value', [
    ('base_policy', None), ('base_policy', {}),
    ('scale_exponents', [0]*6), ('scale_exponents', _TupleSubclass(ZERO)),
    ('scale_exponents', (0,)*5),
    ('scale_exponents', (_IntSubclass(0), 0, 0, 0, 0, 0)),
    ('scale_exponents', (True, 0, 0, 0, 0, 0)),
    ('scale_exponents', (0., 0, 0, 0, 0, 0)),
    ('scale_exponents', (33, 0, 0, 0, 0, 0)),
    ('scale_exponents', (-33, 0, 0, 0, 0, 0)),
])
def test_v2_base_and_scale_ownership_is_strict(name, value):
    with pytest.raises((TypeError, ValueError)):
        policy_v2(**{name: value})


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('field,value', [
    ('method_version', True), ('method_version', 1.),
    ('method_version', _IntSubclass(1)), ('method_version', 2),
    ('method_id', _TextSubclass('m2-centered-zonotope-pb6-v1')),
    ('method_id', 'different-method'),
])
def test_forged_algorithm_identity_rejected_before_nominal(monkeypatch, version, field, value):
    p = policy() if version == 1 else policy_v2()
    object.__setattr__(p, field, value)
    calls = []
    monkeypatch.setattr(z, '_nominal_evaluator', lambda *a: calls.append(a))
    with pytest.raises((TypeError, ValueError)):
        run(0, p=p, version=version)
    assert calls == []


@pytest.mark.parametrize('value', [True, 2., _IntSubclass(2), 1, 3])
def test_forged_resource_version_rejected_at_v2_boundary(monkeypatch, value):
    p = policy_v2()
    object.__setattr__(p, 'resource_policy_version', value)
    calls = []
    monkeypatch.setattr(z, '_nominal_evaluator', lambda *a: calls.append(a))
    with pytest.raises((TypeError, ValueError)):
        run(0, p=p, version=2)
    assert calls == []


@pytest.mark.parametrize('version', [True, 1, 2, _IntSubclass(2)])
def test_resource_version_cannot_be_supplied_as_constructor_input(version):
    with pytest.raises(TypeError):
        z.J2ZonotopePolicyV2(base(), ZERO, 2**31, resource_policy_version=version)


@pytest.mark.parametrize('receiver', [1, 2])
@pytest.mark.parametrize('subclass', [False, True])
def test_public_versions_reject_other_policy_and_subclasses_before_work(monkeypatch, receiver, subclass):
    cls = z.J2ZonotopePolicyV2 if receiver == 1 else z.J2ZonotopePolicy
    if subclass:
        cls = type('PolicySubclass', (cls,), {})
    p = cls(base(), ZERO, 2**24)
    calls = []
    monkeypatch.setattr(z, '_nominal_evaluator', lambda *a: calls.append(a))
    with pytest.raises(TypeError):
        run(0, p=p, version=receiver)
    assert calls == []


@pytest.mark.parametrize('version', [1, 2])
def test_same_version_policy_subclass_is_also_rejected(version):
    cls = z.J2ZonotopePolicy if version == 1 else z.J2ZonotopePolicyV2
    derived = type('OwnPolicySubclass', (cls,), {})
    with pytest.raises(TypeError):
        run(0, p=derived(base(), ZERO, 2**24), version=version)


@pytest.mark.parametrize('cap', [2**24, 2**24+1, 2**31])
def test_v2_large_ledger_single_bounded_reservation_and_latched_exhaustion(cap):
    ar = z._ArithmeticV2(50, cap)
    spy = _ContextSpy(ar.down._context)
    ar.down._context = spy
    ar.reserve(cap-5, 'test-owned bounded reservation; no repeated operations')
    assert ar.operations == ar.reserved_units == cap-5 and ar.leaf_operations == 0
    value = ar.down.multiply(Decimal(2), Decimal(3))
    assert Decimal(value) == Decimal(6)
    assert spy.calls == ['multiply']
    assert ar.leaf_operations == 5 and ar.operations == cap
    assert ar.operations == ar.leaf_operations+ar.reserved_units
    before = (ar.operations, ar.leaf_operations, ar.reserved_units)
    with pytest.raises(old._Unresolved, match='exhausted'):
        ar.down.add(Decimal(1), Decimal(1))
    assert ar.rejected and spy.calls == ['multiply']
    for operation in (lambda: ar.charge(0),
                      lambda: ar.reserve(0, 'zero does not unlatch'),
                      lambda: ar.point(0)):
        with pytest.raises(old._Unresolved, match='already rejected'):
            operation()
    assert (ar.operations, ar.leaf_operations, ar.reserved_units) == before
    assert spy.calls == ['multiply']


def test_v2_one_ledger_rejects_mixed_query_endpoints_before_context_work():
    left, right = z._Arithmetic(50), z._ArithmeticV2(50)
    value = left.point(Decimal(2)).lo
    spy = _ContextSpy(right.down._context)
    right.down._context = spy
    with pytest.raises(old._Unresolved, match='mixed query'):
        right.down.multiply(value, Decimal(3))
    assert spy.calls == []
    assert right.operations == right.leaf_operations == 3
    assert right.reserved_units == 0


@pytest.mark.parametrize('span', [-.0625, 0., .0625])
def test_complete_v2_scientific_fields_and_all_accounting_equal_v1(span):
    cap = 2**24
    v1 = run(span, p=policy(max_scalar_operations=cap))
    v2 = run(span, p=policy_v2(max_scalar_operations=cap), version=2)
    assert type(v1) is z.J2ZonotopeResult and type(v2) is z.J2ZonotopeResultV2
    assert v1.status == v2.status == 'enclosed'
    assert scientific_record(v1) == scientific_record(v2)
    assert v2.resource_policy_version == v2.policy.resource_policy_version == 2
    assert v2.scalar_operations == v2.charged_leaf_operations+v2.reserved_control_operations


def test_v2_tiny_work_rejects_before_policy_or_nominal_reconstruction(monkeypatch):
    t = circle()
    p = policy_v2(max_scalar_operations=1)
    def forbidden(*arguments):
        raise AssertionError('numeric work before failed reservation')
    monkeypatch.setattr(z.J2ZonotopePolicyV2, '__post_init__', forbidden)
    monkeypatch.setattr(z, '_nominal_evaluator', forbidden)
    result = run(0, t=t, p=p, version=2)
    assert_atomic(result)
    assert result.scalar_operations == result.nominal_evaluations == 0


def test_v2_closed_constructor_does_not_call_or_top_up_v1_ledger(monkeypatch):
    def forbidden(*arguments):
        raise AssertionError('v1 ledger constructed then topped up')
    monkeypatch.setattr(z._Arithmetic, '__init__', forbidden)
    ar = z._ArithmeticV2(50, 2**31)
    assert ar.limit == 2**31 and ar.operations == ar.reserved_units == ar.leaf_operations == 0
