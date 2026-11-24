from fractions import Fraction as Q
from decimal import Decimal, localcontext
from math import pi
import pytest
from ops_sim.v5.mission_general_geometry import (GeneralGeometryPolicy, _Arithmetic,
    _geodetic_constants, _ground_bounds, _los_predicate, _ray_quadratic, _cell)


def arithmetic(policy=None):
    counts = {}
    def charge(name, n): counts[name] = counts.get(name, 0)+n
    return _Arithmetic(policy or GeneralGeometryPolicy(), charge), counts


def point(x): return tuple((Q(v), Q(v)) for v in x)


@pytest.mark.parametrize('latitude', [0., .4, -.7, pi/2, -pi/2, 1.569])
@pytest.mark.parametrize('height', [0, 1234, -100])
def test_geodetic_bounds_against_independent_decimal_series(latitude, height):
    ar, costs = arithmetic(); a = Q(6378137); f = Q(1/298.257223563)
    const = _geodetic_constants(ar, a, f, Q(height), Q(latitude))
    g, n = _ground_bounds(ar, const, Q(.3), Q(0), Q(128), Q(129))
    with localcontext() as context:
        context.prec = 100
        def dec(q): return Decimal(q.numerator)/Decimal(q.denominator)
        def trig(x, cosine=False):
            # Independent factorial/power sum with >90 digit tail at |x|<2.
            from math import factorial
            return sum(((-1)**k*(Decimal(1) if k==0 and cosine else x**(2*k+(0 if cosine else 1)))/Decimal(factorial(2*k+(0 if cosine else 1))) for k in range(100)), Decimal(0))
        phi = dec(Q(latitude)); L = dec(Q(.3)); sp = trig(phi); cp = trig(phi, True)
        e2 = dec(f)*(2-dec(f)); N = dec(a)/(1-e2*sp*sp).sqrt()
        xyz = ((N+height)*cp*trig(L, True), (N+height)*cp*trig(L), (N*(1-e2)+height)*sp)
        normal = (cp*trig(L, True), cp*trig(L), sp)
        # Decimal oracle rounding <=1e-85 m here; much narrower than dyadic bounds.
        for bounds, reference in zip((*g, *n), (*xyz, *normal)):
            assert dec(bounds[0])-Decimal('1e-85') <= reference <= dec(bounds[1])+Decimal('1e-85')
        C = sum(x*x*d for x, d in zip(xyz, map(dec, const['metric'])))-1
        if height == 0:
            assert const['ground_level_minus_one'] == (Q(0), Q(0))
            assert abs(C) < Decimal('1e-90')
        else:
            lo, hi = const['ground_level_minus_one']
            assert dec(lo)-Decimal('1e-85') <= C <= dec(hi)+Decimal('1e-85')
    assert costs['geometry_operations'] > 0 and costs['geometry_control_units'] > 0


@pytest.mark.parametrize('A,B,C,space,status,reason', [
    (4, 2, 0, 8, 'CLEAR', 'SURFACE_OUTWARD'),
    (4, -2, 0, 0, 'BLOCKED', 'SURFACE_INTERIOR_ENTRY'),
    (4, 0, 0, 4, 'UNRESOLVED', 'SURFACE_TANGENCY_OR_BOUNDARY'),
    (16, -8, 3, 3, 'BLOCKED', 'INTERIOR_PENETRATION_WITNESS'),
    (16, -8, 4, 4, 'UNRESOLVED', 'INTERIOR_TANGENCY'),
    (4, -1, 2, 4, 'CLEAR', 'WHOLE_LINE_MINIMUM_POSITIVE'),
    (1, -2, 4, 1, 'CLEAR', 'MONOTONE_INWARD_OUTSIDE_ENDPOINT'),
    (1, 1, -1, 2, 'BLOCKED', 'GROUND_INSIDE'),
    (1, 1, 1, -1, 'BLOCKED', 'SPACECRAFT_INSIDE'),
])
def test_exact_quadratic_references(A, B, C, space, status, reason):
    ar, _ = arithmetic()
    result = _los_predicate(ar, (Q(A),)*2, (Q(B),)*2, (Q(C),)*2, (Q(space),)*2)
    assert result[:2] == (status, reason)
    if result[2] and status == 'BLOCKED':
        u, bounds = result[2]
        assert 0 < u < 1 and bounds[0] <= A*u*u+2*B*u+C <= bounds[1] < 0


def test_elevated_endpoint_trap_and_grazing_ray():
    ar, _ = arithmetic(); metric = (Q(1, 4), Q(1, 4), Q(1))
    # Ellipse a=2,b=1: opposite endpoints x=+-4 are outside, midpoint inside.
    from ops_sim.v5.mission_general_geometry import _level, _metric_dot, _sub
    ground = point((-4, 0, 0)); orbit = point((4, 0, 0)); v = point((8, 0, 0))
    A = _level(ar, v, metric); B = _metric_dot(ar, ground, v, metric)
    C = _sub(ar, _level(ar, ground, metric), (Q(1),)*2)
    assert _los_predicate(ar, A, B, C, C)[0] == 'BLOCKED'
    # x=2 is tangent to this ellipse; nominal direction has a double root.
    result = _ray_quadratic(ar, point((2, 4, 0)), point((0, -1, 0)), metric)
    assert result[0] == 'GRAZING' and result[-1] == (Q(0), Q(0))


@pytest.mark.parametrize('origin,camera,status,first,second', [
    ((4, 0, 0), (-1, 0, 0), 'VISIBLE', 2, 6),
    ((0, 0, 3), (0, 0, -1), 'VISIBLE', 2, 4),
    ((4, 0, 0), (1, 0, 0), 'NO_FORWARD_INTERSECTION', None, None),
    ((0, 0, 0), (1, 0, 0), 'SPACECRAFT_INSIDE', None, None),
])
def test_ellipsoid_ordered_roots(origin, camera, status, first, second):
    ar, _ = arithmetic()
    result = _ray_quadratic(ar, point(origin), point(camera), (Q(1, 4), Q(1, 4), Q(1)))
    assert result[0] == status
    if first is not None:
        assert result[1] == (Q(first),)*2 and result[2] == (Q(second),)*2
    else: assert result[1] is result[2] is None


def test_sign_guard_and_geodetic_normal_differs_radial():
    ar, _ = arithmetic(); c = _geodetic_constants(ar, Q(6378137), Q(1/298.257223563), Q(100), Q(.7))
    g, n = _ground_bounds(ar, c, Q(0), Q(0), Q(0), Q(1))
    assert g[2][0]/g[0][1] < n[2][0]/n[0][1]
    # Negative camera dot cannot become a positive FOV by squaring.
    r = tuple((v[0]+1000000*u[0], v[1]+1000000*u[1]) for v, u in zip(g, n))
    result = _cell(ar, r, g, n, c, (Q(0), Q(0)), point((1, 0, 0)), (Q(9, 10),)*2, Q(1))
    assert result[-2] == 'BLOCKED'


@pytest.mark.parametrize('keyword,value', [('maximum_cells', True), ('maximum_rational_bits', 1024),
    ('maximum_cell_seconds', .5), ('maximum_operations', 2**22+1), ('method', 'foreign')])
def test_exact_policy_refuses(keyword, value):
    with pytest.raises((TypeError, ValueError)): GeneralGeometryPolicy(**{keyword: value})
