"""Opt-in forcing boundaries preserve the paid profile owner and its rollback."""

from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
from math import fsum, pi, ulp

import pytest

from ops_sim.v5.comparison_campaign import build_inputs_program
from ops_sim.v5.continuation import checked_checkpoint
from ops_sim.v5.design_trade_execution import execute_profile
from ops_sim.v5.experiment_codec import canonical_content, json_text
from ops_sim.v5.state import FDIRState


def setup(start=0):
    inputs, program = build_inputs_program("J-E4")
    context = program.initial_checkpoint.restore(inputs)
    # A valid completed clock tests absolute boundaries independently of offsets.
    context.simulation_time_seconds = start
    return context, program


def trajectory(duration=20, angle=.5):
    def at(t):
        x = float(t) / duration
        return (angle * (3*x*x - 2*x*x*x),
                angle * 6*x*(1-x)/duration,
                angle * 6*(1-2*x)/(duration*duration))
    return at


def forcing(program, power=20.):
    def at(t, angle, rate, torque, moving):
        base = program.forcing[0].standby
        wait = replace(base, sunlit=False, incidence_angle_deg=angle*180/pi,
                       loads=replace(base.loads, adcs_w=power if moving else 0.))
        return wait, {"actuator_w": power if moving else 0.}
    return at


def run(context, program, **changes):
    args = dict(duration_seconds=20, integration_level=1, start_angle_rad=0.,
                trajectory_at=trajectory(), forcing_at=forcing(program),
                policy=program.protection)
    args.update(changes)
    return execute_profile(context, **args)


@pytest.mark.parametrize("level", [0, 1, 2])
def test_eclipse_boundaries_during_motion_have_exact_elapsed_generation(level):
    context, program = setup(11)
    calls = []
    motion = trajectory(23)

    def changing(time, angle, rate, torque, moving):
        calls.append((time, angle, rate, torque))
        wait, diagnostics = forcing(program)(time, angle, rate, torque, moving)
        # Explicit half-open synthetic illumination: 7 + 4 seconds of light.
        # Constant incidence isolates time integration from angular quadrature.
        return replace(wait, sunlit=time < 18 or time >= 30,
                       incidence_angle_deg=0.), diagnostics

    out = run(context, program, duration_seconds=23, integration_level=level,
              trajectory_at=motion, forcing_at=changing,
              forcing_breakpoints_seconds=(18, 30))
    assert out.approved and context.simulation_time_seconds == 34
    assert out.accounting.numerical_substeps == (2 + 3 + 1) * 2**level
    assert out.samples[0].time_seconds == 11 and out.samples[-1].time_seconds == 34
    assert {Fraction(18), Fraction(30)} <= {s.time_seconds for s in out.samples}
    assert all(type(s.time_seconds) is Fraction for s in out.samples)
    assert sum((i.end_seconds - i.start_seconds for i in out.intervals), Fraction()) == 23
    assert sum((i.end_seconds - i.start_seconds for i in out.intervals
                if i.end_seconds <= 18 or i.start_seconds >= 30), Fraction()) == 11
    assert out.accounting.generation_wh == pytest.approx(225 * 11 / 3600, abs=2*ulp(1.))
    assert out.accounting.requested_load_wh == pytest.approx(32 * 23 / 3600, abs=2*ulp(1.))
    for sample in out.samples:
        assert sample.angle_rad == motion(sample.time_seconds - 11)[0]
    for interval, (time, angle, rate, torque) in zip(out.intervals, calls, strict=True):
        assert time == (interval.start_seconds + interval.end_seconds) / 2
        assert type(time) is Fraction and time not in (18, 30)
        assert (angle, rate, torque) == motion(time - 11)
        assert not any(interval.start_seconds < b < interval.end_seconds for b in (18, 30))
        assert interval.end_seconds - interval.start_seconds <= Fraction(5, 2**level)


def test_nonuniform_kinetic_heat_uses_global_endpoint_rates_and_local_duration():
    context, program = setup(11)
    motion = trajectory(23)
    ordinary = forcing(program)

    def kinetic(time, angle, rate, torque, moving):
        wait, diagnostic = ordinary(time, angle, rate, torque, moving)
        return wait, dict(diagnostic, body_inertia_kg_m2=2., rotor_inertia_kg_m2=.5)

    out = run(context, program, duration_seconds=23, trajectory_at=motion,
              forcing_at=kinetic, forcing_breakpoints_seconds=(18, 30))
    adjustments = []
    for interval in out.intervals:
        a = motion(interval.start_seconds - 11)[1]
        b = motion(interval.end_seconds - 11)[1]
        # 0.5 I_body omega^2 + 0.5 (I_body omega)^2 / I_rotor.
        energy_a, energy_b = .5*2*a*a + .5*(2*a)**2/.5, .5*2*b*b + .5*(2*b)**2/.5
        d = dict(interval.diagnostics)
        assert d["kinetic_start_j"] == energy_a
        assert d["kinetic_end_j"] == energy_b
        seconds = float(interval.end_seconds - interval.start_seconds)
        assert d["actuator_heat_adjustment_w"] == (energy_a-energy_b)/seconds
        adjustments.append(d["actuator_heat_adjustment_w"] * seconds)
    assert abs(fsum(adjustments)) <= 8*ulp(1.)
    assert out.accounting.routed_internal_heat_wh == pytest.approx(32*23/3600, abs=8*ulp(1.))


