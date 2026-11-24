"""Independent motion energy, protection, exact-clock and refinement checks."""

from dataclasses import replace
from fractions import Fraction
from math import cos, pi, ulp

import pytest

from ops_sim.v5.comparison_campaign import build_inputs_program
from ops_sim.v5.continuation import checked_checkpoint
from ops_sim.v5.design_trade_execution import execute_profile
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.state import FDIRState, OperationalMode


def setup():
    inputs, program = build_inputs_program("J-E4")
    return program.initial_checkpoint.restore(inputs), program


def trajectory(duration=20, angle=.5):
    def at(t):
        x = float(t) / duration
        return (angle * (3*x*x - 2*x*x*x),
            angle * 6*x*(1-x)/duration,
            angle * 6*(1-2*x)/(duration*duration))
    return at


def forcing(program, power=20., *, sunlit=False):
    def at(t, angle, rate, torque, moving):
        base = program.forcing[0].standby
        wait = replace(base, sunlit=sunlit, incidence_angle_deg=angle*180/pi,
            loads=replace(base.loads, adcs_w=power if moving else 0.))
        return wait, {"actuator_w": power if moving else 0.}
    return at


def run(context, program, **changes):
    args = dict(duration_seconds=20, integration_level=1, start_angle_rad=0.,
        trajectory_at=trajectory(), forcing_at=forcing(program), policy=program.protection)
    args.update(changes)
    return execute_profile(context, **args)


@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_real_motion_pays_independent_electrical_budget_and_time(level):
    c, p = setup()
    start = c.spacecraft_state.battery.energy_wh
    outcome = run(c, p, integration_level=level)
    assert outcome.approved and outcome.final_angle_rad == .5
    assert c.simulation_time_seconds == 20 and c.diagnostics.completed_steps == 1
    assert len(outcome.intervals) == 4 * 2**level
    # Literal independent 12 W baseline + 20 W actuator, 20 s, eta_dis=0.9.
    expected = start - 32 * 20 / (3600 * .9)
    assert abs(c.spacecraft_state.battery.energy_wh - expected) <= 2*len(outcome.intervals)*ulp(start)
    assert abs(outcome.accounting.requested_load_wh - 32*20/3600) <= 8*ulp(1.)
    assert abs(outcome.accounting.routed_internal_heat_wh - 32*20/3600) <= 8*ulp(1.)
    assert outcome.accounting.conversion_loss_wh > 0
    assert not c.spacecraft_state.data_storage.stored_records
    assert c.spacecraft_state.onboard.operational_mode is OperationalMode.STANDBY
    assert c.spacecraft_state.onboard.fdir_state is FDIRState.NORMAL


def test_denied_motion_executes_same_duration_hold_without_turn_or_motor_heat():
    c, p = setup()
    start = c.spacecraft_state.battery.energy_wh
    outcome = run(c, p, forcing_at=forcing(p, 1000.))
    assert not outcome.approved and outcome.final_angle_rad == 0
    assert outcome.reasons == ("motion-full-electrical-service-unavailable",)
    assert outcome.predicted_unmet_w > 0
    assert c.simulation_time_seconds == 20
    expected = start - 12 * 20 / (3600 * .9)
    assert abs(c.spacecraft_state.battery.energy_wh - expected) <= 16*ulp(start)
    assert all(s.angle_rad == 0 for s in outcome.samples)
    assert all(dict(i.diagnostics)["actuator_w"] == 0 for i in outcome.intervals)
    assert abs(outcome.accounting.requested_load_wh - 12*20/3600) <= 8*ulp(1.)
    assert c.spacecraft_state.onboard.fdir_state is FDIRState.BACKUP


def test_energy_deficient_hold_is_safe_and_never_moves():
    c, p = setup()
    c.spacecraft_state.battery.energy_wh = 0.
    outcome = run(c, p)
    assert not outcome.approved and outcome.final_angle_rad == 0
    assert outcome.accounting.unmet_load_wh > 0
    assert c.spacecraft_state.battery.energy_wh == 0
    assert c.spacecraft_state.onboard.operational_mode is OperationalMode.SAFE
    assert c.spacecraft_state.onboard.critical_energy_since_seconds == 0


def test_thermal_start_denial_cannot_publish_target_attitude():
    c, p = setup()
    c.spacecraft_state.thermal.node_states[0].temperature_k = 321.
    outcome = run(c, p)
    assert not outcome.approved
    assert "motion-required-node-outside-operating-at-start" in outcome.reasons
    assert outcome.final_angle_rad == 0
    assert c.simulation_time_seconds == 20


def test_midpoint_forcing_and_samples_refine_without_changing_action_duration():
    evidence = []
    for level in (1, 2):
        c, p = setup()
        calls = []
        original = forcing(p)
        def recorder(t, angle, rate, torque, moving):
            calls.append((t, angle))
            return original(t, angle, rate, torque, moving)
        out = run(c, p, duration_seconds=21, trajectory_at=trajectory(21),
            integration_level=level, forcing_at=recorder)
        n = 5 * 2**level
        assert [t for t, _ in calls] == [(Fraction(i)+Fraction(1,2))*Fraction(21,n) for i in range(n)]
        assert [s.time_seconds for s in out.samples] == [Fraction(i*21,n) for i in range(n+1)]
        assert out.start_seconds == 0 and out.end_seconds == 21
        evidence.append(out)
    assert {s.time_seconds for s in evidence[0].samples} <= {s.time_seconds for s in evidence[1].samples}


