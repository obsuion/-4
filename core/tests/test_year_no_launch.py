"""Runner-owned pre-thread refusal; no numerical child or fake scientific result."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from ops_sim.v5 import lifecycle_application as app, lifetime_supervisor as sup
from ops_sim.v5 import lifetime_no_launch as nl, lifetime_execution_authority as authority
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,METHOD_NO_LAUNCH,WINDOWS_USER
from ops_sim.v5.lifetime_journal import Journal,encoded

JID='1'*32

class Store:
    def __init__(self,path):
        self.directory=path;path.mkdir(exist_ok=True)
        self.runner_policy=replace(LifetimeCampaignPolicyV2(),method=METHOD_NO_LAUNCH,mode=WINDOWS_USER,
            maximum_primary_segments=8,reserved_diagnostic_slots=2,hard_seconds=60,soft_seconds=30,finalization_seconds=30)
        self.source_identity='2'*64
        self.meta=dict(root_identity='3'*64,source_identity=self.source_identity,input_sha256='4'*64,runtime={'test':'runtime'})
        self.root_input=SimpleNamespace(identity='3'*64,start_seconds=128,end_seconds=728)
        self.publication_profile=None;self.charged=0;self.fail=False;self._last=None
        self.plan={'plan_identity':'5'*64}
        if not self.path('lifetime-plan.json').exists():self.path('lifetime-plan.json').write_bytes(encoded(self.plan))
        self._status_writers={};self._catalogs={}
    def path(self,*parts):return self.directory.joinpath(*parts)
    def _pinned(self):pass
    def _parent_charge(self,jid,n):self.charged+=n
    def prepare_job(self,intent):
        request=dict(format='test',job_id=JID,intent=intent,**self.meta,resume=None)
        folder=self.path('jobs',JID);folder.mkdir(parents=True)
        (folder/'request.json').write_bytes(encoded(request))
        job=dict(**request,status='QUEUED',publication_sequence=0,reason=None,progress=None,checkpoints=[],result=None,
            launch=None,ownership_valid=None,created_utc='test',worker_artifact_bytes=None)
        self.update_job(job);return job,True
    def job(self,jid):return json.loads(self.path('jobs',jid,'test-status.json').read_bytes())
    def jobs(self):return []if not self.path('jobs',JID,'test-status.json').exists()else [self.job(JID)]
    def update_job(self,job):
        if self.fail:raise OSError('expected status publication injection')
        job['publication_sequence']+=1
        self.path('jobs',job['job_id'],'test-status.json').write_bytes(encoded(job))
    def reconcile(self,intent):
        for j in self.jobs():
            if j['intent']==intent:return j
    def close_publications(self):pass
    def parent_error(self,*a,**k):return None


def refused(tmp_path,monkeypatch,callback=None):
    s=Store(tmp_path/'store');monkeypatch.setattr(authority,'admit_public_execution',lambda s:None)
    intent=app.make_intent(s.root_input.identity,key='6'*32)
    Journal(s,s.plan).append('DISPATCH',dict(ordinal=1,intent=intent))
    def refusal(job):raise RuntimeError('expected no launch')
    runner=app.LifecycleRunner(s,on_launch=refusal if callback is None else callback)
    with pytest.raises(RuntimeError,match='expected no launch'):runner.submit(intent)
    return s,runner,nl.validate(s,s.job(JID))


def test_runner_receipt_is_durable_charged_non_scientific(tmp_path,monkeypatch):
    s,r,p=refused(tmp_path,monkeypatch)
    assert r.thread is None and r.active is None and r.lease is None
    assert p['thread_start_attempted']is p['scientific_launch_attempted']is p['scientific_authority']is False
    assert s.charged==nl.RESERVE and not s.path('jobs',JID,'thread-attempt.json').exists()
    j=s.job(JID);assert j['result']is j['launch']is None and j['checkpoints']==[]
    fresh=Store(s.directory);assert nl.validate(fresh,fresh.job(JID))==p


def test_duplicate_reconciliation_and_explicit_new_intent_authority(tmp_path,monkeypatch):
    s,r,p=refused(tmp_path,monkeypatch);charge=s.charged;raw=s.path('jobs',JID,'test-status.json').read_bytes()
    from contextlib import nullcontext
    monkeypatch.setattr(sup,'_store',lambda d:(s,s.plan));monkeypatch.setattr(sup,'_lock',lambda s:nullcontext())
    h=nl.digest(p)
    d=sup.reconcile_no_launch(s.directory,JID,h)
    assert sup.reconcile_no_launch(s.directory,JID,h)==d
    assert len(list(Journal(s,s.plan).records()))==2
    assert s.charged==charge and s.path('jobs',JID,'test-status.json').read_bytes()==raw
    with pytest.raises(ValueError,match='new'):sup.authorize_no_launch_recovery(s.directory,JID,h,new_key='6'*32)
    token=sup.authorize_no_launch_recovery(s.directory,JID,h,new_key='7'*32)
    assert sup.authorize_no_launch_recovery(s.directory,JID,h,new_key='7'*32)==token
    records=list(Journal(s,s.plan).records())
    with pytest.raises(ValueError,match='explicit'):nl.admit_recovery(s,records,None)
    new=app.make_intent(s.root_input.identity,key='7'*32)
    g=nl.admit_recovery(s,records,token,new);assert g['maximum_new_intents']==1
    Journal(s,s.plan).append('DISPATCH',dict(ordinal=2,intent=new,recovery_job_id=JID,recovery_authority=token))
    nl.validate_next_dispatch(s,new)
    assert nl.pending_recovery(s,list(Journal(s,s.plan).records()))=={}
    assert s.charged==charge and s.job(JID)['result']is None
    summary=sup._summary(s,s.plan)
    assert summary['clock']==128 and summary['parent_job_id']is None and summary['no_launch_jobs']==1
    assert summary['primary_jobs']==1 and summary['reserved_unknown_seconds']==62


@pytest.mark.parametrize('mutation',['root','intent','owner','started','launch','status','checkpoint','receipt_hash'])
def test_forged_or_uncertain_receipt_is_fail_closed(tmp_path,monkeypatch,mutation):
    s,r,p=refused(tmp_path,monkeypatch)
    if mutation in ('root','intent','owner','receipt_hash'):
        if mutation=='root':p['boundary']['root_identity']='a'*64
        elif mutation=='intent':p['boundary']['intent']['idempotency_key']='a'*32
        elif mutation=='owner':p['boundary']['owner']['PID']=True
        else:p['boundary']['request_sha256']='a'*64
        s.path('jobs',JID,'no-launch-proof.json').write_bytes(encoded(p))
    elif mutation=='started':s.path('jobs',JID,'thread-attempt.json').write_bytes(b'{}')
    else:
        j=s.job(JID)
        if mutation=='launch':j['launch']={}
        if mutation=='status':j['status']='UNKNOWN'
        if mutation=='checkpoint':j['checkpoints']=[{}]
        s.update_job(j)
    with pytest.raises(ValueError):nl.validate(s,s.job(JID))


def test_unknown_owner_not_adopted(tmp_path,monkeypatch):
    s,r,p=refused(tmp_path,monkeypatch)
    s.path('dispatch-owner.json').write_bytes(encoded(p['boundary']['owner']))
    with pytest.raises(ValueError,match='owner'):nl.validate(s,s.job(JID))


def test_thread_start_exception_is_attempted_unknown_not_no_launch(tmp_path,monkeypatch):
    s=Store(tmp_path/'thread-store');monkeypatch.setattr(authority,'admit_public_execution',lambda s:None)
    intent=app.make_intent(s.root_input.identity,key='8'*32)
    Journal(s,s.plan).append('DISPATCH',dict(ordinal=1,intent=intent))
    def fail(_):raise RuntimeError('expected Thread.start injection')
    monkeypatch.setattr(app.threading.Thread,'start',fail)
    r=app.LifecycleRunner(s)
    with pytest.raises(RuntimeError,match='Thread.start'):r.submit(intent)
    assert s.path('jobs',JID,'thread-attempt.json').is_file()
    assert not s.path('jobs',JID,'no-launch-proof.json').exists()
    assert s.job(JID)['status']=='UNKNOWN' and s.job(JID)['ownership_valid']is False
    assert r.lease is not None and s.path('dispatch-quarantine.json').exists()


def test_failed_receipt_publication_retains_owner_and_charge(tmp_path,monkeypatch):
    s=Store(tmp_path/'failed-store');monkeypatch.setattr(authority,'admit_public_execution',lambda s:None)
    intent=app.make_intent(s.root_input.identity,key='8'*32)
    Journal(s,s.plan).append('DISPATCH',dict(ordinal=1,intent=intent))
    original=nl.publish
    def fail(path,value,cap):
        if Path(path).name=='no-launch-proof.json':raise OSError('expected proof publication failure')
        return original(path,value,cap)
    monkeypatch.setattr(nl,'publish',fail)
    def refused(job):raise RuntimeError('original callback')
    r=app.LifecycleRunner(s,on_launch=refused)
    with pytest.raises(OSError,match='proof publication'):r.submit(intent)
    assert s.charged==nl.RESERVE and r.lease is not None
    assert s.job(JID)['status']=='QUEUED' and s.path('dispatch-quarantine.json').exists()
    assert not s.path('jobs',JID,'no-launch-proof.json').exists()


def test_reentrant_busy_thread_refuses_before_claiming_new_owner(tmp_path,monkeypatch):
    s=Store(tmp_path/'busy-store');monkeypatch.setattr(authority,'admit_public_execution',lambda s:None)
    r=app.LifecycleRunner(s);r.thread=SimpleNamespace(is_alive=lambda:True)
    intent=app.make_intent(s.root_input.identity,key='9'*32)
    with pytest.raises(ValueError,match='thread|worker'):r.submit(intent)
    assert not s.path('dispatch-owner.json').exists()
    assert r.lease is None and s.jobs()==[] and s.charged==0
