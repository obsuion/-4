from dataclasses import replace,asdict
from fractions import Fraction as Q
import pytest
from examples.m4_mass_closed_mission_demo import make_inputs,report
from ops_sim.v5.harness_mission import start_harness_mission,advance_harness_mission,continue_harness_mission
from ops_sim.v5.harness_hardware import compile_effective_hardware
from ops_sim.v5.harness_slew import plan_effective_slew
from ops_sim.v5.checkpoint import CheckpointState


def test_actual_mass_aware_600s_chain_and_mechanical_effect():
    base=continue_harness_mission(start_harness_mission(make_inputs('unassembled')))
    augmented=continue_harness_mission(start_harness_mission(make_inputs('augmented')))
    for state in (base,augmented):
        assert state.context.simulation_time_seconds==728 and len(state.context.ground_data_delivery_state.completed_deliveries)==1
        assert not state.context.ground_data_delivery_state.partial_transfers and len(state.assessment()[0].credited_record_ids)==1
    a,b=report(base)['harness'],report(augmented)['harness']
    assert a['mass_scope']=='NOT_MASS_CLOSED_UNASSEMBLED_CONTROL'
    assert b['mass_scope']=='MASS_CLOSED_WITHIN_RIGID_LUMPED_B46_MODEL'
    assert b['effective_mass_properties']['total_mass_kg']>b['base_mass_properties']['total_mass_kg']
    assert a['effective_axis_inertia']!=b['effective_axis_inertia']
    assert a['actuator_electrical_wh']!=b['actuator_electrical_wh']
    assert augmented.harness.work.compilation_calls>0


def test_cached_arbitrary_tensor_cannot_grant_hardware_or_mission():
    state=start_harness_mission(make_inputs());before=CheckpointState.from_context(state.context).to_dict()
    hardware=state.harness.hardware
    fake=replace(hardware,tensor_exact=((Q(1),Q(0),Q(0)),(Q(0),Q(1),Q(0)),(Q(0),Q(0),Q(1))))
    with pytest.raises(ValueError,match='foreign/stale'):plan_effective_slew(fake,state.attitude,(0.,1.,0.))
    state.harness=replace(state.harness,hardware=fake)
    with pytest.raises(ValueError,match='foreign cached'):advance_harness_mission(state)
    assert CheckpointState.from_context(state.context).to_dict()==before and state.runtime_work.physical_completed_calls==0


def test_distribution_same_mass_has_actual_paid_dynamics_effect():
    first=make_inputs('augmented');second=make_inputs('redistributed');assert first.coupled==second.coupled
    a=advance_harness_mission(start_harness_mission(first));b=advance_harness_mission(start_harness_mission(second))
    assert a.harness.hardware.augmentation.added_mass_exact_kg==b.harness.hardware.augmentation.added_mass_exact_kg
    assert a.harness.hardware.augmentation.effective_tensor_exact_kg_m2!=b.harness.hardware.augmentation.effective_tensor_exact_kg_m2
    assert a.outcomes[0].slew.effective_inertia_kg_m2!=b.outcomes[0].slew.effective_inertia_kg_m2
    assert any(x.actuator_draw_w!=y.actuator_draw_w for x,y in zip(a.outcomes[0].cuts,b.outcomes[0].cuts)) or a.outcomes[0].slew.duration_seconds!=b.outcomes[0].slew.duration_seconds
