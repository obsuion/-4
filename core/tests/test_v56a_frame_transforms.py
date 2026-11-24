"""Independent mathematical references, SI error bounds, and transform guards.

All approximate assertions disable relative tolerance explicitly. Short-time
Earth-scale positions use 2e-8 m (~22 ulps at 6e6 m, allowing trigonometry and
several products/additions); directions use 2e-15 dimensionless. State
velocities use 3e-12 m/s at O(1e3 m/s), allowing ~27 ulps and cross terms.
Long-time tests use a separate phase accumulation budget, documented below.
These are numerical/model-equation checks, not Earth-orientation accuracy.
"""

from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR, localcontext
import math

import pytest

from ops_sim.v5.orbit_config import GeometryInstant, GeodeticLocation
from ops_sim.v5.frames import (
    CartesianPosition, CartesianVelocity, CartesianDirection, CartesianState,
    geodetic_position, geodetic_normal, rotation_angle,
    transform_position, transform_direction, transform_state,
)
from test_v56a_time_frame_contracts import _model, _sphere, _forge


def _sincos_decimal(x):
    """Offline Taylor reference for |x|<pi; never calls production or math trig."""
    s = st = x
    c = ct = Decimal(1)
    k = 1
    while max(abs(st), abs(ct)) > Decimal('1e-85'):
        st *= -x*x / ((2*k)*(2*k+1))
        ct *= -x*x / ((2*k-1)*(2*k))
        s += st
        c += ct
        k += 1
    return s, c


def _support_reference(a, f, phi, longitude, height):
    """Independent ellipsoid-gradient/support-function derivation.

    For Q=diag(a²,a²,b²), surface support point q=Q*n/sqrt(n.T*Q*n).
    This solves surface q.T*Q^-1*q=1 and gradient parallel to n; then r=q+h*n.
    It does not use the production prime-vertical-radius formula.
    Decimal.from_float uses the exact binary inputs; 90-digit context and
    <1e-85 Taylor term threshold give far more precision than stored fixtures.
    """
    with localcontext() as ctx:
        ctx.prec = 90
        a, f, phi, longitude, height = map(Decimal.from_float, (a, f, phi, longitude, height))
        sp, cp = _sincos_decimal(phi)
        sl, cl = _sincos_decimal(longitude)
        normal = (cp*cl, cp*sl, sp)
        diagonal = (a*a, a*a, (a*(1-f))**2)
        denominator = sum(d*n*n for d, n in zip(diagonal, normal)).sqrt()
        return tuple(d*n/denominator + height*n for d, n in zip(diagonal, normal))


def _phase_reference(phase, rate, time):
    """Independent true-pi reduction: Machin formula and Decimal90 arithmetic."""
    def atan(x):
        power, total, k = x, x, 1
        term = x
        while abs(term) > Decimal('1e-85'):
            power *= -x*x
            term = power / (2*k + 1)
            total += term
            k += 1
        return total
    with localcontext() as ctx:
        ctx.prec = 90
        pi = 16*atan(Decimal(1)/5) - 4*atan(Decimal(1)/239)
        angle = Decimal.from_float(phase) + Decimal.from_float(rate)*Decimal.from_float(time)
        turns = ((angle + pi)/(2*pi)).to_integral_value(rounding=ROUND_FLOOR)
        return angle - turns*2*pi


@pytest.mark.parametrize(("latitude", "longitude", "height", "expected"), [
    (0.0, 0.0, 0.0, (10.0, 0.0, 0.0)),
    (0.0, math.pi/2, 0.0, (0.0, 10.0, 0.0)),
    (math.pi/2, 0.0, 0.0, (0.0, 0.0, 8.0)),
    (-math.pi/2, 0.0, 0.0, (0.0, 0.0, -8.0)),
    (0.0, 0.0, 2.0, (12.0, 0.0, 0.0)),
    (0.0, 0.0, -1.0, (9.0, 0.0, 0.0)),
])
def test_hand_solved_axes_height_and_polar_radius(latitude, longitude, height, expected):
    fixed, _ = _model(ellipsoid=_sphere(10.0, 0.2))
    instant = GeometryInstant(fixed.rotation.epoch, 0.25)
    actual = geodetic_position(GeodeticLocation(fixed.ellipsoid, latitude, longitude, height), fixed, instant)
    assert actual.components_m == pytest.approx(expected, rel=0, abs=5e-15)  # m; <=3 ulps at 10m.
    assert actual.instant == instant and actual.frame == fixed


