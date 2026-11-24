"""Bounded real journal/publication owners; no model transition or child launch."""
from pathlib import Path
from threading import Barrier, Event, RLock, Thread
from types import SimpleNamespace

import pytest

from ops_sim.v5 import lifecycle_application as owner
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy


JID = 'a' * 32


def journal_store(tmp_path):
    # Isolate the real append owner without constructing a scientific root.
    store = object.__new__(owner.LifecycleStore)
    store.lock = RLock()
    store._parent_work = {}
    store.runner_policy = None
    store.root_input = SimpleNamespace(output_policy=LifecycleStreamPolicy(),
        policy=SimpleNamespace(max_control_units=2**40))
    store.path = lambda *parts: tmp_path.joinpath(*parts)
    store.path('jobs', JID).mkdir(parents=True)
    return store


def ledger(store, jid=JID):
    raw = store.path('jobs', jid, 'parent-publication-work.bin').read_bytes()
    assert len(raw) % owner.PARENT_COST.size == 0
    return list(owner.PARENT_COST.iter_unpack(raw))


def run_threads(functions):
    errors = []
    start = Barrier(len(functions) + 1, timeout=5)
    def call(function):
        try:
            start.wait()
            function()
        except BaseException as error:
            errors.append(error)
    threads = [Thread(target=call, args=(function,), daemon=True) for function in functions]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(5)
    assert not any(thread.is_alive() for thread in threads), 'bounded journal writer deadlock'
    return errors


def test_concurrent_real_charge_owner_has_no_lost_updates(tmp_path):
    store = journal_store(tmp_path)
    def writer(n):
        return lambda: [store._parent_charge(JID, n) for _ in range(12)]
    assert not run_threads([writer(n) for n in range(1, 9)])
    rows = ledger(store)
    assert [seq for seq, _ in rows] == list(range(1, 97))
    assert rows[-1][1] == 12 * sum(n + owner.PARENT_COST.size for n in range(1, 9))
    assert all(a[1] < b[1] for a, b in zip(rows, rows[1:]))
    assert store._parent_work[JID] == list(rows[-1])


def test_checkpoint_status_and_stop_share_store_lock_during_append(tmp_path, monkeypatch):
    from examples.m5_command_mission_demo import make_inputs
    from ops_sim.v5.lifecycle_contract import LifecycleRoot
    root = LifecycleRoot(make_inputs(wire='weakness'), 600, output_policy=LifecycleStreamPolicy())
    store = owner.LifecycleStore(tmp_path / 'store', root, create=True)
    job, _ = store.prepare_job(owner.make_intent(root.identity, key='b'*32,
        maximum_output_bytes=256*2**20))
    jid = job['job_id']
    catalog = store.checkpoint_catalog(jid)
    before = ledger(store, jid)
    charges = []
    entered = Event()
    release = Event()
    contenders = [Event(), Event()]
    real_charge = store._parent_charge_locked
    real_fsync = owner._io_fsync
    armed = [True]
    def charged(current_jid, n):
        assert store.lock._is_owned()
        charges.append(n)
        return real_charge(current_jid, n)
    def held_fsync(fd):
        if armed[0]:
            armed[0] = False
            entered.set()
            assert release.wait(5), 'test release deadline'
        return real_fsync(fd)
    monkeypatch.setattr(store, '_parent_charge_locked', charged)
    monkeypatch.setattr(owner, '_io_fsync', held_fsync)
    cp = dict(file='checkpoint-00000001.json', sha256='c'*64, bytes=2,
        clock=128, bindings={}, kind='FINAL', publication={})
    errors = []
    def capture(function):
        try:
            function()
        except BaseException as error:
            errors.append(error)
    first = Thread(target=capture, args=(lambda: catalog.append(cp),), daemon=True)
    first.start()
    assert entered.wait(5)
    runner = object.__new__(owner.LifecycleRunner)
    runner.lock = RLock()
    runner.store = store
    runner.active = jid
    runner.stop_event = Event()
    def status():
        contenders[0].set()
        with store.lock:
            current = store.job(jid)
            current['reason'] = 'BOUNDED_CONCURRENT_METADATA_TEST'
            store.update_job(current)
    def stop():
        contenders[1].set()
        runner.stop(jid)
    rest = [Thread(target=capture, args=(function,), daemon=True) for function in (status, stop)]
    for thread in rest:
        thread.start()
    assert all(event.wait(5) for event in contenders)
    release.set()
    for thread in [first, *rest]:
        thread.join(5)
    assert not any(thread.is_alive() for thread in [first, *rest]), 'store/runner lock deadlock'
    assert not errors
    rows = ledger(store, jid)
    assert [seq for seq, _ in rows] == list(range(1, len(rows)+1))
    assert len(rows) == len(before) + len(charges)
    assert rows[-1][1] == before[-1][1] + sum(n + owner.PARENT_COST.size for n in charges)
    assert all(a[1] < b[1] for a, b in zip(rows, rows[1:]))
    assert runner.stop_event.is_set()
    assert store.path('jobs', jid, 'stop-request.json').exists()
    assert store.find_checkpoint(jid, cp['sha256']) == cp
    store.close_publications()


