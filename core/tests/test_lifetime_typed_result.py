"""V3 read-only packaging metadata; no mission or native activation."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from ops_sim.v5 import lifetime_result as owner,lifetime_typed_portable as typed,portable_job
from ops_sim.v5 import lifetime_execution_authority as authority
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION
from ops_sim.v5.lifecycle_document import dumps_root
from test_lifetime_typed_portable import declared_contract


def evidence(monkeypatch):
    contract,root,build=declared_contract(monkeypatch)
    policy=LifetimeCampaignPolicyV2(mode=QUALIFICATION,maximum_primary_segments=2,reserved_diagnostic_slots=1,
        hard_seconds=60,soft_seconds=8,finalization_seconds=52)
    raw=dumps_root(root);execution=authority.make_authority(root,raw,contract,policy,
        backend=build['execution_domain'],build=build)
    auth_raw=portable_job.canonical(execution)
    plan=dict(format=typed.PLAN_V3,root_identity=root.identity,input_sha256=portable_job.digest(raw),
        source_identity='c'*64,runtime=contract['runtime'],policy=asdict(policy),policy_identity=policy.identity,
        execution_contract_sha256=portable_job.digest(portable_job.canonical(contract)),root_target=root.end_seconds,
        original_anchor=root.start_seconds,automatic_resume=['RESOURCE_TIME','RESOURCE_OUTPUT'],incomplete_is_not_coverage=True,
        pool_key='METADATA_ONLY',execution_authority_sha256=portable_job.digest(auth_raw),backend_binding=contract['backend_binding'],
        pool_inventory='B63_VERIFIED_IMMUTABLE_INITIAL_FILES_ONLY_V1')
    plan['plan_identity']=portable_job.digest(portable_job.canonical(plan))
    view=dict(format=owner.FORMAT_V3,root_identity=root.identity,input_sha256=portable_job.digest(raw),
        source_manifest_sha256=contract['source_manifest_sha256'],execution_contract_sha256=plan['execution_contract_sha256'],
        plan_identity=plan['plan_identity'],requested_end_seconds=root.end_seconds,actual_end_seconds=root.start_seconds,
        read_only=True,native_execution_rights=False,backup_required_for_resume=True,primary_totals=None,
        monthly_environment=[],monthly_actual=[],cumulative_work=None,jobs=[],
        scope='LATEST_FORWARD_PRIMARY_ACTUAL_PREFIX_DIAGNOSTICS_NEVER_ADDED',
        execution_authority_sha256=portable_job.digest(auth_raw),backend_binding=contract['backend_binding'])
    payload={'input.json':raw,'execution-contract.json':portable_job.canonical(contract),
        'execution-authority.json':auth_raw,'plan.json':portable_job.canonical(plan),'view.json':portable_job.canonical(view)}
    return payload,view,plan,root,policy


def bundle(path,payload,format=owner.FORMAT_V3):
    manifest={name:dict(bytes=len(raw),sha256=portable_job.digest(raw))for name,raw in payload.items()}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as archive:
        archive.writestr('MANIFEST.json',portable_job.canonical(dict(format=format,files=manifest)))
        for name,raw in payload.items():archive.writestr(name,raw)


def test_typed_result_v3_inspection_is_portable_data_and_never_native_rights(tmp_path,monkeypatch):
    payload,view,_,_,_=evidence(monkeypatch);path=tmp_path/'read-only.zip';bundle(path,payload)
    from ops_sim.v5 import lifecycle_typed_backend,lifecycle_backend,lifecycle_document
    def forbidden(*a,**k):raise AssertionError('read-only typed result activated native/model/runtime authority')
    monkeypatch.setattr(lifecycle_typed_backend,'admit_typed_build',forbidden)
    monkeypatch.setattr(lifecycle_backend,'runtime_binding',forbidden)
    monkeypatch.setattr(lifecycle_document,'loads_root',forbidden)
    assert owner.inspect_result(path)==view
    assert view['native_execution_rights']is False and view['actual_end_seconds']<view['requested_end_seconds']


def test_empty_typed_store_export_emits_v3_and_roundtrips_without_running(tmp_path,monkeypatch):
    payload,view,plan,root,policy=evidence(monkeypatch)
    directory=tmp_path/'metadata-store';directory.mkdir()
    for name,raw in payload.items():
        if name not in ('view.json','execution-contract.json'): (directory/name).write_bytes(raw)
    (directory/'portable-execution.json').write_bytes(payload['execution-contract.json'])
    store=SimpleNamespace(directory=directory,runner_policy=policy,root_input=root,
        meta={'input_sha256':view['input_sha256'],'execution_authority_sha256':view['execution_authority_sha256']},
        path=lambda *parts:directory.joinpath(*parts),jobs=lambda:[],_cache={})
    from ops_sim.v5 import lifetime_supervisor
    monkeypatch.setattr(lifetime_supervisor,'_summary',lambda *a:dict(parent_job_id=None,clock=root.start_seconds))
    output=tmp_path/'export.zip';result=owner.export_result(store,plan,output)
    assert result['native_execution_rights']is False and owner.inspect_result(output)==view
    with zipfile.ZipFile(output)as archive:
        assert portable_job.parse(archive.read('MANIFEST.json'))['format']==owner.FORMAT_V3
        assert set(archive.namelist())==set(payload)|{'MANIFEST.json'}


@pytest.mark.parametrize('part',('view-family','plan-family','contract-family','backend-family','rights','artifact-member'))
def test_repacked_cross_family_or_execution_claim_is_refused(tmp_path,monkeypatch,part):
    payload,view,plan,_,_=evidence(monkeypatch)
    if part=='view-family':
        view['format']=owner.FORMAT_V2;payload['view.json']=portable_job.canonical(view)
    elif part=='plan-family':
        plan['format']='B63_ORIGINAL_ROOT_PREPARED_SERIAL_PLAN_V2'
        plan['plan_identity']=portable_job.digest(portable_job.canonical({k:v for k,v in plan.items()if k!='plan_identity'}))
        view['plan_identity']=plan['plan_identity'];payload['view.json']=portable_job.canonical(view);payload['plan.json']=portable_job.canonical(plan)
    elif part=='contract-family':
        contract=portable_job.parse(payload['execution-contract.json']);contract['format']='B63_PREPARED_LIFETIME_EXECUTION_CONTRACT_V2'
        payload['execution-contract.json']=portable_job.canonical(contract)
    elif part=='backend-family':
        view['backend_binding']=authority.backend_binding('REFERENCE');payload['view.json']=portable_job.canonical(view)
    elif part=='rights':
        view['native_execution_rights']=True;payload['view.json']=portable_job.canonical(view)
    else:payload['ops_sim/v5/_lifecycle_typed.pyd']=b'NOT_EXECUTABLE'
    path=tmp_path/'repacked.zip';bundle(path,payload)
    with pytest.raises(ValueError):owner.inspect_result(path)


def test_v2_view_does_not_silently_accept_typed_binding(monkeypatch):
    payload,view,_,_,_=evidence(monkeypatch);view['format']=owner.FORMAT_V2
    with pytest.raises(ValueError,match='format family'):owner._view(view)
