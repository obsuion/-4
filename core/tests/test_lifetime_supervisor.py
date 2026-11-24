from types import SimpleNamespace
from pathlib import Path
from dataclasses import replace
import json,pytest
from ops_sim.v5.lifetime_journal import Journal,lease,publish
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy,QUALIFICATION

def fake_store(path):
    return SimpleNamespace(path=lambda *parts:path.joinpath(*parts),runner_policy=LifetimeCampaignPolicy())

def test_durable_journal_hashes_reopen_and_incomplete_publication_refuse(tmp_path):
    store=fake_store(tmp_path);plan={'plan_identity':'a'*64};j=Journal(store,plan)
    j.append('HALT',{'reason':'TEST'});j.append('EXPLICIT_CONTINUE',{'pause':None})
    reopened=Journal(store,plan);assert reopened.sequence==2 and len(list(reopened.records()))==2
    (tmp_path/'lifetime-journal/00000003.pending').write_bytes(b'{')
    with pytest.raises(ValueError,match='incomplete'):Journal(store,plan)

def test_hash_tampering_is_not_reconciled(tmp_path):
    store=fake_store(tmp_path);p={'plan_identity':'a'*64};j=Journal(store,p);j.append('HALT',{'reason':'X'});j.append('HALT',{'reason':'Y'})
    path=tmp_path/'lifetime-journal/00000001.json';path.write_bytes(path.read_bytes().replace(b'"X"',b'"Z"'))
    with pytest.raises(ValueError,match='hash'):Journal(store,p)

def test_os_lock_is_handle_owned_and_read_only_journal_does_not_clear_pause(tmp_path):
    with lease(tmp_path/'lease',windows=True):
        with pytest.raises((OSError,ValueError)):
            with lease(tmp_path/'lease',windows=True):pass
    with lease(tmp_path/'lease',windows=True):pass
    marker=tmp_path/'operator-pause.json';publish(marker,{'plan_identity':'a'*64},16384)
    assert list(Journal(fake_store(tmp_path),{'plan_identity':'a'*64}).records())==[]
    assert marker.exists()

def test_production_cannot_use_local_windows_lock(tmp_path):
    import sys
    from ops_sim.v5.lifetime_supervisor import _lock
    if sys.platform=='win32':
        with pytest.raises(RuntimeError,match='Linux doctor'):_lock(fake_store(tmp_path))


def test_diagnostic_passes_original_horizon_to_real_typed_intent(monkeypatch,tmp_path):
    from contextlib import nullcontext
    from ops_sim.v5 import lifetime_supervisor as supervisor
    from ops_sim.v5 import lifecycle_application as application
    from ops_sim.v5 import lifetime_campaign as campaign
    p=LifetimeCampaignPolicy(mode=QUALIFICATION,maximum_primary_segments=8,reserved_diagnostic_slots=2,hard_seconds=240,soft_seconds=210,finalization_seconds=30)
    store=SimpleNamespace(runner_policy=p,publication_profile=None,root_input=SimpleNamespace(identity='a'*64,end_seconds=7328),
        job=lambda name:{'job_id':name},find_checkpoint=lambda *args:{'clock':369})
    monkeypatch.setattr(supervisor,'_store',lambda directory:(store,{'plan_identity':'b'*64}))
    monkeypatch.setattr(supervisor,'_lock',lambda store:nullcontext())
    monkeypatch.setattr(campaign,'validate_settled_parent',lambda *args:None)
    original=application.make_intent;seen=[]
    class AdmissionOnly(Exception):pass
    def admit_then_stop(*args,**kwargs):
        value=original(*args,**kwargs);seen.append(value);raise AdmissionOnly
    monkeypatch.setattr(application,'make_intent',admit_then_stop)
    with pytest.raises(AdmissionOnly):supervisor.diagnostic(tmp_path,'c'*32,'d'*64,verbose=True)
    assert len(seen)==1 and seen[0]['window_end_seconds']==7328
    assert seen[0]['mode']=='DIAGNOSTIC_VERBOSE' and seen[0]['snapshot_sha256']=='d'*64


