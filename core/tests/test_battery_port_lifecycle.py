"""B58 strict input/native/actual/forecast coupling and unit-aware quiet checks."""
from dataclasses import replace,asdict
from hashlib import sha256
from fractions import Fraction as Q
import json
import pytest
from examples.m8_battery_port import make_inputs
from ops_sim.v5.lifecycle_document import dumps_root,loads_root,canonical,FORMAT58
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection,progress_projection,_estimate
from ops_sim.v5.lifecycle_checkpoint import make_bindings,checkpoint_bytes,restore_checkpoint
from ops_sim.v5.lifecycle_physics import execute_lifecycle_action,resume_pending_lifecycle_action
from ops_sim.v5.lifecycle_quiet import BatteryQuietIntegrationPolicy,_scale
from ops_sim.v5.battery_port import BatteryPortPolicy
from ops_sim.v5.solar_lifecycle import select_solar_action
from ops_sim.v5.solar_attitude import SolarAction

def test_v6_input_roundtrip_and_none_preserves_old_input_wire():
    r=make_inputs();raw=dumps_root(r);d=json.loads(raw)
    assert d['format']==FORMAT58 and d['version']==6
    assert dumps_root(loads_root(raw))==raw
    old=replace(r,battery_port_policy=None,policy=replace(r.policy,quiet_solver=None))
    assert 'battery_port_policy'not in json.loads(dumps_root(old))['inputs'] and old.identity!=r.identity

@pytest.mark.parametrize('field,value',[('resistance_reference_ohm',True),('bms_sensor','unknown'),('extra',1)])
def test_strict_input_policy_rejects_downgrade(field,value):
    d=json.loads(dumps_root(make_inputs()));d['inputs']['battery_port_policy'][field]=value
    d['digest']=sha256(canonical({n:d[n]for n in ('format','version','inputs')}).encode()).hexdigest()
    with pytest.raises((ValueError,TypeError)):loads_root(canonical(d).encode())

def test_actual_paid_port_state_and_received_forecast_are_separate():
    s=start_lifecycle(make_inputs());initial=s.knowledge.battery_port_state
    s,event,_=step_lifecycle(s)
    assert s.physical.battery_port_state.selected_steps>0 and s.physical.battery_port_state.resistance_damage>0
    assert s.knowledge.battery_port_state is initial and s.knowledge.observed_at_seconds==128
    actual=asdict(s.physical.battery_port_state);_estimate(s)
    assert asdict(s.physical.battery_port_state)==actual
    assert s.forecast_port_work is not s.physical.battery_port_work
    assert progress_projection(s)['battery_port']['sampled_report']['selected_steps']>0
    assert event['battery_port']['status']=='AVAILABLE_SAMPLED_MODEL'

def test_native_direct_restore_pending_paid_slew_and_future_equality():
    r=make_inputs();s=start_lifecycle(r);p,a=select_solar_action(s.physical,188,'unit-pending')
    p,o=execute_lifecycle_action(p,a,stop_at_seconds=130)
    # Physical-only direct partial action is unit evidence; report/controller
    # checkpoints must come from their chronological coordinator, tested below.
    assert p.pending is not None and p.battery_port_state.clock_seconds==130
    assert p.battery_port_state.selected_steps>0 and p.battery_port_state.chemical_throughput_wh>0
    p,done=resume_pending_lifecycle_action(p)
    assert done.status=='completed' and p.battery_port_state.clock_seconds==p.context.simulation_time_seconds
    s=start_lifecycle(r);s,_,_=step_lifecycle(s)
    bindings=make_bindings(r,s.clock);raw=checkpoint_bytes(s,bindings)
    assert json.loads(raw)['format']=='B59_TYPED_BATTERY_CHECKPOINT_V7'
    restored,proof=restore_checkpoint(raw,r,sha256(raw).hexdigest(),bindings)
    assert scientific_projection(restored)==scientific_projection(s)
    assert restored.physical.battery_port_work is not s.physical.battery_port_work
    a,_,_=step_lifecycle(s);b,_,_=step_lifecycle(restored)
    assert scientific_projection(a)==scientific_projection(b)

def test_port_unit_scales_never_fall_through_energy():
    p=BatteryQuietIntegrationPolicy()
    assert _scale('port_voltage_v',p)==p.absolute_voltage_v
    assert _scale('port_resistance_ohm',p)==p.absolute_resistance_ohm
    assert _scale('port_resistance_damage',p)==p.absolute_resistance_damage
    with pytest.raises(ValueError,match='unknown port metric'):_scale('port_undocumented_unit',p)

