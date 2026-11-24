"""Production checkpoint boundaries preserve canonical authority through transport."""
from copy import deepcopy
from hashlib import sha256

import pytest

from ops_sim.v5 import lifecycle_checkpoint as owner
from ops_sim.v5 import checkpoint_transport as transport
from ops_sim.v5.lifecycle_execution import scientific_projection
from test_lifecycle_checkpoint import initial_packet


def package(packet, kind='WORKING'):
    state, bindings, raw = packet
    encoded, receipt = transport.encode_checkpoint(raw, bindings, kind)
    cp = dict(file='checkpoint-00000001.json', sha256=sha256(raw).hexdigest(),
        bytes=len(raw), clock=state.clock, bindings=bindings, kind=kind,
        publication=dict(file='checkpoint-00000001-publication.json', sha256='1'*64, bytes=1),
        transport=receipt)
    return state.root, raw, encoded, cp


def test_file_boundary_keeps_raw_sha_bytes_and_separately_verifies_transport(tmp_path, initial_packet):
    root, raw, encoded, cp = package(initial_packet)
    path = tmp_path / cp['file']; path.write_bytes(encoded)
    assert cp['sha256'] == sha256(raw).hexdigest()
    assert cp['transport']['encoded_sha256'] == sha256(encoded).hexdigest()
    assert cp['bytes'] == len(raw) and cp['transport']['encoded_bytes'] == len(encoded)
    assert owner.checkpoint_file_bytes(path, cp, root, require_transport=True) == raw
    assert owner.admit_checkpoint(encoded, root, cp['sha256'], cp['bindings']) == owner.admit_checkpoint(raw, root, cp['sha256'], cp['bindings'])


def test_legacy_file_stays_separate_and_physical_store_cannot_downgrade(tmp_path, initial_packet):
    root, raw, encoded, cp = package(initial_packet)
    legacy = dict(cp); legacy.pop('transport')
    path = tmp_path / cp['file']; path.write_bytes(raw)
    assert owner.checkpoint_file_bytes(path, legacy, root) == raw
    with pytest.raises(ValueError, match='requires checkpoint transport'):
        owner.checkpoint_file_bytes(path, legacy, root, require_transport=True)
    with pytest.raises(ValueError, match='receipt disagreement'):
        owner.checkpoint_file_bytes(path, cp, root)
    path.write_bytes(encoded)
    with pytest.raises(ValueError, match='receipt disagreement'):
        owner.checkpoint_file_bytes(path, legacy, root)


@pytest.mark.parametrize('fault', ('encoded_sha', 'encoded_bytes', 'raw_sha', 'raw_bytes', 'role', 'binding', 'receipt_field', 'checkpoint_field'))
def test_metadata_or_actual_file_disagreement_refuses_without_rewrite(tmp_path, initial_packet, fault):
    root, raw, encoded, cp = package(initial_packet)
    cp = deepcopy(cp)
    if fault == 'encoded_sha': cp['transport']['encoded_sha256'] = '0'*64
    elif fault == 'encoded_bytes': cp['transport']['encoded_bytes'] += 1
    elif fault == 'raw_sha': cp['transport']['decoded_sha256'] = '0'*64
    elif fault == 'raw_bytes': cp['transport']['decoded_bytes'] += 1
    elif fault == 'role': cp['transport']['role'] = 'FINAL'
    elif fault == 'binding': cp['transport']['bindings']['source_identity'] = '0'*64
    elif fault == 'receipt_field': cp['transport']['extra'] = True
    else: cp['extra'] = True
    path = tmp_path / cp['file']; path.write_bytes(encoded)
    with pytest.raises((ValueError, TypeError)):
        owner.checkpoint_file_bytes(path, cp, root, require_transport=True)
    assert path.read_bytes() == encoded


def test_valid_transport_does_not_grant_invalid_scientific_graph(initial_packet):
    root, raw, _, cp = package(initial_packet)
    document = owner.parse_snapshot(raw)
    document['graph']['value'] = ['ref', True]
    invalid = owner.canonical(document).encode('utf8')
    encoded, _ = transport.encode_checkpoint(invalid, cp['bindings'], cp['kind'])
    with pytest.raises((ValueError, TypeError)):
        owner.admit_checkpoint(encoded, root, sha256(invalid).hexdigest(), cp['bindings'])


def test_direct_restore_decodes_before_canonical_owner_admission(initial_packet):
    root, raw, encoded, cp = package(initial_packet)
    direct, proof = owner.restore_checkpoint(encoded, root, cp['sha256'], cp['bindings'])
    legacy, legacy_proof = owner.restore_checkpoint(raw, root, cp['sha256'], cp['bindings'])
    assert scientific_projection(direct) == scientific_projection(legacy)
    assert proof == legacy_proof