def test_common_authority_refusal_precedes_supervisor_lease(monkeypatch,tmp_path):
    from ops_sim.v5 import lifetime_supervisor as supervisor,lifetime_execution_authority as authority,lifetime_journal
    p=replace(LifetimeCampaignPolicy(),mode=QUALIFICATION,maximum_primary_segments=8,reserved_diagnostic_slots=2,hard_seconds=240,soft_seconds=210,finalization_seconds=30)
    calls=[]
    def refuse(store):raise ValueError('expected unqualified long authority')
    monkeypatch.setattr(authority,'admit_store_execution',refuse)
    monkeypatch.setattr(lifetime_journal,'lease',lambda *a,**k:calls.append('lease'))
    with pytest.raises(ValueError,match='unqualified long'):supervisor._lock(SimpleNamespace(runner_policy=p))
    assert calls==[]


def test_v2_prepare_authority_refusal_precedes_pool_or_directory_writes(monkeypatch,tmp_path):
    from ops_sim.v5 import lifetime_supervisor as supervisor,lifetime_execution_authority as authority,lifetime_portable,lifetime_pool,lifecycle_document
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    p=replace(LifetimeCampaignPolicyV2(),mode=QUALIFICATION,maximum_primary_segments=8,reserved_diagnostic_slots=2,hard_seconds=240,soft_seconds=210,finalization_seconds=30)
    original=tmp_path/'input.json';original.write_bytes(b'{}');store=tmp_path/'cohort'/'candidate.store';calls=[]
    monkeypatch.setattr(lifecycle_document,'loads_root',lambda raw:SimpleNamespace(identity='a'*64))
    monkeypatch.setattr(lifetime_portable,'execution_contract_v2',lambda *a,**k:{'source':'frozen'})
    def refuse(*args,**kwargs):raise ValueError('expected genuine execution authority refusal')
    monkeypatch.setattr(authority,'make_authority',refuse)
    monkeypatch.setattr(lifetime_pool,'reserve_v2',lambda *a,**k:calls.append('pool'))
    with pytest.raises(ValueError,match='execution authority refusal'):supervisor.prepare(original,store,p,backend='PREPARED_PYTHON')
    assert calls==[] and not store.parent.exists()


def test_pool_inventory_only_credits_admitted_immutable_names(monkeypatch,tmp_path):
    from hashlib import sha256
    from ops_sim.v5 import lifetime_supervisor as supervisor,portable_job
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    directory=tmp_path/'pilot.store';directory.mkdir();policy=LifetimeCampaignPolicyV2();key='a'*64
    contract={'native_build':None};plan={'execution_contract_sha256':supervisor.digest(contract)}
    names=('input.json','store.json','portable-execution.json','portable-job.json','execution-authority.json','lifetime-plan.json')
    for name in names:(directory/name).write_bytes(supervisor.encoded(plan)if name=='lifetime-plan.json'else b'{}')
    (directory/'foreign.bin').write_bytes(b'foreign bytes are not ownership authority')
    (tmp_path/'foreign-pool.bin').write_bytes(b'also not credit')
    (tmp_path/'pilot.store.initial.zip').write_bytes(b'not credited without source-verified immutable receipt')
    (directory/'jobs').mkdir();(directory/'jobs'/'dynamic-checkpoint.bin').write_bytes(b'uncredited dynamic bytes')
    store=SimpleNamespace(directory=directory,meta={'input_sha256':sha256(b'{}').hexdigest()},
        path=lambda name:directory/name,_pinned=lambda:None)
    monkeypatch.setattr(portable_job,'worker_contract',lambda *a,**k:contract)
    owners=supervisor._pool_owners(directory,key,policy)
    inventory=supervisor._pool_inventory(store,plan,owners)
    assert {x['path']for x in inventory}=={'pilot.store/'+name for name in names}
    assert all(x['owner']==next(y['owner']for y in owners if y['role']=='STORE')for x in inventory)
    assert (directory/'foreign.bin').exists()and(tmp_path/'foreign-pool.bin').exists()
    padded=directory/'portable-job.json';padded.write_bytes(b'{} '+b' '*4096)
    with pytest.raises(ValueError,match='exact canonical producer'):supervisor._pool_inventory(store,plan,owners)
    assert padded.read_bytes()==b'{} '+b' '*4096
    padded.write_bytes(b'{}')
    stranger=directory/'lifetime-native-build.json';stranger_bytes=b'{"foreign":"not an admitted native build"}'
    stranger.write_bytes(stranger_bytes)
    with pytest.raises(ValueError,match='no owned inventory authority'):supervisor._pool_inventory(store,plan,owners)
    assert stranger.read_bytes()==stranger_bytes


