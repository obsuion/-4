"""Independent instantaneous force references; no orbit propagator is used.

Decimal differentiates the unsimplified negative potential, not the production
acceleration expression. Scoped binary64 comparison budgets reserve 128u for
norm/quotient/product/angular arithmetic and add eight absolute output ulps.
They scale with uncancelled terms, not the small final residual. Decimal
90/120-digit agreement separately verifies reference precision.
"""

from decimal import Decimal, localcontext
from fractions import Fraction
from math import isfinite, ulp

import pytest

from ops_sim.v5.orbit_j2_gravity import evaluate_j2_gravity
from test_v56f1_j2_gravity_contracts import make_model, make_position, outputs


def reference(model, position, precision=90):
    """Differentiate -mu/r+A*(3*z*z*r^-5-r^-3) before simplification."""
    with localcontext() as ctx:
        ctx.prec = precision
        d = Decimal.from_float
        mu, j2, rg = (d(p.value) for p in (model.gravitational_parameter_m3_s2, model.j2, model.reference_radius_m))
        xyz = tuple(d(v) for v in position.components_m)
        radius = sum(v*v for v in xyz).sqrt()
        z = xyz[2]
        amplitude = mu*j2*rg*rg/2
        potential = -mu/radius + amplitude*(3*z*z/radius**5 - 1/radius**3)
        gradients = tuple(mu*v/radius**3 + amplitude*(
            (6*z/radius**5 if index == 2 else Decimal(0))
            - 15*z*z*v/radius**7 + 3*v/radius**5)
            for index, v in enumerate(xyz))
        # Full un-cancelled angular reserve also covers q rounding near roots.
        scales = tuple(abs(mu*v/radius**3) + 12*abs(mu*j2*rg*rg*v/radius**5)
                       for v in xyz)
        potential_scale = abs(mu/radius) + 2*abs(mu*j2*rg*rg/radius**3)
        return (*(-v for v in gradients), potential), (*scales, potential_scale)


def assert_reference(model, position):
    expected, scales = reference(model, position)
    refined, _ = reference(model, position, 120)
    actual = outputs(evaluate_j2_gravity(model, position))
    for value, exact, tighter, scale in zip(actual, expected, refined, scales):
        # The precision test is relative to the uncancelled reference scale.
        assert abs(exact-tighter) <= scale*Decimal("1e-80")
        with localcontext() as ctx:
            ctx.prec = 120
            budget = Decimal(128)*Decimal(2)**-53*scale + Decimal(8)*Decimal.from_float(ulp(float(exact)))
            assert abs(Decimal.from_float(value)-exact) <= budget
        assert isfinite(value)


@pytest.mark.parametrize("position,expected", [
    ((2, 0, 0), (-131/64, 0, 0, -129/32)),
    ((0, 0, 2), (0, 0, -61/32, -63/16)),
])
def test_prescribed_exact_binary_hand_cases(position, expected):
    assert outputs(evaluate_j2_gravity(make_model(), make_position(position))) == expected


@pytest.mark.parametrize("components", [(2, 0, 0), (3, 4, 12), (3, 4, -12), (-4, 3, 12), (0, 0, 2), (0, 0, -2)])
def test_zero_j2_against_independent_central_potential_gradient(components):
    assert_reference(make_model(j2=0), make_position(components))


@pytest.mark.parametrize("j2", [0, 1/16, -1/16, 4, -4])
@pytest.mark.parametrize("components", [(3, 4, 12), (1, 2, 2), (7, -2, 5), (2, 0, 0), (0, 0, 2)])
def test_axisymmetry_and_z_reflection(j2, components):
    x, y, z = components
    model = make_model(j2=j2)
    ax, ay, az, potential = outputs(evaluate_j2_gravity(model, make_position(components)))
    assert outputs(evaluate_j2_gravity(model, make_position((x, y, -z)))) == (ax, ay, -az, potential)
    assert outputs(evaluate_j2_gravity(model, make_position((-y, x, z)))) == (-ay, ax, az, potential)


@pytest.mark.parametrize("j2", [0, 1/16, -1/16, 4, -4])
@pytest.mark.parametrize("components", [(3, 4, 12), (1, 2, 1), (1, 1, 3), (7, -2, 5), (2, 0, 0), (0, 0, 2)])
def test_independent_analytic_gradient_of_potential(j2, components):
    assert_reference(make_model(j2=j2), make_position(components))


