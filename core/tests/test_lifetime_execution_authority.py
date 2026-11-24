"""Permission admission only; these tests never dispatch a scientific child."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import pytest

from ops_sim.v5 import lifetime_execution_authority as authority
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy, QUALIFICATION
from ops_sim.v5.project_store import runtime_identity
from lifetime_support import root_for


def policy():
    return LifetimeCampaignPolicy(mode=QUALIFICATION, maximum_primary_segments=2,
        reserved_diagnostic_slots=1, hard_seconds=60, soft_seconds=8,
        finalization_seconds=52)


def contract(root, backend='REFERENCE', build=None):
    manifest={'owned.py':dict(bytes=1,sha256='a'*64)}
    return dict(format='TEST_EXACT_CONTRACT',root_identity=root.identity,
        input_sha256=sha256(dumps_root(root)).hexdigest(),
        source_manifest=manifest,source_manifest_sha256=authority.digest(manifest),
        runtime=runtime_identity(),backend_binding=authority.backend_binding(backend,build))


def native_build():
    capabilities=dict(signed_zero='PASS',ordered='PASS',finite='PASS')
    return dict(format='B63_NATIVE_BUILD_RECEIPT_V1',
        artifact=dict(path='ops_sim/v5/_lifecycle_native.pyd',sha256='b'*64,bytes=1024),
        runtime=dict(implementation='cpython',python='3.14.7',cache_tag='cpython-314',
                     ext_suffix='.pyd',platform='win32',machine='AMD64'),
        engine_source_sha256='c'*64,compiler=dict(name='test',version='1',flags=['-fno-fast-math']),
        capabilities=capabilities,capability_sha256=authority.digest(capabilities))


def create(root=None, selected='REFERENCE', build=None):
    root=root_for(1800)if root is None else root
    c=contract(root,selected,build);p=policy();raw=dumps_root(root)
    return root,c,p,raw,authority.make_authority(root,raw,c,p,backend=selected,build=build)


def test_explicit_pilot_roundtrip_and_data_copy():
    root,c,p,raw,value=create()
    admitted=authority.admit_authority(value,root,raw,c,p)
    assert admitted==value and admitted is not value
    admitted['pilot_limits']['duration_seconds']=1
    assert value['pilot_limits']['duration_seconds']==86400


def test_horizon_domain_changes_only_declared_duration():
    assert authority.domain_identity(root_for(1800))==authority.domain_identity(root_for(7200))
    root=root_for(1800)
    changed=replace(root,policy=replace(root.policy,max_control_units=root.policy.max_control_units-1))
    assert authority.domain_identity(root)!=authority.domain_identity(changed)


def test_full_day_pilot_bound_and_long_refusal_before_owner_work():
    root=root_for(86400);c=contract(root);p=policy()
    assert authority.make_authority(root,dumps_root(root),c,p)['mode']==authority.PILOT
    root=root_for(86401);c=contract(root)
    with pytest.raises(ValueError,match='bounded pilot'):
        authority.make_authority(root,dumps_root(root),c,p)
    with pytest.raises(ValueError,match='evidence reference'):
        authority.make_authority(root,dumps_root(root),c,p,mode=authority.LONG,
                                 acceptance={'ready':True})


@pytest.mark.parametrize('field,value',[
    ('maximum_primary_segments',9),('reserved_diagnostic_slots',3),
    ('hard_seconds',241)])
def test_pilot_population_and_deadline_are_not_promoted_by_doctor(field,value):
    from ops_sim.v5.lifetime_policy import PRODUCTION
    p=replace(policy(),mode=PRODUCTION)
    values={field:value}
    if field=='hard_seconds':values.update(soft_seconds=211,finalization_seconds=30)
    p=replace(p,**values)
    root=root_for(1800)
    with pytest.raises(ValueError,match='bounded pilot'):
        authority.make_authority(root,dumps_root(root),contract(root),p)


@pytest.mark.parametrize('change',[
    lambda v:v['binding'].__setitem__('input_sha256','d'*64),
    lambda v:v['binding'].__setitem__('source_manifest_sha256','d'*64),
    lambda v:v['binding']['runtime'].__setitem__('platform','foreign'),
    lambda v:v['binding'].__setitem__('duration_seconds',1800.0),
    lambda v:v['pilot_limits'].__setitem__('hard_seconds',240.0),
])
def test_rehashed_foreign_or_numeric_downgrade_is_rejected(change):
    root,c,p,raw,value=create();changed=deepcopy(value);change(changed)
    changed['identity']=authority.digest({k:v for k,v in changed.items()if k!='identity'})
    with pytest.raises(ValueError):authority.admit_authority(changed,root,raw,c,p)


def test_input_contract_policy_backend_and_native_build_are_all_bound():
    root,c,p,raw,value=create()
    with pytest.raises(ValueError,match='owner input'):
        authority.admit_authority(value,root,raw+b' ',c,p)
    with pytest.raises(ValueError,match='authority drift'):
        authority.admit_authority(value,root,raw,c,replace(p,backup_copies=2))
    altered=deepcopy(c);altered['runtime']['platform']='foreign'
    with pytest.raises(ValueError,match='runtime'):
        authority.admit_authority(value,root,raw,altered,p)
    with pytest.raises(ValueError,match='backend'):
        authority.admit_authority(value,root,raw,c,p,backend='PREPARED_PYTHON')
    build=native_build();root,c,p,raw,value=create(selected='PREPARED_NATIVE',build=build)
    assert value['binding']['backend_binding']['build_sha256']==authority.digest(build)
    foreign=deepcopy(build);foreign['artifact']['sha256']='f'*64
    with pytest.raises(ValueError,match='backend'):
        authority.admit_authority(value,root,raw,c,p,backend='PREPARED_NATIVE',build=foreign)


@pytest.mark.parametrize('build',[True,{'ready':True},None])
def test_native_backend_cannot_claim_untyped_build(build):
    with pytest.raises(ValueError):authority.backend_binding('PREPARED_NATIVE',build)


def test_acceptance_reference_raw_hash_and_symlink_refuse(tmp_path):
    path=tmp_path/'evidence.json';path.write_text('{"ready":true}',encoding='utf8')
    ref=authority.reference(path)
    assert ref['bytes']==path.stat().st_size
    path.write_text('{"ready":false}',encoding='utf8')
    root,c,p,raw,_=create()
    with pytest.raises(ValueError,match='raw binding'):
        authority.make_authority(root,raw,c,p,mode=authority.LONG,acceptance=ref)
    ref=authority.reference(path)
    with pytest.raises(ValueError,match='genuine acceptance'):
        authority.make_authority(root,raw,c,p,mode=authority.LONG,acceptance=ref)


def test_new_build_or_domain_cannot_reuse_even_well_shaped_wrapper(tmp_path,monkeypatch):
    root,c,p,raw,pilot=create()
    wrapper=dict(format=authority.ACCEPTANCE,
        qualification_binding=authority._qualification_binding(pilot['binding']),
        genuine_evidence={'path':str(tmp_path/'not-read'),'sha256':'a'*64,'bytes':1})
    wrapper['qualification_binding']['domain_identity']='f'*64
    path=tmp_path/'acceptance.json';path.write_bytes(authority.canonical(wrapper))
    called=[]
    from ops_sim.v5 import lifetime_server_acceptance
    monkeypatch.setattr(lifetime_server_acceptance,'admit_acceptance',lambda *a:called.append(a))
    with pytest.raises(ValueError,match='domain mismatch'):
        authority.make_authority(root,raw,c,p,mode=authority.LONG,
                                 acceptance=authority.reference(path))
    assert called==[]


def test_duplicate_evidence_fields_and_forged_pass_flag_never_grant_long(tmp_path):
    path=tmp_path/'duplicate.json';path.write_bytes(b'{"ready":true,"ready":true}')
    root,c,p,raw,_=create()
    with pytest.raises(ValueError,match='duplicate'):
        authority.make_authority(root,raw,c,p,mode=authority.LONG,
                                 acceptance=authority.reference(path))
    path.write_bytes(b'{"computed_acceptance":"PASS","ready":true}')
    with pytest.raises(ValueError,match='genuine acceptance'):
        authority.make_authority(root,raw,c,p,mode=authority.LONG,
                                 acceptance=authority.reference(path))


def test_pure_data_admission_never_grants_long_or_reads_evidence(tmp_path):
    root,c,p,raw,value=create()
    changed=deepcopy(value);changed['mode']=authority.LONG
    changed['acceptance']=dict(path=str(tmp_path/'absent.json'),sha256='f'*64,bytes=1)
    changed['identity']=authority.digest({k:v for k,v in changed.items()if k!='identity'})
    assert authority.admit_authority_data(changed)==changed
    with pytest.raises((ValueError,FileNotFoundError)):
        authority.admit_authority(changed,root,raw,c,p)


def test_legacy_long_refuses_before_any_store_access_and_bounded_pilot_is_explicit():
    from types import SimpleNamespace
    seen=[]
    def no_path(*parts):seen.append(parts);raise AssertionError('unexpected store I/O')
    store=SimpleNamespace(runner_policy=policy(),root_input=SimpleNamespace(duration_seconds=86401,identity='a'*64),path=no_path)
    with pytest.raises(ValueError,match='legacy store has no qualified long'):
        authority.admit_store_execution(store)
    assert seen==[]
    store.root_input.duration_seconds=86400
    value=authority.admit_store_execution(store)
    assert value['mode']==authority.PILOT and value['format']=='B63_BOUNDED_LEGACY_PILOT_DISPATCH_ONLY_V1'
    assert seen==[]


def test_store_pin_checked_before_contract_hydration(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from ops_sim.v5 import portable_job
    _,_,_,_,value=create()
    (tmp_path/'execution-authority.json').write_bytes(authority.canonical(value))
    seen=[]
    monkeypatch.setattr(portable_job,'worker_contract',lambda *args:seen.append(args))
    store=SimpleNamespace(directory=tmp_path,runner_policy=object(),meta={'execution_authority_sha256':'f'*64},
                          path=lambda *parts:tmp_path.joinpath(*parts))
    with pytest.raises(ValueError,match='canonical SHA256 binding'):
        authority.admit_store_execution(store)
    assert seen==[]


def test_v2_store_metadata_requires_authority_and_legacy_cannot_acquire_policy():
    from dataclasses import asdict
    from ops_sim.v5.lifecycle_runner_policy import admit_runner_store_metadata,STORE_FIELDS
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,STORE,STORE_V2,METHOD_V2
    p=LifetimeCampaignPolicyV2(**dict(asdict(policy()),method=METHOD_V2))
    meta={name:None for name in STORE_FIELDS}
    meta.update(format=STORE_V2,maximum_jobs=p.maximum_jobs,runner_policy=asdict(p),
        runner_policy_identity=p.identity,execution_authority_sha256='a'*64)
    assert admit_runner_store_metadata(meta)[0]==p
    missing=dict(meta);missing.pop('execution_authority_sha256')
    with pytest.raises(ValueError,match='store fields'):admit_runner_store_metadata(missing)
    hidden=dict(missing,format=STORE)
    with pytest.raises(ValueError,match='cannot acquire B63'):admit_runner_store_metadata(hidden)


def test_v2_contract_has_separate_identity_and_exact_frozen_membership(monkeypatch):
    from ops_sim.v5 import lifetime_portable,lifetime_source,lifetime_admission
    root=root_for(1800);manifest={'owned.py':dict(bytes=1,sha256='a'*64)}
    monkeypatch.setattr(lifetime_source,'B63_SOURCE_PATHS',('owned.py',),raising=False)
    monkeypatch.setattr(lifetime_portable,'source_manifest',lambda source:deepcopy(manifest))
    monkeypatch.setattr(lifetime_portable,'runtime_requirements',lambda source:{'runtime':'test'})
    monkeypatch.setattr(lifetime_admission,'resource_plan',lambda root:{'finite':'test'})
    monkeypatch.setattr(lifetime_portable,'legacy_contract',lambda r,s,k:dict(contract(r),strategy=k))
    value=lifetime_portable.execution_contract_v2(root,'.','REFERENCE_B59',backend='PREPARED_PYTHON')
    assert value['format']==lifetime_portable.FORMAT_V2
    assert value['producer']=='M8_B63_PREPARED_CURRENT_SOURCE_PRODUCER_V2'
    assert value['backend_binding']['selection']=='PREPARED_PYTHON' and value['native_build']is None
    assert value['publication_work']=='B63_BOUNDED_STATUS_DETAILS_PRECHARGED_V1'
    monkeypatch.setattr(lifetime_source,'B63_SOURCE_PATHS',('foreign.py',))
    with pytest.raises(ValueError,match='producer membership'):
        lifetime_portable.execution_contract_v2(root,'.','REFERENCE_B59')


def test_v2_package_metadata_rejects_advanced_intent_or_authority_drift(monkeypatch):
    from dataclasses import asdict
    from ops_sim.v5 import lifetime_portable
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,METHOD_V2
    from ops_sim.v5.lifetime_campaign import horizon_preflight
    from ops_sim.v5.lifecycle_application import make_intent
    from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
    from ops_sim.v5.lifecycle_compact import PublicationProfile
    root=root_for(1800);p=LifetimeCampaignPolicyV2(**dict(asdict(policy()),method=METHOD_V2));c=contract(root)
    raw=dumps_root(root);permission=authority.make_authority(root,raw,c,p)
    required={'runtime':'test'}
    monkeypatch.setattr(lifetime_portable,'runtime_requirements',lambda source:required)
    intent=make_intent(root.identity,key='0'*32,execution_seconds=p.hard_seconds,
        maximum_output_bytes=p.maximum_output_bytes,execution_budget=ExecutionBudget(p.hard_seconds,p.soft_seconds,p.finalization_seconds),
        publication_profile=PublicationProfile())
    job=dict(format=lifetime_portable.JOB_V2,contract=c,intent=intent,horizon=horizon_preflight(root,p),
        requirements=required,lifetime_policy=asdict(p),
        limits=dict(rss_bytes=p.maximum_rss_bytes,native_bytes=p.maximum_native_bytes,job_bytes=p.maximum_output_bytes,slots=p.maximum_jobs),
        entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False,execution_authority=permission)
    c['native_build']=None
    permission=authority.make_authority(root,raw,c,p);job['execution_authority']=permission
    assert lifetime_portable._job_metadata_v2(job,root,'.')==p
    advanced=deepcopy(job);advanced['intent']['parent_job_id']='c'*32;advanced['intent']['snapshot_sha256']='d'*64
    with pytest.raises(ValueError,match='advanced checkpoint'):
        lifetime_portable._job_metadata_v2(advanced,root,'.')
    foreign=deepcopy(job);foreign['execution_authority']['binding']['source_manifest_sha256']='f'*64
    foreign['execution_authority']['identity']=authority.digest({k:v for k,v in foreign['execution_authority'].items()if k!='identity'})
    with pytest.raises(ValueError,match='authority drift'):
        lifetime_portable._job_metadata_v2(foreign,root,'.')


@pytest.mark.parametrize('selected',[None,'segmented','finite'])
def test_every_generic_public_policy_refuses_long_root_before_store_io(selected):
    from types import SimpleNamespace
    from ops_sim.v5.lifecycle_runner_policy import LifecycleRunnerStorePolicy
    from ops_sim.v5.finite_campaign import FiniteCampaignPolicy
    p={'segmented':LifecycleRunnerStorePolicy,'finite':FiniteCampaignPolicy}.get(selected)
    p=None if p is None else p()
    def forbidden(*args):raise AssertionError('execution refusal must precede store writes/claims')
    store=SimpleNamespace(root_input=root_for(15*31557600),runner_policy=p,
                          path=forbidden,claim=forbidden,prepare_job=forbidden)
    with pytest.raises(ValueError,match='generic legacy/finite store has no qualified long'):
        authority.admit_public_execution(store)
    store.root_input=root_for(86400)
    admitted=authority.admit_public_execution(store)
    assert admitted['mode']==authority.PILOT and admitted['qualified_long_execution']is False
    assert admitted['root_identity']==store.root_input.identity


def test_public_execution_requires_real_typed_root_and_policy():
    from types import SimpleNamespace
    fake=SimpleNamespace(duration_seconds=1,identity='a'*64)
    with pytest.raises(TypeError,match='exact real LifecycleRoot'):
        authority.admit_public_execution(SimpleNamespace(root_input=fake,runner_policy=None))
    with pytest.raises(TypeError,match='exact public execution store policy'):
        authority.admit_public_execution(SimpleNamespace(root_input=root_for(1800),runner_policy=object()))


def test_generic_worker_without_portable_files_refuses_long_before_any_output(tmp_path):
    from ops_sim.v5.lifecycle_application import LifecycleStore
    from ops_sim.v5.finite_campaign import FiniteCampaignPolicy
    store=LifecycleStore(tmp_path/'long',root_for(15*31557600),create=True,
                         runner_policy=FiniteCampaignPolicy())
    store.close_publications()
    before={p.relative_to(store.directory).as_posix():p.read_bytes()
            for p in store.directory.rglob('*')if p.is_file()}
    assert not(store.directory/'portable-execution.json').exists()
    with pytest.raises(ValueError,match='generic legacy/finite store has no qualified long'):
        authority.admit_worker_execution(store.directory)
    assert before=={p.relative_to(store.directory).as_posix():p.read_bytes()
                    for p in store.directory.rglob('*')if p.is_file()}
    assert not(store.directory/'jobs').exists()


def test_generic_short_worker_remains_read_only_bounded_legacy_pilot(tmp_path):
    from ops_sim.v5.lifecycle_application import LifecycleStore
    from ops_sim.v5.finite_campaign import FiniteCampaignPolicy
    store=LifecycleStore(tmp_path/'short',root_for(1800),create=True,
                         runner_policy=FiniteCampaignPolicy())
    store.close_publications()
    before={p.relative_to(store.directory).as_posix():p.read_bytes()
            for p in store.directory.rglob('*')if p.is_file()}
    admitted=authority.admit_worker_execution(store.directory)
    assert admitted['mode']==authority.PILOT and admitted['qualified_long_execution']is False
    assert before=={p.relative_to(store.directory).as_posix():p.read_bytes()
                    for p in store.directory.rglob('*')if p.is_file()}
    assert not(store.directory/'jobs').exists()


def test_v2_worker_missing_authority_refuses_even_without_portable_files(tmp_path):
    from dataclasses import asdict
    from ops_sim.v5.lifecycle_application import LifecycleStore
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,METHOD_V2
    root=root_for(1800);p=LifetimeCampaignPolicyV2(**dict(asdict(policy()),method=METHOD_V2))
    value=authority.make_authority(root,dumps_root(root),contract(root),p)
    store=LifecycleStore(tmp_path/'v2',root,create=True,runner_policy=p,execution_authority=value)
    store.close_publications()
    (store.directory/'execution-authority.json').unlink()  # Deliberately corrupt test fixture only.
    before={p.relative_to(store.directory).as_posix():p.read_bytes()
            for p in store.directory.rglob('*')if p.is_file()}
    assert not(store.directory/'portable-execution.json').exists()
    with pytest.raises(FileNotFoundError):authority.admit_worker_execution(store.directory)
    assert before=={p.relative_to(store.directory).as_posix():p.read_bytes()
                    for p in store.directory.rglob('*')if p.is_file()}
    assert not(store.directory/'jobs').exists()
