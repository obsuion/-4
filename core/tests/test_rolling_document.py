"""Strict static input admission and pre-numerical reconstruction refusal."""
from dataclasses import replace,asdict
import json
import pytest
from examples.m5_rolling_mission_demo import make_inputs
from ops_sim.v5.rolling_document import inputs_to_json,inputs_from_json,admit_reconstruction
from ops_sim.v5.rolling_cache import CumulativeWork


@pytest.mark.parametrize('scenario',['A','B','C'])
@pytest.mark.parametrize('variant',['compact','outboard'])
def test_static_round_trip(scenario,variant):
    root=make_inputs(variant,scenario)
    text=inputs_to_json(root)
    assert inputs_to_json(inputs_from_json(text))==text


@pytest.mark.parametrize('change',['version','extra','digest','type','callback'])
def test_strict_input_rejects(change):
    data=json.loads(inputs_to_json(make_inputs()))
    if change=='version': data['version']=True
    if change=='extra': data['extra']=0
    if change=='digest': data['digest']='0'*64
    if change=='type': data['inputs']['rolling_type']='RollingState'
    if change=='callback': data['inputs']['fields']['callback']={'path':'x.py'}
    with pytest.raises((TypeError,ValueError)): inputs_from_json(json.dumps(data))


def test_decoder_calls_no_provider_or_physics(monkeypatch):
    from ops_sim.v5 import rolling_execution, rolling_physics, long_nominal_provider
    text=inputs_to_json(make_inputs())
    def forbidden(*a,**k): raise AssertionError('numerical launch during static decoding')
    monkeypatch.setattr(rolling_execution,'start_rolling',forbidden)
    monkeypatch.setattr(rolling_physics,'start_physical',forbidden)
    monkeypatch.setattr(long_nominal_provider.LongNominalProvider,'__init__',forbidden)
    inputs_from_json(text)


def test_reconstruction_quota_rejects_before_start():
    root=make_inputs();small=replace(root,quotas=replace(root.quotas,max_forecast_invocations=1))
    with pytest.raises(ValueError,match='RECONSTRUCTION_ADMISSION'):
        admit_reconstruction(small,3,asdict(CumulativeWork()))
    work,bound=admit_reconstruction(root,3,asdict(CumulativeWork()))
    assert bound['forecast_invocations']==45 and work.forecast_invocations==0


def test_exact_publication_reuse_keeps_encoding_work_and_rejects_new_content():
    from ops_sim.v5.rolling_cache import paid_publication
    from ops_sim.v5.rolling_contract import RollingQuotas
    q=RollingQuotas();w=CumulativeWork()
    raw=paid_publication({'causal':'same'},w,q,1024);first=w.output_bytes
    w.publication_reuse_mode=True
    assert paid_publication({'causal':'same'},w,q,1024)==raw
    assert w.output_bytes==first and w.publication_reencoded_bytes==2*first and w.publication_reuse_hits==1
    with pytest.raises(ValueError,match='NOT_EXACT'): paid_publication({'causal':'different'},w,q,1024)


def test_reconstruction_reencoding_quota_refuses_statically():
    root=make_inputs();w=CumulativeWork(output_bytes=100,publication_reencoded_bytes=root.quotas.max_output_bytes-50,
        publication_digests={'0'*64:100})
    with pytest.raises(ValueError,match='RECONSTRUCTION_ADMISSION:reencoded'):
        admit_reconstruction(root,1,asdict(w))


@pytest.mark.parametrize('value',[None,True,False,123,-17,0.5,'quote" slash\\ newline\n','Казахстан 🌍',
    {'z':[None,True,False,0,-1,'\x00\b\t'], 'a':{}},[],{},'\u2028',(1,('nested',False))])
def test_exact_prospective_utf8_size(value):
    from ops_sim.v5.rolling_cache import canonical_size
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    assert canonical_size(value,len(raw))==len(raw)
    with pytest.raises(ValueError): canonical_size(value,len(raw)-1)