def test_prepared_restore_receives_canonical_bytes_before_backend_gate(initial_packet, monkeypatch):
    root, raw, encoded, cp = package(initial_packet)
    strict = owner.admit_checkpoint
    seen = []
    def admit(current, *args, **kwargs):
        seen.append(current)
        return strict(current, *args, **kwargs)
    monkeypatch.setattr(owner, 'admit_checkpoint', admit)
    with pytest.raises(ValueError, match='explicit backend checkpoint required'):
        owner.prepare_checkpoint_restore(encoded, root, cp['sha256'], cp['bindings'])
    assert seen == [raw]


def test_real_progress_reader_accepts_seven_legacy_or_eight_transport_fields(initial_packet):
    from ops_sim.v5 import lifecycle_application as application
    root, _, _, cp = package(initial_packet)
    job = dict(job_id='a'*32, root_identity=root.identity,
        source_identity=cp['bindings']['source_identity'], runtime=cp['bindings']['runtime'],
        intent=dict(format=application.INTENT))
    record = dict(format=application.JOURNAL, sequence=1, job_id=job['job_id'],
        root_identity=root.identity, kind='checkpoint', data=cp)
    assert application._validate_progress(record, job, 1, method=root.method) is record
    legacy = deepcopy(record); legacy['data'].pop('transport')
    assert application._validate_progress(legacy, job, 1, method=root.method) is legacy
    record['data']['transport']['role'] = 'FINAL'
    with pytest.raises(ValueError, match='role'):
        application._validate_progress(record, job, 1, method=root.method)


def test_producer_registration_failure_precedes_directory_and_file_creation(tmp_path, monkeypatch):
    from ops_sim.v5 import lifecycle_application as application
    from ops_sim.v5 import lifetime_physical_storage as storage
    target = tmp_path / 'uncreated' / 'checkpoint-00000001.json'
    def refuse(path, *, additional_bytes=0):
        assert path == target
        assert additional_bytes == len(b'not published')
        raise ValueError('injected physical file grant refusal')
    monkeypatch.setattr(storage, 'register_producer_path', refuse)
    with pytest.raises(ValueError, match='file grant refusal'):
        application._write_new(target, b'not published')
    assert not target.parent.exists()


def test_parent_metadata_grant_refusal_precedes_append(tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from ops_sim.v5 import lifecycle_application as application
    from ops_sim.v5 import lifetime_physical_storage as storage
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2, METHOD_PHYSICAL
    instance = object.__new__(application.LifecycleStore)
    instance._parent_work = {}
    instance.lock = __import__("threading").RLock()
    instance.runner_policy = replace(LifetimeCampaignPolicyV2(), method=METHOD_PHYSICAL)
    instance.root_input = SimpleNamespace(output_policy=LifecycleStreamPolicy())
    folder = tmp_path / 'jobs' / ('a'*32); folder.mkdir(parents=True)
    instance.path = lambda *parts: tmp_path.joinpath(*parts)
    def refuse(store, jid, leaf, additional):
        assert store is instance and jid == 'a'*32
        assert leaf == 'parent-publication-work.bin' and additional == application.PARENT_COST.size
        raise ValueError('injected mutable metadata grant refusal')
    monkeypatch.setattr(storage, 'reserve_parent_metadata', refuse)
    with pytest.raises(ValueError, match='metadata grant refusal'):
        instance._parent_charge('a'*32, 10)
    assert not (folder / 'parent-publication-work.bin').exists()


@pytest.mark.parametrize('route', ('result', 'initial_package'))
def test_physical_legacy_exports_refuse_before_read_or_creation(tmp_path, route):
    from dataclasses import replace
    from threading import RLock
    from ops_sim.v5 import lifecycle_application as application
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2, METHOD_PHYSICAL
    store = object.__new__(application.LifecycleStore)
    store.runner_policy = replace(LifetimeCampaignPolicyV2(), method=METHOD_PHYSICAL)
    def forbidden(*args):
        raise AssertionError('legacy reader/writer reached before physical refusal')
    store.job = forbidden
    store.path = forbidden
    with pytest.raises(ValueError, match='YEAR-V4 physical stores'):
        if route == 'result':
            store.export('a'*32)
        else:
            workspace = object.__new__(application.LifecycleWorkspace)
            workspace.lock = RLock()
            workspace.store = lambda rid: store
            workspace.prepare_portable('b'*64, tmp_path / 'never-created.zip')
    assert not (tmp_path / 'never-created.zip').exists()


@pytest.mark.parametrize('route', ('result', 'initial_package'))
def test_legacy_export_policy_still_reaches_its_original_admission_boundary(tmp_path, route):
    from threading import RLock
    from ops_sim.v5 import lifecycle_application as application
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    store = object.__new__(application.LifecycleStore)
    store.runner_policy = LifetimeCampaignPolicyV2()
    def original_boundary(*args):
        raise LookupError('original legacy admission reached')
    store.job = original_boundary
    store.path = original_boundary
    with pytest.raises(LookupError, match='original legacy admission reached'):
        if route == 'result':
            store.export('a'*32)
        else:
            workspace = object.__new__(application.LifecycleWorkspace)
            workspace.lock = RLock()
            workspace.store = lambda rid: store
            workspace.prepare_portable('b'*64, tmp_path / 'never-created.zip')
