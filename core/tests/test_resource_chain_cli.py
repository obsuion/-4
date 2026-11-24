"""Pure synthetic controller tests; no scientific starts/steps or subprocesses."""
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
import m8_resource_chain_cli as m
from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
from ops_sim.v5.lifecycle_chain import make_plan

class Store:
    def __init__(self,path):
        self.directory=path;self.source_identity=m.project_source_identity();self.runtime=m.runtime_identity()
        self.meta=dict(root_identity='0'*64,input_sha256='1'*64,source_identity=self.source_identity,runtime=self.runtime)
        self.root_input=NS(start_seconds=0,end_seconds=100,policy=NS(max_task_output_bytes=512*2**20),output_policy=None)
        self.runner_policy=True;self.maximum_jobs=8;self.maximum_reserved_job_output_bytes=1536*2**20
        self.jobs_by_id={};self.charged=[]
    def path(self,*parts):return self.directory.joinpath(*parts)
    def job(self,jid):return deepcopy(self.jobs_by_id[jid])
    def reconcile(self,intent):return next((deepcopy(j) for j in self.jobs_by_id.values() if j['intent']==intent),None)
    def _reserve_saved_read(self,jid,n):self.charged.append((jid,n))

def controller(tmp_path):
    store=Store(tmp_path/'store');original=make_plan(store,chain_id='a'*32,execution_budget=ExecutionBudget(180,10,170),maximum_primary_segments=3,maximum_observed_seconds=1000)
    c=object.__new__(m.ResourceChain);c.store=store;c.chain_id='b'*32;c.folder=tmp_path/'controller'
    import threading
    c.lock=threading.RLock();c.runner=NS(active=None,thread=None)
    c.plan=dict(original,plan_identity='c'*64);c._source_admit=lambda:None
    first=dict(ordinal=1,job_id='1'*32,intent_sha256='2'*64,checkpoint_sha256='3'*64,terminal_sha256='4'*64,clock=10,observed_seconds=1.,resource_cause='OUTPUT')
    c._append(dict(state='READY_ADOPTED_OUTPUT',command_keys=[],segments=[first],pending_intent=None,reason=None,failed_attempt=None,observed_seconds=1.,estimate=None),initial=True)
    return c,first

def test_serial_output_prefix_then_target_without_relabel_or_extra_dispatch(tmp_path,monkeypatch):
    c,first=controller(tmp_path);calls=[]
    c.store.jobs_by_id[first['job_id']]=dict(job_id=first['job_id'],intent={})
    class Runner:
        active=None;thread=None
        def submit(self,intent):
            calls.append(deepcopy(intent));jid=str(len(calls)+1)*32
            job=dict(job_id=jid,intent=intent);c.store.jobs_by_id[jid]=job;return job
    c.runner=Runner()
    def validate(job,n):
        if n==1:return first
        return dict(ordinal=n,job_id=job['job_id'],intent_sha256=m.digest(job['intent']),checkpoint_sha256=str(n+2)*64,terminal_sha256=str(n+3)*64,clock=60 if n==2 else 100,observed_seconds=1.,resource_cause='OUTPUT' if n==2 else 'TARGET')
    monkeypatch.setattr(c,'validate_job',validate)
    out=c.run('d'*32)
    assert out['state']['state']=='COMPLETED' and len(calls)==2 and out['state']['observed_seconds']==3.
    assert calls[0]['parent_job_id']==first['job_id'] and calls[1]['parent_job_id']=='2'*32
    c.run('d'*32);c.run('e'*32);assert len(calls)==2
    assert not (c.folder/'owner.json').exists()