def test_no_owned_pool_claim_when_common_execution_admission_fails(monkeypatch,tmp_path):
    from ops_sim.v5 import lifetime_supervisor as supervisor,lifetime_execution_authority as authority,lifetime_pool
    called=[]
    def refuse(store):raise ValueError('expected source/backend/authority refusal')
    monkeypatch.setattr(authority,'admit_store_execution',refuse)
    monkeypatch.setattr(lifetime_pool,'reserve_v2',lambda *a,**k:called.append(True))
    with pytest.raises(ValueError,match='authority refusal'):supervisor._reserve_pool(object(),{})
    assert called==[]


def test_supervisor_close_preserves_primary_and_all_secondary_failures():
    from ops_sim.v5 import lifetime_supervisor as supervisor
    called=[]
    class Closer:
        _last_job_id=None
        def close(self):called.append('runner');raise OSError('expected runner close')
    class Store:
        def close_publications(self):called.append('store');raise OSError('expected store close')
    with pytest.raises(ValueError)as caught:
        try:raise ValueError('original primary gate')
        finally:supervisor._close_session(Store(),Closer())
    assert str(caught.value)=='original primary gate'
    assert len(caught.value.supervisor_close_failures)==2 and called==['runner','store']


def test_v2_plan_explicitly_binds_backend_authority_and_inventory_policy(tmp_path):
    from ops_sim.v5 import lifetime_supervisor as supervisor
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    from ops_sim.v5.lifetime_campaign import PLAN_V2
    p=LifetimeCampaignPolicyV2();contract={'backend_binding':{'selection':'PREPARED_PYTHON'}}
    store=SimpleNamespace(directory=tmp_path/'bounded.store',runner_policy=p,
        root_input=SimpleNamespace(identity='a'*64,start_seconds=128,end_seconds=7328),
        meta=dict(root_identity='a'*64,input_sha256='b'*64,source_identity='c'*64,runtime={'version':'test'},execution_authority_sha256='d'*64))
    plan=supervisor._plan(store,contract)
    assert plan['format']==PLAN_V2 and plan['execution_authority_sha256']=='d'*64
    assert plan['backend_binding']==contract['backend_binding']
    assert plan['pool_inventory']=='B63_VERIFIED_IMMUTABLE_INITIAL_FILES_ONLY_V1'
    assert plan['plan_identity']==supervisor.digest({k:v for k,v in plan.items()if k!='plan_identity'})


def test_cli_forwards_explicit_new_backend_and_permission(monkeypatch,tmp_path,capsys):
    import m8_lifetime_campaign_cli as cli
    from dataclasses import asdict
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    policy=tmp_path/'policy.json';policy.write_text(json.dumps(asdict(LifetimeCampaignPolicyV2())),encoding='utf8')
    calls=[]
    def prepare(*args,**kwargs):calls.append((args,kwargs));return {'prepared':True,'dispatch':False}
    monkeypatch.setattr(cli.supervisor,'prepare',prepare)
    result=cli.main(['prepare','--input',str(tmp_path/'input.json'),'--store',str(tmp_path/'new.store'),
        '--policy',str(policy),'--backend','PREPARED_PYTHON','--execution-mode','PILOT'])
    assert result['dispatch']is False and len(calls)==1
    assert calls[0][1]['backend']=='PREPARED_PYTHON'and calls[0][1]['execution_mode']=='PILOT'
    assert calls[0][1]['build']is None and calls[0][1]['acceptance']is None


def test_cli_admit_is_real_common_owner_gate(monkeypatch,tmp_path):
    import m8_lifetime_campaign_cli as cli
    from ops_sim.v5 import lifetime_execution_authority as authority
    store=SimpleNamespace(close_publications=lambda:None)
    monkeypatch.setattr(cli.supervisor,'_store',lambda directory:(store,{}))
    monkeypatch.setattr(cli.supervisor,'_summary',lambda *a:{'mode':'declared only'})
    def refuse(_):raise ValueError('expected real common authority refusal')
    monkeypatch.setattr(authority,'admit_store_execution',refuse)
    with pytest.raises(ValueError,match='common authority refusal'):cli.main(['admit','--store',str(tmp_path)])