def test_concurrent_near_limit_admits_only_paid_write(tmp_path):
    store = journal_store(tmp_path)
    policy = store.root_input.output_policy
    allowance = policy.status_total_bytes + 4*policy.max_index_bytes + owner.MAX_METADATA
    charged = 7 + owner.PARENT_COST.size
    path = store.path('jobs', JID, 'parent-publication-work.bin')
    path.write_bytes(owner.PARENT_COST.pack(1, allowance-charged))
    errors = run_threads([lambda: store._parent_charge(JID, 7)] * 4)
    assert len(errors) == 3 and all(isinstance(error, ValueError) for error in errors)
    assert all('allowance' in str(error) for error in errors)
    assert ledger(store) == [(1, allowance-charged), (2, allowance)]


def test_fsync_failure_preserves_charge_and_reloads_actual_full_record(tmp_path, monkeypatch):
    store = journal_store(tmp_path)
    store._parent_charge(JID, 3)
    def fail(fd):
        raise OSError('injected fsync failure')
    with monkeypatch.context() as patch:
        patch.setattr(owner, '_io_fsync', fail)
        with pytest.raises(OSError, match='injected fsync'):
            store._parent_charge(JID, 5)
    assert JID not in store._parent_work
    saved = store.path('jobs', JID, 'parent-publication-work.bin').read_bytes()
    assert ledger(store) == [(1, 19), (2, 40)]
    store._parent_charge(JID, 7)
    assert store.path('jobs', JID, 'parent-publication-work.bin').read_bytes().startswith(saved)
    assert ledger(store) == [(1, 19), (2, 40), (3, 63)]


@pytest.mark.parametrize('fault', ('partial_exception', 'short_write', 'flush'))
def test_failed_append_never_succeeds_or_reuses_cached_tip(tmp_path, monkeypatch, fault):
    store = journal_store(tmp_path)
    store._parent_charge(JID, 3)
    path = store.path('jobs', JID, 'parent-publication-work.bin')
    original_open = Path.open
    class BrokenAppend:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, raw):
            if fault == 'partial_exception':
                self.stream.write(raw[:7])
                self.stream.flush()
                raise OSError('injected partial write')
            if fault == 'short_write':
                self.stream.write(raw[:7])
                self.stream.flush()
                return 7
            return self.stream.write(raw)
        def flush(self):
            self.stream.flush()
            raise OSError('injected flush failure')
        def fileno(self):
            return self.stream.fileno()
    def opened(current, mode='r', *args, **kwargs):
        stream = original_open(current, mode, *args, **kwargs)
        return BrokenAppend(stream) if current == path and mode == 'ab' else stream
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', opened)
        with pytest.raises(OSError):
            store._parent_charge(JID, 5)
    assert JID not in store._parent_work
    saved = path.read_bytes()
    if fault == 'flush':
        assert ledger(store) == [(1, 19), (2, 40)]
        store._parent_charge(JID, 7)
        assert ledger(store) == [(1, 19), (2, 40), (3, 63)]
    else:
        assert len(saved) == owner.PARENT_COST.size + 7
        with pytest.raises(ValueError, match='incomplete parent publication'):
            store._parent_charge(JID, 7)
        assert path.read_bytes() == saved