def test_spherical_limit_off_axis_has_analytic_radius_and_normal():
    fixed, _ = _model(ellipsoid=_sphere(10))
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    location = GeodeticLocation(fixed.ellipsoid, math.pi/6, math.pi/4, 2)
    position = geodetic_position(location, fixed, instant).components_m
    expected = (3*math.sqrt(6), 3*math.sqrt(6), 6)
    assert position == pytest.approx(expected, rel=0, abs=5e-15)
    assert math.hypot(*position) == pytest.approx(12, rel=0, abs=5e-15)
    assert geodetic_normal(location, fixed, instant).components == pytest.approx(
        tuple(x/12 for x in expected), rel=0, abs=2e-15)


@pytest.mark.parametrize(("height", "expected"), [
    (1234.5, ('2085196.7339265579447656897932387432147021',
              '-4275170.5417870129952136277604196129437845',
              '4236779.4040669416955892942890901307454706')),
    (-350.25, ('2084679.5069744995837363870783007623105583',
               '-4274110.0982361091456434315606947224749941',
               '4235721.4020263430715514578483990040724263')),
])
def test_independent_high_precision_wgs84_support_reference(height, expected):
    fixed, _ = _model()
    earth = fixed.ellipsoid
    reference = _support_reference(6378137.0, 1/298.257223563, 0.731, -1.117, height)
    # Independent generator/literals agree to <1e-30m, far below double rounding.
    assert all(abs(x - Decimal(y)) < Decimal('1e-30') for x, y in zip(reference, expected))
    location = GeodeticLocation(earth, 0.731, -1.117, height)
    instant = GeometryInstant(fixed.rotation.epoch, 123.25)
    actual = geodetic_position(location, fixed, instant)
    assert actual.components_m == pytest.approx(tuple(map(float, expected)), rel=0, abs=2e-8)


def test_wgs84_normal_is_not_geocentric_radial_direction():
    fixed, _ = _model()
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    location = GeodeticLocation(fixed.ellipsoid, 0.731, -1.117, 0)
    normal = geodetic_normal(location, fixed, instant).components
    expected = (0.32637763183995016835634323267449,
                -0.66915510389894277974204115784223,
                0.66761447584705728842810581550823)
    assert normal == pytest.approx(expected, rel=0, abs=2e-15)
    assert math.hypot(*normal) == pytest.approx(1, rel=0, abs=2e-15)
    position = geodetic_position(location, fixed, instant).components_m
    radial = tuple(x/math.hypot(*position) for x in position)
    assert math.hypot(*(x-y for x, y in zip(normal, radial))) > 0.003


@pytest.mark.parametrize(("phase", "rate", "time", "expected"), [
    (0, 0, 0, (2, 0, 0)),
    (0, math.pi/2, 1, (0, 2, 0)),
    (0, math.pi, 1, (-2, 0, 0)),
    (math.pi/2, 0, 1000, (0, 2, 0)),
    (0, math.pi, 0.5, (0, 2, 0)),
    (0, -math.pi/2, 1, (0, -2, 0)),
    (0, math.pi/2, -1, (0, -2, 0)),
])
def test_active_rotation_analytic_sign_phase_and_fractional_time(phase, rate, time, expected):
    fixed, inertial = _model(phase=phase, rate=rate)
    instant = GeometryInstant(fixed.rotation.epoch, time)
    position = CartesianPosition(fixed, instant, (2, 0, 0))
    actual = transform_position(position, inertial)
    assert actual.components_m == pytest.approx(expected, rel=0, abs=1e-15)  # m at 2m scale.
    direction = transform_direction(CartesianDirection(fixed, instant, (2, 0, 0)), inertial)
    assert direction.components == actual.components_m
    assert actual.instant == instant


def test_general_angles_are_not_snapped_to_cardinal_directions():
    fixed, inertial = _model(phase=1e-12)
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    result = transform_position(CartesianPosition(fixed, instant, (1, 0, 0)), inertial)
    assert result.components_m[1] != 0
    assert result.components_m[1] == pytest.approx(1e-12, rel=0, abs=1e-27)


@pytest.mark.parametrize("time", [0.0, 0.125, -4321.25, 12345.6789, 1e9 + 0.125])
def test_rotation_norm_and_inverse_checks_supplement_independent_references(time):
    fixed, inertial = _model(phase=0.271, rate=7.292115e-5)
    instant = GeometryInstant(fixed.rotation.epoch, time)
    position = CartesianPosition(fixed, instant, (6e6, -2e6, 1e6))
    transformed = transform_position(position, inertial)
    recovered = transform_position(transformed, fixed)
    assert recovered.components_m == pytest.approx(position.components_m, rel=0, abs=2e-8)
    assert math.hypot(*transformed.components_m) == pytest.approx(math.hypot(*position.components_m), rel=0, abs=2e-8)
    direction = CartesianDirection(fixed, instant, (3.0, -4.0, 2.0))
    restored = transform_direction(transform_direction(direction, inertial), fixed)
    assert restored.components == pytest.approx(direction.components, rel=0, abs=5e-15)
    assert recovered.instant == instant


