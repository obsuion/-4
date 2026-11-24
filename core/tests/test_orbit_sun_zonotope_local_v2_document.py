"""Strict input-only v2 admission precedes decode/authority construction."""
from hashlib import sha256
import json
import pytest
from test_orbit_sun_zonotope_local_v2 import request
from ops_sim.v5 import orbit_sun_zonotope_local_v2_document as d
from ops_sim.v5 import experiment_codec as codec
from ops_sim.v5 import orbit_j2 as f2


def payload():return json.loads(d.zonotope_local_request_to_json_v2(request()))


def test_roundtrip_digest_versions_and_exclusive_save(tmp_path):
    q=request();text=d.zonotope_local_request_to_json_v2(q);digest=d.zonotope_local_request_digest_v2(q)
    assert d.zonotope_local_request_from_json_v2(text,expected_digest=digest)==q
    p=tmp_path/'input.json';d.save_zonotope_local_request_v2(p,q)
    assert d.load_zonotope_local_request_v2(p,expected_digest=digest)==q
    with pytest.raises(FileExistsError):d.save_zonotope_local_request_v2(p,q)
    with pytest.raises(ValueError):d.zonotope_local_request_from_json_v2(text,expected_digest='0'*64)
    doc=payload();env=dict(domain=d.DOMAIN,canonical_version=1,content=doc['inputs'])
    assert sha256(codec.json_text(env).encode()).hexdigest()==doc['digest']
    assert doc['format']=='M2_ZONOTOPE_LOCAL_ILLUMINATION_V2_REQUEST'and doc['version']==2


@pytest.mark.parametrize('name',['J2CartesianTrajectory','J2ZonotopeSegmentResult','J2ZonotopeSegmentDiagnostic','ZonotopeLocalIlluminationResultV2','J2EnclosureResult','EngineCheckpoint','ForeignBoundary'])
def test_unsafe_records_rejected_before_any_decode(monkeypatch,name):
    p=payload();p['inputs']['items'][0][1]=dict(kind='record',type=name,fields={})
    monkeypatch.setattr(codec,'decode_content',lambda *a:pytest.fail('decode before admission'))
    with pytest.raises(ValueError):d.zonotope_local_request_from_json_v2(json.dumps(p))


@pytest.mark.parametrize('identity',['api_id','api_version','resource_policy_version','geometry_resource_policy_version'])
@pytest.mark.parametrize('value',[True,1,'m2-zonotope-local-illumination-v1'])
def test_every_root_identity_strict_before_decode(monkeypatch,identity,value):
    p=payload();items=dict(p['inputs']['items']);items[identity]=codec.canonical_content(value);p['inputs']['items']=[[k,items[k]]for k in sorted(items)]
    monkeypatch.setattr(codec,'decode_content',lambda *a:pytest.fail('decode before root identities'))
    with pytest.raises((ValueError,TypeError)):d.zonotope_local_request_from_json_v2(json.dumps(p))


@pytest.mark.parametrize('mode',['extra','missing','version_bool','duplicate','badkind','nestedextra','digest','policy_identity','unknown_enum','nested_record_field'])
def test_malformed_input_rejected(mode):
    p=payload()
    if mode=='extra':p['extra']=1
    elif mode=='missing':del p['inputs']
    elif mode=='version_bool':p['version']=True
    elif mode=='duplicate':p['inputs']['items'].append(p['inputs']['items'][-1])
    elif mode=='badkind':p['inputs']['kind']='result'
    elif mode=='digest':p['digest']='0'*64
    elif mode in('nestedextra','policy_identity'):
        data=dict(p['inputs']['items']);key='policy'if mode=='policy_identity'else'segment'
        if mode=='nestedextra':data[key]['items'].append(['z',dict(kind='none')])
        else:
            for pair in data[key]['items']:
                if pair[0]=='resource_policy_version':pair[1]=dict(kind='int',value='1')
    else:
        def change(v):
            if type(v)is dict:
                if mode=='unknown_enum'and v.get('kind')=='enum':v['member']='INVALID';return True
                if mode=='nested_record_field'and v.get('kind')=='record':v['fields']['derived_output']=dict(kind='none');return True
                return any(change(x)for x in v.values())
            if type(v)is list:return any(change(x)for x in v)
            return False
        assert change(p['inputs'])
    with pytest.raises((TypeError,ValueError)):d.zonotope_local_request_from_json_v2(json.dumps(p))


def test_no_force_or_nominal_entry_during_safe_decomposed_load(monkeypatch):
    text=d.zonotope_local_request_to_json_v2(request())
    def forbid(*a,**k):pytest.fail('numerical setup in input-only decode')
    monkeypatch.setattr(f2.J2CartesianTrajectory,'__post_init__',forbid);monkeypatch.setattr(f2,'_gravity',forbid)
    monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbid)
    assert d.zonotope_local_request_from_json_v2(text).api_version==2


def test_text_duplicate_depth_container_and_primitive_bounds():
    with pytest.raises(ValueError):d.zonotope_local_request_from_json_v2('x'*(4*2**20+1))
    with pytest.raises(ValueError):d.zonotope_local_request_from_json_v2('{"format":1,"format":2}')
    for node in [dict(kind='tuple',items=[dict(kind='none')]*4097),dict(kind='str',value='x'*16385),dict(kind='int',value='1'*6000)]:
        with pytest.raises((TypeError,ValueError)):d._safe_tree(node)
    node=dict(kind='none')
    for _ in range(65):node=dict(kind='tuple',items=[node])
    with pytest.raises(ValueError):d._safe_tree(node)


@pytest.mark.parametrize('budget',list(d.LIMITS))
@pytest.mark.parametrize('value',[True,-1])
def test_budget_schema_rejected_before_physical_decode(monkeypatch,budget,value):
    p=payload();root=dict(p['inputs']['items']);items=dict(root['policy']['items'])
    items[budget]=codec.canonical_content(value)
    root['policy']['items']=[[k,items[k]]for k in sorted(items)]
    monkeypatch.setattr(codec,'decode_content',lambda *a:pytest.fail('decode before budget admission'))
    with pytest.raises((ValueError,TypeError)):d.zonotope_local_request_from_json_v2(json.dumps(p))


@pytest.mark.parametrize('value',[True,1,0.,-1.])
def test_resolution_schema_rejected_before_physical_decode(monkeypatch,value):
    p=payload();root=dict(p['inputs']['items']);root['requested_resolution_seconds']=codec.canonical_content(value)
    p['inputs']['items']=[[k,root[k]]for k in sorted(root)]
    monkeypatch.setattr(codec,'decode_content',lambda *a:pytest.fail('decode before resolution admission'))
    with pytest.raises((ValueError,TypeError)):d.zonotope_local_request_from_json_v2(json.dumps(p))
