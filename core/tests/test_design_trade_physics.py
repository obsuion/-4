"""Independent analytic references for the bounded 05E physical reductions.

Approximate comparisons below permit 2e-14 relative/absolute binary64 rounding
for these small closed-form fixtures; they do not assert model uncertainty.
"""

from dataclasses import FrozenInstanceError, replace
import math

import pytest

from ops_sim.v5.design_trade_physics import (
    BoxMassComponent, ElectricalLimitError, SlewProfile, WireSpec,
    constant_power_load, generated_power_line, mass_properties_y, select_wire_size,
)


def near(value):
    return pytest.approx(value, rel=2e-14, abs=2e-14)


def wire(**changes):
    # Unit fixture: 2-m loop, area 1 m², rho .25 ohm*m -> R=.5 ohm.
    baseline = WireSpec(1, 1, .25, 10, 0, 0, 0, 100, 100)
    return replace(baseline, **changes)


def test_two_point_masses_parallel_axis_center_and_translation():
    points = (BoxMassComponent("left", 2, (0, 0, 0), (-1, 0, 0)),
              BoxMassComponent("right", 2, (0, 0, 0), (1, 0, 0)))
    result = mass_properties_y(points)
    assert result.total_mass_kg == 4
    assert result.center_m == (0, 0, 0)
    assert result.inertia_y_kg_m2 == 4
    shifted = tuple(replace(c, center_m=(c.center_m[0] + 7, 5, -3)) for c in points)
    other = mass_properties_y(shifted)
    assert other.center_m == (7, 5, -3)
    assert other.inertia_y_kg_m2 == result.inertia_y_kg_m2


def test_rectangular_box_self_inertia_and_asymmetric_mass_center():
    # 12-kg 2x7x4 box: Iy = 12*(2²+4²)/12 = 20 kg*m².
    box = BoxMassComponent("box", 12, (2, 7, 4), (3, 2, 1))
    assert mass_properties_y((box,)).inertia_y_kg_m2 == 20
    # 1 kg at x=0, 3 kg at x=4 -> center=3, Iy=1*9+3*1=12.
    points = (BoxMassComponent("a", 1, (0, 0, 0), (0, 0, 0)),
              BoxMassComponent("b", 3, (0, 0, 0), (4, 0, 0)))
    result = mass_properties_y(points)
    assert result.center_m == (3, 0, 0)
    assert result.inertia_y_kg_m2 == 12


def test_mass_name_duplicate_rejects_and_output_immutable():
    box = BoxMassComponent("box", 1, (1, 1, 1), (0, 0, 0))
    with pytest.raises(ValueError, match="unique"):
        mass_properties_y((box, box))
    with pytest.raises(FrozenInstanceError):
        box.mass_kg = 2
    with pytest.raises(TypeError):
        mass_properties_y([box])


def test_triangle_hand_solution_and_held_endpoint():
    # alpha=1/2; theta=2 -> acceleration 2 s, peak 1 rad/s, total 4 s.
    profile = SlewProfile(2, 2, 1, 10, 20)
    assert profile.triangular
    assert profile.alpha_rad_s2 == .5
    assert profile.acceleration_s == 2
    assert profile.coast_s == 0
    assert profile.duration_s == 4
    assert profile.peak_rate_rad_s == 1
    assert [profile.angle_at(t) for t in (0, 1, 2, 3, 4, 5)] == [0, .25, 1, 1.75, 2, 2]
    assert [profile.omega_at(t) for t in (0, 1, 2, 3, 4, 5)] == [0, .5, 1, .5, 0, 0]
    assert [profile.acceleration_at(t) for t in (0, 1, 2, 3, 4)] == [.5, .5, -.5, -.5, 0]
    assert profile.angle_fraction(2) == .5
    assert profile.angle_fraction(8) == 1


@pytest.mark.parametrize("rate,momentum", [(1, 200), (10, 2), (1, 2)])
def test_trapezoid_independent_rate_or_momentum_cap(rate, momentum):
    # alpha=.5, cap=1, theta=6: two 2-s ramps and 4-s coast.
    profile = SlewProfile(6, 2, 1, rate, momentum)
    assert not profile.triangular
    assert profile.rate_cap_rad_s == 1
    assert profile.acceleration_s == 2
    assert profile.coast_s == 4
    assert profile.duration_s == 8
    assert [profile.angle_at(t) for t in (0, 2, 4, 6, 8)] == [0, 1, 3, 5, 6]
    assert [profile.omega_at(t) for t in (0, 2, 4, 6, 8)] == [0, 1, 1, 1, 0]
    assert [profile.torque_abs_at(t) for t in (0, 2, 4, 6, 8)] == [1, 0, 0, 1, 0]
    assert profile.peak_rate_rad_s <= rate
    assert profile.inertia_kg_m2 * profile.peak_rate_rad_s <= momentum


