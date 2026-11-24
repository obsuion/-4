"""Focused additive-owner contracts; no claim of lifecycle integration."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from fractions import Fraction as Q
from math import fsum, ulp

import pytest

from examples.m4_construction_mission_demo import make_inputs
from ops_sim.v5.assembly_attitude_3d import compile_assembly_hardware_3d
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.construction_mission import start_construction_mission
from ops_sim.v5.construction_physics import construction_physical_substep
from ops_sim.v5.construction_service import (ConstructionServicePolicy,
    ConstructionServiceWork, service_physical_substep)
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.long_mission import _forcing


def leaf(*, energy=None, sunlit=False, seconds=1, mode='SAFE'):
    state = start_construction_mission(make_inputs())
    if energy is not None:
        state.context.spacecraft_state.battery.energy_wh = energy
    hardware = compile_assembly_hardware_3d(state.inputs.assembly,
        state.inputs.capabilities, state.inputs.actuator)
    forcing, eps, *_ = _forcing(state, hardware, Q(130), Q(131), state.attitude.quaternion)
    eps = replace(eps, sunlit=sunlit, incidence_angle_deg=0.)
    paid = ConstructionServiceWork()
    kwargs = dict(compilation=state.construction.compilation,
        service_policy=ConstructionServicePolicy(), service_mode=mode,
        service_work=paid, work=state.construction.work,
        limits=state.construction.inputs.limits,
        start_seconds=Q(130), end_seconds=Q(130+seconds))
    return state, forcing, eps, RationalSeconds.from_fraction(Q(seconds)), paid, kwargs


def test_full_normal_keeps_accepted_coupled_projection_exact():
    state, forcing, eps, duration, paid, kwargs = leaf(mode='NORMAL')
    old = deepcopy(state.context)
    expected, _ = construction_physical_substep(old, duration, forcing, eps,
        state.inputs.protection, None, compilation=state.construction.compilation,
        work=None, limits=None)
    part, _ = service_physical_substep(state.context, duration, forcing, eps,
        state.inputs.protection, None, **kwargs)
    assert asdict(part.physical) == asdict(expected.physical)
    assert part.electrical == expected.electrical
    assert part.receiving_retained_heat_w == expected.receiving_retained_heat_w
    assert CheckpointState.from_context(old).to_dict() == CheckpointState.from_context(state.context).to_dict()
    assert part.service.full_commanded_service and paid.allocation_trials == 1
    assert part.service.full_demand_trial is part.electrical


def test_empty_dark_power_off_advances_passive_thermal_without_service_grant():
    state, forcing, eps, duration, paid, kwargs = leaf(energy=0., mode='POWER_OFF')
    before = tuple(n.temperature_k for n in state.context.spacecraft_state.thermal.node_states)
    part, carrier = service_physical_substep(state.context, duration, forcing, eps,
        state.inputs.protection, None, **kwargs)
    d = part.service
    assert d.commanded_load_w > 0 and d.served_load_w == 0
    assert d.essential_unserved_w > 0 and not d.essential_fully_served
    assert not d.obc_serviceable and not d.communications_serviceable
    assert d.full_demand_trial.battery.unmet_load_w > 0
    assert d.full_demand_trial.battery is not carrier.battery
    assert carrier.battery.start_energy_wh == carrier.battery.end_energy_wh == 0
    assert paid.allocation_trials == 2 and paid.bisection_trials == 0
    assert paid.selected_coupled_calls == 1
    assert tuple(n.temperature_k for n in state.context.spacecraft_state.thermal.node_states) != before
    # The leaf does not counterfeit clock/orbit/attitude evolution.
    assert state.context.simulation_time_seconds == 128
    assert d.start_seconds == 130 and d.end_seconds == 131
    with pytest.raises(FrozenInstanceError):
        d.reason = 'fabricated'


def test_partial_receiving_service_has_real_wire_heat_and_no_working_obc():
    state, forcing, eps, duration, paid, kwargs = leaf(energy=.0001)
    part, carrier = service_physical_substep(state.context, duration, forcing, eps,
        state.inputs.protection, None, **kwargs)
    d = part.service
    assert 0 < d.served_load_w < d.commanded_load_w
    assert d.essential_unserved_w > 0 and not d.obc_serviceable
    assert d.selected_electrical.receiving_wire_loss_w > 0
    assert d.selected_electrical.source_load_w > d.served_load_w
    assert carrier.battery.unmet_load_w == 0
    assert 0 < paid.bisection_trials <= 64
    paid.validate()
    b = carrier.battery
    energy_delta = (b.charge_input_w-b.discharge_output_w)*b.dt_seconds/3600-b.conversion_loss_wh
    assert abs((b.end_energy_wh-b.start_energy_wh)-energy_delta) <= 8*ulp(max(b.start_energy_wh, 1.))
    assert abs(fsum(v for _, v in part.wire_heat_w)-part.electrical.receiving_wire_loss_w) <= 8*ulp(max(part.electrical.source_load_w, 1.))


def test_safe_sheds_authored_nonessential_without_renaming_it_served():
    state, forcing, eps, duration, paid, kwargs = leaf()
    eps = replace(eps, load_breakdown=replace(eps.load_breakdown,
        payload_w=7., communications_w=3., adcs_w=2.))
    part, _ = service_physical_substep(state.context, duration, forcing, eps,
        state.inputs.protection, None, **kwargs)
    d = part.service
    assert d.shed_load_w == 12.
    assert d.commanded_loads.payload_w == d.served_loads.payload_w == 0
    assert d.desired_loads.payload_w == 7.
    assert d.obc_serviceable and not d.communications_serviceable
    assert d.full_commanded_service


def test_power_off_can_charge_without_inventing_attitude_change():
    state, forcing, eps, duration, paid, kwargs = leaf(energy=0., sunlit=True, mode='POWER_OFF')
    attitude = state.attitude
    part, carrier = service_physical_substep(state.context, duration, forcing, eps,
        state.inputs.protection, None, **kwargs)
    assert part.electrical.source_generation_w > part.electrical.delivered_generation_w > 0
    assert carrier.battery.charge_input_w > 0 and carrier.battery.end_energy_wh > 0
    assert part.electrical.pv_wire_loss_w > 0
    assert state.attitude == attitude
    assert not part.service.communications_serviceable


@pytest.mark.parametrize('field,value', [('method', 'other'), ('max_bisections', True), ('max_bisections', 33)])
def test_policy_rejects_unknown_or_changed_numerical_contract(field, value):
    with pytest.raises(ValueError):
        ConstructionServicePolicy(**{field: value})


def test_zero_essential_demand_is_rejected_before_any_trial():
    state, forcing, eps, duration, paid, kwargs = leaf()
    eps = replace(eps, load_breakdown=replace(eps.load_breakdown, base_bus_w=0., obc_w=0.))
    before = CheckpointState.from_context(state.context).to_dict()
    with pytest.raises(ValueError, match='positive authored essential'):
        service_physical_substep(state.context, duration, forcing, eps,
            state.inputs.protection, None, **kwargs)
    assert paid.allocation_trials == 0
    assert CheckpointState.from_context(state.context).to_dict() == before


def test_invalid_interval_is_rejected_before_any_trial():
    state, forcing, eps, duration, paid, kwargs = leaf()
    kwargs['end_seconds'] = Q(132)
    with pytest.raises(ValueError, match='exact inner service interval'):
        service_physical_substep(state.context, duration, forcing, eps,
            state.inputs.protection, None, **kwargs)
    assert paid.allocation_trials == 0
