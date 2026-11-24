"""B63 parent settlement regression with fake owned handles, no model steps."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from ops_sim.v5 import lifecycle_application as owner


JID = '1' * 32


class FaultStore:
    def __init__(self, directory, *, refuse=False):
        self.directory = directory
        directory.mkdir()
        self.source_identity = '2' * 64
        self.runner_policy = None
        self.meta = dict(root_identity='3' * 64, source_identity=self.source_identity)
        self._status_writers = {}
        self.refuse = refuse
        self.value = dict(job_id=JID, status='RUNNING', launch=None,
                          ownership_valid=None, reason=None, result=None, publication_sequence=4)
        self.errors = []
        self.close_called = False

    def path(self, *parts):
        return self.directory.joinpath(*parts)

    def job(self, jid):
        assert jid == JID
        return deepcopy(self.value)

    def update_job(self, value):
        if self.refuse:
            raise OSError('expected injected status publication refusal')
        self.value = deepcopy(value)

    def parent_error(self, jid, stage, primary, **kwargs):
        assert jid == JID
        self.errors.append((stage, primary, kwargs))
        return dict(path='independent-error', bytes=1, sha256='0' * 64)

    def close_publications(self):
        self.close_called = True


def armed(tmp_path, *, valid=False, refuse=False):
    store = FaultStore(tmp_path / 'fault-store', refuse=refuse)
    runner = owner.LifecycleRunner(store)
    runner._claim_dispatch()
    runner.active = JID
    runner._last_job_id = JID
    runner.owned_authority = dict(job_id=JID, dispatch_token=deepcopy(runner.lease),
        launch_attempted=True, handle=object(), cleanup=dict(owned_job_empty=valid),
        ownership_valid=valid, application_settled=False)
    def fail(_):
        raise RuntimeError('expected original parent application failure')
    runner._execute = fail
    return store, runner


def test_launch_null_does_not_fabricate_owned_cleanup(tmp_path):
    store, runner = armed(tmp_path, valid=False)
    runner._run(dict(job_id=JID))
    assert store.value['launch'] is None
    assert store.value['status'] == 'UNKNOWN' and store.value['ownership_valid'] is False
    assert runner.active == JID and runner.lease is not None
    assert store.path('dispatch-owner.json').exists()
    assert runner.application_quarantined


def test_real_cleanup_pass_is_separate_from_failed_application_settlement(tmp_path):
    store, runner = armed(tmp_path, valid=True, refuse=True)
    original = deepcopy(store.value)
    runner._run(dict(job_id=JID))
    assert store.value == original and store.value['status'] == 'RUNNING'
    assert runner.active is None and runner.lease is None
    assert not store.path('dispatch-owner.json').exists()
    assert store.path('dispatch-quarantine.json').exists()
    assert runner.owned_authority['ownership_valid'] is True
    assert runner.owned_authority['application_settled'] is False
    assert store.errors[0][0] == 'PARENT_APPLICATION_FAILURE'
    assert isinstance(store.errors[0][1], RuntimeError)
    assert isinstance(store.errors[0][2]['secondary'][0], OSError)
    with pytest.raises(ValueError, match='quarantined'):
        runner._claim_dispatch()
    with pytest.raises(RuntimeError, match='application outcome quarantined'):
        runner.close()
    assert store.close_called


def test_failed_writer_is_not_reused_for_secondary_parent_error(tmp_path):
    store, runner = armed(tmp_path, valid=True)
    store._status_writers[JID] = SimpleNamespace(failed=True)
    runner._run(dict(job_id=JID))
    assert store.value['status'] == 'RUNNING'
    assert 'failed status writer quarantined' in str(store.errors[0][2]['secondary'][0])
    assert store.errors[0][0] == 'PARENT_APPLICATION_FAILURE'


def test_post_commit_parent_error_never_rewrites_durable_terminal(tmp_path):
    store, runner = armed(tmp_path, valid=True)
    store.value.update(status='COMPLETED', ownership_valid=True, reason='TARGET')
    before = deepcopy(store.value)
    runner.owned_authority['application_settled'] = True
    runner._run(dict(job_id=JID))
    assert store.value == before
    assert store.errors[0][0] == 'AFTER_COMMITTED_TERMINAL_PARENT_ERROR'
    assert runner.application_quarantined


@pytest.mark.parametrize('field', ('owned_job_empty', 'root_signaled', 'root_status_captured',
                                 'handles_closed', 'cleanup_within_two_seconds'))
def test_cleanup_evidence_requires_exact_true_flags(field):
    receipt = dict(owned_job_empty=True, root_signaled=True, root_status_captured=True,
        handles_closed=True, cleanup_within_two_seconds=True, errors=[], root_exit_code=0)
    assert owner._valid_owned_cleanup(receipt)
    receipt[field] = 1
    assert not owner._valid_owned_cleanup(receipt)


@pytest.mark.parametrize('mutation', (
    lambda receipt:receipt.pop('root_reaped'),
    lambda receipt:receipt.update(root_reaped=False),
    lambda receipt:receipt.update(root_reaped=1),
    lambda receipt:receipt.pop('cleanup_deadline_monotonic'),
    lambda receipt:receipt.update(cleanup_wall_seconds=1.5,cleanup_deadline_monotonic=101.0),
    lambda receipt:receipt.update(cleanup_within_deadline=False),
    lambda receipt:receipt.update(cleanup_started_monotonic=float('nan')),
    lambda receipt:receipt.update(cleanup_wall_seconds=True),
))
def test_v2_cleanup_requires_reaped_root_and_absolute_deadline(mutation):
    receipt=dict(owned_job_empty=True,root_signaled=True,root_status_captured=True,
        handles_closed=True,cleanup_within_two_seconds=True,errors=[],root_exit_code=0,
        root_reaped=True,cleanup_started_monotonic=100.0,cleanup_wall_seconds=.5,
        cleanup_deadline_monotonic=102.0,cleanup_within_deadline=True)
    assert owner._valid_owned_cleanup(receipt,strict=True)
    mutation(receipt)
    assert not owner._valid_owned_cleanup(receipt,strict=True)


def test_foreign_dispatch_token_never_released(tmp_path):
    store, runner = armed(tmp_path, valid=True, refuse=True)
    foreign = dict(runner.lease, owner='foreign')
    store.path('dispatch-owner.json').unlink()
    owner._write_new(store.path('dispatch-owner.json'), foreign)
    runner._run(dict(job_id=JID))
    assert owner._read(store.path('dispatch-owner.json')) == foreign
    assert runner.active == JID and runner.lease is not None
    assert any(stage == 'MATCHING_TOKEN_RELEASE' for stage, _, _ in store.errors)


def test_best_effort_close_does_not_skip_publications_after_stop_failure(tmp_path):
    store, runner = armed(tmp_path, valid=False)
    class Thread:
        def is_alive(self):
            return True
        def join(self, timeout):
            assert timeout >= 5
    runner.thread = Thread()
    def stop(_):
        raise OSError('expected stop publication failure')
    runner.stop = stop
    with pytest.raises(RuntimeError) as caught:
        runner.close()
    assert store.close_called and runner.stop_event.is_set()
    assert len(caught.value.close_failures) == 2
    assert 'expected stop publication failure' in str(caught.value.close_failures[0])
    assert 'owned shutdown unresolved' in str(caught.value.close_failures[1])


def test_publication_close_attempts_every_writer_and_catalog(tmp_path):
    closed = []
    class Resource:
        def __init__(self, name, failure):
            self.name, self.failure = name, failure
            self.head = SimpleNamespace(closed=False)
        def close(self):
            closed.append(self.name)
            self.head.closed = True
            if self.failure:
                raise OSError('expected ' + self.name)
    store = object.__new__(owner.LifecycleStore)
    store._status_writers = dict(first=Resource('first', True), second=Resource('second', False))
    store._catalogs = dict(third=Resource('third', True), fourth=Resource('fourth', False))
    with pytest.raises(RuntimeError) as caught:
        store.close_publications()
    assert closed == ['first', 'second', 'third', 'fourth']
    assert [name for name, _ in caught.value.close_failures] == ['status:first', 'catalog:third']


def legacy_store(tmp_path):
    from examples.m5_command_mission_demo import make_inputs
    from ops_sim.v5.lifecycle_contract import LifecycleRoot
    root = LifecycleRoot(make_inputs(wire='weakness'), 600)
    return owner.LifecycleStore(tmp_path / 'legacy-application', root, create=True)


def test_failed_status_write_does_not_advance_caller_or_cache_sequence(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)
    value, _ = store.prepare_job(owner.make_intent(store.root_input.identity, key='9' * 32))
    before = deepcopy(value)
    original = owner._write_new
    def refuse(path, *args, **kwargs):
        if Path(path).parent.name == 'status':
            raise OSError('expected injected durable status write')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(owner, '_write_new', refuse)
    value.update(status='REFUSED', ownership_valid=True)
    with pytest.raises(OSError, match='expected injected'):
        store.update_job(value)
    assert value['publication_sequence'] == before['publication_sequence']
    assert store.job(value['job_id']) == before


def test_after_commit_callback_error_keeps_committed_application_outcome(tmp_path):
    store = legacy_store(tmp_path)
    class Owned:
        def __init__(self, command, source, env, out, err):
            self.pid = 424242
            self.assigned_before_resume = True
            self.closed = False
        def state(self):
            return dict(job_active_PIDs=[self.pid], job_active_count=0)
        def poll(self):
            return 0
        def reap(self, **kwargs):
            self.closed = True
            return dict(owned_job_empty=True, root_signaled=True, root_status_captured=True,
                handles_closed=True, errors=[], cleanup_within_two_seconds=True, root_exit_code=0)
    def callback(_):
        raise ValueError('expected on_finish callback failure')
    runner = owner.LifecycleRunner(store, job_factory=Owned, on_finish=callback)
    value = runner.submit(owner.make_intent(store.root_input.identity, key='a' * 32))
    runner.thread.join(5)
    settled = store.job(value['job_id'])
    assert settled['status'] == 'INCOMPLETE' and settled['reason'] == 'NO_VALID_TERMINAL_PUBLICATION'
    assert settled['ownership_valid'] is True and 'parent_failure' not in settled
    assert runner.active is None and runner.lease is None and not runner.application_quarantined
    assert runner.parent_errors[0]['stage'] == 'AFTER_COMMITTED_TERMINAL_CALLBACK'
    runner.close()


def test_v2_listing_uses_only_envelopes_not_hydration(tmp_path, monkeypatch):
    from ops_sim.v5 import lifetime_status
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    value = dict(format='B59_FINITE_OWNED_LIFECYCLE_JOB_V1', job_id=JID,
        intent=dict(root_identity='2' * 64, maximum_output_bytes=16 * 2 ** 20),
        root_identity='2' * 64, source_identity='4' * 64, runtime=dict(version=[3, 14]),
        input_sha256='5' * 64, resume=None, publication_sequence=0, status='QUEUED',
        reason=None, progress=None, checkpoints=[], result=None, launch=None,
        ownership_valid=None, created_utc='now', worker_artifact_bytes=None)
    bound = lifetime_status.make_binding(value, '6' * 64, None, '7' * 64)
    plan = lifetime_status.preflight(value, bound)
    store = object.__new__(owner.LifecycleStore)
    store.directory = tmp_path / 'index-store'
    (store.directory / 'jobs' / JID).mkdir(parents=True)
    store.lock = threading.RLock()
    store.runner_policy = LifetimeCampaignPolicyV2()
    store.maximum_jobs = store.runner_policy.maximum_jobs
    store.maximum_reserved_job_output_bytes = store.runner_policy.maximum_reserved_job_output_bytes
    store.root_input = SimpleNamespace(output_policy=LifecycleStreamPolicy())
    store.publication_profile = None
    store._status_binding = lambda jid: bound
    store._status_read_charge = lambda units: None
    def no_hydration(*args, **kwargs):
        raise AssertionError('listing hydrated historical job')
    store.job = no_hydration
    monkeypatch.setattr(lifetime_status, 'hydrate', no_hydration)
    monkeypatch.setattr(lifetime_status, 'read_envelope', lambda *a, **k:
        (plan.envelope, dict(read_validation_reserved_units=65536)))
    rows = store.jobs()
    assert len(rows) == 1 and rows[0]['storage_view'] == lifetime_status.INDEX


def test_v2_idempotent_reconcile_returns_full_job_not_index(monkeypatch):
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    store=object.__new__(owner.LifecycleStore);store.runner_policy=LifetimeCampaignPolicyV2()
    intent={'idempotency_key':'a'*32}
    compact=dict(job_id=JID,intent=intent,storage_view='B63_COMPACT_JOB_INDEX_V1',result={'clock':374})
    full=dict(job_id=JID,intent=intent,result={'clock':374,'full_report':'retained scientific result'})
    store.jobs=lambda:[compact];store.job=lambda jid:deepcopy(full)
    monkeypatch.setattr(owner,'validate_intent',lambda value:value)
    assert store.reconcile(intent)==full
    assert 'storage_view'not in store.reconcile(intent)


def request_store(tmp_path):
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    store=object.__new__(owner.LifecycleStore);store.directory=tmp_path/'request-store'
    store.lock=threading.RLock();store.runner_policy=LifetimeCampaignPolicyV2()
    store._cache={};store._status_writers={}
    request=dict(format='B59_FINITE_OWNED_LIFECYCLE_JOB_V1',job_id=JID,
        intent=dict(root_identity='2'*64,idempotency_key='3'*32,execution_seconds=240),
        root_identity='2'*64,source_identity='4'*64,runtime={'version':[3,14]},input_sha256='5'*64,resume=None)
    owner._write_new(store.path('jobs',JID,'request.json'),request)
    return store,request


@pytest.mark.parametrize('field',('format','job_id','intent','root_identity','source_identity','runtime','input_sha256','resume'))
def test_v2_full_job_cannot_change_any_immutable_request_field(tmp_path,field):
    store,request=request_store(tmp_path);value=deepcopy(request)
    value.update(publication_sequence=0,progress={'mutable':'allowed'},result=None)
    store._admit_request_job(value,JID)
    if field=='intent':value[field]['execution_seconds']=1200
    elif field=='runtime':value[field]['version']=[3,14,1]
    elif field=='resume':value[field]={'parent_job_id':'f'*32,'checkpoint':{'clock':200}}
    else:value[field]='foreign'
    with pytest.raises(ValueError,match='immutable request disagreement'):store._admit_request_job(value,JID)


def test_v2_request_drift_rejected_before_preflight_writer_or_sequence(tmp_path):
    store,request=request_store(tmp_path);value=deepcopy(request)
    value.update(publication_sequence=0,status='QUEUED',reason=None,progress=None,
        checkpoints=[],result=None,launch=None,ownership_valid=None,created_utc='now',worker_artifact_bytes=None)
    value['intent']['execution_seconds']=1200
    with pytest.raises(ValueError,match='immutable request disagreement'):store.update_job(value)
    assert value['publication_sequence']==0 and store._cache=={} and store._status_writers=={}
    assert not store.path('jobs',JID,'status63').exists()


def test_v2_hydrated_request_drift_rejected_before_cache(tmp_path,monkeypatch):
    from ops_sim.v5 import lifetime_status
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    store,request=request_store(tmp_path)
    store.root_input=SimpleNamespace(output_policy=LifecycleStreamPolicy())
    store.publication_profile=None;store._status_read_charge=lambda units:None
    value=deepcopy(request);value['intent']['execution_seconds']=1200
    monkeypatch.setattr(lifetime_status,'read_envelope',lambda *a,**k:({}, {'sequence':1}))
    monkeypatch.setattr(lifetime_status,'hydrate',lambda *a,**k:value)
    with pytest.raises(ValueError,match='immutable request disagreement'):store.job(JID)
    assert store._cache=={}


def test_v2_backend_receipt_must_be_admitted_and_match_saved_raw_bytes(tmp_path,monkeypatch):
    from ops_sim.v5 import lifecycle_backend,portable_job
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    directory=tmp_path/'backend-receipt';(directory/'jobs'/JID).mkdir(parents=True)
    calls=[];charges=[];contract={'backend_binding':{'selection':'PREPARED_NATIVE'}}
    store=SimpleNamespace(directory=directory,runner_policy=LifetimeCampaignPolicyV2(),
        path=lambda *parts:directory.joinpath(*parts),_parent_codec_charge=lambda jid,units:charges.append(units))
    monkeypatch.setattr(portable_job,'worker_contract',lambda *a,**k:contract)
    def admit(value,bound):
        assert bound is contract
        if type(value)is not dict or value.get('selection')!='PREPARED_NATIVE':raise ValueError('expected invalid backend receipt schema/binding')
        calls.append(deepcopy(value))
    monkeypatch.setattr(lifecycle_backend,'admit_backend_receipt',admit)
    value={'selection':'PREPARED_NATIVE','source_binding':'a'*64};path=store.path('jobs',JID,'backend-execution.json')
    path.write_bytes(owner._bytes(value))
    owner._admit_backend_terminal(store,{'job_id':JID},{'backend_execution':value})
    assert calls==[value]and len(charges)==1
    path.write_bytes(owner._bytes(dict(value,source_binding='f'*64)))
    with pytest.raises(ValueError,match='saved receipt exact raw binding'):owner._admit_backend_terminal(store,{'job_id':JID},{'backend_execution':value})
    with pytest.raises(ValueError,match='invalid backend receipt schema'):owner._admit_backend_terminal(store,{'job_id':JID},{'backend_execution':None})
    with pytest.raises(ValueError,match='invalid backend receipt schema'):owner._admit_backend_terminal(store,{'job_id':JID},{'backend_execution':{'selection':'REFERENCE'}})
