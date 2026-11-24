"""Durable finite chain negative and idempotency checks with fake dispatch."""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot
from ops_sim.v5.lifecycle_application import LifecycleStore
from ops_sim.v5.lifecycle_runner_policy import LifecycleRunnerStorePolicy
from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
from ops_sim.v5.lifecycle_chain import LifecycleChain,make_plan,admit_plan,encoded

def setup(tmp_path):
    store=LifecycleStore(tmp_path/'store',LifecycleRoot(make_inputs(wire='weakness'),600),create=True,runner_policy=LifecycleRunnerStorePolicy())
    p=make_plan(store,chain_id='a'*32,execution_budget=ExecutionBudget(180,10,170),maximum_observed_seconds=1000)
    return store,p,LifecycleChain(store,p['chain_id'],plan=p)

def test_reopen_never_dispatches_and_plan_is_strict(tmp_path):
    store,p,c=setup(tmp_path);before={x.relative_to(c.folder):x.read_bytes() for x in c.folder.rglob('*') if x.is_file()}
    reopened=LifecycleChain(store,p['chain_id']);assert reopened.snapshot()['state']['state']=='READY'
    assert before=={x.relative_to(c.folder):x.read_bytes() for x in c.folder.rglob('*') if x.is_file()}
    assert store.jobs()==[]
    for mutation in (dict(cached_trust=True),dict(maximum_primary_segments=True),dict(reserved_diagnostic_slots=0),dict(source_identity='f'*64),dict(maximum_output_bytes=256*2**20)):
        bad=deepcopy(p);bad.update(mutation)
        with pytest.raises((ValueError,TypeError)):admit_plan(bad,store)

def test_pause_reopen_requires_explicit_continue_and_duplicate_has_no_dispatch(tmp_path,monkeypatch):
    store,p,c=setup(tmp_path);c.stop()
    reopened=LifecycleChain(store,p['chain_id']);assert reopened._paused(reopened.snapshot()['state'])
    calls=[]
    def dispatch(intent):calls.append(intent);raise RuntimeError('expected fake dispatch refusal')
    monkeypatch.setattr(reopened.runner,'submit',dispatch)
    with pytest.raises(RuntimeError,match='expected fake'):reopened.run('b'*32)
    assert len(calls)==1 and reopened.snapshot()['state']['state']=='BLOCKED'
    reopened.run('b'*32);reopened.run('c'*32);assert len(calls)==1
    assert not (c.folder/'writer-owner.json').exists()

def test_duplicate_owned_writer_and_changed_plan_are_refused(tmp_path):
    store,p,c=setup(tmp_path);(c.folder/'writer-owner.json').write_text('{}')
    with pytest.raises(ValueError,match='claimed'):c.run('b'*32)
    assert store.jobs()==[]
    (c.folder/'plan.json').write_bytes(encoded(dict(p,maximum_primary_segments=5)))
    with pytest.raises(ValueError):c.snapshot()

def test_corrupt_journal_and_stale_pending_intent_are_rejected(tmp_path):
    store,p,c=setup(tmp_path);path=c.folder/'states/0001.json';v=json.loads(path.read_bytes());v['pending_intent']=c._intent(1,None);v['pending_intent']['maximum_output_bytes']+=1
    path.write_bytes(encoded(v))
    with pytest.raises(ValueError,match='intent drift'):c.snapshot()

@pytest.mark.parametrize('status,launch',[('UNKNOWN',{}),('INCOMPLETE',dict(forced_interruption=True)),('CANCELLED',dict(forced_interruption=True)),('PROCESS_FAILED',dict(forced_interruption=False,unexpected=None,timeout=False))])
def test_unknown_forced_failed_parent_never_becomes_checkpoint_authority(tmp_path,status,launch):
    store,p,c=setup(tmp_path)
    with pytest.raises((ValueError,KeyError)):
        c._settled_segment(dict(status=status,ownership_valid=True,launch=launch,result=None),1)
    assert store.jobs()==[]

