"""Typed V3 DATA/routing tests; no native import, build or mission dispatch."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import zipfile

import pytest

from ops_sim.v5 import lifetime_typed_portable as owner,portable_job,lifetime_execution_authority as authority
from ops_sim.v5 import lifecycle_typed_backend as typed
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy,LifetimeCampaignPolicyV2,QUALIFICATION
from test_lifecycle_typed_backend import receipt
from lifetime_support import root_for


def declared_contract(monkeypatch,*,quiet=True):
    from ops_sim.v5 import lifetime_source,lifecycle_backend
    build=receipt(quiet=quiet);manifest={}
    for item in (build['artifact'],build['engine_source'],build['generated_c'],*build['support_sources'].values()):
        manifest[item['path']]=dict(bytes=item['bytes'],sha256=item['sha256'])
    requirements=dict(python_major_minor=[3,14],requirements_sha256='b'*64,
        dependency_versions={'pytest':'METADATA_ONLY'},dependencies='PINNED_REQUIREMENTS_TXT_NOT_BUNDLED_OR_AUTOINSTALLED')
    monkeypatch.setattr(owner,'source_manifest',lambda source:deepcopy(manifest))
    monkeypatch.setattr(owner,'runtime_requirements',lambda source:deepcopy(requirements))
    monkeypatch.setattr(lifetime_source,'B64_SOURCE_PATHS',tuple(manifest),raising=False)
    monkeypatch.setattr(lifecycle_backend,'runtime_binding',lambda:deepcopy(build['runtime']))
    root=root_for(600)
    value=owner.execution_contract_v3(root,'.',owner.FAST,backend=build['execution_domain'],build=build)
    return value,root,build


def test_v3_data_has_distinct_format_build_domain_and_current_raw_bindings(monkeypatch):
    value,root,build=declared_contract(monkeypatch)
    assert owner.admit_execution_contract_data_v3(value)==value
    assert value['format']==owner.FORMAT_V3 and value['job_preparation']==owner.PREPARATION
    assert value['backend_binding']==authority.typed_backend_binding(typed.FULL_DOMAIN,build)
    assert value['native_build']==build and value['root_identity']==root.identity
    assert value['source_manifest_sha256']==portable_job.digest(portable_job.canonical(value['source_manifest']))


@pytest.mark.parametrize('field',('format','producer','job_preparation','backend_binding','native_build','source_manifest_sha256'))
def test_v3_missing_fields_are_not_inferred(monkeypatch,field):
    value,_,_=declared_contract(monkeypatch);del value[field]
    with pytest.raises(ValueError):owner.admit_execution_contract_data_v3(value)


@pytest.mark.parametrize('part',('artifact','engine_source','generated_c','support_sources'))
def test_every_typed_build_source_member_is_manifest_bound(monkeypatch,part):
    value,_,_=declared_contract(monkeypatch)
    item=next(iter(value['native_build'][part].values())) if part=='support_sources'else value['native_build'][part]
    value['source_manifest'][item['path']]['sha256']='f'*64
    value['source_manifest_sha256']=portable_job.digest(portable_job.canonical(value['source_manifest']))
    with pytest.raises(ValueError,match='source manifest raw binding'):owner.admit_execution_contract_data_v3(value)


def test_support_is_separate_selection_and_cannot_be_hidden_in_old_container(monkeypatch):
    from ops_sim.v5.lifetime_portable import admit_execution_contract_data_v2,FORMAT_V2
    value,_,build=declared_contract(monkeypatch,quiet=False)
    assert value['backend_binding']['selection']==typed.SUPPORT_DOMAIN
    assert owner.admit_execution_contract_data_v3(value)['native_build']['capabilities']['quiet_interval_callback_free']is False
    with pytest.raises(ValueError,match='selection/build domain mismatch'):authority.typed_backend_binding(typed.FULL_DOMAIN,build)
    with pytest.raises(ValueError,match='explicit numerical backend'):authority.backend_binding(typed.SUPPORT_DOMAIN,build)
    old=dict(value);old.pop('job_preparation');old.update(format=FORMAT_V2,producer='M8_B63_PREPARED_CURRENT_SOURCE_PRODUCER_V2')
    with pytest.raises(ValueError,match='explicit numerical backend'):admit_execution_contract_data_v2(old)


def test_typed_authority_binding_roundtrip_keeps_real_pilot_semantics(monkeypatch):
    from ops_sim.v5.lifecycle_document import dumps_root
    value,root,build=declared_contract(monkeypatch)
    policy=LifetimeCampaignPolicyV2(mode=QUALIFICATION,maximum_primary_segments=2,reserved_diagnostic_slots=1,
        hard_seconds=60,soft_seconds=8,finalization_seconds=52)
    raw=dumps_root(root)
    admitted=authority.make_authority(root,raw,value,policy,backend=typed.FULL_DOMAIN,build=build)
    assert authority.admit_authority_data(admitted)==admitted
    assert admitted['mode']=='PILOT' and admitted['acceptance']is None
    assert admitted['binding']['backend_binding']==value['backend_binding']
    changed=deepcopy(admitted);changed['binding']['backend_binding']['selection']=typed.SUPPORT_DOMAIN
    changed['identity']=authority.digest({k:v for k,v in changed.items()if k!='identity'})
    with pytest.raises(ValueError,match='authority drift'):
        authority.admit_authority(changed,root,raw,value,policy,backend=typed.FULL_DOMAIN,build=build)


def test_public_contract_route_precedes_any_legacy_root_decode(monkeypatch):
    from ops_sim.v5 import lifecycle_document
    calls=[]
    monkeypatch.setattr(owner,'admit_execution_contract_v3',lambda *a,**k:calls.append(a)or a[0])
    def forbidden(*a,**k):raise AssertionError('typed public route decoded legacy root first')
    monkeypatch.setattr(lifecycle_document,'loads_root',forbidden)
    value={'format':owner.FORMAT_V3}
    assert portable_job.admit_contract(value,b'UNREAD_METADATA',Path('.'))is value
    assert len(calls)==1


@pytest.mark.parametrize('selection',(typed.FULL_DOMAIN,typed.SUPPORT_DOMAIN))
def test_public_prepare_explicitly_routes_only_exact_new_policy(monkeypatch,selection):
    calls=[]
    monkeypatch.setattr(owner,'prepare_lifetime_v3',lambda *a,**k:calls.append((a,k))or {'routed':'V3'})
    p=LifetimeCampaignPolicyV2()
    result=portable_job.prepare_lifetime('new.zip',object(),'.',p,backend=selection,build={'METADATA_SPY':True})
    assert result=={'routed':'V3'} and calls[0][1]['backend']==selection
    with pytest.raises(TypeError,match='exact V2'):
        portable_job.prepare_lifetime('new.zip',object(),'.',LifetimeCampaignPolicy(),backend=selection,build={})
    assert len(calls)==1


def test_public_worker_route_uses_new_admission_helper(tmp_path,monkeypatch):
    path=tmp_path/'store';path.mkdir();contract={'METADATA_ROUTING_SPY':'NOT_EXECUTION'}
    (path/'portable-execution.json').write_bytes(portable_job.canonical(contract))
    (path/'portable-job.json').write_bytes(portable_job.canonical({'format':owner.JOB_V3}))
    calls=[]
    monkeypatch.setattr(owner,'worker_contract_v3',lambda *a,**k:calls.append((a,k))or contract)
    assert portable_job.worker_contract(path,'.',job_id='a'*32,request_sha256='b'*64)is contract
    assert calls[0][1]==dict(job_id='a'*32,request_sha256='b'*64)


def test_public_package_create_and_admit_use_new_format_without_duplicate_admission(tmp_path,monkeypatch):
    archive=tmp_path/'new.zip'
    with zipfile.ZipFile(archive,'w')as z:
        z.writestr('MANIFEST.json',portable_job.canonical({'format':owner.JOB_V3}))
        z.writestr('irrelevant-metadata-only',b'x')
    created=[];admitted=[]
    monkeypatch.setattr(owner,'create_lifetime_store_v3',lambda *a:created.append(a)or ('STORE_SPY','INTENT_SPY'))
    monkeypatch.setattr(owner,'admit_lifetime_job_v3',lambda *a:admitted.append(a)or ('JOB_SPY','ROOT_SPY','RAW_SPY'))
    assert portable_job.create_lifetime_store(archive,tmp_path/'store',tmp_path/'source')==('STORE_SPY','INTENT_SPY')
    assert len(created)==1 and admitted==[]
    assert portable_job.admit_lifetime_job(archive,'.')==('JOB_SPY','ROOT_SPY','RAW_SPY')
    assert len(admitted)==1


def test_saved_receipt_or_arbitrary_object_is_not_a_private_input_admission():
    with pytest.raises(TypeError,match='current-process'):
        owner._admit_token({'method':owner.PREPARATION},object(),b'input',{})
