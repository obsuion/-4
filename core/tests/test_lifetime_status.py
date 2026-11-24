"""B63 saved-data and publication fault checks; no numerical owners called."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import random
import zlib

import pytest

import ops_sim.v5.lifetime_status as owner
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy


def job():
    return dict(format='B59_FINITE_OWNED_LIFECYCLE_JOB_V1', job_id='1' * 32,
        intent=dict(root_identity='2' * 64, idempotency_key='3' * 32,
                    parent_job_id=None, mode='NORMAL', maximum_output_bytes=128 * 2 ** 20),
        root_identity='2' * 64, source_identity='4' * 64,
        runtime=dict(implementation='CPython', version=[3, 14, 7]), input_sha256='5' * 64,
        resume=None, publication_sequence=0, status='QUEUED', reason=None,
        progress=None, checkpoints=[], result=None, launch=None, ownership_valid=None,
        created_utc='2026-10-18T00:00:00Z', worker_artifact_bytes=None)


def binding(value=None):
    return owner.make_binding(job() if value is None else value, '6' * 64, None, '7' * 64)


POLICY = LifecycleStreamPolicy()


class FakeWriter:
    def __init__(self, directory, policy, **kwargs):
        self.directory = directory
        self.head = SimpleNamespace(closed=False)
        self.sequence = 0
        self.values = []

    def publish(self, value, *, terminal=False):
        self.sequence += 1
        self.values.append((deepcopy(value), terminal))
        return self.sequence

    def close(self):
        self.head.closed = True


def publisher(tmp_path, **kwargs):
    return owner.Publisher(tmp_path / 'status63', binding(), POLICY,
                           writer_factory=FakeWriter, **kwargs)


def saved(tmp_path, value=None):
    value = job() if value is None else value
    plan = owner.preflight(value, binding())
    writer = publisher(tmp_path)
    writer.publish(plan)
    return writer, plan


def test_status_preflight_is_pure_and_full_sidecar_preserves_old_job_wire(tmp_path):
    value = job()
    value['progress'] = dict(padding='x' * 90000)
    before = deepcopy(value)
    plan = owner.preflight(value, binding())
    assert value == before and plan.sequence == 1
    assert len(plan.envelope_raw) < 65536 < len(plan.details_raw) <= 256 * 1024
    writer = publisher(tmp_path)
    assert writer.writer is None and not writer.directory.exists()
    assert writer.publish(plan) == 1
    admitted = owner.hydrate(writer.directory, plan.envelope, binding())
    assert admitted == dict(before, publication_sequence=1)
    assert 'storage_view' not in admitted
    assert writer.sequence == 1 and value == before


@pytest.mark.parametrize('delta', (-1, 0, 1))
def test_exact_decoded_record_cap_including_newline(delta):
    envelope = owner.preflight(job(), binding()).envelope
    envelope['index']['job']['intent']['padding'] = ''
    initial = len(owner.raw(envelope))
    envelope['index']['job']['intent']['padding'] = 'x' * (65536 - initial - 1 + delta)
    if delta > 0:
        with pytest.raises(ValueError, match='decoded byte cap'):
            owner.admit_envelope(envelope, binding())
    else:
        owner.admit_envelope(envelope, binding())
        assert len(owner.raw(envelope)) + 1 == 65536 + delta


def test_incompressible_progress_is_details_and_not_an_encoded_cap_escape():
    randomizer = random.Random(63)
    value = job()
    value['progress'] = dict(payload=''.join(randomizer.choice(
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(90000)))
    plan = owner.preflight(value, binding())
    assert len(zlib.compress(plan.details_raw)) > 65536
    assert len(plan.envelope_raw) < 65536


@pytest.mark.parametrize('delta', (0, 1))
def test_exact_details_cap(delta):
    value = job()
    value['progress'] = dict(padding='')
    initial = owner.preflight(value, binding())
    value['progress']['padding'] = 'x' * (owner.MAX_DETAILS_BYTES - len(initial.details_raw) + delta)
    if delta:
        with pytest.raises(ValueError, match='details byte cap'):
            owner.preflight(value, binding())
    else:
        assert len(owner.preflight(value, binding()).details_raw) == owner.MAX_DETAILS_BYTES


@pytest.mark.parametrize('key', owner.BINDING_KEYS)
def test_every_foreign_binding_refused(tmp_path, key):
    writer, plan = saved(tmp_path)
    foreign = binding()
    if key == 'runtime':
        foreign[key]['version'] = [3, 14, 8]
    elif key == 'profile_identity':
        foreign[key] = '8' * 64
    else:
        foreign[key] = ('8' * 32 if key == 'job_id' else '8' * 64)
    with pytest.raises(ValueError):
        owner.hydrate(writer.directory, plan.envelope, foreign)


@pytest.mark.parametrize('mutation', ('missing', 'hash', 'size', 'format', 'canonical', 'job'))
def test_details_faults_refused(tmp_path, mutation):
    writer, plan = saved(tmp_path)
    reference = plan.envelope['details']
    path = writer.directory / reference['path']
    if mutation == 'missing':
        path.unlink()
    elif mutation == 'hash':
        content = path.read_bytes()
        path.write_bytes(b' ' + content[1:])
    elif mutation == 'size':
        path.write_bytes(path.read_bytes() + b' ')
    else:
        envelope = plan.envelope
        details = json.loads(path.read_bytes())
        if mutation == 'format':
            details['format'] = 'FOREIGN'
        elif mutation == 'job':
            details['job']['job_id'] = '8' * 32
        content = (json.dumps(details, indent=1).encode() if mutation == 'canonical' else owner.raw(details))
        digest = sha256(content).hexdigest()
        envelope['details'].update(sha256=digest, bytes=len(content),
            path='details/00000001-' + digest + '.json')
        path = writer.directory / envelope['details']['path']
        path.write_bytes(content)
        with pytest.raises(ValueError):
            owner.hydrate(writer.directory, envelope, binding())
        return
    with pytest.raises((ValueError, FileNotFoundError)):
        owner.hydrate(writer.directory, plan.envelope, binding())


@pytest.mark.parametrize('path', ('/tmp/details.json', '../details.json', 'details/../x.json',
    'C:/details.json', 'details\\00000001.json', 'details/a:b.json'))
def test_path_escape_not_allowlisted(tmp_path, path):
    writer, plan = saved(tmp_path)
    envelope = plan.envelope
    envelope['details']['path'] = path
    with pytest.raises(ValueError):
        owner.hydrate(writer.directory, envelope, binding())


def test_reparse_bit_is_rejected_without_windows_handle_operations(tmp_path, monkeypatch):
    path = tmp_path / 'link'
    original = Path.lstat
    def metadata(candidate):
        if candidate == path:
            return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        return original(candidate)
    monkeypatch.setattr(Path, 'lstat', metadata)
    with pytest.raises(ValueError, match='link/reparse'):
        owner._reject_links(path)


def test_compact_index_never_hydrates_or_reads_details(tmp_path, monkeypatch):
    writer, plan = saved(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('compact listing tried to hydrate a result')
    monkeypatch.setattr(owner, 'hydrate', forbidden)
    monkeypatch.setattr(Path, 'open', forbidden)
    index = owner.index(plan.envelope, binding())
    assert index['storage_view'] == owner.INDEX and index['progress'] is None


def test_codec_reservation_failure_before_io_does_not_poison_writer(tmp_path):
    value = job()
    before = deepcopy(value)
    def refused(_):
        raise ValueError('expected injected codec quota')
    writer = publisher(tmp_path, codec_charge=refused)
    with pytest.raises(ValueError, match='expected injected'):
        writer.publish(owner.preflight(value, binding()))
    assert not writer.failed and writer.sequence == 0
    assert writer.writer is None and not writer.directory.exists() and value == before


def test_terminal_details_reserve_refusal_before_io(tmp_path):
    writer = publisher(tmp_path)
    writer.details_bytes = POLICY.status_total_bytes // 2 - owner.TERMINAL_RESERVE_BYTES
    with pytest.raises(ValueError, match='terminal reservation'):
        writer.publish(owner.preflight(job(), binding()))
    assert not writer.failed and not writer.directory.exists()


@pytest.mark.parametrize('stage', ('details', 'head', 'fsync'))
def test_started_io_failure_quarantines_no_replay_or_sequence_change(tmp_path, monkeypatch, stage):
    writer = publisher(tmp_path)
    plan = owner.preflight(job(), binding())
    original = owner._write_new
    def inject(path, content):
        if stage == 'details' and path.parent.name == 'details':
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content[:3])
            raise OSError('expected injected details write')
        return original(path, content)
    monkeypatch.setattr(owner, '_write_new', inject)
    if stage == 'head':
        def fail(*args, **kwargs):
            raise OSError('expected injected head write')
        monkeypatch.setattr(FakeWriter, 'publish', fail)
    if stage == 'fsync':
        def fail(_):
            raise OSError('expected injected fsync')
        monkeypatch.setattr(owner.os, 'fsync', fail)
    with pytest.raises(OSError, match='expected injected'):
        writer.publish(plan)
    assert writer.failed and writer.sequence == 0
    with pytest.raises(ValueError, match='quarantined'):
        writer.publish(plan)


def test_committed_head_not_rolled_back_by_later_consumer_failure(tmp_path):
    writer, plan = saved(tmp_path)
    before = deepcopy(plan.job)
    with pytest.raises(RuntimeError, match='expected callback'):
        raise RuntimeError('expected callback after successful publication')
    assert owner.hydrate(writer.directory, plan.envelope, binding()) == before
    assert writer.sequence == 1 and not writer.failed


def test_read_only_hydration_has_finite_read_reservation_and_no_writes(tmp_path):
    writer, plan = saved(tmp_path)
    before = {p.relative_to(writer.directory).as_posix(): p.read_bytes()
              for p in writer.directory.rglob('*') if p.is_file()}
    charges = []
    owner.hydrate(writer.directory, plan.envelope, binding(), read_charge=charges.append)
    assert charges == [16 * len(plan.details_raw) + 65536]
    after = {p.relative_to(writer.directory).as_posix(): p.read_bytes()
             for p in writer.directory.rglob('*') if p.is_file()}
    assert after == before


def test_independent_error_channel_large_primary_and_secondary_are_separate(tmp_path):
    writer, _ = saved(tmp_path)
    receipt = writer.errors.record('SETTLEMENT', ValueError('я' * 100000),
        traceback_text='traceя' * 100000, secondary=[OSError('副' * 10000)] * 8)
    content = (writer.directory / receipt['path']).read_bytes()
    assert len(content) <= owner.MAX_ERROR_BYTES
    value = json.loads(content)
    assert value['traceback_truncated'] is True and len(value['secondary']) == 8
    assert value['scientific_authority'] is False and value['application_terminal'] is False
    assert value['primary_type'] == 'ValueError'
    writer.failed = True
    assert writer.errors.record('CLOSE', OSError('secondary close failure'))


def test_error_channel_and_close_population_finite(tmp_path):
    writer, _ = saved(tmp_path)
    for _ in range(owner.MAX_ERRORS):
        writer.errors.record('EXPECTED_INJECTION', ValueError('expected'))
    with pytest.raises(ValueError, match='exhausted'):
        writer.errors.record('FIFTH', RuntimeError('expected fifth refusal'))
    closed = []
    class Resource:
        def __init__(self, name, fail):
            self.name, self.fail = name, fail
        def close(self):
            closed.append(self.name)
            if self.fail:
                raise OSError('expected ' + self.name)
    errors = owner.close_all([(name, Resource(name, name != 'second'))
                              for name in ('first', 'second', 'third')])
    assert closed == ['first', 'second', 'third']
    assert [name for name, _ in errors] == ['first', 'third']


def test_typed_runtime_binding_does_not_accept_bool_as_int(tmp_path):
    writer, plan = saved(tmp_path)
    foreign = binding()
    foreign['runtime']['version'] = [3, 14, 7.0]
    with pytest.raises(ValueError):
        owner.hydrate(writer.directory, plan.envelope, foreign)


@pytest.mark.parametrize('compact', (False, True))
def test_real_status_head_commit_readonly_reopen_and_incomplete_tail_failclosed(tmp_path, compact):
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    from ops_sim.v5.lifecycle_compact import PublicationProfile
    policy = LifecycleStreamPolicy()
    profile = PublicationProfile() if compact else None
    value = job()
    expected_binding = owner.make_binding(value, '6' * 64,
        None if profile is None else profile.identity, '7' * 64)
    plan = owner.preflight(value, expected_binding)
    writer = owner.Publisher(tmp_path / 'real-status', expected_binding, policy, profile=profile)
    writer.publish(plan)
    writer.close()
    before = {p.relative_to(writer.directory).as_posix(): p.read_bytes()
              for p in writer.directory.rglob('*') if p.is_file()}
    envelope, proof = owner.read_envelope(writer.directory, expected_binding, policy, profile=profile)
    assert proof['sequence'] == 1
    assert owner.hydrate(writer.directory, envelope, expected_binding) == plan.job
    after = {p.relative_to(writer.directory).as_posix(): p.read_bytes()
             for p in writer.directory.rglob('*') if p.is_file()}
    assert after == before
    with (writer.directory / 'head' / 'heads.bin').open('ab') as stream:
        stream.write(b'expected injected incomplete head')
    with pytest.raises(ValueError, match='incomplete/uncertain'):
        owner.read_envelope(writer.directory, expected_binding, policy, profile=profile)