def test_predeclared_small_physical_quiet_detailed_refinement_screen():
    outputs=[]
    for integration in ('ADAPTIVE','DETAILED','FINER'):
        s=start_lifecycle(make_inputs(integration=integration));p,a=select_solar_action(s.physical,188,'screen-point')
        p,o=execute_lifecycle_action(p,a);assert o.status=='completed'
        end=p.context.simulation_time_seconds+60
        p,o=execute_lifecycle_action(p,SolarAction('screen-hold','SOLAR_HOLD',p.inputs.energy_attitude_policy.identity,until_seconds=end))
        assert o.status=='completed';outputs.append(p)
    ref=outputs[-1]
    # Independent first-order refinement screens, declared before any actual
    # day/month: 0.005 Wh,0.05 K,0.05 V,0.001 Ohm; no ranking requirement.
    for p in outputs[:2]:
        assert abs(p.context.spacecraft_state.battery.energy_wh-ref.context.spacecraft_state.battery.energy_wh)<=.005
        assert max(abs(a.temperature_k-b.temperature_k)for a,b in zip(p.context.spacecraft_state.thermal.node_states,ref.context.spacecraft_state.thermal.node_states))<=.05
        assert abs(p.battery_port_state.last_voltage_v-ref.battery_port_state.last_voltage_v)<=.05
        assert abs(p.battery_port_state.last_resistance_ohm-ref.battery_port_state.last_resistance_ohm)<=.001


def test_new_trusted_membership_is_exact_and_includes_every_new_owner():
    from pathlib import Path
    from m8_finite_campaign_cli import trusted_worker_binding,EXPECTED_WORKER_MEMBERS
    # B59 producer remains exact and refuses successor membership; no migration.
    source=Path(__file__).resolve().parents[1]
    current={p.relative_to(source).as_posix()for p in source.rglob('*')if p.is_file()}
    if current==set(EXPECTED_WORKER_MEMBERS)|{'m8_finite_campaign_cli.py'}:
        value=trusted_worker_binding()
        assert set(value['source_sha256'])==set(EXPECTED_WORKER_MEMBERS)
    else:
        with pytest.raises(ValueError,match='membership drift'):trusted_worker_binding()
    assert 'ops_sim/v5/battery_port_construction.py'in EXPECTED_WORKER_MEMBERS


def test_strict_progress_port_lineage_and_unknown_data():
    from copy import deepcopy
    from ops_sim.v5.battery_port_reporting import validate_port_progress
    s=start_lifecycle(make_inputs());v=progress_projection(s)['battery_port']
    validate_port_progress(v,s.root,s.clock)
    for name in ('policy','clock','scope','extra'):
        bad=deepcopy(v)
        if name=='policy':bad['actual']['policy_identity']='f'*64
        elif name=='clock':bad['actual']['pack_measurements']['clock_seconds']['numerator']+=1
        elif name=='scope':bad['knowledge_scope']='CURRENT_ACTUAL_IS_GROUND'
        else:bad['extra']=None
        with pytest.raises((TypeError,ValueError)):validate_port_progress(bad,s.root,s.clock)


def test_application_admits_the_bound_unit_aware_quiet_and_selector():
    from ops_sim.v5.lifecycle_application import _quiet_accounting,requested_lifecycle_root
    from ops_sim.v5.battery_port import METHOD as PORT_METHOD
    s=start_lifecycle(make_inputs(),execution_mode='B54_FROZEN_INPUT_ADMISSION_V1')
    value=progress_projection(s)['quiet']
    _quiet_accounting(value,clock=128,elapsed=0,expected_method=s.root.policy.quiet_solver.method)
    with pytest.raises(ValueError,match='quiet progress method'):_quiet_accounting(value,clock=128,elapsed=0)
    selected=requested_lifecycle_root(s.root.base,600,{'quiet_solver':{}},{},s.root.sun_mode,
        service_policy='B55_CONSTRUCTION_RECOVERY_POLICY_V1',energy_attitude_policy='B56_ONBOARD_PREVENTIVE_SOLAR_ATTITUDE_V1',battery_port_policy=PORT_METHOD)
    assert type(selected.policy.quiet_solver)is BatteryQuietIntegrationPolicy and selected.battery_port_policy==BatteryPortPolicy()


def test_new_store_admission_json_roundtrip_and_empty_dispatch(tmp_path):
    from ops_sim.v5.lifecycle_application import LifecycleStore
    from ops_sim.v5.lifecycle_runner_policy import LifecycleRunnerStorePolicy
    from ops_sim.v5.lifecycle_compact import PublicationProfile
    from ops_sim.v5.lifecycle_contract import static_admission
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    root=replace(make_inputs(),output_policy=LifecycleStreamPolicy())
    store=LifecycleStore(tmp_path/'port',root,create=True,runner_policy=LifecycleRunnerStorePolicy(),publication_profile=PublicationProfile())
    assert store.meta['admission']==static_admission(root) and not store.jobs()
    assert store.snapshot()['battery_port_policy_identity']==root.battery_port_policy.identity
    store.close_publications();restored=LifecycleStore(tmp_path/'port')
    assert restored.root_input.identity==root.identity and not restored.jobs()
    restored.close_publications()