def test_triangle_trapezoid_boundary_and_continuity():
    triangle = SlewProfile(2, 2, 1, 1, 2)
    assert triangle.duration_s == 4
    assert triangle.coast_s == 0
    for angle in (math.nextafter(2, 0), 2, math.nextafter(2, math.inf)):
        profile = SlewProfile(angle, 2, 1, 1, 2)
        assert profile.duration_s == near(4)
        for time in (profile.acceleration_s, profile.acceleration_s + profile.coast_s):
            before, after = math.nextafter(time, 0), math.nextafter(time, math.inf)
            assert profile.angle_at(before) == near(profile.angle_at(after))
            assert profile.omega_at(before) == near(profile.omega_at(after))


def test_slew_work_independent_torque_angle_integral_no_regeneration():
    profile = SlewProfile(6, 2, 1, 1, 2)
    # Each ramp covers 1 rad at 1 Nm; acceleration work=1 J, brake heat=1 J.
    assert profile.mechanical_energy_j == 1
    assert profile.braking_heat_j == 1
    assert profile.absolute_mechanical_work_j == 2
    assert [profile.cumulative_drive_work_j(t) for t in (0, 1, 2, 6, 7, 8, 9)] == [0, .25, 1, 1, 1, 1, 1]
    assert [profile.cumulative_brake_heat_j(t) for t in (0, 2, 6, 7, 8, 9)] == [0, 0, 0, .75, 1, 1]
    assert profile.mechanical_energy_j == profile.torque_nm * profile.angle_at(profile.acceleration_s)
    assert profile.braking_heat_j == profile.torque_nm * (profile.angle_rad - profile.angle_at(6))
    # Torque impulse on each ramp is ±2 Nms; net body angular momentum is zero.
    assert profile.torque_nm * profile.acceleration_s == profile.inertia_kg_m2 * profile.peak_rate_rad_s


def test_zero_angle_has_no_time_motion_or_mechanical_work():
    profile = SlewProfile(0, 2, 1, 1, 2)
    assert profile.duration_s == profile.coast_s == profile.acceleration_s == 0
    assert profile.mechanical_energy_j == profile.braking_heat_j == 0
    for t in (0, 1, 10):
        assert profile.angle_at(t) == profile.omega_at(t) == profile.torque_abs_at(t) == 0
        assert profile.cumulative_drive_work_j(t) == profile.cumulative_brake_heat_j(t) == 0
        assert profile.angle_fraction(t) == 1


def test_wire_return_conductor_and_connectors_counted_once():
    route = wire(connector_count=2, connector_resistance_ohm=.1, connector_mass_kg=.5)
    assert route.loop_length_m == 2
    assert route.resistance_ohm == near(.7)
    assert route.conductor_mass_kg == 20
    assert route.connector_total_mass_kg == 1
    assert route.harness_mass_kg == 21


def test_load_low_current_quadratic_hand_solution():
    # R=.5 ohm, V=10 V, load=18 W -> low root I=2 A, drop=1 V, loss=2 W.
    result = constant_power_load(wire(), 10, 18)
    assert result.current_a == 2
    assert result.voltage_drop_v == 1
    assert result.load_voltage_v == 9
    assert result.loss_w == 2
    assert result.source_power_w == 20
    assert result.delivered_power_w == 18
    assert result.source_power_w == result.delivered_power_w + result.loss_w
    assert result.delivered_power_w == result.current_a * result.load_voltage_v
    assert result.source_power_w == result.current_a * 10


def test_generated_current_source_hand_solution():
    # The same 20-W source-side point supplies 18 W after its two-conductor loss.
    result = generated_power_line(wire(), 10, 20)
    assert result.current_a == 2
    assert result.voltage_drop_v == 1
    assert result.load_voltage_v == 9
    assert result.source_power_w == 20
    assert result.loss_w == 2
    assert result.delivered_power_w == 18
    assert result.source_power_w == result.delivered_power_w + result.loss_w


