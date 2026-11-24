from dataclasses import replace
import json
import pytest
from examples.m3_long_mission_demo import make_inputs
from ops_sim.v5.long_environment import NOMINAL,CONTINUOUS
from ops_sim.v5.long_mission_document import mission_inputs_to_json,mission_inputs_from_json,mission_input_digest,canonical_json

@pytest.mark.parametrize('mode,duration',[(NOMINAL,600),(NOMINAL,86400),(CONTINUOUS,600)])
def test_fixed_v5_roundtrip(mode,duration):
    i=make_inputs(mode=mode,duration=duration);text=mission_inputs_to_json(i)
    restored=mission_inputs_from_json(text,expected_digest=mission_input_digest(i))
    assert mission_inputs_to_json(restored)==text and restored.environment.mode==mode
    assert len(restored.products)==(2 if duration==86400 else 1)

@pytest.mark.parametrize('edit',['digest','version','unknown-type','extra'])
def test_unsafe_or_edited_input_rejected(edit):
    p=json.loads(mission_inputs_to_json(make_inputs(duration=600)))
    if edit=='digest':p['digest']='0'*64
    if edit=='version':p['version']=4
    if edit=='unknown-type':p['inputs']['actions']['input_tuple'][0]['input_type']='subprocess.Popen'
    if edit=='extra':p['inputs']['callback']='dangerous'
    with pytest.raises((ValueError,TypeError)):mission_inputs_from_json(canonical_json(p))

def test_memory_action_and_quota_admission():
    i=make_inputs(duration=600)
    with pytest.raises(ValueError):replace(i,limits=replace(i.limits,max_document_bytes=1))
    with pytest.raises(ValueError):replace(i,nominal_policy=replace(i.nominal_policy,max_steps=1))
    with pytest.raises(ValueError):replace(i,limits=replace(i.limits,max_actions=1))

def test_same_day_world_program_and_declared_negative_entry():
    a=make_inputs('compact');b=make_inputs('outboard')
    da=json.loads(mission_inputs_to_json(a))['inputs'];db=json.loads(mission_inputs_to_json(b))['inputs']
    da.pop('assembly');db.pop('assembly')
    assert da==db and a.assembly!=b.assembly
    assert any(x.action_id=='blocked-point' and x.point_id=='blocked-target' for x in a.actions)
