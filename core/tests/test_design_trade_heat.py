"""Opt-in mechanical-energy/heat exchange preserves the legacy EPS owner."""

from copy import deepcopy
from dataclasses import replace
from math import ulp

import pytest

from examples import v5_substepped_execution_demo as demo
from ops_sim.v5.eps_system import EPSIntervalInputs
from ops_sim.v5.ids import ThermalNodeId
from ops_sim.v5.integration_time import DyadicDuration
from ops_sim.v5.substepped_execution import _aggregate, _physical_substep


def execute(state, **optional):
    forcing = state.program.requests[0].request.standby
    return _physical_substep(state.context, DyadicDuration(1, 0), forcing,
        EPSIntervalInputs(forcing.sunlit, forcing.incidence_angle_deg, forcing.loads),
        state.program.policy, None, standby=True, **optional)


def by_name(part):
    return {node.node_id.value: node for node in part.thermal_coupling_result.node_heat_ledgers}


def transitions(part):
    return {node.node_id.value: node for node in part.thermal_coupling_result.thermal_result.node_transitions}


def test_default_none_preserves_existing_exact_eps_heat_and_state():
    first, second = demo.build_demo_state(), demo.build_demo_state()
    a, eps_a = execute(first)
    b, eps_b = execute(second, internal_heat_adjustments_w=None)
    assert a == b and eps_a == eps_b and first.context == second.context
    # Independent legacy fixture: 20 W served, 50% routed to bus, plus 2 W
    # external. Its isolated 3600 J/K bus receives exactly 12 J over 1 s.
    assert eps_a.battery.served_load_w == 20
    assert by_name(a)["bus"].internal_dissipation_w == 10
    assert transitions(a)["bus"].thermal_energy_change_j == 12
    assert transitions(a)["bus"].end_temperature_k == 300 + 12 / 3600


@pytest.mark.parametrize("watts", [-5.0, 5.0, -10.0, 0.0])
def test_signed_storage_release_changes_only_routed_heat_not_electrical_energy(watts):
    baseline, adjusted = demo.build_demo_state(), demo.build_demo_state()
    forcing_before = deepcopy(adjusted.program.requests[0].request.standby)
    original, original_eps = execute(baseline)
    changed, changed_eps = execute(adjusted,
        internal_heat_adjustments_w=((ThermalNodeId("bus"), watts),))
    assert changed_eps == original_eps
    assert adjusted.context.spacecraft_state.battery == baseline.context.spacecraft_state.battery
    assert adjusted.program.requests[0].request.standby == forcing_before
    assert by_name(changed)["bus"].internal_dissipation_w == 10 + watts
    assert transitions(changed)["bus"].thermal_energy_change_j == 12 + watts
    assert transitions(changed)["bus"].end_temperature_k == 300 + (12 + watts) / 3600
    for node in ("battery", "payload"):
        assert by_name(changed)[node] == by_name(original)[node]
        assert transitions(changed)[node] == transitions(original)[node]
    a, b = _aggregate((original,)), _aggregate((changed,))
    assert b.routed_internal_heat_wh - a.routed_internal_heat_wh == pytest.approx(
        watts / 3600, rel=2e-15, abs=1e-18)
    assert b.conversion_loss_wh == a.conversion_loss_wh
    assert b.external_heat_wh == a.external_heat_wh
    assert b.served_load_wh == a.served_load_wh


def test_two_node_heat_exchange_and_unchanged_battery_conversion_owner():
    state = demo.build_demo_state()
    part, eps = execute(state, internal_heat_adjustments_w=(
        (ThermalNodeId("bus"), -5.0), (ThermalNodeId("battery"), 5.0)))
    ledgers = by_name(part)
    assert ledgers["bus"].internal_dissipation_w == 5
    assert ledgers["battery"].internal_dissipation_w == 5
    conversion_w = eps.battery.conversion_loss_wh * 3600 / eps.battery.dt_seconds
    assert ledgers["battery"].battery_conversion_heat_w == conversion_w
    assert ledgers["battery"].total_applied_heat_w == 6 + conversion_w
    assert _aggregate((part,)).routed_internal_heat_wh == 10 / 3600