@pytest.mark.parametrize("evaluate", [constant_power_load, generated_power_line])
def test_zero_power_and_zero_length_ideal_line(evaluate):
    empty = evaluate(wire(), 10, 0)
    assert empty.current_a == empty.voltage_drop_v == empty.loss_w == empty.delivered_power_w == 0
    ideal = evaluate(wire(one_way_length_m=0), 10, 20)
    assert ideal.resistance_ohm == ideal.harness_mass_kg == ideal.loss_w == 0
    assert ideal.source_power_w == ideal.delivered_power_w == 20
    assert ideal.current_a == 2


@pytest.mark.parametrize("power", [50, 51])
def test_constant_power_fold_and_collapse_reject(power):
    # Maximum ideal receiving power V²/(4R)=50 W; the fold is not a stable root.
    with pytest.raises(ElectricalLimitError, match="stable"):
        constant_power_load(wire(), 10, power)


@pytest.mark.parametrize("evaluate,power", [(constant_power_load, 18), (generated_power_line, 20)])
def test_exact_electrical_limits_pass_but_next_lower_reject(evaluate, power):
    evaluate(wire(current_limit_a=2, max_drop_v=1), 10, power)
    with pytest.raises(ElectricalLimitError, match="current"):
        evaluate(wire(current_limit_a=math.nextafter(2, 0)), 10, power)
    with pytest.raises(ElectricalLimitError, match="drop"):
        evaluate(wire(max_drop_v=math.nextafter(1, 0)), 10, power)


def test_generated_line_nonpositive_receiving_voltage_rejects():
    with pytest.raises(ElectricalLimitError, match="nonpositive"):
        generated_power_line(wire(), 10, 200)


def test_wire_sizing_sorted_common_rule_no_unlisted_fallback():
    # Areas .5/1/2 m² give R=1/.5/.25: 20-W generated drop=2/1/.5 V.
    template = wire(max_drop_v=1)
    selected = select_wire_size(template, (2, .5, 1), 10, 20, generated=True)
    assert selected.cross_section_m2 == 1
    assert selected.current_limit_a == template.current_limit_a
    with pytest.raises(ElectricalLimitError, match="no declared"):
        select_wire_size(template, (.5,), 10, 20, generated=True)
    with pytest.raises(ValueError, match="unique"):
        select_wire_size(template, (1, 1), 10, 20)


class HostileFloat(float):
    def __eq__(self, other):
        return True


@pytest.mark.parametrize("bad", [True, "1", HostileFloat(1), float("nan"), float("inf"), -1])
def test_invalid_scalar_inputs_reject_before_arithmetic(bad):
    with pytest.raises((ValueError, TypeError)):
        SlewProfile(bad, 2, 1, 1, 2)
    with pytest.raises((ValueError, TypeError)):
        wire(one_way_length_m=bad)
    with pytest.raises((ValueError, TypeError)):
        constant_power_load(wire(), 10, bad)
    with pytest.raises((ValueError, TypeError)):
        generated_power_line(wire(), 10, bad)


@pytest.mark.parametrize("field", ["inertia_kg_m2", "torque_nm", "max_rate_rad_s", "momentum_nms"])
def test_zero_actuator_authority_rejects(field):
    values = dict(angle_rad=1, inertia_kg_m2=2, torque_nm=1, max_rate_rad_s=1, momentum_nms=2)
    values[field] = 0
    with pytest.raises(ValueError):
        SlewProfile(**values)


@pytest.mark.parametrize("changes", [dict(mass_kg=0), dict(size_m=(-1, 1, 1)),
                                   dict(center_m=(0, float("nan"), 0)),
                                   dict(size_m=[1, 1, 1]), dict(name="")])
def test_invalid_component_rejects(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(BoxMassComponent("box", 1, (1, 1, 1), (0, 0, 0)), **changes)


@pytest.mark.parametrize("count", [True, -1, 1.0])
def test_connector_count_strict_integer(count):
    with pytest.raises(ValueError):
        wire(connector_count=count)


def test_negative_query_time_and_hostile_subclasses_reject():
    profile = SlewProfile(2, 2, 1, 1, 2)
    for query in (profile.angle_at, profile.omega_at, profile.acceleration_at,
                  profile.cumulative_drive_work_j, profile.cumulative_brake_heat_j):
        with pytest.raises(ValueError):
            query(-1)
        with pytest.raises(TypeError):
            query(HostileFloat(1))