def test_reopen_snapshot_and_duplicate_are_read_only_and_pause_is_explicit(tmp_path):
    c,_=controller(tmp_path);before={p.relative_to(c.folder):p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    c.snapshot();assert before=={p.relative_to(c.folder):p.read_bytes() for p in c.folder.rglob('*') if p.is_file()}
    c.stop();assert c._paused(c.snapshot()['state'])

@pytest.mark.parametrize('kind',('UNKNOWN','forced','timeout','ownership','no_terminal','other_admission'))
def test_unknown_or_unapproved_job_is_never_authority(tmp_path,kind):
    c,_=controller(tmp_path)
    job=dict(status='INCOMPLETE',ownership_valid=True,launch=dict(forced_interruption=False,timeout=False,unexpected=None),result=None)
    if kind=='UNKNOWN':job['status']='UNKNOWN';job['ownership_valid']=False
    if kind=='forced':job['launch']['forced_interruption']=True
    if kind=='timeout':job['launch']['timeout']=True
    if kind=='ownership':job['ownership_valid']=False
    with pytest.raises((ValueError,KeyError)):c.validate_job(job,2)

def test_output_cut_delegates_to_all_unchanged_proofs_without_mutating_job(tmp_path,monkeypatch):
    c,_=controller(tmp_path);s=c.store;jid='f'*32;folder=s.path('jobs',jid);folder.mkdir(parents=True)
    cp=dict(kind='FINAL',file='cp.json',clock=60,bindings={'test':'binding'},sha256='a'*64)
    result=dict(format='test',application_status='INCOMPLETE_APPLICATION_ADMISSION',reason=m.OUTPUT_REASON,status='ACTIVE',clock=60,checkpoint=cp)
    (folder/'cp.json').write_bytes(b'{}');(folder/'terminal.json').write_bytes(m.raw(result))
    job=dict(job_id=jid,intent={'test':'intent'},status='INCOMPLETE',ownership_valid=True,launch=dict(forced_interruption=False,timeout=False,unexpected=None,observed_envelope_seconds=2.),result=result,checkpoints=[cp],source_identity=s.source_identity,runtime=s.runtime,root_identity=s.meta['root_identity'])
    seen=[]
    monkeypatch.setattr(m,'_admit_execution_terminal',lambda j,r:seen.append('terminal'))
    monkeypatch.setattr(m,'make_bindings',lambda root,t:{'test':'binding'})
    monkeypatch.setattr(m,'_settled_publication_work',lambda *a:seen.append('settlement'))
    monkeypatch.setattr(m,'_admit_publication',lambda *a,**k:seen.append('sidecar'))
    monkeypatch.setattr(m,'admit_checkpoint',lambda *a,**k:seen.append('native'))
    def streams(*args,reserve):seen.append('streams');reserve(7)
    monkeypatch.setattr(m,'_verify_checkpoint_streams',streams)
    before=deepcopy(job);segment=c.validate_job(job,2)
    assert segment['resource_cause']=='OUTPUT' and job==before
    assert seen==['terminal','settlement','sidecar','native','streams'] and s.charged==[(jid,7)]
    for reason in ('MEMORY_TARGET_BOUNDARY','OTHER',None):
        bad=deepcopy(job);bad['result']['reason']=reason
        with pytest.raises(ValueError,match='not an approved'):c.validate_job(bad,2)

def test_corrupt_journal_and_stale_parent_block_before_dispatch(tmp_path,monkeypatch):
    c,first=controller(tmp_path);c.store.jobs_by_id[first['job_id']]=dict(job_id=first['job_id'],intent={})
    monkeypatch.setattr(c,'validate_job',lambda j,n:dict(first,clock=11))
    with pytest.raises(ValueError,match='stale'):c.run('d'*32)
    assert c.snapshot()['state']['state']=='BLOCKED'
    path=c.folder/'states/0001.json';v=m._read(path);v['sequence']=2;path.write_bytes(m.raw(v))
    with pytest.raises(ValueError,match='journal'):c.snapshot()

def test_unpublished_state_and_existing_owner_are_not_repaired(tmp_path):
    c,_=controller(tmp_path);p=c.folder/'states/0002.pending';p.write_bytes(b'partial')
    with pytest.raises(ValueError,match='unpublished'):c.run('d'*32)
    assert p.read_bytes()==b'partial'

def test_resource_plan_rejects_unknown_fields_and_cap_changes(tmp_path):
    s=Store(tmp_path);b=ExecutionBudget(180,10,170)
    original=make_plan(s,chain_id='a'*32,execution_budget=b,maximum_primary_segments=3,maximum_observed_seconds=1000)
    binding=dict(revision='test-frozen659',source_root=str(tmp_path),source_sha256={f'f{n}.py':'a'*64 for n in range(659)},runtime={},frozen_utc='2026-10-17T00:00:00+00:00')
    p=dict(format=m.PLAN,policy=m.POLICY,chain_id='b'*32,controller_sha256=m.controller_sha(),worker_source_identity=s.source_identity,worker_manifest_sha256=m.digest(binding),root_identity=s.meta['root_identity'],input_sha256=s.meta['input_sha256'],runtime=s.runtime,original_plan_sha256=m.digest(original),original_chain_id=original['chain_id'],adopted_parent_job_id='c'*32,adopted_snapshot_sha256='d'*64,**{k:original[k] for k in ('maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes','reserved_diagnostic_slots','execution_budget','execution_budget_identity')})
    p['plan_identity']=m.digest(p);assert m.admit_plan(p,s,binding,original)==p
    for changes in (dict(cached_trust=True),dict(maximum_output_bytes=256*2**20),dict(maximum_primary_segments=True),dict(worker_source_identity='e'*64),dict(controller_sha256='f'*64)):
        bad=deepcopy(p);bad.update(changes);bad['plan_identity']=m.digest({k:v for k,v in bad.items() if k!='plan_identity'})
        with pytest.raises((ValueError,TypeError)):m.admit_plan(bad,s,binding,original)


def test_new_initial_chain_uses_original_authority_then_same_policy_main(tmp_path,monkeypatch):
    c,_=controller(tmp_path);c.folder=tmp_path/'new-initial';calls=[]
    c._append(dict(state='READY_INITIAL',command_keys=[],segments=[],pending_intent=None,reason='NEW_INITIAL_AUTHORITY_NO_BORROWED_STATE',failed_attempt=None,observed_seconds=0.,estimate=None),initial=True)
    class Runner:
        active=None;thread=None
        def submit(self,intent):
            calls.append(deepcopy(intent));jid=str(len(calls))*32
            job=dict(job_id=jid,intent=intent);c.store.jobs_by_id[jid]=job;return job
    c.runner=Runner()
    def validate(job,n):return dict(ordinal=n,job_id=job['job_id'],intent_sha256=m.digest(job['intent']),checkpoint_sha256=str(n+2)*64,terminal_sha256=str(n+3)*64,clock=60 if n==1 else 100,observed_seconds=1.,resource_cause='OUTPUT' if n==1 else 'TARGET')
    monkeypatch.setattr(c,'validate_job',validate)
    assert c.run('d'*32)['state']['state']=='COMPLETED' and len(calls)==2
    assert calls[0]['parent_job_id'] is None and calls[0]['snapshot_sha256'] is None
    assert calls[1]['parent_job_id']=='1'*32 and calls[0]['execution_budget']==calls[1]['execution_budget']
