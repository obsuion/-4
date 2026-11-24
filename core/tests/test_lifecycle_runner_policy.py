"""Finite store admission only; no scientific transition or owned worker.

Added after the B54 test budget was exhausted. These checks are NOT reported
as executed; production acceptance evidence must be attributed separately.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json,zipfile
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot
from ops_sim.v5.lifecycle_application import LifecycleStore,LifecycleWorkspace,make_intent
from ops_sim.v5.lifecycle_runner_policy import (LifecycleRunnerStorePolicy,SEGMENTED,
    STORE_V1,STORE_V2,STORE_FIELDS,admit_runner_store_metadata,requested_runner_policy)


@pytest.fixture(scope='module')
def root():return LifecycleRoot(make_inputs(wire='weakness'),600)


def metadata():
    policy=LifecycleRunnerStorePolicy()
    value={name:None for name in STORE_FIELDS}
    value.update(format=STORE_V2,maximum_jobs=8,runner_policy=asdict(policy),runner_policy_identity=policy.identity)
    return value


def test_exact_policy_identity_and_explicit_selection():
    p=LifecycleRunnerStorePolicy()
    raw=json.dumps(asdict(p),sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')
    assert p.identity==sha256(raw).hexdigest()
    assert admit_runner_store_metadata(metadata())==(p,8,8,1536*2**20)
    assert requested_runner_policy('LEGACY') is None and requested_runner_policy(SEGMENTED)==p
    with pytest.raises(ValueError):requested_runner_policy('eight')
    with pytest.raises(TypeError):requested_runner_policy(True)


@pytest.mark.parametrize('mutation',[
    lambda x:x.update(unbound=True),lambda x:x.pop('runner_policy_identity'),
    lambda x:x.update(format=STORE_V1),lambda x:x.update(maximum_jobs=True),
    lambda x:x.update(runner_policy_identity='0'*64),
    lambda x:x['runner_policy'].update(maximum_jobs=9),
    lambda x:x['runner_policy'].update(maximum_lineage_jobs=4),
    lambda x:x['runner_policy'].update(maximum_reserved_job_output_bytes=2**31),
    lambda x:x['runner_policy'].update(maximum_jobs=8.),
    lambda x:x['runner_policy'].update(unknown=1)])
def test_unknown_mixed_and_mutated_metadata_refused(mutation):
    value=metadata();mutation(value)
    with pytest.raises((TypeError,ValueError)):admit_runner_store_metadata(value)


def settle(store,n,output=128*2**20,status='REFUSED'):
    job,new=store.prepare_job(make_intent(store.root_input.identity,key=f'{n:032x}',maximum_output_bytes=output))
    assert new
    job.update(status=status,ownership_valid=True);store.update_job(job)
    return job


@pytest.mark.parametrize('segmented,limit',[(False,4),(True,8)])
def test_exact_population_failed_jobs_retained_and_duplicate_reconciled(tmp_path,root,segmented,limit):
    policy=LifecycleRunnerStorePolicy() if segmented else None
    store=LifecycleStore(tmp_path/'store',root,create=True,runner_policy=policy)
    jobs=[settle(store,n+1,status='PROCESS_FAILED') for n in range(limit)]
    duplicate,new=store.prepare_job(jobs[-1]['intent']);assert not new and duplicate['job_id']==jobs[-1]['job_id']
    with pytest.raises(ValueError,match='population'):settle(store,100)
    assert len(store.jobs())==limit
    if segmented:
        snapshot=store.snapshot()
        assert snapshot['remaining_job_slots']==0 and snapshot['reserved_job_output_bytes']==limit*128*2**20
    else:assert set(store.meta)==set(STORE_FIELDS) and store.meta['format']==STORE_V1
    reopened=LifecycleStore(store.directory)
    assert reopened.maximum_jobs==limit and reopened.runner_policy==policy


def test_exact_reservation_boundary_no_refund_and_readonly_reopen(tmp_path,root):
    store=LifecycleStore(tmp_path/'store',root,create=True,runner_policy=LifecycleRunnerStorePolicy())
    for n in range(3):settle(store,n+1,512*2**20,status='CANCELLED')
    assert store.snapshot()['remaining_reserved_job_output_bytes']==0
    before={p.relative_to(store.directory).as_posix():p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match='output reservation'):settle(store,4)
    reopened=LifecycleStore(store.directory)
    assert reopened.maximum_reserved_job_output_bytes==1536*2**20
    assert before=={p.relative_to(store.directory).as_posix():p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}


def test_no_legacy_migration_or_duplicate_root_policy_substitution(tmp_path,root):
    workspace=LifecycleWorkspace(tmp_path/'workspace');workspace.create(root)
    before=(workspace.store(root.identity).directory/'store.json').read_bytes()
    with pytest.raises(ValueError,match='another runner policy'):workspace.create(root,runner_policy=LifecycleRunnerStorePolicy())
    with pytest.raises(ValueError,match='not migrated'):LifecycleStore(workspace.store(root.identity).directory,runner_policy=LifecycleRunnerStorePolicy())
    assert (workspace.store(root.identity).directory/'store.json').read_bytes()==before


@pytest.mark.parametrize('extended',[False,True])
def test_http_explicit_selector_accepts_both_known_bodies_before_project_lookup(tmp_path,extended):
    workspace=LifecycleWorkspace(tmp_path/'workspace')
    body=dict(project_id='p',revision='r',duration_seconds=600,policy={},scenario={},sun_mode='REDUCED_ASSUMED_ANNUAL_V1',runner_store_policy=SEGMENTED)
    if extended:body.update(study_preset='LEGACY',ageing_multiplier=1.,output_policy=None)
    with pytest.raises(ValueError,match='no constructor project authority'):workspace.create_project(body)
    body['unknown']=True
    with pytest.raises(ValueError):workspace.create_project(body)


def test_eight_deep_export_retains_pinned_policy_and_rejects_cycle(tmp_path,root):
    store=LifecycleStore(tmp_path/'store',root,create=True,runner_policy=LifecycleRunnerStorePolicy())
    previous=None
    for n in range(8):
        job=settle(store,n+1)
        if previous is not None:
            job['resume']=dict(parent_job_id=previous['job_id'],checkpoint={'synthetic':'lineage-only-no-scientific-authority'})
            store.update_job(job)
        previous=job
    result=store.export(job['job_id'])
    with zipfile.ZipFile(result['path']) as archive:
        assert archive.testzip() is None
        admitted=admit_runner_store_metadata(json.loads(archive.read('store.json')))
        assert admitted[1:]==(8,8,1536*2**20)
        assert sum(name.endswith('/request.json') for name in archive.namelist())==8
    job['resume']['parent_job_id']=job['job_id'];store.update_job(job)
    with pytest.raises(ValueError,match='cycle'):store.export(job['job_id'])