def test_turn_changes_generation_and_its_quadrature_is_refined():
    energies = []
    for level in (1, 2, 3):
        c, p = setup()
        # Linear angular sweep with endpoint rest evidence. Pure quadrature
        # fixture; physical torque-profile equations have separate analytic tests.
        def turn(t):
            return (float(t)/20*pi/3, 0. if t in (0,20) else pi/60, 0.)
        out = run(c, p, integration_level=level, trajectory_at=turn, forcing_at=forcing(p, 0., sunlit=True))
        energies.append(out.accounting.generation_wh)
    # Integral of 225*cos(pi*t/60) W over 0..20 s, divided by 3600.
    from math import sin
    exact = 225 * 20 * sin(pi/3)/(pi/3) / 3600
    assert abs(energies[2]-exact) < abs(energies[1]-exact) < abs(energies[0]-exact)
    # Composite midpoint error <= T*max|f''|*h^2/24, converted to Wh.
    h = 20/(4*2**3)
    bound = 20 * 225 * (pi/60)**2 * h*h / (24*3600)
    assert abs(energies[2]-exact) <= bound + 16*ulp(exact)


@pytest.mark.parametrize("change", [
    {"duration_seconds": 0}, {"duration_seconds": True},
    {"duration_seconds": 3601}, {"integration_level": 13},
    {"max_interval_seconds": 0}, {"max_interval_seconds": True},
    {"duration_seconds": 3600, "integration_level": 4},
    {"start_angle_rad": float("nan")},
    {"trajectory_at": lambda t: (0., 1., 0.)},
    {"trajectory_at": lambda t: (1., 0., 0.)},
    {"trajectory_at": lambda t: (0., 0.)},
])
def test_invalid_request_preserves_original_context(change):
    c, p = setup()
    before = canonical_content(checked_checkpoint(c))
    with pytest.raises((TypeError, ValueError)):
        run(c, p, **change)
    assert canonical_content(checked_checkpoint(c)) == before


def test_callback_exception_after_private_progress_rolls_back_everything():
    c, p = setup()
    before = canonical_content(checked_checkpoint(c))
    original = forcing(p)
    def broken(t, angle, rate, torque, moving):
        if t > 5:
            raise ValueError("deliberate incomplete force contract")
        return original(t, angle, rate, torque, moving)
    with pytest.raises(ValueError, match="deliberate"):
        run(c, p, forcing_at=broken)
    assert canonical_content(checked_checkpoint(c)) == before


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "one"])
def test_diagnostics_cannot_smuggle_invalid_scalars(bad):
    c, p = setup()
    before = canonical_content(checked_checkpoint(c))
    def malformed(t, angle, rate, torque, moving):
        return p.forcing[0].standby, {"loss_w": bad}
    with pytest.raises(ValueError):
        run(c, p, forcing_at=malformed)
    assert canonical_content(checked_checkpoint(c)) == before


def test_restart_checkpoint_at_completed_motion_preserves_following_physics():
    c, p = setup()
    first = run(c, p)
    restored = checked_checkpoint(c).restore(c.inputs)
    second = dict(duration_seconds=20, integration_level=2, start_angle_rad=first.final_angle_rad,
        trajectory_at=lambda t: (.5, 0., 0.), forcing_at=forcing(p, 2.), policy=p.protection)
    a, b = execute_profile(c, **second), execute_profile(restored, **second)
    assert a == b
    assert canonical_content(checked_checkpoint(c)) == canonical_content(checked_checkpoint(restored))


def test_body_and_rotor_kinetic_storage_changes_phase_heat_but_closes_at_rest():
    c, p = setup()
    base = forcing(p)
    def with_kinetic(time, angle, rate, torque, moving):
        wait, diagnostic = base(time, angle, rate, torque, moving)
        return wait, dict(diagnostic, body_inertia_kg_m2=2., rotor_inertia_kg_m2=.5)
    out = run(c, p, forcing_at=with_kinetic)
    adjustments = [dict(i.diagnostics)["actuator_heat_adjustment_w"] for i in out.intervals]
    assert min(adjustments) < 0 < max(adjustments)
    assert dict(out.intervals[0].diagnostics)["kinetic_start_j"] == 0
    assert dict(out.intervals[-1].diagnostics)["kinetic_end_j"] == 0
    from math import fsum
    assert abs(fsum(value*float(i.end_seconds-i.start_seconds) for i,value in zip(out.intervals, adjustments))) <= 8*ulp(1.)
    assert abs(out.accounting.routed_internal_heat_wh-32*20/3600) <= 8*ulp(1.)
    for interval in out.intervals:
        d = dict(interval.diagnostics)
        assert d["actuator_heat_adjustment_w"] == (d["kinetic_start_j"]-d["kinetic_end_j"])/float(interval.end_seconds-interval.start_seconds)


def test_inadequate_declared_motor_draw_cannot_borrow_baseline_power_for_kinetics():
    c, p = setup()
    before = canonical_content(checked_checkpoint(c))
    def impossible(time, angle, rate, torque, moving):
        wait, diagnostic = forcing(p)(time, angle, rate, torque, moving)
        return wait, dict(diagnostic, body_inertia_kg_m2=100., rotor_inertia_kg_m2=.000001)
    with pytest.raises(ValueError, match="cannot fund kinetic"):
        run(c, p, forcing_at=impossible)
    assert canonical_content(checked_checkpoint(c)) == before