@pytest.mark.parametrize(("position", "expected_velocity"), [
    ((10, 0, 0), (0, 20, 0)), ((0, 10, 0), (-20, 0, 0)),
    ((0, 0, 10), (0, 0, 0)), ((0, 0, 0), (0, 0, 0)),
])
def test_stationary_fixed_point_has_analytic_rotational_velocity(position, expected_velocity):
    fixed, inertial = _model(rate=2)
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    state = CartesianState(CartesianPosition(fixed, instant, position), CartesianVelocity(fixed, instant, (0, 0, 0)))
    transformed = transform_state(state, inertial)
    assert transformed.velocity.components_m_per_s == expected_velocity
    assert transform_state(transformed, fixed) == state


def test_general_velocity_hand_solution_and_inverse_compensation():
    fixed, inertial = _model(phase=math.pi/2, rate=2)
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    state = CartesianState(CartesianPosition(fixed, instant, (3, 4, 5)), CartesianVelocity(fixed, instant, (6, 7, 8)))
    result = transform_state(state, inertial)
    assert result.position.components_m == pytest.approx((-4, 3, 5), rel=0, abs=2e-15)
    assert result.velocity.components_m_per_s == pytest.approx((-13, -2, 8), rel=0, abs=5e-15)
    recovered = transform_state(result, fixed)
    assert recovered.velocity.components_m_per_s == pytest.approx((6, 7, 8), rel=0, abs=5e-15)


@pytest.mark.parametrize(("time", "r_reference", "v_reference", "phase_reference"), [
    (12345.6789, (4176425.05235337809788408, 4749470.89496030947245242, 1000000),
     (121.595217068821145214593, 240.482932614533511939865, 78), None),
    (1000000000.125, (135207.181873987175745283, -6323109.916644632752363438, 1000000),
     (73.05215063930433699999, -259.38546794273650292983, 78), -1.22766601113797578745993172),
])
def test_independent_complex_derivative_state_reference(time, r_reference, v_reference, phase_reference):
    """Decimal100 reference: zI=exp(i*theta)zF, zI'=exp(i*theta)(vF+i*omega*zF).

    Inputs are exact binary floats (.271, 7.292115e-5, time), rF=(6e6,-2e6,1e6),
    vF=(123,-456,78). Independent reviewer generated fixtures using true pi
    from Machin 16 atan(1/5)-4 atan(1/239), Taylor cutoff 1e-90, no production
    imports. Thus the long reference includes neither math.tau nor its error.
    """
    fixed, inertial = _model(phase=0.271, rate=7.292115e-5)
    instant = GeometryInstant(fixed.rotation.epoch, time)
    state = CartesianState(CartesianPosition(fixed, instant, (6e6, -2e6, 1e6)), CartesianVelocity(fixed, instant, (123, -456, 78)))
    result = transform_state(state, inertial)
    phase_error = 8 * 2**-53 * (0.271 + abs(7.292115e-5*time) + 1)
    r_error = 2e-8 + math.hypot(6e6, -2e6, 1e6) * phase_error  # metres.
    v_error = 3e-12 + (math.hypot(123, -456, 78) + 7.292115e-5*math.hypot(6e6, -2e6, 1e6)) * phase_error  # m/s.
    assert result.position.components_m == pytest.approx(r_reference, rel=0, abs=r_error)
    assert result.velocity.components_m_per_s == pytest.approx(v_reference, rel=0, abs=v_error)
    if phase_reference is not None:
        assert rotation_angle(fixed.rotation, instant) == pytest.approx(phase_reference, rel=0, abs=phase_error)


