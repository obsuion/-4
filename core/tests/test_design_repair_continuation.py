from dataclasses import asdict
from hashlib import sha256
import json,pytest
from examples.m7_design_repair_demo import make_spec
from ops_sim.v5.design_repair_study import start_study
from ops_sim.v5.design_repair_continuation import save_study,restore_study
from ops_sim.v5.long_mission_document import canonical_json


def packet(tmp_path):
    s=start_study(make_spec());p=tmp_path/'study.json';h=save_study(p,s)
    return s,p,h


def test_empty_study_roundtrip_preserves_paid_construction(tmp_path):
    s,p,h=packet(tmp_path)
    restored,proof=restore_study(p,expected_packet_sha256=h,expected_spec_identity=s.spec.identity,
        expected_source_identity=s.spec.source_identity,completed_outputs={})
    assert restored.spec==s.spec and restored.work.constructor.compiles==16
    assert proof['completed_cases_reused']==0 and restored.active is None
    assert restored.work.metadata_reserved_bytes>=s.work.metadata_reserved_bytes


@pytest.mark.parametrize('field',['catalogue','work','selected_variant','source_identity','in_progress','proposals','inputs'])
def test_mutation_rejects_under_external_packet_authority(tmp_path,field):
    s,p,h=packet(tmp_path);d=json.loads(p.read_bytes());d[field]='MUTATED';p.write_text(canonical_json(d),encoding='utf-8')
    with pytest.raises(ValueError,match='EXTERNAL_STUDY_PACKET'):
        restore_study(p,expected_packet_sha256=h,expected_spec_identity=s.spec.identity,expected_source_identity=s.spec.source_identity,completed_outputs={})


def test_unknown_packet_field_rejects_with_new_external_hash(tmp_path):
    s,p,h=packet(tmp_path);d=json.loads(p.read_bytes());d['execution_callback']='bad';raw=canonical_json(d).encode();p.write_bytes(raw)
    with pytest.raises(ValueError):restore_study(p,expected_packet_sha256=sha256(raw).hexdigest(),expected_spec_identity=s.spec.identity,expected_source_identity=s.spec.source_identity,completed_outputs={})