def test_nested_codec_publication_and_existing_outer_lock_are_reentrant(tmp_path):
    store = journal_store(tmp_path)
    with store.lock:
        store._parent_codec_charge(JID, 21)
        store._parent_charge(JID, 8)
    assert ledger(store) == [(1, 32), (2, 56)]
    assert list(owner.PARENT_COST.iter_unpack(store.path('jobs', JID, 'parent-codec-work.bin').read_bytes())) == [(1, 21)]


@pytest.mark.parametrize('raw', (b'x', owner.PARENT_COST.pack(2, 10),
    owner.PARENT_COST.pack(1, 10) + owner.PARENT_COST.pack(1, 20)))
def test_corrupt_existing_ledger_is_refused_without_rewrite(tmp_path, raw):
    store = journal_store(tmp_path)
    path = store.path('jobs', JID, 'parent-publication-work.bin')
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='ledger|sequence'):
        store._parent_charge(JID, 3)
    assert path.read_bytes() == raw
    assert JID not in store._parent_work


@pytest.mark.parametrize('n', (True, -1, 2**30 + 1, '1'))
def test_existing_charge_input_guard_stays_strict(tmp_path, n):
    store = journal_store(tmp_path)
    with pytest.raises((ValueError, TypeError)):
        store._parent_charge(JID, n)
    assert not store.path('jobs', JID, 'parent-publication-work.bin').exists()


def test_current_producer_population_exactly_covers_frozen_source_and_raw_hashes():
    from hashlib import sha256
    from ops_sim.v5 import lifetime_source
    from ops_sim.v5.portable_job import source_manifest
    source = Path(__file__).resolve().parents[1]
    # The gate's source directory is frozen before launch. This independent
    # file walk includes all files, rather than trusting a filtered manifest.
    actual = {p.relative_to(source).as_posix(): p for p in source.rglob('*') if p.is_file()}
    populations = (lifetime_source.B63_SOURCE_PATHS,
        lifetime_source.B64_SOURCE_PATHS, lifetime_source.B65_SOURCE_PATHS)
    for population in populations:
        assert len(population) == len(set(population)) == 923
        assert set(population) == set(actual)
    manifest = source_manifest(source)
    assert set(manifest) == set(actual)
    for name, path in actual.items():
        raw = path.read_bytes()
        assert manifest[name] == dict(bytes=len(raw), sha256=sha256(raw).hexdigest())
    assert 'tests/test_parent_publication_atomic.py' in manifest


@pytest.mark.parametrize('family', ('v2', 'v3'))
def test_execution_contract_rejects_unknown_member_before_root_or_build(family, monkeypatch):
    from hashlib import sha256
    from ops_sim.v5 import lifetime_portable, lifetime_typed_portable
    from ops_sim.v5.portable_job import source_manifest
    source = Path(__file__).resolve().parents[1]
    manifest = source_manifest(source)
    assert len(manifest) == 923
    unknown = 'tests/UNAPPROVED-PRODUCER-MEMBER.txt'
    assert unknown not in manifest
    manifest[unknown] = dict(bytes=1, sha256=sha256(b'x').hexdigest())
    contract_owner = lifetime_portable if family == 'v2' else lifetime_typed_portable
    monkeypatch.setattr(contract_owner, 'source_manifest', lambda _: manifest)
    # No root/build may be consulted when the exact source population is wrong.
    with pytest.raises(ValueError, match='frozen current producer membership'):
        if family == 'v2':
            contract_owner.execution_contract_v2(None, source, contract_owner.FAST)
        else:
            contract_owner.execution_contract_v3(None, source, contract_owner.FAST,
                backend=contract_owner.NEW_DOMAIN, build=None)