def test_velocity_finite_difference_supplements_analytic_reference():
    fixed, inertial = _model(phase=0.271, rate=7.292115e-5)
    t, dt = 12345.0, 0.125
    r, v = (6e6, -2e6, 1e6), (123, -456, 78)
    def evaluated(offset):
        position = CartesianPosition(fixed, GeometryInstant(fixed.rotation.epoch, t + offset), tuple(x + offset*y for x, y in zip(r, v)))
        return transform_position(position, inertial).components_m
    derivative = tuple((a-b)/(2*dt) for a, b in zip(evaluated(dt), evaluated(-dt)))
    state = CartesianState(CartesianPosition(fixed, GeometryInstant(fixed.rotation.epoch, t), r), CartesianVelocity(fixed, GeometryInstant(fixed.rotation.epoch, t), v))
    velocity = transform_state(state, inertial).velocity.components_m_per_s
    # Central truncation <=dt²*(w³|r|+3w²|v|)/6 plus ~1e-8m subtraction/dt.
    bound = dt**2 * ((7.292115e-5)**3*math.hypot(*r) + 3*(7.292115e-5)**2*math.hypot(*v))/6 + 1e-8/dt
    assert derivative == pytest.approx(velocity, rel=0, abs=bound)


def test_phase_envelope_and_derived_overflows_reject():
    fixed, inertial = _model(rate=1)
    assert math.isfinite(rotation_angle(fixed.rotation, GeometryInstant(fixed.rotation.epoch, 2**20)))
    with pytest.raises(ValueError, match="phase envelope"):
        rotation_angle(fixed.rotation, GeometryInstant(fixed.rotation.epoch, math.nextafter(float(2**20), math.inf)))
    huge_fixed, huge_inertial = _model(rate=1e308)
    with pytest.raises(ValueError):
        rotation_angle(huge_fixed.rotation, GeometryInstant(huge_fixed.rotation.epoch, 2))
    zero_time = GeometryInstant(huge_fixed.rotation.epoch, 0)
    state = CartesianState(CartesianPosition(huge_fixed, zero_time, (2, 0, 0)), CartesianVelocity(huge_fixed, zero_time, (0, 0, 0)))
    with pytest.raises(ValueError, match="finite"):
        transform_state(state, huge_inertial)
    fixed, inertial = _model(phase=math.pi/4)
    t = GeometryInstant(fixed.rotation.epoch, 0)
    with pytest.raises(ValueError, match="finite"):
        transform_position(CartesianPosition(fixed, t, (1.7e308, -1.7e308, 0)), inertial)
    huge_earth, _ = _model(ellipsoid=_sphere(1e308))
    with pytest.raises(ValueError, match="finite"):
        geodetic_position(GeodeticLocation(huge_earth.ellipsoid, 0, 0, 1e308), huge_earth, t)


@pytest.mark.parametrize("time", [float(2**20), -float(2**20)])
def test_independent_true_pi_reference_at_phase_envelope_boundary(time):
    fixed, _ = _model(phase=0.271, rate=1)
    instant = GeometryInstant(fixed.rotation.epoch, time)
    expected = float(_phase_reference(0.271, 1.0, time))
    budget = 8*2**-53*(0.271 + abs(time) + 1)  # radians, product/sum/reduction budget.
    assert rotation_angle(fixed.rotation, instant) == pytest.approx(expected, rel=0, abs=budget)


@pytest.mark.parametrize("latitude", [0.731, math.pi/2 - 2**-20])
def test_independent_geodesy_at_accepted_ellipsoid_conditioning_boundary(latitude):
    a, f, longitude, height = 10.0, 1 - 2**-20, -1.117, 0.0
    fixed, _ = _model(ellipsoid=_sphere(a, f))
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    reference = _support_reference(a, f, latitude, longitude, height)
    result = geodetic_position(GeodeticLocation(fixed.ellipsoid, latitude, longitude, height), fixed, instant)
    # Conservative input-angle/trig sensitivity bound 64*u*a/(b/a) metres.
    # Unlike the ordinary WGS84 budget, this explicitly allows the 2**20 ratio.
    budget = 64*2**-53*a/(1-f)
    assert result.components_m == pytest.approx(tuple(map(float, reference)), rel=0, abs=budget)


def test_public_transforms_revalidate_forged_vectors_and_wrong_kinds():
    fixed, inertial = _model()
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    position = CartesianPosition(fixed, instant, (1, 0, 0))
    direction = CartesianDirection(fixed, instant, (1, 0, 0))
    for value, function, field in ((position, transform_position, "components_m"), (direction, transform_direction, "components")):
        with pytest.raises(ValueError): function(_forge(value, field, (math.inf, 0, 0)), inertial)
        with pytest.raises(ValueError, match="opposite"): function(value, fixed)
    with pytest.raises(ValueError, match="nonzero"):
        transform_direction(_forge(direction, "components", (0, 0, 0)), inertial)
    with pytest.raises(TypeError):
        transform_state(CartesianVelocity(fixed, instant, (1, 0, 0)), inertial)
