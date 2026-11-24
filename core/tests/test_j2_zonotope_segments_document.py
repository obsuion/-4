"""Input-only canonical binding and no evaluation even for malicious documents."""
import copy,hashlib,json
from dataclasses import replace
import pytest
from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_zonotope_segments_document as doc
from ops_sim.v5 import orbit_j2_zonotope_segments as seg
from ops_sim.v5.experiment_codec import canonical_content,json_text
from test_j2_zonotope_segments import request,policy


def node_map(node):return {k:v for k,v in node['items']}

def redigest(payload):
    envelope=dict(domain=doc.SEGMENT_DIGEST_DOMAIN,canonical_version=1,content=payload['inputs'])
    payload['digest']=hashlib.sha256(json_text(envelope).encode('utf-8')).hexdigest()
    return json_text(payload)


def test_exact_input_roundtrip_no_force_or_segment_evaluation(monkeypatch,tmp_path):
    req=request();text=doc.zonotope_segment_request_to_json(req)
    digest=doc.zonotope_segment_request_digest(req)
    def forbidden(*a,**k):raise AssertionError('document loading must not evaluate')
    monkeypatch.setattr(f2,'_gravity',forbidden)
    monkeypatch.setattr(seg,'evaluate_j2_zonotope_segments',forbidden)
    got=doc.zonotope_segment_request_from_json(text,expected_digest=digest)
    assert got==req and doc.zonotope_segment_request_to_json(got)==text
    p=tmp_path/'input.json';doc.save_zonotope_segment_request(p,got)
    assert doc.load_zonotope_segment_request(p)==got
    with pytest.raises(FileExistsError):doc.save_zonotope_segment_request(p,got)
    assert p.read_text(encoding='utf-8')==text+'\n'


@pytest.mark.parametrize('key', ['format','version','canonical_version','inputs','digest'])
def test_missing_extra_top_fields(key):
    p=json.loads(doc.zonotope_segment_request_to_json(request()));del p[key]
    with pytest.raises((TypeError,ValueError)):doc.zonotope_segment_request_from_json(json_text(p))
    p=json.loads(doc.zonotope_segment_request_to_json(request()));p[key+'extra']=None
    with pytest.raises((TypeError,ValueError)):doc.zonotope_segment_request_from_json(json_text(p))


@pytest.mark.parametrize('key', ['cells','result','final_diagnostic','counters','cache','solver_config','start'])
def test_redigested_forbidden_inputs(key):
    p=json.loads(doc.zonotope_segment_request_to_json(request()))
    p['inputs']['items'].append([key,{'kind':'none'}]);p['inputs']['items'].sort(key=lambda x:x[0])
    with pytest.raises((TypeError,ValueError)):doc.zonotope_segment_request_from_json(redigest(p))


@pytest.mark.parametrize('key,value',[('api_id','wrong'),('api_version',2),('publication_version',True),
 ('transport_resource_policy_version',2),('method_id','wrong'),('method_version',True),('kernel_id','wrong')])
def test_redigested_wrong_owner_identity(key,value):
    p=json.loads(doc.zonotope_segment_request_to_json(request()))
    node_map(p['inputs'])[key].clear();node_map(p['inputs'])[key].update(canonical_content(value))
    with pytest.raises((TypeError,ValueError)):doc.zonotope_segment_request_from_json(redigest(p))


@pytest.mark.parametrize('key,value',[('resource_policy_version',2),('pb_order',7),('max_generators',True),
 ('kernel_id','wrong'),('rank_bit_cap',8192),('max_scalar_operations',True)])
def test_redigested_wrong_policy(key,value):
    p=json.loads(doc.zonotope_segment_request_to_json(request()))
    n=node_map(node_map(p['inputs'])['policy'])[key];n.clear();n.update(canonical_content(value))
    with pytest.raises((TypeError,ValueError)):doc.zonotope_segment_request_from_json(redigest(p))


def test_malicious_full_trajectory_rejected_before_constructor(monkeypatch):
    req=request();p=json.loads(doc.zonotope_segment_request_to_json(req));m=node_map(p['inputs'])
    m['initial_state'].clear();m['initial_state'].update(dict(kind='record',type='ops_sim.v5.orbit_j2.J2CartesianTrajectory',fields=dict(initial_state=canonical_content(req.trajectory.initial_state),gravity_model=canonical_content(req.trajectory.gravity_model))))
    def forbidden(*a):raise AssertionError('malformed decode called F1')
    monkeypatch.setattr(f2,'_gravity',forbidden)
    with pytest.raises(ValueError,match='unsafe authority'):doc.zonotope_segment_request_from_json(redigest(p))


@pytest.mark.parametrize('case',['negative_mu','wrong_frame','epoch','noncanonical_float','unknown_record','duplicate_key'])
def test_redigested_malformed_authorities(case):
    p=json.loads(doc.zonotope_segment_request_to_json(request()));m=node_map(p['inputs'])
    if case=='negative_mu':m['gravity_model']['fields']['gravitational_parameter_m3_s2']['fields']['value']['value']=(-8.).hex()
    if case=='wrong_frame':m['initial_state']['fields']['position']['fields']['frame']['fields']['kind']['member']='EARTH_FIXED'
    if case=='epoch':m['end']['fields']['epoch']['fields']['julian_day']['value']=str(int(m['end']['fields']['epoch']['fields']['julian_day']['value'])+1)
    if case=='noncanonical_float':m['end']['fields']['elapsed_seconds']['value']='128.5'
    if case=='unknown_record':m['end']['type']='ops_sim.v5.world.CommonWorld'
    if case=='duplicate_key':p['inputs']['items'].append(copy.deepcopy(p['inputs']['items'][0]))
    with pytest.raises((TypeError,ValueError)):doc.zonotope_segment_request_from_json(redigest(p))


def test_digest_expected_digest_boolean_versions_and_normalization_drift():
    req=request();p=json.loads(doc.zonotope_segment_request_to_json(req));p['digest']='0'*64
    with pytest.raises(ValueError,match='digest'):doc.zonotope_segment_request_from_json(json_text(p))
    with pytest.raises(ValueError,match='expected'):doc.zonotope_segment_request_from_json(doc.zonotope_segment_request_to_json(req),expected_digest='0'*64)
    p=json.loads(doc.zonotope_segment_request_to_json(req));p['version']=True
    with pytest.raises(TypeError):doc.zonotope_segment_request_from_json(json_text(p))
    object.__setattr__(req.trajectory.initial_state.position,'components_m',(2,0.,0.))
    # Early exact-type rejection and later codec drift rejection both forbid it.
    with pytest.raises((TypeError,ValueError),match='SI component|normalized'):
        doc.zonotope_segment_request_to_json(req)
