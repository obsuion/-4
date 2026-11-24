from dataclasses import replace,asdict
from hashlib import sha256
from fractions import Fraction as Q
import json
import pytest
from examples.m8_environment_ageing import make_inputs,add_ageing
from examples.m8_battery_port import make_inputs as old_inputs
from ops_sim.v5.lifecycle_document import dumps_root,loads_root,canonical
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection,progress_projection,_estimate
from ops_sim.v5.lifecycle_checkpoint import make_bindings,checkpoint_bytes,restore_checkpoint
from ops_sim.v5.environment_lifecycle import validate_progress
from ops_sim.v5.environment_ageing import retention

def test_new_input_v7_roundtrip_legacy_wire_untouched():
    r=make_inputs(duration=600);raw=dumps_root(r);d=json.loads(raw)
    assert d['format']=='B61_EXPLICIT_ENVIRONMENT_AGEING_INPUT_V7'and d['version']==7
    assert dumps_root(loads_root(raw))==raw
    old=old_inputs(duration=600);assert 'environment_ageing_policy'not in json.loads(dumps_root(old))['inputs']
    assert json.loads(dumps_root(old))['version']==6 and old.identity!=r.identity

@pytest.mark.parametrize('field,value',[('pv_floor_fraction',True),('initial_calendar_seconds',0.),('method','NASA'),('foreign',1)])
def test_input_malformed_fails_before_dispatch(field,value):
    d=json.loads(dumps_root(make_inputs(duration=600)));d['inputs']['environment_ageing_policy'][field]=value
    d['digest']=sha256(canonical({n:d[n]for n in ('format','version','inputs')}).encode()).hexdigest()
    with pytest.raises((ValueError,TypeError)):loads_root(canonical(d).encode())

def test_actual_cut_received_delay_and_separate_forecast():
    s=start_lifecycle(make_inputs(duration=600));initial=s.knowledge.environment_ageing_state
    s,event,_=step_lifecycle(s)
    assert s.clock>128 and s.physical.environment_ageing_state.calendar_seconds>0
    assert s.physical.environment_ageing_state.selected_cuts>0 and s.physical.environment_ageing_work.proposed>=s.physical.environment_ageing_state.selected_cuts
    assert s.knowledge.environment_ageing_state is initial and s.knowledge.observed_at_seconds==128
    actual=s.physical.environment_ageing_state;_estimate(s)
    assert s.physical.environment_ageing_state==actual and s.forecast_environment_work is not s.physical.environment_ageing_work
    v=progress_projection(s)['environment_ageing'];validate_progress(v,s.root,s.clock)
    assert event['environment_ageing']['clock_seconds']==str(s.clock)

def test_native_v8_full_science_future_equality():
    r=make_inputs(duration=600);s=start_lifecycle(r);s,_,_=step_lifecycle(s)
    b=make_bindings(r,s.clock);raw=checkpoint_bytes(s,b)
    assert json.loads(raw)['format']=='B61_EXPOSURE_THERMAL_CHECKPOINT_V8'
    t,proof=restore_checkpoint(raw,r,sha256(raw).hexdigest(),b)
    assert scientific_projection(t)==scientific_projection(s)
    assert proof['environment_derived_validation']['prefix_evaluations']==0
    a,_,_=step_lifecycle(s);b,_,_=step_lifecycle(t)
    assert scientific_projection(a)==scientific_projection(b)


@pytest.mark.parametrize('service',[True,False])
def test_contact_inner_cuts_own_calendar_and_pv_trace(service):
    from test_construction_service import leaf
    from ops_sim.v5.environment_ageing import EnvironmentAgeingPolicy,initial_state,EnvironmentAgeingWork
    from ops_sim.v5.lifecycle_service import PowerServicePolicy,initial_service_state,PowerServiceWork
    from ops_sim.v5.construction_service import ConstructionServiceWork
    from ops_sim.v5.coupled_downlink import CoupledDownlinkInputs
    from ops_sim.v5.operational_protection import StandbyInputs
    from ops_sim.v5.communications import ServiceableGroundContact
    from ops_sim.v5.ids import GroundContactId,GroundStationId
    from ops_sim.v5.contact_execution import ContactPlan,ConsumedContacts
    from ops_sim.v5.integration_time import IntegrationPolicy
    state,forcing,eps,duration,paid,kw=leaf(mode='NORMAL')
    ctx=state.context;net=ctx.inputs.spacecraft_configuration.thermal.network
    p=EnvironmentAgeingPolicy(pv_calendar_rate_per_second=.1);history=initial_state(p,128,net,ctx.spacecraft_state.degradation.solar.generation_retention);work=EnvironmentAgeingWork()
    tx=CoupledDownlinkInputs(state.inputs.transmitter,forcing.loads,False,0.,forcing.routing_config,forcing.thermal_inputs,forcing.external_heat_sources,None)
    idle=StandbyInputs(forcing.loads,False,0.,forcing.routing_config,forcing.thermal_inputs,forcing.external_heat_sources,None,'Synthetic dark idle leaf; not geometric coverage.')
    contact=ServiceableGroundContact(GroundContactId('b61-unit'),GroundStationId('station'),128,129)
    kwargs=dict(consumed_contacts=ConsumedContacts(()),policy=state.inputs.protection,integration=IntegrationPolicy(2),compilation=state.construction.compilation,work=state.construction.work,limits=state.construction.inputs.limits)
    if service:
        from ops_sim.v5.lifecycle_service_contact import execute_service_contact_plan
        result=execute_service_contact_plan(ctx,ContactPlan(contact,(),tx,idle),**kwargs,service_policy=PowerServicePolicy(),service_state=initial_service_state(Q(128)),service_work=PowerServiceWork(),allocation_work=ConstructionServiceWork(),environment_ageing_policy=p,environment_ageing_state=history,environment_ageing_work=work)
        after=result.environment_ageing_state
    else:
        from ops_sim.v5.environment_contact import execute_environment_contact_plan
        result,after=execute_environment_contact_plan(ctx,ContactPlan(contact,(),tx,idle),**kwargs,environment_policy=p,environment_state=history,environment_work=work)
    assert ctx.simulation_time_seconds==129 and after.clock_seconds==129 and after.calendar_seconds==1
    assert after.selected_cuts==4 and work.proposed==work.returned==4
    assert ctx.spacecraft_state.degradation.solar.generation_retention==retention(p,after)<retention(p,history)
    assert result.outcome.transmitted_bits==0

