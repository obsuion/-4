"""Narrow synthetic deadline domain, real paid physical state/coordinator."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy,LifecycleScenario
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.lifecycle_service import PowerServicePolicy
from ops_sim.v5.solar_attitude import EnergyAttitudePolicy,SolarAction
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle
from ops_sim.v5.lifecycle_physics import pending_pins_product,guard_lifecycle_physical
from ops_sim.v5.long_mission import LongMissionAction

def root(deadline):
    b=make_inputs();ctx=b.initial_checkpoint.restore(b.model.simulation_inputs);ctx.spacecraft_state.battery.energy_wh=45.
    b=replace(b,reference=replace(b.reference,initial_checkpoint=CheckpointState.from_context(ctx)))
    return LifecycleRoot(b,600,policy=LifecyclePolicy(quiet_solver=QuietIntegrationPolicy()),
        scenario=LifecycleScenario(acquisition_window_seconds=2,capture_duration_seconds=1,contact_offset_seconds=1,contact_duration_seconds=1,deadline_offset_seconds=deadline),
        service_policy=PowerServicePolicy(),energy_attitude_policy=EnergyAttitudePolicy())

def test_expiry_retirement_during_partial_paid_solar_point_then_original_resume():
    s=start_lifecycle(root(2));s,event,_=step_lifecycle(s)
    # The existing1s delayed-observation boundary precedes the2s expiry.
    if s.clock==129:s,event,_=step_lifecycle(s)
    assert s.clock==130 and s.physical.pending.kind=='SOLAR_POINT'
    original=s.physical.pending.slew;paid=s.physical.solar_state.paid_point_seconds
    assert paid==2 and s.work.retired_requests==1 and not s.physical.inputs.products
    assert not s.active and not s.pinned_requests
    guard_lifecycle_physical(s.physical)
    for _ in range(24):
        s,_,_=step_lifecycle(s)
        if s.physical.pending is None or s.physical.pending.kind!='SOLAR_POINT':break
    assert s.physical.solar_state.point_completions==1
    assert s.physical.solar_state.paid_point_seconds==original.duration_seconds

def test_expiry_retirement_during_partial_solar_hold_preserves_pending():
    s=start_lifecycle(root(12))
    for _ in range(24):
        s,_,_=step_lifecycle(s)
        if s.clock>=138:break
    assert s.clock==138 and s.physical.pending is None
    # Explicit physical cut inside a longer original hold, not a changed month
    # partition. The normal coordinator's hold ends at the deadline itself.
    from ops_sim.v5.lifecycle_physics import execute_lifecycle_action,resume_pending_lifecycle_action
    from ops_sim.v5.lifecycle_execution import _dispositions,_prune_power_requests
    p,o=execute_lifecycle_action(s.physical,SolarAction('partial-hold','SOLAR_HOLD',s.root.energy_attitude_policy.identity,until_seconds=148),stop_at_seconds=140)
    s=replace(s,physical=p);s,_,expired=_dispositions(s,140);assert expired==1
    s,_=_prune_power_requests(s,defer_retention=True)
    assert s.clock==140 and s.physical.pending.kind=='SOLAR_HOLD'
    original=s.physical.pending
    assert s.work.retired_requests==1 and not s.physical.inputs.products
    assert s.physical.solar_state.charge_hold_seconds==2
    guard_lifecycle_physical(s.physical)
    assert s.physical.pending==original
    p,o=resume_pending_lifecycle_action(s.physical)
    assert o.status=='completed' and o.end_seconds==148 and p.pending is None

@pytest.mark.parametrize('kind',['SOLAR_POINT','SOLAR_HOLD'])
def test_solar_has_no_product_pin_without_fake_product_id(kind):
    action=SolarAction('autonomy',kind,EnergyAttitudePolicy().identity,**({'until_seconds':200} if kind=='SOLAR_HOLD' else {}))
    assert not hasattr(action,'product_id')
    assert pending_pins_product(SimpleNamespace(action=action),'request') is False

def test_capture_pin_and_unknown_action_rejected():
    a=LongMissionAction('capture','CAPTURE','target',duration_seconds=1,product_id='request')
    assert pending_pins_product(SimpleNamespace(action=a),'request') is True
    assert pending_pins_product(SimpleNamespace(action=a),'other') is False
    contact=LongMissionAction('contact','CONTACT','station',duration_seconds=20)
    assert pending_pins_product(SimpleNamespace(action=contact),'request') is True
    with pytest.raises(TypeError):pending_pins_product(SimpleNamespace(action=SimpleNamespace(product_id='request')),'request')
    assert pending_pins_product(None,'request') is False
