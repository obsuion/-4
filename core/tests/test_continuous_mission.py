from dataclasses import replace,asdict
from hashlib import sha256
from fractions import Fraction as Q
import json
import pytest
from examples.m3_continuous_mission_demo import make_continuous_inputs
from ops_sim.v5.environment_mission import start_environment_mission,advance_environment_mission,RuntimeWork,MissionAction
from ops_sim.v5.environment_mission_document import mission_inputs_to_json,mission_inputs_from_json,mission_input_digest
from ops_sim.v5.environment_mission_continuation import save_continuation,restore_continuation,scientific_bytes,_admit
from ops_sim.v5.checkpoint import CheckpointState


@pytest.fixture(scope='module')
def initial():return start_environment_mission(make_continuous_inputs())


def clone(s,d=None):
    d=s.inputs if d is None else d
    return replace(s,inputs=d,context=d.initial_checkpoint.restore(d.simulation_inputs),attitude=replace(s.attitude),cursor=0,
        outcomes=(),acquisitions=(),runtime_work=RuntimeWork(upstream_entries=1),input_digest=mission_input_digest(d))


def test_whole_capture_contact_real_credit_and_rays(initial):
    s=clone(initial)
    while s.cursor<len(s.inputs.actions):s=advance_environment_mission(s)
    assert s.assessment().credited_products==1 and len(s.context.ground_data_delivery_state.completed_deliveries)==1
    for o in (s.outcomes[1],s.outcomes[3]):
        assert o.status=='completed' and o.continuous_geometry.status=='VISIBLE'
        assert o.continuous_geometry.cells and all(c.status=='VISIBLE' for c in o.continuous_geometry.cells)
    capture=s.outcomes[1].continuous_geometry
    assert capture.start_ray.at_seconds==139 and capture.end_ray.at_seconds==143
    assert capture.end_ray.origin_position_bounds_m!=capture.start_ray.origin_position_bounds_m
    assert capture.end_ray.held_inertial_direction==capture.start_ray.held_inertial_direction
    assert capture.end_ray.forward_sphere_intersection=='VISIBLE'
    assert s.runtime_work.geometry_queries==2 and s.runtime_work.geometry_operations>0


def test_strict_mode_policy_wire_no_silent_upgrade():
    d=make_continuous_inputs();text=mission_inputs_to_json(d)
    assert mission_inputs_to_json(mission_inputs_from_json(text))==text
    for change in ({'geometry_mode':'CLAIMED_VISIBLE'},{'geometry_policy':None}):
        with pytest.raises((TypeError,ValueError)):replace(d,**change)
    bad=json.loads(text);bad['inputs']['geometry_policy']['fields']['method']['typed']['value']='fake'
    with pytest.raises(ValueError):mission_inputs_from_json(json.dumps(bad))
    bad=json.loads(text);bad['version']=1
    with pytest.raises(ValueError,match='format'):mission_inputs_from_json(json.dumps(bad))


def test_paid_reconstruction_full_geometry_equality_and_no_reset(initial,tmp_path):
    s=clone(initial)
    for _ in range(2):s=advance_environment_mission(s)
    packet=tmp_path/'packet.json';h=save_continuation(packet,s);before=asdict(s.runtime_work)
    restored,work=restore_continuation(packet,expected_packet_sha256=h,expected_input_digest=s.input_digest)
    assert scientific_bytes(restored)==scientific_bytes(s)
    assert work['reconstruction_delta']['geometry_queries']==1
    assert work['reconstruction_delta']['geometry_operations']==before['geometry_operations']
    assert work['reconstruction_delta']['geometry_control_units']==before['geometry_control_units']
    data=json.loads(packet.read_bytes());data['runtime_work']['geometry_operations']=0
    p=tmp_path/'forged.json';p.write_bytes(json.dumps(data).encode())
    # Fail lower-bound after real privately charged reconstruction, not forged proof acceptance.
    with pytest.raises(ValueError,match='reset'):
        restore_continuation(p,expected_packet_sha256=sha256(p.read_bytes()).hexdigest(),expected_input_digest=s.input_digest)


def test_geometry_refusal_before_physical_and_custody(initial):
    d=replace(initial.inputs,initial_angle_y_rad=0.,actions=(MissionAction('away','CAPTURE','target',4),))
    s=clone(initial,d);before=CheckpointState.from_context(s.context).to_dict()
    out=advance_environment_mission(s)
    assert out.outcomes[-1].reason=='CONTINUOUS_CAPTURE_BLOCKED'
    assert out.outcomes[-1].continuous_geometry.status=='BLOCKED'
    assert out.runtime_work.physical_completed_calls==0 and out.runtime_work.geometry_operations>0
    assert CheckpointState.from_context(out.context).to_dict()==before

def test_continuous_denied_contact_retains_real_returned_count(initial):
    d=replace(initial.inputs,transmitter=replace(initial.inputs.transmitter,electrical_power_w=replace(initial.inputs.transmitter.electrical_power_w,value=1e6)))
    s=clone(initial,d)
    for _ in range(3):s=advance_environment_mission(s)
    actual=s.runtime_work.physical_completed_calls;before=CheckpointState.from_context(s.context).to_dict()
    out=advance_environment_mission(s)
    assert out.outcomes[-1].reason=='CONTACT_EXISTING_PROTECTION_REFUSED'
    assert out.outcomes[-1].continuous_geometry.status=='VISIBLE'
    assert out.runtime_work.physical_completed_calls-actual==9
    assert CheckpointState.from_context(out.context).to_dict()==before


@pytest.mark.parametrize('failure',['physical','commit'])
def test_continuous_capture_late_failure_is_atomic(initial,monkeypatch,failure):
    import ops_sim.v5.environment_mission as m
    import ops_sim.v5.engine as engine
    s=advance_environment_mission(clone(initial));before=CheckpointState.from_context(s.context).to_dict();spent=s.runtime_work.geometry_operations
    if failure=='physical':
        real=m._physical_substep;calls=[]
        def fail(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('injected continuous late physical failure')
            return real(*args,**kwargs)
        monkeypatch.setattr(m,'_physical_substep',fail)
    else:
        def fail(original,candidate):
            original.simulation_time_seconds=999
            raise RuntimeError('injected continuous commit failure')
        monkeypatch.setattr(engine.SimulationEngine,'_commit',fail)
    with pytest.raises(RuntimeError,match='injected'):advance_environment_mission(s)
    assert CheckpointState.from_context(s.context).to_dict()==before and s.cursor==1 and len(s.outcomes)==1
    assert s.runtime_work.geometry_operations>spent and not s.context.spacecraft_state.data_storage.stored_records


def test_changed_source_ancestry_never_new_authority(initial):
    # Explicit identity mismatch, not a reconstructed proof object.
    from copy import copy
    s=clone(initial);s.source_result=copy(s.source_result)
    with pytest.raises(ValueError,match='acquired geometry authority'):
        s=advance_environment_mission(s);advance_environment_mission(s)