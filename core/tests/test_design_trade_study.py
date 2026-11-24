"""Evidence reuse fails closed on incomplete, edited or differently bound runs."""
import json
import platform

import pytest

from examples.v5_design_trade_study import digest, encode, read_matching
from examples.v5_design_trade_report import qualify_pair


def saved(tmp_path):
    case={'case_id':'tiny','spec':{'horizon':1600},'input_digest':'input'}
    source={'sha256':'source'}
    value={'status':'success','case':case,'source':source,
        'python':platform.python_version(),'platform':platform.platform(),
        'summary':{'input_digest':'input','status':'completed-horizon',
            'checkpoint':{'simulation_time_seconds':1600}}}
    value['result_sha256']=digest(value)
    (tmp_path/'runs').mkdir();path=tmp_path/'runs'/'tiny.json'
    path.write_text(encode(value),encoding='utf-8')
    return path,case,source,value


def test_matching_completed_evidence_reuses_exact_result(tmp_path):
    _,case,source,value=saved(tmp_path)
    assert read_matching(tmp_path,case,source)==value


@pytest.mark.parametrize('change',['digest','horizon','status','source','runtime'])
def test_edited_or_incomplete_evidence_rejects_even_with_unchanged_case_label(tmp_path,change):
    path,case,source,value=saved(tmp_path)
    if change=='digest': value['extra']='edited'
    elif change=='horizon': value['summary']['checkpoint']['simulation_time_seconds']=1500
    elif change=='status': value['summary']['status']='incomplete'
    elif change=='source': value['source']={'sha256':'another'}
    elif change=='runtime': value['python']='unknown'
    if change!='digest':
        del value['result_sha256'];value['result_sha256']=digest(value)
    path.write_text(encode(value),encoding='utf-8')
    with pytest.raises(ValueError,match='differs'):
        read_matching(tmp_path,case,source)


def test_refinement_gate_rejects_changed_decisions_despite_identical_primary_score():
    summary={'physical_samples':[{'time':[0,1],'energy_wh':20.,'temperatures_k':{'bus':293.}}],
        'phase_seconds':{'hold':1600},'requests':[],'events':[],'rejections':[],'weighted_credit':[1,1]}
    low={'summary':summary,'case':{'case_id':'test__L1'},'design':{'capacity_wh':172.}}
    high=json.loads(json.dumps(low))
    assert qualify_pair(low,high)['passed']
    high['summary']['rejections']=[['r1','different decision']]
    assert not qualify_pair(low,high)['passed']