def test_pilot_stop_arms_same_parent_ledger_owner_before_ordinary_callback():
    from ops_sim.v5 import lifetime_supervisor as supervisor
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    calls=[];ledger={'sequence':7}
    store=SimpleNamespace(runner_policy=LifetimeCampaignPolicyV2(),_parent_work=ledger)
    def arm(jid,minimum):
        assert store._parent_work is ledger
        ledger['sequence']+=1;calls.append(('arm',jid,minimum,ledger['sequence']))
    store.arm_pilot_stop=arm
    def ordinary(job):calls.append(('ordinary',job['job_id'],ledger['sequence']))
    callback=supervisor._pilot_stop_on_launch(store,6000,ordinary)
    callback({'job_id':'a'*32})
    assert calls==[('arm','a'*32,6000,8),('ordinary','a'*32,8)]
    assert supervisor._pilot_stop_on_launch(store,None,ordinary)is ordinary


def test_pilot_stop_arm_failure_prevents_ordinary_prelaunch_callback():
    from ops_sim.v5 import lifetime_supervisor as supervisor
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    calls=[]
    def refuse(jid,minimum):calls.append('arm');raise ValueError('expected immutable Stop admission failure')
    store=SimpleNamespace(runner_policy=LifetimeCampaignPolicyV2(),arm_pilot_stop=refuse)
    callback=supervisor._pilot_stop_on_launch(store,6000,lambda job:calls.append('ordinary'))
    with pytest.raises(ValueError,match='Stop admission failure'):callback({'job_id':'a'*32})
    assert calls==['arm']


@pytest.mark.parametrize('value',[True,6000.0,0,-1,2**53])
def test_invalid_supervisor_stop_threshold_refuses_before_store_or_lease(monkeypatch,tmp_path,value):
    from ops_sim.v5 import lifetime_supervisor as supervisor
    calls=[]
    monkeypatch.setattr(supervisor,'_store',lambda path:calls.append('store'))
    with pytest.raises(ValueError,match='bounded integer'):
        supervisor.run(tmp_path,pilot_stop_minimum_partial_bits=value)
    assert calls==[]


def test_supervisor_forwards_stop_rule_without_changing_ordinary_callback(monkeypatch,tmp_path):
    from contextlib import nullcontext
    from ops_sim.v5 import lifetime_supervisor as supervisor
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2
    store=SimpleNamespace(runner_policy=LifetimeCampaignPolicyV2());plan={'plan_identity':'b'*64};seen=[]
    ordinary=lambda job:None
    monkeypatch.setattr(supervisor,'_store',lambda path:(store,plan))
    monkeypatch.setattr(supervisor,'_lock',lambda value:nullcontext())
    monkeypatch.setattr(supervisor,'_close_session',lambda *args:None)
    def locked(value,bound,**kwargs):
        assert value is store and bound is plan;seen.append(kwargs);return {'completed':False}
    monkeypatch.setattr(supervisor,'_run_locked',locked)
    assert supervisor.run(tmp_path,on_launch=ordinary,pilot_stop_minimum_partial_bits=6000)=={'completed':False}
    assert seen[0]['on_launch']is ordinary and seen[0]['pilot_stop_minimum_partial_bits']==6000


def test_legacy_supervisor_cannot_acquire_pilot_stop_sidecar():
    from ops_sim.v5 import lifetime_supervisor as supervisor
    store=SimpleNamespace(runner_policy=LifetimeCampaignPolicy())
    with pytest.raises(ValueError,match='explicit V2'):
        supervisor._pilot_stop_on_launch(store,6000,None)


def test_legacy_public_run_stop_rejects_before_lease(monkeypatch,tmp_path):
    from ops_sim.v5 import lifetime_supervisor as supervisor
    calls=[];store=SimpleNamespace(runner_policy=LifetimeCampaignPolicy())
    monkeypatch.setattr(supervisor,'_store',lambda path:(store,{}))
    monkeypatch.setattr(supervisor,'_lock',lambda value:calls.append('lease'))
    monkeypatch.setattr(supervisor,'_close_session',lambda *args:None)
    with pytest.raises(ValueError,match='explicit V2'):
        supervisor.run(tmp_path,pilot_stop_minimum_partial_bits=6000)
    assert calls==[]
