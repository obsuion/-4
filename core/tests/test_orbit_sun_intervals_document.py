"""Strict, input-only content identity and exact offline reconstruction."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import subprocess
import sys

import pytest

from examples.m2_interval_illumination_demo import KINDS, example_request, summary
from ops_sim.v5.experiment_codec import CANONICAL_VERSION, canonical_content, content_digest, json_text
from ops_sim.v5.orbit_sun_intervals import evaluate_interval_illumination
from ops_sim.v5 import orbit_j2_segments as b2
from ops_sim.v5.orbit_sun_intervals_document import (
    DOMAIN, interval_request_digest, interval_request_to_json, interval_request_from_json,
    save_interval_request, load_interval_request,
)


def mapping(wire):return dict(wire['items'])


def redigest(payload):
    # An attacker can hash malformed canonical data without the valid encoder.
    payload['digest']=hashlib.sha256(json_text({'domain':DOMAIN,'canonical_version':CANONICAL_VERSION,
        'content':payload['inputs']}).encode('utf-8')).hexdigest()
    return json.dumps(payload)


@pytest.mark.parametrize('kind',KINDS)
def test_exact_input_roundtrip_and_exclusive_save(kind,tmp_path):
    q=example_request(kind); text=interval_request_to_json(q); digest=interval_request_digest(q)
    p=tmp_path/'input.json'
    save_interval_request(p,q)
    assert p.read_bytes()==(text+'\n').encode('utf-8')
    assert load_interval_request(p,expected_digest=digest)==q
    assert interval_request_from_json(text)==q
    with pytest.raises(FileExistsError):save_interval_request(p,q)
    assert p.read_bytes()==(text+'\n').encode('utf-8')


@pytest.mark.parametrize('key,value',[
    ('version',True),('version',1.),('version',2),('version','1'),
    ('canonical_version',True),('canonical_version',2),('format','wrong'),('format',None),
    ('digest','0'*64),('digest','F'*64),('digest',None),('digest','a'*63),
    ('cells',[]),('current_state',{}),('combined_qualification','ILLUMINATED'),
])
def test_envelope_rejects_wrong_types_versions_and_derived_fields(key,value):
    p=json.loads(interval_request_to_json(example_request('illuminated')));p[key]=value
    with pytest.raises((TypeError,ValueError)):interval_request_from_json(json.dumps(p))


@pytest.mark.parametrize('key',['format','version','canonical_version','inputs','digest'])
def test_missing_envelope_fields(key):
    p=json.loads(interval_request_to_json(example_request('illuminated')));del p[key]
    with pytest.raises(ValueError):interval_request_from_json(json.dumps(p))


@pytest.mark.parametrize('key',['coast','table','start','end','policy'])
def test_missing_authorities_with_recomputed_hash(key):
    p=json.loads(interval_request_to_json(example_request('illuminated')))
    p['inputs']['items']=[x for x in p['inputs']['items'] if x[0]!=key]
    with pytest.raises(ValueError):interval_request_from_json(redigest(p))


@pytest.mark.parametrize('which',[
    'coast-version','bool-time','epoch','reversed','outside-domain','policy-bool','policy-limit',
    'policy-extra','duplicate-map','noncanonical-order','table-normalization','table-zero',
    'table-policy','table-frame','table-epoch','table-provenance','table-extra','derived-cells',
])
def test_malformed_redigested_content_remains_invalid(which):
    p=json.loads(interval_request_to_json(example_request('illuminated')))
    data=mapping(p['inputs']);table=mapping(data['table']);policy=mapping(data['policy'])
    start=data['start']['fields'];end=data['end']['fields'];coast=data['coast']['fields']
    if which=='coast-version':coast['policy_version']=canonical_content(True)
    elif which=='bool-time':start['elapsed_seconds']=canonical_content(True)
    elif which=='epoch':end['epoch']['fields']['julian_day']=canonical_content(2451546)
    elif which=='reversed':start['elapsed_seconds'],end['elapsed_seconds']=end['elapsed_seconds'],start['elapsed_seconds']
    elif which=='outside-domain':end['elapsed_seconds']=canonical_content(129.)
    elif which in ('policy-bool','policy-limit'):
        policy['max_cells'].clear();policy['max_cells'].update(canonical_content(True if which=='policy-bool' else 5119))
    elif which=='policy-extra':data['policy']['items'].append(['tolerance',canonical_content(1.)])
    elif which=='duplicate-map':p['inputs']['items'].append(deepcopy(p['inputs']['items'][0]))
    elif which=='noncanonical-order':p['inputs']['items'].reverse()
    elif which in ('table-normalization','table-zero'):
        sample=mapping(table['samples']['items'][0])
        if which=='table-normalization':
            sample['elapsed_seconds'].clear();sample['elapsed_seconds'].update(canonical_content(128))
        else:
            sample['position_m'].clear();sample['position_m'].update(canonical_content((0.,0.,0.)))
    elif which=='table-policy':
        table['interpolation'].clear();table['interpolation'].update(canonical_content('CUBIC'))
    elif which=='table-frame':
        table['frame']['fields']['rotation']['fields']['initial_phase_rad']['fields']['value']=canonical_content(.5)
    elif which=='table-epoch':table['epoch']['fields']['julian_day']=canonical_content(2451546)
    elif which=='table-provenance':
        prov=mapping(table['provenance'])
        prov['accuracy_policy'].clear();prov['accuracy_policy'].update(canonical_content('ZERO_ERROR'))
    elif which=='table-extra':data['table']['items'].append(['cached_samples',canonical_content(())])
    else:p['inputs']['items'].append(['derived_cells',canonical_content(())])
    with pytest.raises((TypeError,ValueError)):interval_request_from_json(redigest(p))


def test_duplicate_json_keys_and_nonfinite_constants_rejected():
    text=interval_request_to_json(example_request('illuminated'))
    with pytest.raises(ValueError,match='duplicate'):interval_request_from_json('{"format":"x",'+text[1:])
    with pytest.raises(ValueError,match='non-finite'):interval_request_from_json('{"inputs":NaN}')


@pytest.mark.parametrize('expected',['0'*64,'F'*64,True,1.,'bad'])
def test_expected_digest_is_strict(expected):
    with pytest.raises((TypeError,ValueError)):
        interval_request_from_json(interval_request_to_json(example_request('illuminated')),expected_digest=expected)


@pytest.mark.parametrize('which',['start','end','nominal','enclosure','geometry','sun-node','provenance'])
def test_digest_binds_all_inputs_and_provenance(which):
    q=example_request('illuminated')
    if which=='start':changed=replace(q,start=replace(q.start,elapsed_seconds=q.start.elapsed_seconds+1/256))
    elif which=='end':changed=replace(q,end=replace(q.end,elapsed_seconds=q.end.elapsed_seconds-1/256))
    elif which=='nominal':changed=replace(q,coast=replace(q.coast,solver_config=replace(q.coast.solver_config,max_steps=31)))
    elif which=='enclosure':changed=replace(q,coast=replace(q.coast,enclosure_policy=replace(q.coast.enclosure_policy,precision_digits=60)))
    elif which=='geometry':changed=replace(q,policy=replace(q.policy,max_cells=31))
    elif which=='sun-node':changed=replace(q,table=replace(q.table,samples=(replace(q.table.samples[0],position_m=(101.,-1.,0.)),q.table.samples[1])))
    else:changed=replace(q,table=replace(q.table,provenance=replace(q.table.provenance,accuracy_statement='Still unquantified; changed explicit rationale')))
    assert interval_request_digest(changed)!=interval_request_digest(q)
    with pytest.raises(ValueError,match='expected'):
        interval_request_from_json(interval_request_to_json(changed),expected_digest=interval_request_digest(q))


def test_loading_does_not_propagate_or_register_new_types(monkeypatch):
    q=example_request('illuminated'); text=interval_request_to_json(q)
    def forbidden(*args):raise AssertionError('loading propagated derived evidence')
    monkeypatch.setattr(b2,'evaluate_j2_segments',forbidden)
    assert interval_request_from_json(text)==q
    with pytest.raises(TypeError):canonical_content(q)
    data={'coast':q.coast,'start':q.start,'end':q.end}
    assert content_digest(DOMAIN,data)!=content_digest('m2-j2-segment-request-v1',data)


@pytest.mark.parametrize('kind',KINDS)
def test_fresh_process_offline_reconstructs_complete_evidence(kind,tmp_path):
    q=example_request(kind); path=tmp_path/'inputs.json';save_interval_request(path,q)
    command=[sys.executable,'-B','-m','examples.m2_interval_illumination_demo','--offline',
             '--inputs',str(path),'--expected-digest',interval_request_digest(q)]
    p=subprocess.run(command,capture_output=True,text=True,check=True,timeout=60,
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'))
    actual=json.loads(p.stdout)
    assert actual['python_network_disabled'] is True
    expected=json.loads(json.dumps(summary(evaluate_interval_illumination(q))))
    assert actual['evidence']==expected
