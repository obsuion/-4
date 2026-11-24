"""PILOT wrapper-only stop DATA and pre-launch publication, no mission run."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from hashlib import sha256
from threading import RLock

import pytest

from ops_sim.v5 import lifecycle_pilot_stop as owner
from ops_sim.v5 import lifetime_execution_authority as authority
from ops_sim.v5.context import SimulationContext
from ops_sim.v5.data_delivery import DownlinkTransferProgress, GroundDataDeliveryState
from ops_sim.v5.ids import AcquisitionDataRecordId
from ops_sim.v5.lifecycle_application import LifecycleStore
from ops_sim.v5.lifecycle_backend import BackendContext
from ops_sim.v5.lifecycle_contract import LifecycleRoot
from ops_sim.v5.lifecycle_orbit import LifecycleOrbitProvider
from ops_sim.v5.lifecycle_physics import (
    LifecyclePhysicalState, LifecycleActionOutcome, PendingLifecycleAction,
)
from ops_sim.v5.lifecycle_state import LifecycleState
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
from ops_sim.v5.long_mission import LongMissionAction


JID = '1' * 32
ROOT = 'a' * 64
INPUT = 'b' * 64
SOURCE = 'c' * 64


def minimal_root():
    # Pure typed shell: tests exercise only the explicitly read fields, not
    # initial simulation/orbit/physical owner construction or a lifecycle step.
    root = object.__new__(LifecycleRoot)
    object.__setattr__(root, '_identity', ROOT)
    return root


def contract():
    return dict(format='TEST_ALREADY_ADMITTED_EXECUTION_CONTRACT',
                root_identity=ROOT, input_sha256=INPUT,
                source_manifest_sha256=SOURCE)


def rule_value(request_sha='d' * 64, threshold=6000):
    value = dict(format=owner.FORMAT, kind=owner.KIND, job_id=JID,
                 root_identity=ROOT, input_sha256=INPUT, request_sha256=request_sha,
                 execution_contract_sha256=sha256(owner._canonical(contract())).hexdigest(),
                 source_manifest_sha256=SOURCE, minimum_partial_bits=threshold,
                 scope=owner.SCOPE)
    value['identity'] = sha256(owner._canonical(value)).hexdigest()
    return value


def rehash(value):
    value['identity'] = sha256(owner._canonical({k: v for k, v in value.items() if k != 'identity'})).hexdigest()
    return value


def authority_value(c):
    value = dict(format=authority.FORMAT, mode=authority.PILOT,
        binding=dict(root_identity=ROOT, input_sha256=INPUT,
            source_manifest_sha256=SOURCE,
            runtime=dict(python='test', platform='test', executable='test', interpreter_sha256='e' * 64),
            execution_contract_sha256=sha256(owner._canonical(c)).hexdigest(),
            policy_identity='f' * 64, backend_binding=authority.backend_binding(),
            domain_identity='9' * 64, original_anchor_seconds=0, duration_seconds=600),
        acceptance=None,
        pilot_limits=dict(duration_seconds=authority.PILOT_SECONDS,
            primary_segments=authority.PILOT_PRIMARY_SEGMENTS,
            diagnostic_slots=authority.PILOT_DIAGNOSTIC_SLOTS,
            hard_seconds=authority.PILOT_HARD_SECONDS))
    value['identity'] = authority.digest(value)
    return value


@pytest.fixture
def directory(tmp_path, monkeypatch):
    # The common authority and source gates are unit stubs. They must be
    # invoked before writes. Production never accepts these incomplete shells.
    import ops_sim.v5.lifetime_portable as portable
    seen = []
    monkeypatch.setattr(portable, 'admit_execution_contract_data_v2',
                        lambda c: seen.append(('contract_data_admission', deepcopy(c))) or c)
    store = object.__new__(LifecycleStore)
    store.directory = tmp_path / 'store'
    store.lock = RLock()
    store.runner_policy = object.__new__(LifetimeCampaignPolicyV2)
    store.root_input = minimal_root()
    jobdir = store.directory / 'jobs' / JID
    jobdir.mkdir(parents=True)
    request = dict(format='TEST_REQUEST', job_id=JID, intent={'mode': 'MAIN'},
        root_identity=ROOT, source_identity='source', runtime={'test': 'runtime'},
        input_sha256=INPUT, resume=None)
    raw = owner._canonical(request)
    (jobdir / 'request.json').write_bytes(raw)
    job = dict(request, status='QUEUED', launch=None, result=None, ownership_valid=None)
    store.job = lambda jid: deepcopy(job)
    store._pinned = lambda: seen.append(('pinned', None))
    store._parent_codec_charge = lambda jid, n: seen.append(('codec_charge', n))
    store._parent_charge = lambda jid, n: seen.append(('byte_charge', n))
    c = contract()
    auth = authority_value(c)
    (store.directory / 'execution-authority.json').write_bytes(owner._canonical(auth))
    def gate(s):
        assert s is store
        seen.append(('full_common_gate', None))
        return deepcopy(auth)
    monkeypatch.setattr(authority, 'admit_store_execution', gate)
    import ops_sim.v5.portable_job as jobs
    def worker_contract(path, source, *, job_id, request_sha256):
        assert path == store.directory and job_id == JID
        assert request_sha256 == sha256(raw).hexdigest()
        seen.append(('full_source_request_admission', None))
        return deepcopy(c)
    monkeypatch.setattr(jobs, 'worker_contract', worker_contract)
    return store, jobdir, raw, job, c, auth, seen


def state(bits=(7712.,), *, threshold=6000):
    rule = owner._rule(rule_value(threshold=threshold))
    root = minimal_root()
    model = object()
    backend = object.__new__(BackendContext)
    backend.root, backend.model, backend.source_binding = root, model, SOURCE
    provider = object.__new__(LifecycleOrbitProvider)
    provider.role = 'ACTUAL'
    context = object.__new__(SimulationContext)
    context.simulation_time_seconds = 100
    context.ground_data_delivery_state = GroundDataDeliveryState(tuple(
        DownlinkTransferProgress(AcquisitionDataRecordId('record-' + str(i)), value)
        for i, value in enumerate(bits)), ())
    action = LongMissionAction('pilot-contact', 'CONTACT', 'station', duration_seconds=60)
    pending = PendingLifecycleAction(action, 90, 150, None)
    outcome = object.__new__(LifecycleActionOutcome)
    for name, value in dict(action_id=action.action_id, kind='CONTACT', status='partial',
                            start_seconds=99, end_seconds=100).items():
        object.__setattr__(outcome, name, value)
    physical = object.__new__(LifecyclePhysicalState)
    physical.context, physical.backend_context = context, backend
    physical.nominal_provider, physical.pending = provider, pending
    selected = object.__new__(LifecycleState)
    selected.root, selected.root_identity, selected.model = root, ROOT, model
    selected.physical, selected.backend_context = physical, backend
    selected.actual_provider, selected.transition_count = provider, 1
    selected.status, selected.last_outcome = 'ACTIVE', outcome
    return rule, selected


def test_rule_is_strict_immutable_data_with_no_arbitrary_predicate():
    rule = owner._rule(rule_value())
    assert rule.kind == owner.KIND and rule.minimum_partial_bits == 6000
    with pytest.raises(FrozenInstanceError):
        rule.minimum_partial_bits = 1
    changed = rule_value()
    changed['callable'] = 'arbitrary-code'
    with pytest.raises(ValueError, match='exact schema'):
        owner._rule(changed)
    with pytest.raises(ValueError, match='duplicate key'):
        owner._parse(b'{"kind":1,"kind":2}')


@pytest.mark.parametrize('threshold', [True, False, 0, -1, 6000., '6000', 2**53, None])
def test_threshold_requires_finite_exact_author_integer(threshold):
    with pytest.raises(ValueError, match='bounded integer'):
        owner._rule(rule_value(threshold=threshold))


@pytest.mark.parametrize('field,value', [
    ('kind', 'ARBITRARY_PREDICATE'), ('format', 'LEGACY'), ('scope', 'NUMERICAL_CUT'),
    ('job_id', 'x' * 32), ('source_manifest_sha256', 'G' * 64),
    ('minimum_partial_bits', 1),
])
def test_unbound_or_foreign_rule_cannot_silently_change(field, value):
    changed = rule_value()
    changed[field] = value
    with pytest.raises(ValueError):
        owner._rule(changed)


def test_arm_runs_full_permission_source_gates_before_exclusive_publication(directory):
    store, jobdir, raw, job, c, auth, seen = directory
    result = owner.arm(store, JID, 6000)
    captured = (jobdir / owner.FILENAME).read_bytes()
    assert result['sha256'] == sha256(captured).hexdigest()
    assert result['bytes'] == len(captured) <= owner.MAX_BYTES
    assert result['numerical_policy_changed'] is False
    assert captured == owner._canonical(result['rule'])
    assert (jobdir / 'request.json').read_bytes() == raw
    assert [name for name, _ in seen][:3] == ['full_common_gate', 'pinned', 'full_source_request_admission']
    assert [name for name, _ in seen][-2:] == ['codec_charge', 'byte_charge']
    assert result['rule']['execution_contract_sha256'] == sha256(owner._canonical(c)).hexdigest()
    # Do not rerun/replace an existing immutable sidecar, even if equal.
    with pytest.raises(FileExistsError):
        owner.arm(store, JID, 6000)
    assert (jobdir / owner.FILENAME).read_bytes() == captured


@pytest.mark.parametrize('change', ['running', 'launch', 'result', 'owned', 'launch_marker'])
def test_cannot_arm_after_launch_or_status_change(directory, change):
    store, jobdir, raw, job, c, auth, seen = directory
    if change == 'running':
        job['status'] = 'RUNNING'
    elif change == 'launch':
        job['launch'] = {'started': True}
    elif change == 'result':
        job['result'] = {'returned': True}
    elif change == 'owned':
        job['ownership_valid'] = True
    else:
        (jobdir / 'parent-launch-authority.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='QUEUED'):
        owner.arm(store, JID, 6000)
    assert not (jobdir / owner.FILENAME).exists()
    assert not any('charge' in name for name, _ in seen)


def test_common_gate_failure_is_retained_without_stop_write(directory, monkeypatch):
    store, jobdir, raw, job, c, auth, seen = directory
    def failed(_):
        raise ValueError('synthetic missing source authority')
    monkeypatch.setattr(authority, 'admit_store_execution', failed)
    with pytest.raises(ValueError, match='missing source authority'):
        owner.arm(store, JID, 6000)
    assert not (jobdir / owner.FILENAME).exists() and seen == []


def test_only_v2_pilot_may_arm_no_legacy_or_long(directory, monkeypatch):
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy
    store, jobdir, raw, job, c, auth, seen = directory
    store.runner_policy = object.__new__(LifetimeCampaignPolicy)
    with pytest.raises(ValueError, match='V2'):
        owner.arm(store, JID, 6000)
    store.runner_policy = object.__new__(LifetimeCampaignPolicyV2)
    monkeypatch.setattr(authority, 'admit_store_execution', lambda _: {'mode': authority.LONG})
    with pytest.raises(ValueError, match='PILOT'):
        owner.arm(store, JID, 6000)
    assert not (jobdir / owner.FILENAME).exists()


def test_stop_output_charge_failure_never_publishes_or_refunds(directory):
    store, jobdir, raw, job, c, auth, seen = directory
    def exhausted(jid, n):
        seen.append(('failed_byte_charge', n))
        raise ValueError('synthetic prospective output cap')
    store._parent_charge = exhausted
    with pytest.raises(ValueError, match='prospective output cap'):
        owner.arm(store, JID, 6000)
    assert [name for name, _ in seen][-2:] == ['codec_charge', 'failed_byte_charge']
    assert not (jobdir / owner.FILENAME).exists()


def test_admit_saved_rule_exact_request_source_and_full_contract(directory):
    store, jobdir, raw, job, c, auth, seen = directory
    assert owner.admit_rule(store.directory, JID, sha256(raw).hexdigest(), c, store.root_input) is None
    saved = owner.arm(store, JID, 6000)
    admitted = owner.admit_rule(store.directory, JID, sha256(raw).hexdigest(), c, store.root_input)
    assert asdict(admitted) == saved['rule']
    for changed in ({**c, 'source_manifest_sha256': 'f' * 64}, {**c, 'new_contract_field': 'changed'}):
        with pytest.raises(ValueError, match='stale/foreign'):
            owner.admit_rule(store.directory, JID, sha256(raw).hexdigest(), changed, store.root_input)
    with pytest.raises(ValueError, match='stale/foreign'):
        owner.admit_rule(store.directory, JID, 'f' * 64, c, store.root_input)


def test_admit_rejects_raw_drift_or_source_authority_replacement(directory):
    store, jobdir, raw, job, c, auth, seen = directory
    owner.arm(store, JID, 6000)
    path = jobdir / owner.FILENAME
    original = path.read_bytes()
    path.write_bytes(original + b'\n')
    with pytest.raises(ValueError, match='canonical raw'):
        owner.admit_rule(store.directory, JID, sha256(raw).hexdigest(), c, store.root_input)
    path.write_bytes(original)
    changed = deepcopy(auth)
    changed['binding']['source_manifest_sha256'] = 'f' * 64
    changed['identity'] = authority.digest({k: v for k, v in changed.items() if k != 'identity'})
    (store.directory / 'execution-authority.json').write_bytes(owner._canonical(changed))
    with pytest.raises(ValueError, match='same PILOT'):
        owner.admit_rule(store.directory, JID, sha256(raw).hexdigest(), c, store.root_input)


@pytest.mark.parametrize('bits,expected', [((5999.,), False), ((6000.,), True),
    ((7712.,), True), ((3000., 3000.), False), ((), False)])
def test_selected_actual_threshold_is_per_record_and_read_only(bits, expected):
    rule, selected = state(bits)
    before = tuple(selected.physical.context.ground_data_delivery_state.partial_transfers)
    assert owner.matches(rule, selected) is expected
    assert selected.clock == 100 and selected.transition_count == 1
    assert selected.physical.pending.end_seconds == 150
    assert selected.physical.context.ground_data_delivery_state.partial_transfers == before
    if expected:
        receipt = owner.trigger_receipt(rule, selected)
        assert receipt['clock_seconds'] == 100 and receipt['transition_count'] == 1
        assert receipt['rule'] == asdict(rule) and receipt['numerical_policy_changed'] is False
        assert receipt['rule_sha256'] == sha256(owner._canonical(asdict(rule))).hexdigest()
    else:
        with pytest.raises(ValueError, match='has not matched'):
            owner.trigger_receipt(rule, selected)


@pytest.mark.parametrize('change', ['no_step', 'finished', 'no_pending', 'not_contact'])
def test_no_match_before_committed_step_or_after_contact_completion(change):
    rule, selected = state()
    if change == 'no_step':
        selected.transition_count = 0
    elif change == 'finished':
        selected.status = 'COMPLETED'
    elif change == 'no_pending':
        selected.physical.pending = None
    else:
        action = LongMissionAction('pilot-point', 'POINT', 'station')
        selected.physical.pending = replace(selected.physical.pending, action=action)
    assert owner.matches(rule, selected) is False


@pytest.mark.parametrize('change', ['forecast', 'foreign_source', 'foreign_root', 'wrong_end',
    'zero_duration', 'completed_outcome', 'foreign_action', 'stale_pending'])
def test_forecast_trial_stale_and_foreign_data_do_not_trigger(change):
    rule, selected = state()
    if change == 'forecast':
        selected.actual_provider.role = 'FORECAST'
    elif change == 'foreign_source':
        selected.backend_context.source_binding = 'f' * 64
    elif change == 'foreign_root':
        selected.root_identity = 'f' * 64
    elif change == 'wrong_end':
        object.__setattr__(selected.last_outcome, 'end_seconds', 99)
    elif change == 'zero_duration':
        object.__setattr__(selected.last_outcome, 'start_seconds', 100)
    elif change == 'completed_outcome':
        object.__setattr__(selected.last_outcome, 'status', 'completed')
    elif change == 'foreign_action':
        object.__setattr__(selected.last_outcome, 'action_id', 'another-contact')
    else:
        selected.physical.pending = replace(selected.physical.pending, end_seconds=100)
    with pytest.raises(ValueError):
        owner.matches(rule, selected)


@pytest.mark.parametrize('bits', [True, 6000, float('nan'), float('inf'), -1., 6000.5])
def test_actual_partial_bits_reject_hostile_or_noninteger_data(bits):
    rule, selected = state()
    progress = selected.physical.context.ground_data_delivery_state.partial_transfers[0]
    object.__setattr__(progress, 'transmitted_equivalent_bits', bits)
    with pytest.raises(ValueError, match='integer-valued partial bits'):
        owner.matches(rule, selected)


def test_mutating_rule_cannot_keep_an_old_identity():
    rule, selected = state()
    object.__setattr__(rule, 'minimum_partial_bits', 1)
    with pytest.raises(ValueError, match='immutable content'):
        owner.matches(rule, selected)
