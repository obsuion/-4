from dataclasses import asdict,replace
from unittest.mock import patch
import pytest
from tests.test_long_environment import fresh,genuine
from tests.test_long_mission import finish
from ops_sim.v5.long_mission import advance_long_mission
from ops_sim.v5.long_mission_continuation import (save_continuation,restore_continuation,scientific_bytes,admit_reconstruction)
from ops_sim.v5.long_mission_document import mission_input_digest
from ops_sim.v5 import orbit_sun_zonotope_local_v2 as light

def prefix():
    s=fresh()
    for _ in range(3):s=advance_long_mission(s)
    return s

def test_full_causal_replay_equality_and_one_receipt(tmp_path):
    s=prefix();p=tmp_path/'packet.json';digest=save_continuation(p,s)
    reference=scientific_bytes(finish(s))
    with patch.object(light,'evaluate_zonotope_local_illumination_v2',return_value=genuine()[1]):
        restored,cost=restore_continuation(p,expected_packet_sha256=digest,expected_input_digest=mission_input_digest(s.inputs))
    result=finish(restored)
    assert scientific_bytes(result)==reference
    assert cost['reconstruction_delta']['upstream_entries']==1 and cost['reconstruction_delta']['runtime_entries']==1
    assert cost['reconstruction_delta']['nominal_force_reserved']>0
    assert len(result.context.ground_data_delivery_state.completed_deliveries)==1

def test_edited_packet_and_external_binding_before_entry(tmp_path,monkeypatch):
    s=prefix();p=tmp_path/'packet.json';digest=save_continuation(p,s)
    monkeypatch.setattr(light,'evaluate_zonotope_local_illumination_v2',lambda *a:pytest.fail('must reject before numerical source'))
    with pytest.raises(ValueError):restore_continuation(p,expected_packet_sha256='0'*64,expected_input_digest=s.input_digest)
    p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError):restore_continuation(p,expected_packet_sha256=digest,expected_input_digest=s.input_digest)

def test_stale_alias_cannot_save(tmp_path):
    s=fresh();advance_long_mission(s)
    with pytest.raises(ValueError,match='stale'):save_continuation(tmp_path/'packet.json',s)

def test_reconstruction_quota_before_work():
    s=prefix();work=replace(s.runtime_work,runtime_entries=s.inputs.limits.max_runtime_entries)
    with pytest.raises(ValueError,match='RECONSTRUCTION_ADMISSION'):admit_reconstruction(s.inputs,s.cursor,work)
