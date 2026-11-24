from dataclasses import replace,asdict
from hashlib import sha256
import json
import pytest
from examples.m3_constructor_mission_demo import make_inputs
from ops_sim.v5.environment_mission import start_environment_mission,advance_environment_mission
from ops_sim.v5.environment_mission_continuation import save_continuation,restore_continuation,scientific_bytes,_admit
from ops_sim.v5.environment_mission_document import mission_input_digest


@pytest.fixture(scope='module')
def prefix():
    s=start_environment_mission(make_inputs());s=advance_environment_mission(s)
    return advance_environment_mission(s)


def test_replay_restore_full_science_and_paid_runtime_delta(prefix,tmp_path):
    packet=tmp_path/'packet.json';digest=save_continuation(packet,prefix);prior=asdict(prefix.runtime_work)
    restored,work=restore_continuation(packet,expected_packet_sha256=digest,expected_input_digest=prefix.input_digest)
    assert scientific_bytes(restored)==scientific_bytes(prefix)
    assert work['prior']==prior and work['reconstruction_delta']['upstream_entries']==1
    assert work['reconstruction_delta']['reconstruction_count']==1
    assert all(work['after'][n]==prior[n]+work['reconstruction_delta'][n] for n in prior)
    assert work['original_anchor_seconds']==128


def test_foreign_binding_reset_quota_wrong_cursor_refused_before_owner(prefix,tmp_path,monkeypatch):
    import ops_sim.v5.environment_mission_continuation as c
    packet=tmp_path/'packet.json';digest=save_continuation(packet,prefix)
    monkeypatch.setattr(c,'start_environment_mission',lambda *a,**k:pytest.fail('owner must not launch during failed admission'))
    with pytest.raises(ValueError,match='authority'):
        restore_continuation(packet,expected_packet_sha256=digest,expected_input_digest='0'*64)
    data=json.loads(packet.read_bytes())
    for field,value in [('cursor',True),('cursor',999)]:
        edited={**data,field:value};p=tmp_path/(str(value)+'.json');p.write_bytes(json.dumps(edited).encode())
        with pytest.raises((TypeError,ValueError)):_admit(p,sha256(p.read_bytes()).hexdigest(),prefix.input_digest)
    edited={**data,'runtime_work':{n:0 for n in data['runtime_work']}}
    p=tmp_path/'reset.json';p.write_bytes(json.dumps(edited).encode())
    with pytest.raises(ValueError,match='reset'):_admit(p,sha256(p.read_bytes()).hexdigest(),prefix.input_digest)
    with pytest.raises(ValueError,match='edited packet'):_admit(p,digest,prefix.input_digest)


def test_foreign_assembly_or_policy_cannot_resume_original_packet(prefix,tmp_path):
    packet=tmp_path/'packet.json';digest=save_continuation(packet,prefix)
    for inputs in (make_inputs('outboard'),replace(prefix.inputs,camera_half_fov_rad=.1)):
        with pytest.raises(ValueError,match='authority'):
            _admit(packet,digest,mission_input_digest(inputs))


def test_unsafe_payload_rejected_without_executable_deserialization(prefix,tmp_path):
    packet=tmp_path/'packet.json';digest=save_continuation(packet,prefix)
    data=json.loads(packet.read_bytes());data['pickle']='arbitrary';p=tmp_path/'unsafe.json';p.write_bytes(json.dumps(data).encode())
    with pytest.raises(ValueError):_admit(p,sha256(p.read_bytes()).hexdigest(),prefix.input_digest)