def test_rotor_momentum_energy_has_an_independent_nominal_budget():
    from ops_sim.v5.comparison_campaign import build_inputs_program
    from ops_sim.v5.design_trade_execution import execute_profile
    from ops_sim.v5.design_trade_physics import SlewProfile

    inputs, program = build_inputs_program("J-E1")
    context = program.initial_checkpoint.restore(inputs)
    initial_energy = context.spacecraft_state.battery.energy_wh
    profile = SlewProfile(.8, 10., .02, .02, .2)
    assert profile.duration_s == 50

    def trajectory(t):
        elapsed = float(t)
        return (profile.angle_at(elapsed), profile.omega_at(elapsed),
                profile.acceleration_at(elapsed) * profile.inertia_kg_m2)

    def forcing(t, angle, rate, torque, moving):
        original = program.forcing[0].standby
        return (replace(original, sunlit=False, loads=replace(original.loads,
                    adcs_w=25. if moving else .5)),
                dict(body_inertia_kg_m2=10., rotor_inertia_kg_m2=.00034))

    outcome = execute_profile(context, duration_seconds=50, integration_level=1,
        start_angle_rad=0., trajectory_at=trajectory, forcing_at=forcing,
        policy=program.protection)
    assert outcome.approved
    # Independent H²/(2J) rotor energy, plus H²/(2I) body energy. The wheel
    # stores ~58.8235 J, so counting only the 0.002 J body term is insufficient.
    expected_peak = .2**2 / (2*.00034) + .2**2 / (2*10)
    peak = max(dict(item.diagnostics)["kinetic_end_j"] for item in outcome.intervals)
    assert abs(peak - expected_peak) <= 8*ulp(expected_peak)
    assert dict(outcome.intervals[0].diagnostics)["kinetic_start_j"] == 0
    assert dict(outcome.intervals[-1].diagnostics)["kinetic_end_j"] == 0
    expected_load = (12 + 25) * 50 / 3600
    assert abs(outcome.accounting.routed_internal_heat_wh - expected_load) <= 8*ulp(expected_load)
    expected_battery = initial_energy - expected_load/.9
    assert abs(context.spacecraft_state.battery.energy_wh - expected_battery) <= (
        2*len(outcome.intervals)*ulp(initial_energy))


class HostileFloat(float):
    def __eq__(self, other):
        return True


class HostileText(str):
    pass


@pytest.mark.parametrize("adjustments", [
    [(ThermalNodeId("bus"), 1.0)],
    ([ThermalNodeId("bus"), 1.0],),
    ((ThermalNodeId("bus"),),),
    ((ThermalNodeId("unknown"), 1.0),),
    ((ThermalNodeId("bus"), 1.0), (ThermalNodeId("bus"), 2.0)),
    (("bus", 1.0),),
    ((ThermalNodeId(HostileText("bus")), 1.0),),
    ((ThermalNodeId("bus"), True),),
    ((ThermalNodeId("bus"), HostileFloat(1.0)),),
    ((ThermalNodeId("bus"), float("nan")),),
    ((ThermalNodeId("bus"), float("inf")),),
    ((ThermalNodeId("bus"), float("-inf")),),
    ((ThermalNodeId("bus"), 10**1000),),
    ((ThermalNodeId("bus"), -10.000000000000002),),
    ((ThermalNodeId("payload"), -1.0),),
])
def test_invalid_adjustment_rejects_without_private_state_mutation(adjustments):
    state = demo.build_demo_state()
    before = deepcopy(state.context)
    with pytest.raises((ValueError, TypeError)):
        execute(state, internal_heat_adjustments_w=adjustments)
    assert state.context == before
