from dataclasses import replace,asdict
import json
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.command_document import inputs_to_json,inputs_from_json,admit_command_reconstruction
from ops_sim.v5.command_estimation import CommandWork


@pytest.mark.parametrize('variant',['compact','outboard'])
@pytest.mark.parametrize('wire',['nominal','weakness','repair'])
def test_strict_round_trip(variant,wire):
    text=inputs_to_json(make_inputs(variant,wire=wire))
    assert inputs_to_json(inputs_from_json(text))==text


@pytest.mark.parametrize('mutation',['extra','method','callback','derived','version','bool','digest'])
def test_unknown_or_derived_authority_rejected(mutation):
    d=json.loads(inputs_to_json(make_inputs()))
    if mutation=='extra':d['inputs']['extra']=0
    if mutation=='method':d['inputs']['estimation']['method']='old'
    if mutation=='callback':d['inputs']['estimation']['callback']='x.py'
    if mutation=='derived':d['inputs']['estimated_pose']=[1,0,0,0]
    if mutation=='version':d['version']=2
    if mutation=='bool':d['inputs']['estimation']['maximum_unreceived_intents']=True
    if mutation=='digest':d['digest']='0'*64
    with pytest.raises((TypeError,ValueError)):inputs_from_json(json.dumps(d))


def test_no_source_or_physics_evaluation_during_decode(monkeypatch):
    text=inputs_to_json(make_inputs())
    import ops_sim.v5.rolling_execution as e
    import ops_sim.v5.long_nominal_provider as p
    def forbidden(*a,**k):raise AssertionError('numerical decode')
    monkeypatch.setattr(e,'start_rolling',forbidden);monkeypatch.setattr(p.LongNominalProvider,'__init__',forbidden)
    inputs_from_json(text)


def test_additive_static_reconstruction_estimator_bound():
    root=make_inputs();work,bound=admit_command_reconstruction(root,2,asdict(CommandWork()))
    assert bound['forecast_invocations']==30 and bound['estimator_command_propagations']==240
    assert work.estimator_invocations==0
    exhausted=CommandWork(estimator_invocations=512)
    with pytest.raises(ValueError,match='ESTIMATOR_RECONSTRUCTION_ADMISSION'):admit_command_reconstruction(root,2,asdict(exhausted))


def test_insufficient_harness_reconstruction_refuses():
    root=make_inputs();reference=replace(root.reference,quotas=replace(root.quotas,max_harness_compiles=400))
    with pytest.raises(ValueError,match='RECONSTRUCTION_HARNESS'):admit_command_reconstruction(replace(root,reference=reference),2,asdict(CommandWork()))