@pytest.mark.parametrize("breakpoints", [
    None, [], [18], (True,), (18.,), (Fraction(18),), ("18",),
    (11,), (34,), (10,), (35,), (18, 18), (30, 18), (18, 34),
])
def test_breakpoints_reject_invalid_type_order_and_noninterior_times(breakpoints):
    context, program = setup(11)
    before = canonical_content(checked_checkpoint(context))
    with pytest.raises((TypeError, ValueError), match="forcing breakpoints"):
        run(context, program, duration_seconds=23, trajectory_at=trajectory(23),
            forcing_breakpoints_seconds=breakpoints)
    assert canonical_content(checked_checkpoint(context)) == before


def test_guard_applies_to_total_partition_across_all_spans():
    context, program = setup()
    before = canonical_content(checked_checkpoint(context))
    # Each span would individually fit 4096; together they must still reject.
    with pytest.raises(ValueError, match="bounded physical work"):
        run(context, program, duration_seconds=10, trajectory_at=trajectory(10),
            integration_level=12, max_interval_seconds=10, forcing_breakpoints_seconds=(5,))
    assert canonical_content(checked_checkpoint(context)) == before


def test_late_denial_discards_motion_prefix_and_replays_complete_partition_as_hold():
    context, program = setup(11)
    reference, _ = setup(11)
    calls = []

    def changing(time, angle, rate, torque, moving):
        calls.append((time, moving))
        power = 1000. if time >= 18 else 20.
        wait, diagnostic = forcing(program, power)(time, angle, rate, torque, moving)
        return replace(wait, sunlit=time < 18, incidence_angle_deg=0.), diagnostic

    def held(time, angle, rate, torque, moving):
        wait, diagnostic = forcing(program, 0.)(time, 0., 0., 0., False)
        return replace(wait, sunlit=time < 18, incidence_angle_deg=0.), diagnostic

    args = dict(duration_seconds=23, forcing_breakpoints_seconds=(18, 30))
    out = run(context, program, trajectory_at=trajectory(23), forcing_at=changing, **args)
    hold = run(reference, program, trajectory_at=lambda _: (0., 0., 0.), forcing_at=held, **args)
    assert not out.approved and hold.approved
    assert out.reasons == ("motion-full-electrical-service-unavailable",)
    assert out.predicted_unmet_w > 0 and out.final_angle_rad == 0.
    assert any(time < 18 and moving for time, moving in calls)
    assert any(time > 18 and moving for time, moving in calls)
    assert out.samples == hold.samples and out.intervals == hold.intervals
    assert out.accounting == hold.accounting
    assert out.accounting.requested_load_wh == pytest.approx(12*23/3600, abs=2*ulp(1.))
    assert out.accounting.generation_wh == pytest.approx(225*7/3600, abs=2*ulp(1.))
    assert context.simulation_time_seconds == 34
    assert context.spacecraft_state.onboard.fdir_state is FDIRState.BACKUP


def test_callback_failure_after_forcing_boundary_preserves_whole_original_state():
    context, program = setup(11)
    before = canonical_content(checked_checkpoint(context))
    ordinary = forcing(program)

    def broken(time, angle, rate, torque, moving):
        if time > 18:
            raise ValueError("incomplete forcing after physical progress")
        return ordinary(time, angle, rate, torque, moving)

    with pytest.raises(ValueError, match="incomplete forcing"):
        run(context, program, duration_seconds=23, trajectory_at=trajectory(23),
            forcing_at=broken, forcing_breakpoints_seconds=(18, 30))
    assert canonical_content(checked_checkpoint(context)) == before


@pytest.mark.parametrize("duration,level,power,expected", [
    (20, 1, 20., "4c0a70d8ef9daddf3b8e70a1fc1d1bc19cb8bea7ea766e1e18134ac223683d31"),
    (21, 2, 20., "6aa69e6134d0374de52381bb780f910c9082980317d9029a74ec66ae46ccbca9"),
    (20, 1, 1000., "72640078440aca14a7cfdd7fd7c18592bbb86692e9145a04f3c8b830743c53a8"),
])
def test_default_outcome_and_checkpoint_match_frozen_05e_bytes(duration, level, power, expected):
    # Captured from a80f34c before editing the profile owner. ProfileOutcome is
    # deliberately not a canonical codec record, so its complete repr is bound
    # alongside the canonical checkpoint; no schema widening is needed.
    results = []
    for extra in ({}, {"forcing_breakpoints_seconds": ()}):
        context, program = setup()
        out = run(context, program, duration_seconds=duration, integration_level=level,
                  trajectory_at=trajectory(duration), forcing_at=forcing(program, power), **extra)
        content = repr(out) + json_text(canonical_content(checked_checkpoint(context)))
        results.append(sha256(content.encode()).hexdigest())
    assert results == [expected, expected]
