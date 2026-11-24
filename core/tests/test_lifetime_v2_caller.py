"""Metadata-only caller tests; these fixtures grant no execution authority.

The public execution gate and native checkpoint admission are explicit spies.
No runner, physical owner, LONG authority, or numerical endpoint is exercised.
Real intents, role admission, status storage and checkpoint catalogues remain.
"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
import threading

import pytest

from ops_sim.v5 import lifecycle_application as owner
from ops_sim.v5.battery_terminal import bind_terminal,make_terminal
from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy,LifetimeCampaignPolicyV2

ROOT='2'*64
SOURCE='4'*64


def metadata_store(tmp_path,monkeypatch,policy=None):
    """Real store methods, with visibly non-executable metadata admissions."""
    from ops_sim.v5 import lifecycle_checkpoint,lifetime_execution_authority
    store=object.__new__(owner.LifecycleStore)
    store.directory=tmp_path/'metadata-store';store.directory.mkdir()
    store.lock=threading.RLock();store._cache={};store._status_writers={};store._catalogs={}
    store._parent_work={};store._status_read_work=0;store._lifetime_retirement_failed=False
    store.runner_policy=LifetimeCampaignPolicyV2() if policy is None else policy
    p=store.runner_policy
    store.maximum_jobs=p.maximum_jobs;store.maximum_lineage_jobs=p.maximum_lineage_jobs
    store.maximum_reserved_job_output_bytes=p.maximum_reserved_job_output_bytes
    store.publication_profile=None
    store.meta=dict(root_identity=ROOT,source_identity=SOURCE,runtime={'fixture':'METADATA_ONLY'},input_sha256='5'*64)
    store.root_input=SimpleNamespace(identity=ROOT,end_seconds=10000,method=owner.METHOD,
        output_policy=LifecycleStreamPolicy(),policy=SimpleNamespace(max_task_output_bytes=2**30,max_control_units=2**50))
    calls=[]
    store._pinned=lambda:calls.append('pinned-metadata-spy')
    monkeypatch.setattr(lifetime_execution_authority,'admit_public_execution',lambda s:calls.append('execution-admission-spy-NOT-AUTHORITY'))
    monkeypatch.setattr(lifecycle_checkpoint,'make_bindings',lambda root,clock:{'metadata_clock':clock})
    def checkpoint_spy(raw,root,**kw):
        assert raw.startswith(b'METADATA-NOT-NATIVE:')
        assert sha256(raw).hexdigest()==kw['expected_sha256']
        calls.append('native-checkpoint-admission-spy-NOT-AUTHORITY')
    monkeypatch.setattr(lifecycle_checkpoint,'admit_checkpoint',checkpoint_spy)
    monkeypatch.setattr(owner,'_admit_publication',lambda *a,**k:calls.append('publication-metadata-spy'))
    monkeypatch.setattr(owner,'_verify_checkpoint_streams',lambda *a,**k:calls.append('stream-metadata-spy'))
    return store,calls


def intent_for(store,number,*,parent=None,checkpoint=None,mode='MAIN',window=None,**changes):
    p=store.runner_policy
    arguments=dict(key=f'{number:032x}',execution_seconds=p.hard_seconds,
        maximum_output_bytes=p.maximum_output_bytes,
        execution_budget=ExecutionBudget(p.hard_seconds,p.soft_seconds,p.finalization_seconds))
    if parent is not None:
        arguments.update(parent_job_id=parent['job_id'],snapshot_sha256=(parent['result']['checkpoint'] if checkpoint is None else checkpoint)['sha256'],mode=mode,window_end_seconds=window)
    arguments.update(changes)
    return owner.make_intent(ROOT,**arguments)


def settle_metadata(store,job,clock,*,observed=1.,extra_checkpoint=False,terminal_kind='RESOURCE_TIME',working_clock=None):
    """Persist synthetic metadata only, never manufacture a native graph."""
    value=store.job(job['job_id']);checkpoints=[]
    for n,kind in enumerate(('WORKING','FINAL') if extra_checkpoint else ('FINAL',),1):
        content=f'METADATA-NOT-NATIVE:{job["job_id"]}:{kind}'.encode()
        cp_clock=working_clock if kind=='WORKING' and working_clock is not None else clock
        cp=dict(file=f'checkpoint-{n:08d}.json',sha256=sha256(content).hexdigest(),bytes=len(content),clock=cp_clock,
            bindings={'metadata_clock':cp_clock},kind=kind)
        owner._write_new(store.path('jobs',job['job_id'],cp['file']),content)
        store.checkpoint_catalog(job['job_id']).append(cp);checkpoints.append(cp)
    cp=checkpoints[-1]
    terminal=make_terminal(terminal_kind,'METADATA_PAID_PREFIX','METADATA_ONLY','metadata_fixture',clock)
    target=value['intent']['window_end_seconds'] or store.root_input.end_seconds
    result=dict(checkpoint=cp,clock=clock,actual_end_seconds=clock,target_seconds=target,
        application_status='COMPLETED_WINDOW' if terminal_kind=='TARGET' else 'INCOMPLETE_BUDGET_STOP',status='COMPLETE' if terminal_kind=='TARGET' else 'ACTIVE',reason=terminal['code'])
    result['typed_terminal']=bind_terminal(terminal,value,cp)
    value.update(status='COMPLETED' if terminal_kind=='TARGET' else 'INCOMPLETE',reason=terminal['code'],result=result,checkpoints=checkpoints,
        launch={'observed_envelope_seconds':observed},ownership_valid=True)
    store.update_job(value);store.retire_lifetime_job(value['job_id'])
    return store.job(value['job_id'])


@pytest.mark.parametrize('policy_type',(LifetimeCampaignPolicy,LifetimeCampaignPolicyV2))
def test_actual_caller_uses_lifetime_policy_for_both_exact_versions(tmp_path,monkeypatch,policy_type):
    from ops_sim.v5 import lifetime_campaign
    store,calls=metadata_store(tmp_path,monkeypatch,policy_type());seen=[]
    original=lifetime_campaign.admit_lifetime_role_population
    def admitted(policy,*args):
        seen.append(type(policy));return original(policy,*args)
    monkeypatch.setattr(lifetime_campaign,'admit_lifetime_role_population',admitted)
    job,new=store.prepare_job(intent_for(store,1))
    assert new and seen==[policy_type]
    assert calls[:2]==['execution-admission-spy-NOT-AUTHORITY','pinned-metadata-spy']
    assert store.reconcile(job['intent'])['job_id']==job['job_id']
    store.close_publications()


def test_actual_v2_caller_admits_ninth_primary_under_declared_4096_policy(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch);parent=None
    for n in range(1,10):
        job,new=store.prepare_job(intent_for(store,n,parent=parent));assert new
        parent=settle_metadata(store,job,128+n)
    assert len(store.jobs())==9 and store.runner_policy.maximum_primary_segments==4096
    assert all(j['ownership_valid'] is True for j in store.jobs())
    store.close_publications()


def test_actual_caller_enforces_declared_two_primary_cap(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch,replace(LifetimeCampaignPolicyV2(),maximum_primary_segments=2))
    first,_=store.prepare_job(intent_for(store,1));first=settle_metadata(store,first,129)
    second,_=store.prepare_job(intent_for(store,2,parent=first));second=settle_metadata(store,second,130)
    with pytest.raises(ValueError,match='role reservation exhausted'):
        store.prepare_job(intent_for(store,3,parent=second))
    assert len(list(store.path('jobs').glob('*/request.json')))==2
    store.close_publications()


@pytest.mark.parametrize('change',('hard','output','budget','identity'))
def test_actual_caller_rejects_nonpolicy_intent_without_creating_request(tmp_path,monkeypatch,change):
    store,_=metadata_store(tmp_path,monkeypatch)
    if change=='hard':value=intent_for(store,1,execution_seconds=899,execution_budget=ExecutionBudget(899,839,60))
    elif change=='output':value=intent_for(store,1,maximum_output_bytes=64*2**20)
    elif change=='budget':value=intent_for(store,1,execution_budget=ExecutionBudget(900,839,61))
    else:value=intent_for(store,1);value['execution_budget_identity']='f'*64
    with pytest.raises(ValueError,match='prospective worker allowance|budget identity'):store.prepare_job(value)
    assert not list(store.path('jobs').glob('*/request.json'))


def test_actual_caller_reserves_next_complete_wall_allowance(tmp_path,monkeypatch):
    policy=replace(LifetimeCampaignPolicyV2(),maximum_observed_primary_seconds=902)
    store,_=metadata_store(tmp_path,monkeypatch,policy)
    first,_=store.prepare_job(intent_for(store,1));first=settle_metadata(store,first,129,observed=1.)
    with pytest.raises(ValueError,match='next-job wall reservation exhausted'):
        store.prepare_job(intent_for(store,2,parent=first))
    assert len(store.jobs())==1
    store.close_publications()


def test_actual_caller_forbids_initial_rewind_old_parent_fork_and_nonfinal_main(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    first,_=store.prepare_job(intent_for(store,1));first=settle_metadata(store,first,129,extra_checkpoint=True)
    with pytest.raises(ValueError,match='latest forward primary'):
        store.prepare_job(intent_for(store,2))
    with pytest.raises(ValueError,match='exact settled FINAL'):
        store.prepare_job(intent_for(store,3,parent=first,checkpoint=first['checkpoints'][0]))
    second,_=store.prepare_job(intent_for(store,4,parent=first));second=settle_metadata(store,second,130)
    with pytest.raises(ValueError,match='latest forward primary'):
        store.prepare_job(intent_for(store,5,parent=first))
    assert len(store.jobs())==2
    store.close_publications()


@pytest.mark.parametrize('policy_type',(LifetimeCampaignPolicy,LifetimeCampaignPolicyV2))
def test_workbench_routes_both_lifetime_versions_to_dedicated_controller(policy_type):
    workspace=object.__new__(owner.LifecycleWorkspace);workspace.lock=threading.RLock()
    workspace.stores={};workspace.runners={};workspace.chains={};workspace.chain_threads={}
    workspace.store=lambda rid:SimpleNamespace(runner_policy=policy_type())
    with pytest.raises(ValueError,match='dedicated'):workspace.chain(ROOT,'a'*32)
    body=dict(root_identity=ROOT,chain_id='b'*32,execution_budget={},maximum_primary_segments=2,
        maximum_output_bytes=128*2**20,maximum_observed_seconds=1804)
    with pytest.raises(ValueError,match='lifetime supervisor'):workspace.create_chain(body)
    assert workspace.runners=={} and workspace.chains=={}
