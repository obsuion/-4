"""B52 input/compact-state admission, exact data restore and immutable publish."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction as Q
from functools import lru_cache
from hashlib import sha256
import json
import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot
from ops_sim.v5.lifecycle_document import dumps_root, loads_root, canonical
from ops_sim.v5.lifecycle_checkpoint import (GraphCodec, checkpoint_bytes,
    make_bindings, admit_checkpoint, restore_checkpoint, save_checkpoint,
    admit_graph_structure)
from ops_sim.v5.lifecycle_execution import start_lifecycle, scientific_projection
from ops_sim.v5.orbit_j2 import J2CartesianTrajectory


@lru_cache(maxsize=1)
def root():
    return LifecycleRoot(make_inputs(wire='weakness'), 600, sun_mode='BOUND_SHORT_TABLE_V1')


@pytest.fixture(scope='module')
def initial_packet():
    state = start_lifecycle(root())
    bindings = make_bindings(state.root, state.clock)
    raw = checkpoint_bytes(state, bindings)
    return state, bindings, raw


def test_immutable_root_document_roundtrip_exact_and_canonical():
    r = root()
    raw = dumps_root(r)
    restored = loads_root(raw)
    assert restored.identity == r.identity
    assert dumps_root(restored) == raw


def test_immutable_base_wire_matches_accepted_strict_input_document():
    from ops_sim.v5.command_document import inputs_to_json
    r = root()
    assert json.loads(dumps_root(r))['inputs']['base'] == json.loads(inputs_to_json(r.base))


@pytest.mark.parametrize('name', ('duration_seconds', 'policy', 'scenario', 'extra', 'digest', 'spelling'))
def test_root_document_mutations_are_rejected(name):
    document = json.loads(dumps_root(root()))
    if name == 'duration_seconds':
        document['inputs'][name] = True
    elif name == 'policy':
        document['inputs'][name]['quiet_step_seconds'] = '60'
    elif name == 'scenario':
        document['inputs'][name]['namespace'] = '../outside'
    elif name == 'extra':
        document['inputs']['derived_actual_state'] = {}
    elif name == 'digest':
        document['digest'] = 'f'*64
    if name not in ('digest', 'spelling'):
        document['digest'] = sha256(canonical({k: document[k] for k in ('format', 'version', 'inputs')}).encode()).hexdigest()
    raw = canonical(document).encode()+ (b'\n' if name == 'spelling' else b'')
    with pytest.raises((ValueError, TypeError)):
        loads_root(raw)


def test_local_graph_exact_scalars_aliases_and_no_b51_registry_mutation():
    from ops_sim.v5 import rolling_snapshot_document as old
    old_names = set(old.RECORDS)
    shared = [Q(3, 7), -0.0, 1.5]
    data = (shared, shared, {Q(1, 3): [1, 'bounded'], 2: None})
    codec = GraphCodec(())
    graph = codec.encode(data)
    admit_graph_structure(graph)
    output = codec.decode(graph)
    assert output == data and output[0] is output[1]
    assert output[0][1].hex() == (-0.0).hex()
    assert set(old.RECORDS) == old_names
    assert not any(n.endswith('.LifecycleObservation') for n in old_names)


@pytest.mark.parametrize('token', (['float', 'nan'], ['int', '01'],
    ['rational', '2', '4'], ['enum', 'os', 'system'], ['ref', True]))
def test_local_graph_rejects_unknown_or_noncanonical_tokens(token):
    codec = GraphCodec(())
    graph = codec.encode(1)
    graph['value'] = token
    with pytest.raises((ValueError, KeyError)):
        admit_graph_structure(graph)


def test_graph_root_trajectory_is_opaque_and_never_reconstructed(monkeypatch):
    import ops_sim.v5.orbit_j2 as orbit
    trajectory = root().base.model.environment.trajectory
    codec = GraphCodec(root())
    graph = codec.encode(trajectory)
    assert graph['value'][0] == 'root' and graph['nodes'] == []
    def forbidden(*args, **kw):
        raise AssertionError('original gravity must not run on restore')
    monkeypatch.setattr(orbit, '_gravity', forbidden)
    assert codec.decode(graph) is trajectory


def test_direct_materialization_has_zero_scientific_initialization(initial_packet, monkeypatch):
    import ops_sim.v5.lifecycle_orbit as orbit
    import ops_sim.v5.lifecycle_world as world
    import ops_sim.v5.lifecycle_physics as physical
    import ops_sim.v5.lifecycle_execution as execution
    import ops_sim.v5.orbit_j2 as original
    import ops_sim.v5.experiment_codec as codec
    import ops_sim.v5.command_document as command_document
    import ops_sim.v5.long_mission_document as legacy_document
    state, bindings, raw = initial_packet
    before = deepcopy(scientific_projection(state))
    prior = asdict(state.work)
    calls = []
    def forbidden(*args, **kw):
        calls.append(True)
        raise AssertionError('direct restore invoked numerical owner')
    for owner, name in ((orbit, '_gravity'), (orbit, '_rk4_step'),
        (world, 'nominal_parallel_ray'), (world, 'evaluate_ground_point_geometry'),
        (world, 'evaluate_ground_visibility'), (physical, 'start_lifecycle_physical'),
        (physical, 'construction_physical_substep'), (physical, 'compile_construction'),
        (physical, 'compile_effective_hardware'), (execution, 'start_lifecycle'),
        (original, '_gravity'), (original, '_rk4_step'),
        (codec, '_decode'), (codec, 'canonical_content'),
        (legacy_document, 'canonical_content'), (command_document, 'inputs_to_json')):
        monkeypatch.setattr(owner, name, forbidden)
    restored, proof = restore_checkpoint(raw, state.root, sha256(raw).hexdigest(), bindings)
    assert calls == []
    assert scientific_projection(restored) == before
    assert asdict(restored.work) == prior == proof['retained_prior_work']
    assert proof['restored_clock'] == state.clock
    assert restored.physical.nominal_provider is restored.actual_provider
    assert restored.actual_provider is not restored.forecast_provider
    assert restored.actual_world.provider is restored.actual_provider
    assert restored.forecast_world.provider is restored.forecast_provider


@pytest.mark.parametrize('change', ('source_identity', 'root_identity', 'input_sha256', 'grid_identity', 'clock', 'runtime', 'method'))
def test_changed_binding_rejects_before_record_decode(initial_packet, monkeypatch, change):
    state, bindings, raw = initial_packet
    changed = deepcopy(bindings)
    if change == 'clock':
        changed[change] += 1
    elif change == 'runtime':
        changed[change]['interpreter_sha256'] = 'f'*64
    elif change == 'method':
        changed[change] = 'OLD_METHOD'
    else:
        changed[change] = 'f'*64
    def forbidden(*args, **kwargs):
        raise AssertionError('binding failure reached owner decode')
    monkeypatch.setattr(GraphCodec, 'decode', forbidden)
    with pytest.raises(ValueError):
        admit_checkpoint(raw, state.root, sha256(raw).hexdigest(), changed)


def test_wrong_sha_corrupt_and_unknown_document_fields_fail(initial_packet):
    state, bindings, raw = initial_packet
    with pytest.raises(ValueError):
        admit_checkpoint(raw+b' ', state.root, sha256(raw).hexdigest(), bindings)
    document = json.loads(raw)
    document['unrecognized'] = 'field'
    bad = canonical(document).encode()
    with pytest.raises((ValueError, TypeError)):
        admit_checkpoint(bad, state.root, sha256(bad).hexdigest(), bindings)


def test_checkpoint_encoding_is_pure_and_has_finite_size(initial_packet):
    state, bindings, _ = initial_packet
    before = deepcopy(scientific_projection(state))
    raw = checkpoint_bytes(state, bindings)
    assert len(raw) < state.root.policy.max_checkpoint_bytes <= 64*2**20
    assert scientific_projection(state) == before
    assert json.loads(raw)['format'] == 'B52_TRUSTED_COMPACT_CHECKPOINT_V1'


def test_save_immutable_checkpoint_and_manifest_without_replace(initial_packet, tmp_path, monkeypatch):
    import ops_sim.v5.lifecycle_checkpoint as owner
    state, bindings, raw = initial_packet
    def forbidden(*args, **kwargs):
        raise AssertionError('publication must not replace reader-held files')
    monkeypatch.setattr(owner.os, 'replace', forbidden)
    path = tmp_path/'state.json'
    result = save_checkpoint(path, state, bindings)
    assert path.read_bytes() == raw
    manifest = json.loads((tmp_path/'state.json.manifest.json').read_bytes())
    assert manifest['sha256'] == result['sha256'] == sha256(raw).hexdigest()
    assert manifest['bytes'] == len(raw)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_checkpoint(path, state, bindings)
    assert path.read_bytes() == before
    restored, _ = restore_checkpoint(path, state.root, result['sha256'], bindings)
    assert scientific_projection(restored) == scientific_projection(state)


def test_output_quota_refusal_leaves_no_published_files(initial_packet, tmp_path):
    state, bindings, raw = initial_packet
    directory = tmp_path/'not-created'
    with pytest.raises(ValueError, match='disk quota'):
        save_checkpoint(directory/'state.json', state, bindings, maximum_output_bytes=len(raw)-1)
    assert not directory.exists()


def test_failed_manifest_publication_preserves_existing_authority(initial_packet, tmp_path, monkeypatch):
    import ops_sim.v5.lifecycle_checkpoint as owner
    state, bindings, _ = initial_packet
    old = tmp_path/'old.json'
    old_result = save_checkpoint(old, state, bindings)
    prior = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    original_link = owner.os.link
    calls = []
    def injected(source, target):
        calls.append(str(target))
        if len(calls) == 2:
            raise PermissionError('EXPECTED_INJECTED_MANIFEST_PUBLICATION_FAILURE')
        return original_link(source, target)
    monkeypatch.setattr(owner.os, 'link', injected)
    path = tmp_path/'new.json'
    with pytest.raises(PermissionError, match='EXPECTED_INJECTED'):
        save_checkpoint(path, state, bindings)
    assert path.exists() and not (tmp_path/'new.json.manifest.json').exists()
    for name, data in prior.items():
        assert (tmp_path/name).read_bytes() == data
    assert not any(p.name.endswith('.tmp') for p in tmp_path.iterdir())
    assert old_result['sha256'] == sha256(old.read_bytes()).hexdigest()
