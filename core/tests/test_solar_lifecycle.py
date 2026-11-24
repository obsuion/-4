"""Real original-input physical actions, no fake geometry or mode credit."""
from dataclasses import replace
from fractions import Fraction as Q
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy
from ops_sim.v5.lifecycle_service import PowerServicePolicy
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle
from ops_sim.v5.lifecycle_physics import execute_lifecycle_action,resume_pending_lifecycle_action,guard_lifecycle_physical
from ops_sim.v5.solar_attitude import EnergyAttitudePolicy,SolarAction,panel_axis
from ops_sim.v5.solar_lifecycle import select_solar_action

def root(energy=45.,variant='compact',duration=600):
    from ops_sim.v5.checkpoint import CheckpointState
    b=make_inputs(variant,wire='nominal');context=b.initial_checkpoint.restore(b.model.simulation_inputs)
    context.spacecraft_state.battery.energy_wh=energy
    b=replace(b,reference=replace(b.reference,initial_checkpoint=CheckpointState.from_context(context)))
    return LifecycleRoot(b,duration,policy=LifecyclePolicy(quiet_solver=QuietIntegrationPolicy()),service_policy=PowerServicePolicy(),energy_attitude_policy=EnergyAttitudePolicy())

def test_real_paid_sun_point_changes_pose_and_preserves_true_mounts():
    state=start_lifecycle(root());p,action=select_solar_action(state.physical,188,'solar-original')
    assert action.kind=='SOLAR_POINT' and p.solar_state.phase=='CHARGE'
    before=p.attitude.quaternion;camera=p.harness.hardware.camera_body_axis
    p,out=execute_lifecycle_action(p,action)
    assert out.status=='completed' and out.end_seconds>128
    assert p.attitude.quaternion!=before and p.harness.hardware.camera_body_axis==camera
    target=p.solar_state.held_target
    assert p.attitude.direction(panel_axis(p.harness.hardware))==pytest.approx(target.direction_inertial,abs=3e-14)
    assert p.solar_state.paid_point_seconds==out.end_seconds-128
    assert p.solar_state.actuator_requested_wh>0
    assert out.cuts and any(c.actuator_draw_w>0 for c in out.cuts)
    assert p.service_allocation_work.selected_coupled_calls>=len(out.cuts)
    assert not p.acquisitions and not p.receipts
    guard_lifecycle_physical(p)

def test_substantive_partial_point_then_resume_uses_same_original_plan():
    state=start_lifecycle(root());p,a=select_solar_action(state.physical,188,'partial-sun')
    p,o=execute_lifecycle_action(p,a,stop_at_seconds=130)
    assert o.status=='partial' and p.pending.kind=='SOLAR_POINT'
    original=p.pending.slew
    assert p.solar_state.held_target is None and p.solar_state.point_attempts==1
    p,o=resume_pending_lifecycle_action(p)
    assert o.status=='completed' and p.pending is None
    assert p.solar_state.paid_point_seconds==original.duration_seconds
    assert p.solar_state.point_attempts==p.solar_state.point_completions==1

def test_existing_paid_action_is_never_erased_by_charge_selection():
    state=start_lifecycle(root());p,a=select_solar_action(state.physical,188,'existing-sun')
    p,_=execute_lifecycle_action(p,a,stop_at_seconds=129)
    selected,action=select_solar_action(p,188,'cannot-preempt')
    assert selected is p and action is None and p.pending is not None

def test_empty_battery_has_no_free_slew_and_unpayable_reserve_refuses():
    for energy in (0.,12.):
        state=start_lifecycle(root(energy));p=state.physical;q=p.attitude.quaternion
        p,o=execute_lifecycle_action(p,SolarAction('no-free-turn','SOLAR_POINT',p.inputs.energy_attitude_policy.identity))
        assert o.status=='refused' and o.end_seconds==128
        assert p.attitude.quaternion==q and p.solar_state.paid_point_seconds==0
        assert p.solar_state.point_refusals==1

def test_hysteresis_minimum_dwell_and_paid_repoint_frontier():
    state=start_lifecycle(root());p,a=select_solar_action(state.physical,188,'entry')
    assert p.solar_state.minimum_until_seconds==728
    p,_=execute_lifecycle_action(p,a)
    # Declared counterfactual unit input, not a reached campaign checkpoint.
    p.context.spacecraft_state.battery.energy_wh=90.
    p,a=select_solar_action(p,188,'dwell')
    assert p.solar_state.phase=='CHARGE' and a.kind=='SOLAR_HOLD'
    assert p.solar_state.next_point_check_seconds>p.context.simulation_time_seconds

