"""Input-only safe tree, identities, representation and fresh-process replay."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import subprocess
import sys
import pytest

from test_orbit_sun_zonotope_intervals import request
from ops_sim.v5 import orbit_sun_zonotope_intervals_document as d
from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_zonotope as z
from ops_sim.v5 import orbit_j2_zonotope_segments as seg
from ops_sim.v5 import experiment_codec as codec


def mapping(node):return dict(node['items'])

def redigest(p):
    p['digest']=hashlib.sha256(codec.json_text(dict(domain=d.DOMAIN,canonical_version=1,content=p['inputs'])).encode('utf-8')).hexdigest()
    return json.dumps(p)


@pytest.mark.parametrize('kind',['illuminated','occulted','ambiguous','work-failure','upstream-failure'])
def test_exact_input_roundtrip_exclusive_save_and_no_output_authority(kind,tmp_path):
    q=request(kind);text=d.zonotope_interval_request_to_json(q);digest=d.zonotope_interval_request_digest(q)
    p=tmp_path/'input.json';d.save_zonotope_interval_request(p,q)
    assert p.read_bytes()==(text+'\n').encode('utf-8')
    assert d.load_zonotope_interval_request(p,expected_digest=digest)==q
    assert d.zonotope_interval_request_from_json(text)==q
    with pytest.raises(FileExistsError):d.save_zonotope_interval_request(p,q)
    assert p.read_bytes()==(text+'\n').encode('utf-8')
    data=json.loads(text)['inputs'];assert codec.canonical_content(d._input_map(q))==data
    assert 'J2CartesianTrajectory' not in text and 'J2CoastOrbitInputs' not in text and 'cells' not in mapping(data)


@pytest.mark.parametrize('key,value',[('format','wrong'),('format',None),('version',True),('version',1.),('version',2),('canonical_version',True),('canonical_version',2),('digest','F'*64),('digest','0'*64),('digest',None),('cells',[]),('diagnostic',{})])
def test_wrong_envelope(key,value):
    p=json.loads(d.zonotope_interval_request_to_json(request()));p[key]=value
    with pytest.raises((TypeError,ValueError)):d.zonotope_interval_request_from_json(json.dumps(p))


@pytest.mark.parametrize('target,key,value',[
    ('root','api_id','wrong'),('root','api_version',True),('root','geometry_resource_policy_version',2),
    ('segment','api_id','wrong'),('segment','api_version',2),('segment','publication_version',False),
    ('segment','transport_resource_policy_version',2),('segment','kernel_id','legacy'),
    ('transport','resource_policy_version',2),('transport','kernel_id','wrong'),
    ('transport','pb_order',7),('transport','max_generators',13),('transport','retained_generators',5),
    ('transport','rank_bit_cap',8192),('geometry','resource_policy_version',True),
])
def test_nested_identity_tamper_after_recomputed_digest_before_decode(monkeypatch,target,key,value):
    p=json.loads(d.zonotope_interval_request_to_json(request()));root=mapping(p['inputs']);s=mapping(root['segment'])
    node={'root':root,'segment':s,'transport':mapping(s['policy']),'geometry':mapping(root['policy'])}[target]
    node[key].clear();node[key].update(codec.canonical_content(value))
    def forbidden(*a,**k):raise AssertionError('decode invoked before identity admission')
    monkeypatch.setattr(codec,'decode_content',forbidden)
    with pytest.raises((TypeError,ValueError)):d.zonotope_interval_request_from_json(redigest(p))


@pytest.mark.parametrize('badtype',[
    'ops_sim.v5.orbit_j2.J2CartesianTrajectory','ops_sim.v5.orbit_j2_binding.J2CoastOrbitInputs',
    'ops_sim.v5.orbit_j2_enclosure.J2EnclosureResult','ops_sim.v5.orbit_j2_zonotope_segments.J2ZonotopeSegmentResult',
    'ops_sim.v5.orbit_sun_intervals.IntervalIlluminationResult','ops_sim.v5.orbit_binding.CoastOrbitInputs',
    'ops_sim.v5.checkpoint.SimulationCheckpoint','unknown.Certificate',
])
def test_unsafe_nested_records_rejected_before_constructor_or_decode(monkeypatch,badtype):
    p=json.loads(d.zonotope_interval_request_to_json(request()));root=mapping(p['inputs']);s=mapping(root['segment'])
    s['initial_state'].clear();s['initial_state'].update(dict(kind='record',type=badtype,fields={}))
    def forbidden(*a,**k):raise AssertionError('unsafe decode/constructor reached')
    monkeypatch.setattr(codec,'decode_content',forbidden)
    monkeypatch.setattr(f2.J2CartesianTrajectory,'__post_init__',forbidden)
    with pytest.raises((TypeError,ValueError)):d.zonotope_interval_request_from_json(redigest(p))


@pytest.mark.parametrize('mode',['missing_record_field','unknown_record_field','unknown_enum','bad_member','unknown_map','duplicate_map','bad_primitive','extra_primitive','tuple_as_list','wrong_sample_schema'])
def test_entire_safe_tree_exact_nested_schemas_before_decode(monkeypatch,mode):
    p=json.loads(d.zonotope_interval_request_to_json(request()));root=mapping(p['inputs']);s=mapping(root['segment']);state=s['initial_state'];table=mapping(root['table'])
    if mode=='missing_record_field':del state['fields']['velocity']
    elif mode=='unknown_record_field':state['fields']['result']=dict(kind='none')
    elif mode=='unknown_enum':state['fields']['position']['fields']['frame']['fields']['kind']['type']='unknown.Enum'
    elif mode=='bad_member':state['fields']['position']['fields']['frame']['fields']['kind']['member']='INVALID'
    elif mode=='unknown_map':root['policy']['items'].append(['result',dict(kind='none')])
    elif mode=='duplicate_map':root['policy']['items'].append(root['policy']['items'][0])
    elif mode=='bad_primitive':s['api_version']['value']='01'
    elif mode=='extra_primitive':s['api_version']['result']=None
    elif mode=='tuple_as_list':table['samples']['kind']='list'
    elif mode=='wrong_sample_schema':table['samples']['items'][0]['items'].append(['direction',dict(kind='none')])
    def forbidden(*a,**k):raise AssertionError('decode should not be called')
    monkeypatch.setattr(codec,'decode_content',forbidden)
    with pytest.raises((TypeError,ValueError)):d.zonotope_interval_request_from_json(redigest(p))


def test_loading_digest_and_construction_zero_f1_f2_transport(monkeypatch):
    q=request();text=d.zonotope_interval_request_to_json(q);expected=d.zonotope_interval_request_digest(q)
    def forbidden(*a,**k):raise AssertionError('hidden setup science')
    for owner,name in [(f2.J2CartesianTrajectory,'__post_init__'),(f2,'_gravity'),(f2,'evaluate_j2_cartesian_state'),(z,'evaluate_j2_zonotope_enclosure_v3'),(z,'_coefficients_incremental_v1'),(seg,'evaluate_j2_zonotope_segments')]:monkeypatch.setattr(owner,name,forbidden)
    loaded=d.zonotope_interval_request_from_json(text,expected_digest=expected)
    assert loaded==q and d.zonotope_interval_request_digest(loaded)==expected
    assert d.zonotope_interval_request_to_json(loaded)==text


@pytest.mark.parametrize('expected',['0'*64,'F'*64,None])
def test_expected_digest_binding(expected):
    text=d.zonotope_interval_request_to_json(request())
    if expected is None:assert d.zonotope_interval_request_from_json(text)
    else:
        with pytest.raises(ValueError):d.zonotope_interval_request_from_json(text,expected_digest=expected)


def test_fresh_process_input_only_reconstruction(tmp_path):
    text=d.zonotope_interval_request_to_json(request());p=tmp_path/'input.json';p.write_text(text,encoding='utf-8')
    script="""import sys
from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5.orbit_sun_zonotope_intervals_document import load_zonotope_interval_request,zonotope_interval_request_to_json
f2._gravity=lambda *a,**k: (_ for _ in ()).throw(AssertionError('hidden force'))
f2.J2CartesianTrajectory.__post_init__=f2._gravity
print(zonotope_interval_request_to_json(load_zonotope_interval_request(sys.argv[1])))
"""
    child=subprocess.run([sys.executable,'-B','-c',script,str(p)],capture_output=True,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'))
    assert child.returncode==0,child.stderr
    assert child.stdout.decode('utf-8').strip()==text
