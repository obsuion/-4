from dataclasses import replace
from hashlib import sha256
import json
import pytest
from examples.m4_construction_mission_demo import make_inputs
from ops_sim.v5.construction_document import (inputs_to_json,inputs_from_json,construction_input_digest,
    save_construction_continuation,restore_construction_continuation)
from ops_sim.v5.construction_mission import start_construction_mission,advance_construction_mission,continue_construction_mission
from ops_sim.v5.long_mission_continuation import scientific_bytes,save_continuation


def test_fixed_input_roundtrip_and_no_legacy_migration():
    inputs=make_inputs();text=inputs_to_json(inputs)
    assert inputs_to_json(inputs_from_json(text,expected_digest=construction_input_digest(inputs)))==text
    state=start_construction_mission(inputs)
    with pytest.raises(ValueError,match='B45 continuation'):save_continuation('must-not-be-created.json',state)


@pytest.mark.parametrize('edit',['digest','type','field','format'])
def test_edited_or_unsafe_input_rejects(edit):
    p=json.loads(inputs_to_json(make_inputs()))
    if edit=='digest':p['digest']='0'*64
    elif edit=='type':p['inputs']['configuration']['construction_type']='ArbitraryExecutable'
    elif edit=='field':p['inputs']['configuration']['fields']['execute']={}
    else:p['format']='B44_LONG_CONNECTED_MISSION_INPUT_V5'
    with pytest.raises(ValueError):inputs_from_json(json.dumps(p))


def test_complete_replay_bytes_and_paid_reconstruction(tmp_path):
    state=start_construction_mission(make_inputs())
    for _ in range(3):state=advance_construction_mission(state)
    path=tmp_path/'prefix.json';digest=save_construction_continuation(path,state)
    resumed,work=restore_construction_continuation(path,expected_packet_sha256=digest,expected_input_digest=state.construction.input_digest)
    assert scientific_bytes(state,reserve=False)==scientific_bytes(resumed,reserve=False)
    assert work['construction_delta']['line_calls_reserved']>0 and work['reconstruction_delta']['physical_completed_calls']>0
    uninterrupted=continue_construction_mission(state);resumed=continue_construction_mission(resumed)
    assert scientific_bytes(uninterrupted,reserve=False)==scientific_bytes(resumed,reserve=False)
    assert len(resumed.context.ground_data_delivery_state.completed_deliveries)==1
    raw=path.read_bytes();path.write_bytes(raw+b' ')
    with pytest.raises(ValueError,match='edited/reset'):restore_construction_continuation(path,expected_packet_sha256=digest,expected_input_digest=state.construction.input_digest)


@pytest.mark.parametrize('field,cap',[('ports',64),('lines',64),('thermal_bindings',32)])
def test_predecode_caps_reject_before_nested_constructors(field,cap,monkeypatch):
    import ops_sim.v5.construction_document as owner
    p=json.loads(inputs_to_json(make_inputs()))
    entries=p['inputs']['configuration']['fields'][field]['construction_tuple']
    p['inputs']['configuration']['fields'][field]['construction_tuple']=entries[:1]*(cap+1)
    monkeypatch.setattr(owner,'decode',lambda *a:pytest.fail('cannot decode over-cap inputs'))
    with pytest.raises(ValueError,match='predecode construction cap'):inputs_from_json(json.dumps(p))


def test_thermal_predecode_cap_rejects_before_config_construction(monkeypatch):
    import ops_sim.v5.construction_document as owner
    p=json.loads(inputs_to_json(make_inputs()))
    fields=p['inputs']['configuration']['fields']['thermal_network']['legacy_input']['typed']['fields']
    fields['nodes']['items']=fields['nodes']['items'][:1]*65
    monkeypatch.setattr(owner,'decode',lambda *a:pytest.fail('cannot construct over-cap network'))
    with pytest.raises(ValueError,match='predecode thermal graph cap'):inputs_from_json(json.dumps(p))
