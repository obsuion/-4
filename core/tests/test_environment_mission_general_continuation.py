from dataclasses import replace, asdict
import json
import pytest
from examples.m3_general_earth_mission_demo import make_inputs, run
from examples.m3_spatial_constructor_mission_demo import make_inputs as old_inputs
from ops_sim.v5.environment_mission_3d_document import (mission_inputs_to_json, mission_inputs_from_json, mission_input_digest)
from ops_sim.v5.environment_mission_3d_continuation import (save_continuation, restore_continuation, continue_mission, scientific_bytes)


def test_v4_exact_roundtrip_and_v3_separate_domain():
    new = make_inputs(); old = old_inputs()
    v4 = mission_inputs_to_json(new); v3 = mission_inputs_to_json(old)
    assert json.loads(v4)['version'] == 4 and json.loads(v3)['version'] == 3
    assert mission_inputs_to_json(mission_inputs_from_json(v4)) == v4
    assert mission_inputs_to_json(mission_inputs_from_json(v3)) == v3
    assert mission_input_digest(new) != mission_input_digest(old)
    p = json.loads(v4); p['format'] = json.loads(v3)['format']; p['version'] = 3
    with pytest.raises(ValueError): mission_inputs_from_json(json.dumps(p))


@pytest.mark.parametrize('field', ['latitude_rad', 'ellipsoidal_height_m'])
def test_edited_ground_and_unsafe_codec_refused(field):
    p = json.loads(mission_inputs_to_json(make_inputs()))
    p['inputs']['catalog']['input_tuple'][0]['fields']['point']['fields'][field]['typed']['fields']['value']['value'] = '0x0.0p+0'
    with pytest.raises((TypeError, ValueError)): mission_inputs_from_json(json.dumps(p))


def test_packet_replay_science_and_paid_delta(tmp_path):
    inputs = make_inputs(); direct = run(inputs)
    prefix = run(inputs, stop=3); packet = tmp_path/'packet.json'
    digest = save_continuation(packet, prefix); data = json.loads(packet.read_text())
    assert data['version'] == 4
    state, work = restore_continuation(packet, expected_packet_sha256=digest, expected_input_digest=mission_input_digest(inputs))
    assert work['original_anchor_seconds'] == 128 and work['reconstruction_delta']['upstream_entries'] == 1
    assert work['reconstruction_delta']['physical_completed_calls'] > 0
    assert all(work['after'][n] >= work['prior'][n] for n in work['prior'])
    resumed = continue_mission(state)
    assert scientific_bytes(resumed) == scientific_bytes(direct)
    assert len(resumed.context.ground_data_delivery_state.completed_deliveries) == 1
    with pytest.raises(ValueError): restore_continuation(packet, expected_packet_sha256='0'*64, expected_input_digest=mission_input_digest(inputs))