@pytest.mark.parametrize("j2", [0, 1/16, -1/16])
@pytest.mark.parametrize("axis", [0, 1, 2])
def test_directional_potential_finite_difference_with_predeclared_bound(j2, axis):
    # x +/- h is exactly representable. Along this segment r >= 13-h > 12.
    # Product-rule derivative bounds for r^-p give
    # M3 <= 24*mu/rho^4 + 1110*mu*|J2|*Rg^2/rho^6.
    # Central difference truncation <= h^2*M3/6. 64u*S/h reserves
    # potential evaluation plus subtraction/division; 128u*S/rho covers
    # acceleration comparison. These budgets precede all observed results.
    h, rho, mu, rg, u = Fraction(1, 2**12), Fraction(12), Fraction(8), Fraction(1), Fraction(1, 2**53)
    m3 = 24*mu/rho**4 + 1110*mu*abs(Fraction(j2))*rg**2/rho**6
    scale = mu/rho*(1+abs(Fraction(j2))*(rg/rho)**2)
    budget = h*h*m3/6 + 64*u*scale/h + 128*u*scale/rho
    xyz = [3.0, 4.0, 12.0]
    left, right = xyz.copy(), xyz.copy()
    left[axis] -= float(h)
    right[axis] += float(h)
    model = make_model(j2=j2)
    a = outputs(evaluate_j2_gravity(model, make_position(tuple(xyz))))[axis]
    pleft = evaluate_j2_gravity(model, make_position(tuple(left))).specific_potential_m2_per_s2
    pright = evaluate_j2_gravity(model, make_position(tuple(right))).specific_potential_m2_per_s2
    derivative = (Fraction(pright)-Fraction(pleft))/(2*h)
    assert abs(derivative+Fraction(a)) <= budget


@pytest.mark.parametrize("mu,j2,rg,xyz", [
    (2.0**-1000, 1/16, 2.0**-500, (2.0**-500, 0, 0)),
    (2.0**1000, 1/16, 2.0**500, (2.0**500, 0, 0)),
    (2.0**-1074, -1/16, 2.0**-1000, (0, 0, 2.0**-1000)),
    (2.0**600, 2.0**-1000, 2.0**900, (2.0**300, 0, 0)),
    (2.0**-600, 2.0**1000, 2.0**-900, (0, 0, 2.0**-300)),
    (2.0**1000, 0, 1, (2.0**-1000, 0, 2.0**100)),
    (2.0**-1074, 0, 1, (1, 0, 0)),
    (2.0**600, -1/16, 2.0**300, (2.0**300, 2.0**299, -2.0**299)),
])
def test_extreme_supported_scales_without_radius_power_or_unit_component_loss(mu, j2, rg, xyz):
    assert_reference(make_model(mu, j2, rg), make_position(xyz))


def test_tiny_normalized_component_does_not_erase_representable_acceleration():
    result = evaluate_j2_gravity(make_model(2.0**1000, 0, 1), make_position((2.0**-1000, 0, 2.0**100)))
    assert result.acceleration_x_m_per_s2 == -2.0**-300


@pytest.mark.parametrize("rg", [2.0**-1074, float.fromhex("0x1.fffffffffffffp+1023")])
def test_zero_j2_never_forms_unrelated_gravity_radius_correction(rg):
    assert outputs(evaluate_j2_gravity(make_model(radius=rg, j2=0), make_position())) == (-2, 0, 0, -4)


@pytest.mark.parametrize("mu,j2,rg,xyz", [
    (float.fromhex("0x1.fffffffffffffp+1023"), 0, 1, (0.5, 0, 0)),
    (8, 1, 2.0**1023, (2, 0, 0)),
    (2.0**-1000, 0, 1, (2.0**500, 0, 0)),
    (8, 1/16, 2.0**-1000, (2, 0, 0)),
    (8, 1/16, 1, (2.0**100, 0, 2.0**-1000)),
    (8, 0, 1, (float.fromhex("0x1.fffffffffffffp+1023"),)*3),
])
def test_unrepresentable_terms_norms_and_outputs_fail_intentionally(mu, j2, rg, xyz):
    with pytest.raises(ValueError):
        evaluate_j2_gravity(make_model(mu, j2, rg), make_position(xyz))


def test_output_sum_overflow_is_intentional_even_when_both_terms_are_finite():
    with pytest.raises(ValueError, match="output exceeds"):
        evaluate_j2_gravity(make_model(mu=2.0**1023, j2=1), make_position((1, 0, 0)))


@pytest.mark.parametrize("j2", [8/3, -8/3, 2, -2])
def test_cancellation_uses_absolute_uncancelled_term_budgets(j2):
    for components in ((2, 0, 0), (0, 0, 2), (1, 1, 1), (1, 2, 1)):
        assert_reference(make_model(j2=j2), make_position(components))


def test_repeat_and_query_order_are_exact_and_inputs_do_not_change():
    model = make_model()
    positions = tuple(make_position(x) for x in ((3, 4, 12), (2, 0, 0), (0, 0, 2)))
    before = tuple((p.frame, p.instant, p.components_m) for p in positions)
    forward = tuple(evaluate_j2_gravity(model, p) for p in positions)
    backward = tuple(evaluate_j2_gravity(model, p) for p in reversed(positions))
    assert forward == tuple(reversed(backward))
    assert before == tuple((p.frame, p.instant, p.components_m) for p in positions)
