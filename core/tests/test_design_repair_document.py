from dataclasses import replace
from hashlib import sha256
import json,pytest
from examples.m7_design_repair_demo import make_spec
from ops_sim.v5.design_repair_document import inputs_to_json,inputs_from_json
from ops_sim.v5.long_mission_document import canonical_json


def test_strict_portable_input_roundtrip():
    spec=make_spec();raw=inputs_to_json(spec)
    assert inputs_from_json(raw,expected_spec_identity=spec.identity,expected_source_identity=spec.source_identity)==spec


@pytest.mark.parametrize('key',['score','diagnosis','callback','output_path','cached_inertia','completed_records','selected_variant','physical_state'])
def test_unknown_or_derived_input_rejects_even_with_rebound_digest(key):
    d=json.loads(inputs_to_json(make_spec()));d['inputs'][key]=0
    d['digest']=sha256(canonical_json({n:d[n] for n in ('format','version','inputs')}).encode()).hexdigest()
    with pytest.raises(ValueError):inputs_from_json(canonical_json(d))


@pytest.mark.parametrize('key,value',[('version',True),('source_identity','x'),('selection_rule','caller-score'),('payload_areas_hex',['nan']),('placements',['compact','compact'])])
def test_wrong_type_or_noncanonical_contract_rejects(key,value):
    d=json.loads(inputs_to_json(make_spec()))
    if key=='version':d[key]=value
    else:d['inputs'][key]=value
    d['digest']=sha256(canonical_json({n:d[n] for n in ('format','version','inputs')}).encode()).hexdigest()
    with pytest.raises((ValueError,TypeError)):inputs_from_json(canonical_json(d))
