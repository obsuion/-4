"""Input-only allowlist is complete before any constructor dispatch."""
from dataclasses import replace
import json
import pytest
from test_orbit_sun_zonotope_local import request
from ops_sim.v5 import orbit_sun_zonotope_local_document as d
from ops_sim.v5 import experiment_codec as codec
from ops_sim.v5 import orbit_j2 as f2


def payload(q=None):return json.loads(d.zonotope_local_request_to_json(q or request()))


def test_input_roundtrip_digest_and_exclusive_save(tmp_path):
    q=request();text=d.zonotope_local_request_to_json(q);digest=d.zonotope_local_request_digest(q)
    assert d.zonotope_local_request_from_json(text,expected_digest=digest)==q
    p=tmp_path/'inputs.json';d.save_zonotope_local_request(p,q)
    assert d.load_zonotope_local_request(p,expected_digest=digest)==q
    with pytest.raises(FileExistsError):d.save_zonotope_local_request(p,q)
    with pytest.raises(ValueError):d.zonotope_local_request_from_json(text,expected_digest='0'*64)


@pytest.mark.parametrize('name',['J2CartesianTrajectory','J2ZonotopeSegmentResult','J2ZonotopeSegmentDiagnostic','LocalIlluminationResult','J2EnclosureResult','EngineCheckpoint','ForeignBoundary'])
def test_unsafe_derived_records_refused_before_decode(monkeypatch,name):
    p=payload();p['inputs']['items'][0][1]={'kind':'record','type':name,'fields':{}}
    monkeypatch.setattr(codec,'decode_content',lambda *a:pytest.fail('decode before safe admission'))
    with pytest.raises(ValueError):d.zonotope_local_request_from_json(json.dumps(p))


@pytest.mark.parametrize('mode',['extra','missing','identity_bool','duplicate','badkind','nestedextra','digest','policy_identity'])
def test_malformed_input_refused(mode):
    p=payload()
    if mode=='extra':p['extra']=1
    elif mode=='missing':del p['inputs']
    elif mode=='identity_bool':p['version']=True
    elif mode=='duplicate':p['inputs']['items'].append(p['inputs']['items'][-1])
    elif mode=='badkind':p['inputs']['kind']='result'
    elif mode=='digest':p['digest']='0'*64
    else:
        data=dict(p['inputs']['items']);key='policy' if mode=='policy_identity' else 'segment'
        if mode=='nestedextra':data[key]['items'].append(['z',{'kind':'none'}])
        else:
            for pair in data[key]['items']:
                if pair[0]=='resource_policy_version':pair[1]={'kind':'int','value':'2'}
    with pytest.raises((TypeError,ValueError)):d.zonotope_local_request_from_json(json.dumps(p))


def test_document_constructor_is_not_a_numerical_entry(monkeypatch):
    text=d.zonotope_local_request_to_json(request())
    def forbidden(*a,**k):pytest.fail('hidden force/trajectory construction')
    monkeypatch.setattr(f2.J2CartesianTrajectory,'__post_init__',forbidden)
    monkeypatch.setattr(f2,'_gravity',forbidden)
    assert d.zonotope_local_request_from_json(text).api_id=='m2-zonotope-local-illumination-v1'


def test_oversized_or_duplicate_json():
    with pytest.raises(ValueError):d.zonotope_local_request_from_json('x'*(4*2**20+1))
    with pytest.raises(ValueError):d.zonotope_local_request_from_json('{"format":1,"format":2}')
