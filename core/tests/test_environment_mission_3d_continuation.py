from dataclasses import replace,asdict
from hashlib import sha256
import json
import pytest
from examples.m3_spatial_constructor_mission_demo import make_inputs
from ops_sim.v5.environment_mission_3d import start_environment_mission,advance_environment_mission
from ops_sim.v5.environment_mission_3d_continuation import save_continuation,restore_continuation,scientific_bytes,_admit
from ops_sim.v5.environment_mission_3d_document import mission_input_digest

@pytest.fixture(scope='module')
def prefix():
    s=start_environment_mission(make_inputs());s=advance_environment_mission(s)
    return advance_environment_mission(s)

def test_full_private_replay_and_exact_added_work(prefix,tmp_path):
    p=tmp_path/'packet.json';h=save_continuation(p,prefix);prior=asdict(prefix.runtime_work)
    s,work=restore_continuation(p,expected_packet_sha256=h,expected_input_digest=prefix.input_digest)
    assert scientific_bytes(s)==scientific_bytes(prefix) and s.attitude==prefix.attitude
    assert work['prior']==prior and work['original_anchor_seconds']==128
    assert work['reconstruction_delta']['upstream_entries']==work['reconstruction_delta']['reconstruction_count']==1
    assert work['reconstruction_delta']['spatial_reserved_units']>0 and work['reconstruction_delta']['geometry_operations']>0
    assert all(work['after'][n]==prior[n]+work['reconstruction_delta'][n] for n in prior)
    assert len(s.acquisitions)==1 and not s.context.ground_data_delivery_state.completed_deliveries

@pytest.mark.parametrize('mutation',['quaternion','mount','actuator','method','quota'])
def test_changed_identity_before_launch(prefix,tmp_path,monkeypatch,mutation):
    import ops_sim.v5.environment_mission_3d_continuation as owner
    p=tmp_path/'packet.json';h=save_continuation(p,prefix)
    d=prefix.inputs
    changed={'quaternion':lambda:replace(d,initial_quaternion=(0.,1.,0.,0.)),
       'mount':lambda:replace(d,assembly=make_inputs('outboard').assembly),
       'actuator':lambda:replace(d,actuator=replace(d.actuator,electronics_power_w=3.)),
       'quota':lambda:replace(d,limits=replace(d.limits,max_document_bytes=1024))}
    monkeypatch.setattr(owner,'start_environment_mission',lambda *a,**k:pytest.fail('no owner for invalid admission'))
    if mutation=='method':
        data=json.loads(p.read_bytes());data['format']='foreign';p2=tmp_path/'edited.json';p2.write_bytes(json.dumps(data).encode())
        with pytest.raises(ValueError):owner.restore_continuation(p2,expected_packet_sha256=sha256(p2.read_bytes()).hexdigest(),expected_input_digest=prefix.input_digest)
    else:
        with pytest.raises(ValueError,match='authority'):owner.restore_continuation(p,expected_packet_sha256=h,expected_input_digest=mission_input_digest(changed[mutation]()))


def test_reset_work_and_payload_strict(prefix,tmp_path,monkeypatch):
    import ops_sim.v5.environment_mission_3d_continuation as owner
    p=tmp_path/'p.json';save_continuation(p,prefix);d=json.loads(p.read_bytes())
    monkeypatch.setattr(owner,'start_environment_mission',lambda *a,**k:pytest.fail('not admitted'))
    for key,value in [('cursor',True),('runtime_work',{n:0 for n in d['runtime_work']}),('pickle','unsafe')]:
        v={**d,key:value};f=tmp_path/(key+'.json');f.write_bytes(json.dumps(v).encode())
        with pytest.raises((TypeError,ValueError)):_admit(f,sha256(f.read_bytes()).hexdigest(),prefix.input_digest)


def test_stale_alias_packet_refused(prefix,tmp_path):
    from ops_sim.v5.checkpoint import CheckpointState
    s=replace(prefix,context=CheckpointState.from_context(prefix.context).restore(prefix.inputs.simulation_inputs))
    advance_environment_mission(s)
    with pytest.raises(ValueError,match='stale'):save_continuation(tmp_path/'stale.json',s)
