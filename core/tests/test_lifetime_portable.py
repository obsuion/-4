from dataclasses import replace,asdict
import pytest,json
from lifetime_support import SOURCE,root_for
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION
from ops_sim.v5.portable_job import prepare_lifetime,admit_lifetime_job,create_lifetime_store,worker_contract,canonical
from ops_sim.v5.lifecycle_application import LifecycleStore

def policy():return LifetimeCampaignPolicyV2(mode=QUALIFICATION,maximum_primary_segments=4,reserved_diagnostic_slots=2,hard_seconds=60,soft_seconds=8,finalization_seconds=52)

def test_genuine_v7_package_store_worker_same_contract(tmp_path):
    root=root_for();path=tmp_path/'initial.zip';prepare_lifetime(path,root,SOURCE,policy(),key='a'*32)
    j,r,raw=admit_lifetime_job(path,SOURCE)
    assert r.identity==root.identity and j['native_import']is False
    assert j['contract']['environment_native_format']=='B61_EXPOSURE_THERMAL_CHECKPOINT_V8'
    assert j['contract']['source_manifest_sha256']and j['contract']['runtime']
    store,intent=create_lifetime_store(path,tmp_path/'store',SOURCE)
    try:
        c=worker_contract(store.directory,SOURCE);assert c==j['contract']
        job,new=store.prepare_job(intent);assert new
        assert store.reconcile(intent)['job_id']==job['job_id']
        assert len(store.jobs())==1
    finally:store.close_publications()

def test_old_producers_stay_closed_new_membership_exact():
    from m8_environment_campaign_cli import trusted_worker_binding,EXPECTED_WORKER_MEMBERS
    from ops_sim.v5.lifetime_source import SOURCE_PATHS,B63_SOURCE_PATHS
    from ops_sim.v5.lifetime_portable import execution_contract
    with pytest.raises(ValueError,match='membership drift'):trusted_worker_binding()
    assert len(EXPECTED_WORKER_MEMBERS)==720
    with pytest.raises(ValueError,match='producer membership'):execution_contract(root_for(),SOURCE,'B60_SEALED_STATIC_V1')
    assert len(SOURCE_PATHS)==754 and set(SOURCE_PATHS)<set(B63_SOURCE_PATHS)
    assert set(B63_SOURCE_PATHS)=={p.relative_to(SOURCE).as_posix()for p in SOURCE.rglob('*')if p.is_file()}

def test_store_policy_tamper_refuses_before_dispatch(tmp_path):
    p=tmp_path/'initial.zip';prepare_lifetime(p,root_for(),SOURCE,policy())
    store,intent=create_lifetime_store(p,tmp_path/'store',SOURCE);store.close_publications()
    meta=json.loads((store.directory/'store.json').read_bytes());meta['runner_policy']['hard_seconds']=61
    (store.directory/'store.json').write_bytes(canonical(meta))
    with pytest.raises(ValueError):LifecycleStore(store.directory)

def test_real_supervisor_prepare_canonical_unicode_pool_binding_and_readonly_status(tmp_path):
    from ops_sim.v5.lifecycle_document import dumps_root
    from ops_sim.v5 import lifetime_supervisor as sup
    from ops_sim.v5.portable_job import digest
    path=tmp_path/'initial.json';path.write_bytes(dumps_root(root_for()))
    result=sup.prepare(path,tmp_path/'candidate',policy())
    store,plan=sup._store(tmp_path/'candidate')
    try:
        contract=worker_contract(store.directory,SOURCE)
        assert plan['execution_contract_sha256']==digest(canonical(contract))
        before={p.relative_to(store.directory).as_posix():p.read_bytes()for p in store.directory.rglob('*')if p.is_file()}
        assert sup._summary(store,plan)['jobs']==0
        assert before=={p.relative_to(store.directory).as_posix():p.read_bytes()for p in store.directory.rglob('*')if p.is_file()}
        pool=json.loads((tmp_path/'LIFETIME-POOL-V2.json').read_bytes())
        assert list(pool['reservations'])==[plan['pool_key']]
        assert plan['execution_authority_sha256']==store.meta['execution_authority_sha256']
        assert plan['backend_binding']['selection']=='REFERENCE'
    finally:store.close_publications()


def test_new_worker_refuses_corrupt_authority_before_dispatch(tmp_path):
    path=tmp_path/'initial.zip';prepare_lifetime(path,root_for(),SOURCE,policy())
    store,_=create_lifetime_store(path,tmp_path/'store',SOURCE)
    try:
        authority=store.path('execution-authority.json')
        data=json.loads(authority.read_bytes());data['binding']['domain_identity']='f'*64
        authority.write_bytes(canonical(data))
        with pytest.raises(ValueError):worker_contract(store.directory,SOURCE)
        assert not list(store.path('jobs').glob('*/request.json'))
    finally:store.close_publications()