def test_new_physical_quiet_detailed_finer_screen():
    from ops_sim.v5.lifecycle_physics import execute_lifecycle_action
    from ops_sim.v5.long_mission import LongMissionAction
    outputs=[]
    for mode in ('ADAPTIVE','DETAILED','FINER'):
        s=start_lifecycle(make_inputs(duration=600,integration=mode));p,o=execute_lifecycle_action(s.physical,LongMissionAction('b61-screen','HOLD_UNTIL',until_seconds=188))
        assert o.status=='completed';outputs.append(p)
    ref=outputs[-1]
    # Frozen first-order screens: Wh,K,V,Ohm,illumination s,unitless property.
    for p in outputs[:-1]:
        assert abs(p.context.spacecraft_state.battery.energy_wh-ref.context.spacecraft_state.battery.energy_wh)<=.005
        assert max(abs(a.temperature_k-b.temperature_k)for a,b in zip(p.context.spacecraft_state.thermal.node_states,ref.context.spacecraft_state.thermal.node_states))<=.05
        assert abs(p.battery_port_state.last_voltage_v-ref.battery_port_state.last_voltage_v)<=.05
        assert abs(p.battery_port_state.last_resistance_ohm-ref.battery_port_state.last_resistance_ohm)<=.001
        assert abs(p.environment_ageing_state.pv_exposure_seconds-ref.environment_ageing_state.pv_exposure_seconds)<=.1
        assert abs(retention(p.inputs.environment_ageing_policy,p.environment_ageing_state)-retention(ref.inputs.environment_ageing_policy,ref.environment_ageing_state))<=1.e-7


def test_nonservice_quiet_consumer_owns_new_dimensions():
    from ops_sim.v5.lifecycle_contract import METHOD53
    from ops_sim.v5.lifecycle_physics import execute_lifecycle_action
    from ops_sim.v5.long_mission import LongMissionAction
    r=replace(make_inputs(duration=600),service_policy=None,battery_port_policy=None,energy_attitude_policy=None,method=METHOD53)
    s=start_lifecycle(r);p,o=execute_lifecycle_action(s.physical,LongMissionAction('nonservice','HOLD_UNTIL',until_seconds=188))
    assert o.status=='completed' and p.environment_ageing_state.clock_seconds==188
    assert p.environment_ageing_state.calendar_seconds==60 and p.environment_ageing_state.selected_cuts>0
    assert all(c.part.solar_degradation_result is not None for c in o.cuts)

def test_domain_work_terminal_keeps_atomic_prefix_and_paid_attempts():
    from ops_sim.v5.checkpoint import CheckpointState
    r=make_inputs(duration=600);r=replace(r,environment_ageing_policy=replace(r.environment_ageing_policy,maximum_proposals=1))
    s=start_lifecycle(r);before=CheckpointState.from_context(s.physical.context).to_dict();history=s.physical.environment_ageing_state
    s,event,_=step_lifecycle(s)
    assert s.status=='INCOMPLETE_TYPED_MODEL_BOUNDARY'and s.clock==128
    assert CheckpointState.from_context(s.physical.context).to_dict()==before and s.physical.environment_ageing_state==history
    assert s.physical.environment_ageing_work.proposed==1 and s.physical.environment_ageing_work.returned==1
    assert event['reason'].startswith('B61_ENVIRONMENT_DOMAIN_REFUSED:')and s.terminal['kind']=='MODEL'


def test_off_cut_lives_and_ages_without_functional_grant():
    from ops_sim.v5.lifecycle_physics import execute_lifecycle_action
    from ops_sim.v5.long_mission import LongMissionAction
    s=start_lifecycle(make_inputs(duration=600,energy=0.))
    p,o=execute_lifecycle_action(s.physical,LongMissionAction('off-lived','HOLD_UNTIL',until_seconds=188))
    assert o.status=='completed'and p.environment_ageing_state.calendar_seconds==60
    assert p.environment_ageing_state.selected_cuts==p.service_work.selected_steps
    assert p.service_state.mode in ('SAFE','POWER_OFF')
    assert not p.service_state.tx_fully_served