def test_serial_auto_continue_only_after_validated_settlement(tmp_path,monkeypatch):
    store,p,c=setup(tmp_path);calls=[];jobs={}
    class Runner:
        active=None;thread=None
        def submit(self,intent):
            calls.append(intent);jid=f'{len(calls):032x}';job=dict(job_id=jid,intent=intent,result=dict(application_status='INCOMPLETE_BUDGET_STOP' if len(calls)==1 else 'COMPLETED_WINDOW'))
            jobs[jid]=job;return job
    c.runner=Runner();monkeypatch.setattr(store,'job',lambda jid:deepcopy(jobs[jid]))
    def settle(job,ordinal):
        return dict(ordinal=ordinal,job_id=job['job_id'],intent_sha256=sha256(encoded(job['intent'])).hexdigest(),checkpoint_sha256=f'{ordinal:064x}',clock=200 if ordinal==1 else store.root_input.end_seconds,observed_seconds=1.)
    monkeypatch.setattr(c,'_settled_segment',settle)
    assert c.run('b'*32)['state']['state']=='COMPLETED'
    assert len(calls)==2 and calls[1]['parent_job_id']==f'{1:032x}' and calls[1]['snapshot_sha256']==f'{1:064x}'
    c.run('b'*32);assert len(calls)==2


def test_reader_never_sees_incomplete_new_state_publication(tmp_path,monkeypatch):
    import ops_sim.v5.lifecycle_chain as module
    store,p,c=setup(tmp_path);old=c.snapshot()['state'];rename=module.os.rename;observed=[]
    def publish(pending,target):
        assert pending.suffix=='.pending' and pending.is_file() and not target.exists()
        observed.append(c.snapshot()['state'])
        return rename(pending,target)
    monkeypatch.setattr(module.os,'rename',publish)
    c._save(old,reason='ATOMIC_NEW_FILENAME')
    assert observed==[old] and c.snapshot()['state']['sequence']==2
    assert not list((c.folder/'states').glob('*.pending'))


def test_new_chain_cannot_silently_retry_original_in_populated_store(tmp_path):
    from ops_sim.v5.lifecycle_application import make_intent
    store,p,c=setup(tmp_path)
    store.prepare_job(make_intent(store.root_input.identity,key='f'*32))
    p=make_plan(store,chain_id='b'*32,execution_budget=ExecutionBudget(180,10,170),maximum_observed_seconds=1000)
    with pytest.raises(ValueError,match='new empty store'):LifecycleChain(store,p['chain_id'],plan=p)


def test_user_stop_during_dispatch_waits_for_owned_handle_and_prevents_continue(tmp_path,monkeypatch):
    import threading
    store,p,c=setup(tmp_path);entered=threading.Event();stopped=threading.Event();jobs={};errors=[]
    class Wait:
        def join(self,timeout):assert stopped.wait(2)
        def is_alive(self):return not stopped.is_set()
    class Runner:
        active=None;thread=Wait()
        def submit(self,intent):
            self.active='d'*32
            job=dict(job_id=self.active,intent=intent,result=dict(application_status='INCOMPLETE_STOP'))
            jobs[self.active]=job;entered.set();return job
        def stop(self,jid):
            assert jid==self.active
            stopped.set();self.active=None
    c.runner=Runner();monkeypatch.setattr(store,'job',lambda jid:deepcopy(jobs[jid]))
    monkeypatch.setattr(c,'_settled_segment',lambda job,n:dict(ordinal=n,job_id=job['job_id'],intent_sha256=sha256(encoded(job['intent'])).hexdigest(),checkpoint_sha256='e'*64,clock=200,observed_seconds=1.))
    def execute():
        try:c.run('b'*32)
        except BaseException as error:errors.append(error)
    thread=threading.Thread(target=execute);thread.start();assert entered.wait(2)
    c.stop();thread.join(3)
    assert not thread.is_alive() and not errors and len(jobs)==1
    assert c.snapshot()['state']['state']=='USER_PAUSED'
