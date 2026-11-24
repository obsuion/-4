"""Strict input documents, content identity and fresh-process reconstruction."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples.m1_assembly_interfaces_demo import summary, synthetic_inputs
from ops_sim.v5.assembly_document import assembly_document_digest, save_assembly_document
from ops_sim.v5.assembly_interface_document import (
    dumps_interface_document, interface_document_digest, loads_interface_document,
    load_interface_document, save_interface_document,
)
from ops_sim.v5.assembly_interfaces import compile_interfaces
from ops_sim.v5.ids import SourceRecordId


def payload():
    d,i = synthetic_inputs()
    return d,i,json.loads(dumps_interface_document(d,i))


def test_round_trip_recomputes_static_outputs_and_canonical_identity():
    d,i = synthetic_inputs()
    encoded = dumps_interface_document(d,i)
    digest = interface_document_digest(d,i)
    restored = loads_interface_document(encoded,d,expected_digest=digest)
    assert restored == i
    assert compile_interfaces(d,restored) == compile_interfaces(d,i)
    assert dumps_interface_document(d,restored) == encoded
    assert digest == hashlib.sha256(b'M1-ASSEMBLY-INTERFACES\0v1\0'+encoded.encode('utf-8')).hexdigest()


def test_unordered_inputs_and_records_keep_identity():
    d,i = synthetic_inputs()
    network = replace(i.thermal_network,nodes=tuple(reversed(i.thermal_network.nodes)),links=tuple(reversed(i.thermal_network.links)))
    shuffled = replace(i,ports=tuple(reversed(i.ports)),thermal_bindings=tuple(reversed(i.thermal_bindings)),
        thermal_network=network,thermal_boundaries=replace(i.thermal_boundaries,node_boundaries=tuple(reversed(i.thermal_boundaries.node_boundaries))))
    assert interface_document_digest(d,shuffled) == interface_document_digest(d,i)
    data = json.loads(dumps_interface_document(d,i))
    data['ports'].reverse(); data['thermal_bindings'].reverse()
    loaded = loads_interface_document(json.dumps(data,indent=4),d)
    assert loaded == i


def test_provenance_source_set_sorting_and_provenance_preserved():
    d,i = synthetic_inputs()
    n = i.thermal_network.nodes[0]
    def build(order):
        p = replace(n.heat_capacity_j_per_k, provenance=replace(n.heat_capacity_j_per_k.provenance,
                    source_ids=tuple(SourceRecordId(s) for s in order)))
        nodes = (replace(n,heat_capacity_j_per_k=p),)+i.thermal_network.nodes[1:]
        return replace(i,thermal_network=replace(i.thermal_network,nodes=nodes))
    a,b = build(('z-source','a-source')),build(('a-source','z-source'))
    assert interface_document_digest(d,a) == interface_document_digest(d,b)
    loaded = loads_interface_document(dumps_interface_document(d,a),d)
    assert loaded.thermal_network.nodes[0].heat_capacity_j_per_k.provenance == b.thermal_network.nodes[0].heat_capacity_j_per_k.provenance


@pytest.mark.parametrize('field', ['slack','wire','voltage','power','mode','heat','port','rationale','mass','boundary','capacity','conductance'])
def test_meaningful_input_changes_change_digest(field):
    d,i = synthetic_inputs()
    line = i.lines[0]
    other = i
    if field == 'slack': line = replace(line,slack_m=.125)
    elif field == 'wire': line = replace(line,wire=replace(line.wire,connector_count=1))
    elif field == 'voltage': line = replace(line,operating_point=replace(line.operating_point,source_voltage_v=11))
    elif field == 'power': line = replace(line,operating_point=replace(line.operating_point,power_w=17))
    elif field == 'mode': line = replace(line,operating_point=replace(line.operating_point,mode='GENERATED'))
    elif field == 'heat': line = replace(line,wire_loss_node_id='payload')
    elif field == 'port': other = replace(i,ports=(replace(i.ports[0],position_local_m=(.125,0,0)),i.ports[1]))
    elif field == 'rationale': other = replace(i,supply_rationale='Changed declared assumption')
    elif field == 'mass': line = replace(line,mass=replace(line.mass,status='UNSPECIFIED',coverage=None))
    elif field == 'boundary': other = replace(i,thermal_boundaries=replace(i.thermal_boundaries,node_boundaries=(replace(i.thermal_boundaries.node_boundaries[0],radiative_sink_temperature_k=251),)+i.thermal_boundaries.node_boundaries[1:]))
    elif field == 'capacity':
        node = i.thermal_network.nodes[0]
        node = replace(node,heat_capacity_j_per_k=replace(node.heat_capacity_j_per_k,value=1001.0))
        other = replace(i,thermal_network=replace(i.thermal_network,nodes=(node,)+i.thermal_network.nodes[1:]))
    elif field == 'conductance':
        link = i.thermal_network.links[0]
        link = replace(link,conductance_w_per_k=replace(link.conductance_w_per_k,value=3.0))
        other = replace(i,thermal_network=replace(i.thermal_network,links=(link,)+i.thermal_network.links[1:]))
    other = replace(other,lines=(line,))
    assert interface_document_digest(d,other) != interface_document_digest(d,i)
    with pytest.raises(ValueError,match='digest mismatch'):
        loads_interface_document(dumps_interface_document(d,other),d,expected_digest=interface_document_digest(d,i))


def test_waypoint_order_and_signed_zero_are_authoritative():
    d,i = synthetic_inputs()
    a=replace(i,lines=(replace(i.lines[0],waypoints_body_m=((0,1,0),(1,1,0))),))
    b=replace(i,lines=(replace(i.lines[0],waypoints_body_m=((1,1,0),(0,1,0))),))
    assert interface_document_digest(d,a)!=interface_document_digest(d,b)
    z=replace(i,lines=(replace(i.lines[0],slack_m=-0.0),))
    assert interface_document_digest(d,z)!=interface_document_digest(d,i)


@pytest.mark.parametrize('rationale', ['assumption é','assumption e\u0301','假设 explicitly synthetic'])
def test_exact_unicode_round_trip(rationale):
    d,i=synthetic_inputs();i=replace(i,supply_rationale=rationale)
    text=dumps_interface_document(d,i)
    assert rationale in text
    assert loads_interface_document(text,d).supply_rationale==rationale


@pytest.mark.parametrize('field,value', [('version',2),('version',True),('thermal_codec_version',2),
    ('thermal_codec_version',1.0),('format','OTHER'),('assembly_digest','0'*64),('body_frame_id','wrong')])
def test_stale_format_version_frame_or_binding_reject(field,value):
    d,_,data=payload();data[field]=value
    with pytest.raises((ValueError,TypeError)):loads_interface_document(json.dumps(data),d)


def test_changed_assembly_fails_loading_even_with_same_instance_ids():
    d,i=synthetic_inputs();other,_=synthetic_inputs('far')
    with pytest.raises(ValueError,match='assembly document digest mismatch'):
        loads_interface_document(dumps_interface_document(d,i),other)


OBJECT_PATHS = [(),('units',),('ports',0),('lines',0),('lines',0,'wire'),
    ('lines',0,'operating_point'),('lines',0,'mass'),('thermal_bindings',0),
    ('thermal_network',),('thermal_network','fields'),
    ('thermal_network','fields','nodes','items',0,'fields'),
    ('thermal_network','fields','nodes','items',0,'fields','heat_capacity_j_per_k','fields'),
    ('thermal_network','fields','nodes','items',0,'fields','heat_capacity_j_per_k','fields','provenance','fields'),
    ('thermal_boundaries','fields','node_boundaries','items',0,'fields')]


@pytest.mark.parametrize('path', OBJECT_PATHS)
@pytest.mark.parametrize('operation',['unknown','missing'])
def test_strict_fields_at_every_input_level(path,operation):
    d,_,data=payload();node=data
    for key in path:node=node[key]
    if operation=='unknown':node['derived_cached_result']=0
    else:del node[next(iter(node))]
    with pytest.raises((TypeError,ValueError)):loads_interface_document(json.dumps(data),d)


@pytest.mark.parametrize('bad', [1,True,None,'nan','inf','0x1p+0','1.0','0x1.0000000000000p+1024'])
def test_numeric_spelling_and_type_strict(bad):
    d,_,data=payload();data['lines'][0]['slack_m']=bad
    with pytest.raises((ValueError,TypeError,OverflowError)):loads_interface_document(json.dumps(data),d)


@pytest.mark.parametrize('collection',['ports','lines','thermal_bindings'])
def test_duplicate_records_reject(collection):
    d,_,data=payload();data[collection].append(data[collection][0])
    with pytest.raises(ValueError,match='duplicate'):loads_interface_document(json.dumps(data),d)


def test_duplicate_json_keys_and_nonfinite_constants_reject():
    d,i=synthetic_inputs();s=dumps_interface_document(d,i)
    for bad in ('{"version":1,"version":1}',s.replace('"slack_m":"0x0.0p+0"','"slack_m":NaN')):
        with pytest.raises(ValueError):loads_interface_document(bad,d)


@pytest.mark.parametrize('bad',[True,1.0,-1])
def test_connector_count_remains_exact_integer(bad):
    d,_,data=payload();data['lines'][0]['wire']['connector_count']=bad
    with pytest.raises(ValueError):loads_interface_document(json.dumps(data),d)


def test_missing_endpoints_and_incompatible_roles_cannot_enter_through_document():
    d,_,data=payload();data['ports'][0]['role']='SOURCE'
    with pytest.raises(ValueError,match='incompatible'):loads_interface_document(json.dumps(data),d)
    d,_,data=payload();data['lines'][0]['load_port_id']='absent'
    with pytest.raises(ValueError,match='missing line endpoint'):loads_interface_document(json.dumps(data),d)


def test_incomplete_input_round_trip_retains_outcome_without_cached_outputs():
    d,i=synthetic_inputs();i=replace(i,thermal_network=None,thermal_boundaries=None)
    text=dumps_interface_document(d,i)
    assert 'polyline_length_m' not in text and 'electrical_result' not in text
    other=loads_interface_document(text,d)
    assert compile_interfaces(d,other)==compile_interfaces(d,i)
    assert compile_interfaces(d,other).compilation is None


def test_save_is_exclusive_and_expected_digest_checked(tmp_path):
    d,i=synthetic_inputs();path=tmp_path/'interface.json'
    save_interface_document(d,i,path)
    with pytest.raises(FileExistsError):save_interface_document(d,i,path)
    assert load_interface_document(path,d,expected_digest=interface_document_digest(d,i))==i
    with pytest.raises(ValueError,match='digest'):load_interface_document(path,d,expected_digest='0'*64)


@pytest.mark.parametrize('case,generated',[('near',False),('far',False),('near',True),('far',True)])
def test_fresh_process_recomputes_two_input_files(tmp_path,case,generated):
    d,i=synthetic_inputs(case,generated=generated)
    a,b=tmp_path/'assembly.json',tmp_path/'interfaces.json'
    save_assembly_document(d,a);save_interface_document(d,i,b)
    result=subprocess.run([sys.executable,'-B','-m','examples.m1_assembly_interfaces_demo',
        '--assembly',str(a),'--interfaces',str(b),'--expected-digest',interface_document_digest(d,i)],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1'},check=True)
    assert json.loads(result.stdout)==summary(d,i)
    assert result.stderr==''
