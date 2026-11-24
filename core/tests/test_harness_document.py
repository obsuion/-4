from dataclasses import replace
from pathlib import Path
import json
import pytest
from examples.m4_mass_closed_mission_demo import make_inputs
from ops_sim.v5.harness_document import (inputs_to_json,inputs_from_json,harness_input_digest,save_harness_continuation,restore_harness_continuation)
from ops_sim.v5.harness_mission import start_harness_mission,advance_harness_mission,continue_harness_mission
from ops_sim.v5.long_mission_continuation import scientific_bytes
from ops_sim.v5.construction_document import save_construction_continuation


def test_exact_input_roundtrip_and_explicit_format():
    value=make_inputs();text=inputs_to_json(value)
    assert inputs_to_json(inputs_from_json(text,expected_digest=harness_input_digest(value)))==text
    state=start_harness_mission(value)
    with pytest.raises(ValueError,match='B46'):save_construction_continuation('must-not-write.json',state)


@pytest.mark.parametrize('edit',['tensor','digest','type','routes','connector_count','format'])
def test_strict_augmentation_wire_rejection_before_execution(edit):
    p=json.loads(inputs_to_json(make_inputs()))
    if edit=='tensor':p['inputs']['augmentation']['fields']['inertia_tensor']={}
    elif edit=='digest':p['digest']='0'*64
    elif edit=='type':p['inputs']['augmentation']['mass_type']='EffectiveAssemblyHardware'
    elif edit=='routes':p['inputs']['augmentation']['fields']['routes']['mass_tuple']*=2
    elif edit=='connector_count':
        entries=p['inputs']['augmentation']['fields']['routes']['mass_tuple'][0]['fields']['connector_points']['mass_tuple']
        p['inputs']['augmentation']['fields']['routes']['mass_tuple'][0]['fields']['connector_points']['mass_tuple']=entries[:1]*2049
    else:p['format']='B45_CONSTRUCTION_MISSION_INPUT_V1'
    with pytest.raises(ValueError):inputs_from_json(json.dumps(p))


def test_partial_boundary_full_causal_replay_one_receipt_and_all_paid_ledgers(tmp_path):
    state=start_harness_mission(make_inputs())
    for _ in range(4):state=advance_harness_mission(state)
    assert state.context.simulation_time_seconds==169 and state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits==1000
    path=tmp_path/'partial.json';h=save_harness_continuation(path,state)
    resumed,paid=restore_harness_continuation(path,expected_packet_sha256=h,expected_input_digest=state.harness.input_digest)
    assert scientific_bytes(state,reserve=False)==scientific_bytes(resumed,reserve=False)
    assert all(d.get('reconstruction_count')==1 for d in paid['reconstruction_delta'])
    assert paid['reconstruction_delta'][2]['compilation_calls']>0
    state=continue_harness_mission(state);resumed=continue_harness_mission(resumed)
    assert scientific_bytes(state,reserve=False)==scientific_bytes(resumed,reserve=False)
    assert len(resumed.context.ground_data_delivery_state.completed_deliveries)==1
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='edited/reset'):restore_harness_continuation(path,expected_packet_sha256=h,expected_input_digest=state.harness.input_digest)


@pytest.mark.parametrize('fault',['coupled_shape','root_type','route_type'])
def test_predecode_rejects_foreign_shapes_with_no_execution(fault,monkeypatch):
    import ops_sim.v5.harness_document as owner
    p=json.loads(inputs_to_json(make_inputs()))
    if fault=='coupled_shape':p['inputs']['coupled']={}
    elif fault=='root_type':p['inputs']['augmentation']=owner.encode(make_inputs().augmentation.routes[0].slack_point)
    else:p['inputs']['augmentation']['fields']['routes']['mass_tuple'][0]=owner.encode(make_inputs().augmentation.routes[0].slack_point)
    monkeypatch.setattr(owner,'start_harness_mission',lambda *a,**k:pytest.fail('schema rejects before mission start'))
    with pytest.raises(ValueError):inputs_from_json(json.dumps(p))


def test_exhausted_cumulative_harness_reconstruction_refuses_before_start(tmp_path,monkeypatch):
    import ops_sim.v5.harness_document as owner
    inputs=make_inputs();policy=replace(inputs.augmentation.policy,max_runtime_compiles=4,max_runtime_control_units=4*2**20)
    inputs=replace(inputs,augmentation=replace(inputs.augmentation,policy=policy))
    state=start_harness_mission(inputs);p=tmp_path/'first.json';h=save_harness_continuation(p,state)
    resumed,paid=restore_harness_continuation(p,expected_packet_sha256=h,expected_input_digest=state.harness.input_digest)
    assert resumed.harness.work.compilation_calls==3 and paid['reconstruction_delta'][2]['compilation_calls']==1
    second=tmp_path/'spent.json';h2=save_harness_continuation(second,resumed)
    assert resumed.harness.work.compilation_calls==4
    monkeypatch.setattr(owner,'start_harness_mission',lambda *a,**k:pytest.fail('quota refuses before numerical start'))
    with pytest.raises(ValueError,match='HARNESS_RECONSTRUCTION_ADMISSION'):
        restore_harness_continuation(second,expected_packet_sha256=h2,expected_input_digest=state.harness.input_digest)