def test_initial_chronological_action_is_onboard_not_ground_ack():
    s=start_lifecycle(root());s,_,_=step_lifecycle(s)
    assert s.recent[-1]['kind']=='SOLAR_POINT'
    assert s.recent[-1]['intent_authority']=='ONBOARD_AUTONOMOUS_PREVENTIVE_CHARGE'
    assert s.work.acknowledged_commands==0
    assert not s.intents and not s.physical.receipts


def test_loss_during_motion_retains_paid_phase_without_teleport():
    s=start_lifecycle(root());p,a=select_solar_action(s.physical,188,'moving-loss')
    p,_=execute_lifecycle_action(p,a,stop_at_seconds=129)
    q=p.attitude.quaternion;phase=p.pending;paid=p.solar_state.paid_point_seconds
    # Explicit counterfactual power-loss unit input, not a reached month state.
    p.context.spacecraft_state.battery.energy_wh=0.
    p,o=resume_pending_lifecycle_action(p)
    assert o.status=='refused' and o.end_seconds==129
    assert p.attitude.quaternion==q and p.pending==phase
    assert p.solar_state.paid_point_seconds==paid
    assert p.solar_state.held_target is None


def test_held_target_wrong_epoch_or_clock_rejected():
    s=start_lifecycle(root());p,a=select_solar_action(s.physical,188,'guard-target')
    p,_=execute_lifecycle_action(p,a)
    for changed in (replace(p.solar_state,clock_seconds=p.solar_state.clock_seconds+1),
        replace(p.solar_state,held_target=replace(p.solar_state.held_target,epoch_identity='f'*64))):
        with pytest.raises((TypeError,ValueError)):guard_lifecycle_physical(replace(p,solar_state=changed))


def test_real_hold_retains_quaternion_and_reports_selected_pv_shadow_support():
    s=start_lifecycle(root());p,a=select_solar_action(s.physical,188,'hold-start')
    p,_=execute_lifecycle_action(p,a);q=p.attitude.quaternion;end=p.context.simulation_time_seconds+60
    p,o=execute_lifecycle_action(p,SolarAction('fixed-inertial-hold','SOLAR_HOLD',p.inputs.energy_attitude_policy.identity,until_seconds=end))
    assert o.status=='completed' and p.attitude.quaternion==q
    assert p.solar_state.charge_hold_seconds==60
    for c in o.cuts:
        source=c.part.eps_result.solar
        # Independent one-sided projected-area equation from declared forcing.
        from math import cos,radians
        expected=source.nominal_generation_w*(1. if source.sunlit else 0.)*max(0.,cos(radians(c.incidence_angle_deg)))
        if c.incidence_angle_deg>=90:expected=0.
        assert source.generation_w==expected
        assert c.panel_inertial==p.attitude.direction(panel_axis(p.harness.hardware))
    assert p.solar_state.last_support==(o.cuts[-1].start_seconds,o.cuts[-1].end_seconds)


@pytest.mark.parametrize('sunlit,angle,expected',[(False,0.,0.),(False,60.,0.),(True,0.,1.),(True,60.,.5),(True,120.,0.)])
def test_independent_one_sided_pv_reference(sunlit,angle,expected):
    from ops_sim.v5.solar import compute_solar_generation
    cfg=make_inputs().model.simulation_inputs.spacecraft_configuration.eps.solar_array
    result=compute_solar_generation(cfg,sunlit=sunlit,incidence_angle_deg=angle)
    assert result.generation_w==pytest.approx(expected*cfg.nominal_generation_w.value,abs=2e-14)


def test_selected_solar_hold_quiet_against_finer_detailed_reference():
    results=[]
    for detailed,quiet in ((2,True),(2,False),(1,False)):
        s=start_lifecycle(root());p,a=select_solar_action(s.physical,188,'physical-screen-point')
        p=replace(p,inputs=replace(p.inputs,model=replace(p.inputs.model,
            limits=replace(p.inputs.limits,detailed_interval_seconds=detailed),
            quiet_policy=p.inputs.quiet_policy if quiet else None)),
            quiet_controller=p.quiet_controller if quiet else None,quiet_work=p.quiet_work if quiet else None)
        p,_=execute_lifecycle_action(p,a)
        end=p.context.simulation_time_seconds+60
        p,o=execute_lifecycle_action(p,SolarAction('physical-screen-hold','SOLAR_HOLD',p.inputs.energy_attitude_policy.identity,until_seconds=end))
        assert o.status=='completed';results.append(p)
    reference=results[-1]
    for p in results[:2]:
        assert abs(p.context.spacecraft_state.battery.energy_wh-reference.context.spacecraft_state.battery.energy_wh)<=.005
        assert max(abs(a.temperature_k-b.temperature_k) for a,b in zip(p.context.spacecraft_state.thermal.node_states,reference.context.spacecraft_state.thermal.node_states))<=.05
        assert p.solar_state.point_completions==1 and p.solar_state.charge_hold_seconds==60
