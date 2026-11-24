"""Profile authority/legacy absence and immutable science root boundaries."""
from dataclasses import asdict,replace
from copy import deepcopy
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_application import (LifecycleStore,make_intent,validate_intent,_profile,requested_lifecycle_root)
from ops_sim.v5.lifecycle_compact import PublicationProfile,INTENT,STORE
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
from ops_sim.v5.lifecycle_runner_policy import LifecycleRunnerStorePolicy

def root():
    return requested_lifecycle_root(make_inputs(),7200,{}, {},'REDUCED_ASSUMED_ANNUAL_V1',output_data={},
        service_policy='B55_CONSTRUCTION_RECOVERY_POLICY_V1',energy_attitude_policy='B56_ONBOARD_PREVENTIVE_SOLAR_ATTITUDE_V1')

def test_profile_changes_store_intent_not_root_or_initial_science(tmp_path):
    r=root();before=dumps_root(r)
    a=LifecycleStore(tmp_path/'raw',r,create=True,runner_policy=LifecycleRunnerStorePolicy())
    b=LifecycleStore(tmp_path/'compact',r,create=True,runner_policy=LifecycleRunnerStorePolicy(),publication_profile=PublicationProfile())
    assert a.path('input.json').read_bytes()==b.path('input.json').read_bytes()==before
    assert b.meta['format']==STORE and a.meta['format']!=STORE
    intent=make_intent(r.identity,key='a'*32,execution_seconds=240,execution_budget=ExecutionBudget(240,210,30),publication_profile=b.publication_profile)
    assert intent['format']==INTENT and _profile(intent)==b.publication_profile
    job,new=b.prepare_job(intent);assert new and job['intent']==intent
    assert b.prepare_job(intent)[1] is False
    a.close_publications();b.close_publications()

@pytest.mark.parametrize('change',['profile','identity','extra','type','root'])
def test_intent_strict_binding(tmp_path,change):
    r=root();s=LifecycleStore(tmp_path/'s',r,create=True,publication_profile=PublicationProfile())
    i=make_intent(r.identity,key='a'*32,publication_profile=PublicationProfile())
    if change=='profile':i['publication_profile']['compression_level']=9
    elif change=='identity':i['publication_profile_identity']='f'*64
    elif change=='extra':i['other']=True
    elif change=='type':i['publication_profile']['maximum_frame_records']=True
    else:i['root_identity']='f'*64
    with pytest.raises((TypeError,ValueError)):s.prepare_job(i)
    s.close_publications()

def test_legacy_raw_cannot_silently_acquire_profile(tmp_path):
    r=root();s=LifecycleStore(tmp_path/'raw',r,create=True)
    with pytest.raises(ValueError):s.prepare_job(make_intent(r.identity,publication_profile=PublicationProfile()))

def test_profile_bound_raw_diagnostic_is_explicit():
    i=make_intent('f'*64,profile_bound=True)
    assert i['format']==INTENT and _profile(i) is None and i['publication_profile_identity'] is None

def test_new_controller_exact_source_and_five_primary_cap(tmp_path):
    from m8_compact_chain_cli import trusted_worker_binding,EXPECTED_WORKER_MEMBERS,create_for_store
    r=root();s=LifecycleStore(tmp_path/'s',r,create=True,runner_policy=LifecycleRunnerStorePolicy(),publication_profile=PublicationProfile())
    assert set(trusted_worker_binding()['source_sha256'])==set(EXPECTED_WORKER_MEMBERS)
    with pytest.raises(ValueError):create_for_store(s,'c'*32,ExecutionBudget(240,210,30),6)
    c=create_for_store(s,'c'*32,ExecutionBudget(240,210,30),5)
    assert c.plan['publication_profile_identity']==s.publication_profile.identity
    assert c.snapshot()['state']['state']=='READY_INITIAL'
    assert not s.jobs()

@pytest.mark.parametrize('compact',[False,True])
def test_real_worker_terminal_frontiers_and_exact_settled_receipt(tmp_path,compact):
    import json
    import ops_sim.v5.lifecycle_application as app
    from ops_sim.v5.project_store import file_sha
    r=replace(root(),duration_seconds=120)
    s=LifecycleStore(tmp_path/'actual',r,create=True,publication_profile=PublicationProfile() if compact else None)
    intent=make_intent(r.identity,key='d'*32,execution_seconds=240,execution_budget=ExecutionBudget(240,210,30),publication_profile=s.publication_profile,profile_bound=True)
    job,_=s.prepare_job(intent);directory=s.path('jobs',job['job_id'])
    # Real worker callable in the test child; no claim of private-Job dispatch.
    app.execute_worker(s.directory,job['job_id'],file_sha(directory/'request.json'))
    terminal=json.loads((directory/'terminal.json').read_bytes())
    assert terminal['clock']==248 and terminal['status']=='COMPLETE'
    receipt=app._settled_publication_work(directory,r,job)
    assert receipt['stream_codec_reserved_units']>0 if compact else receipt['stream_codec_reserved_units']==0
    app._verify_checkpoint_streams(directory,terminal['checkpoint'],r,reserve=lambda n:None)
    page_job=deepcopy(job);page_job.update(status='COMPLETED',ownership_valid=True,result=terminal)
    s.update_job(page_job)
    page=s.stream_page(job['job_id'],'events',limit=2)
    assert page['records'] and page['total_records']==terminal['events_count']
    s.close_publications()

@pytest.mark.parametrize('intent',[None,{'format':'unknown'},{'format':True}])
def test_legacy_fallback_does_not_downgrade_unknown_intent(intent):
    from ops_sim.v5.lifecycle_application import _job_profile
    with pytest.raises((TypeError,ValueError)):_job_profile(dict(job_id='1'*32,root_identity='f'*64,intent=intent))
