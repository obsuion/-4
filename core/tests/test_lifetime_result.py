from copy import deepcopy
from pathlib import Path
import zipfile,pytest
from ops_sim.v5.lifetime_result import FORMAT,inspect_result
from ops_sim.v5.portable_job import canonical,digest,inspect_result as workbench_inspect

def bundle(path,edit=None):
    # Synthetic empty-prefix reader fixture using frozen B62 transport DATA.
    # The historical producer must NOT acquire the expanded B63 membership.
    # No current-source mission or old-native migration is claimed here.
    import json
    fixture=json.loads((Path(__file__).parent/'fixtures/lifetime_readonly_actual.json').read_bytes())
    frozen={k:x.encode('utf8')for k,x in fixture['payload'].items()}
    raw=frozen['input.json'];c=json.loads(frozen['execution-contract.json']);p=json.loads(frozen['plan.json'])
    v=dict(format=FORMAT,root_identity=c['root_identity'],input_sha256=digest(raw),source_manifest_sha256=c['source_manifest_sha256'],execution_contract_sha256=digest(canonical(c)),plan_identity=p['plan_identity'],requested_end_seconds=p['root_target'],actual_end_seconds=p['original_anchor'],read_only=True,native_execution_rights=False,backup_required_for_resume=True,primary_totals=None,monthly_environment=[],monthly_actual=[],cumulative_work=None,jobs=[],scope='LATEST_FORWARD_PRIMARY_ACTUAL_PREFIX_DIAGNOSTICS_NEVER_ADDED')
    if edit:edit(v)
    payload={'input.json':raw,'execution-contract.json':canonical(c),'plan.json':canonical(p),'view.json':canonical(v)}
    m={n:dict(bytes=len(b),sha256=digest(b))for n,b in payload.items()}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as z:
        z.writestr('MANIFEST.json',canonical(dict(format=FORMAT,files=m)))
        for n,b in payload.items():z.writestr(n,b)
    return v

def test_exact_readonly_schema_and_workbench_consumer(tmp_path):
    p=tmp_path/'readonly.zip';v=bundle(p)
    assert inspect_result(p)==workbench_inspect(p)==v
    assert v['native_execution_rights']is False

@pytest.mark.parametrize('edit',[lambda v:v.update(native_execution_rights=True),lambda v:v.update(unexpected='x'),lambda v:v.update(monthly_actual=[{}]),lambda v:v.update(actual_end_seconds=9999),lambda v:v.update(scope='MERGE_DIAGNOSTIC_CREDITS')])
def test_no_execution_or_arbitrary_schema_claims(tmp_path,edit):
    p=tmp_path/'bad.zip';bundle(p,edit)
    with pytest.raises(ValueError):inspect_result(p)

def test_crc_and_hash_failure_preserved(tmp_path):
    p=tmp_path/'bad.zip';bundle(p)
    with zipfile.ZipFile(p,'a')as z:z.writestr('extra.py',b'raise AssertionError()')
    with pytest.raises(ValueError):inspect_result(p)

@pytest.mark.parametrize('bad',[{'unexpected':'not typed terminal'},True,[],{'format':'B59_TYPED_TERMINAL_V1'}])
def test_nested_terminal_schema_cannot_be_an_arbitrary_payload(tmp_path,bad):
    from ops_sim.v5.lifetime_result import _view
    p=tmp_path/'data.zip';v=bundle(p)
    v['jobs']=[dict(job_id='d'*32,role='PRIMARY',status='UNKNOWN',terminal=bad,clock=None,scientific_file=None,scientific_sha256=None)]
    with pytest.raises(ValueError):_view(v)

def test_false_central_directory_count_is_bounded_before_zipfile(tmp_path):
    import struct
    p=tmp_path/'bad.zip';bundle(p);raw=bytearray(p.read_bytes())
    struct.pack_into('<H',raw,len(raw)-14,2);struct.pack_into('<H',raw,len(raw)-12,2);p.write_bytes(raw)
    with pytest.raises(ValueError,match='directory'):inspect_result(p)

def actual_bundle(path,edit=None):
    import json
    fixture=json.loads((Path(__file__).parent/'fixtures/lifetime_readonly_actual.json').read_bytes())
    payload={k:x.encode('utf8')for k,x in fixture['payload'].items()}
    if edit:
        view=json.loads(payload['view.json']);edit(view);payload['view.json']=canonical(view)
    manifest={n:dict(bytes=len(b),sha256=digest(b))for n,b in payload.items()}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as z:
        z.writestr('MANIFEST.json',canonical(dict(format=FORMAT,files=manifest)))
        for n,b in payload.items():z.writestr(n,b)

def test_saved_actual_v7_mission_native_continuation_result_consumed_readonly(tmp_path):
    p=tmp_path/'actual.zip';actual_bundle(p);v=inspect_result(p)
    assert v['actual_end_seconds']==7328 and v['primary_totals']['credits']==1
    assert v['cumulative_work']['transitions_completed']==225
    assert not v['native_execution_rights']

@pytest.mark.parametrize('edit',[lambda v:v['primary_totals'].update(credits=2),lambda v:v['cumulative_work'].update(transitions_completed=0),lambda v:v['monthly_actual'][0].update(end_energy_wh=0.),lambda v:v['jobs'][0].update(terminal={'not':'typed'}),lambda v:v['monthly_environment'][0]['paid_work_end'].update(unknown={})])
def test_actual_rows_work_and_credit_cannot_be_relabelled_by_rehash(tmp_path,edit):
    p=tmp_path/'bad-actual.zip';actual_bundle(p,edit)
    with pytest.raises(ValueError):inspect_result(p)

@pytest.mark.parametrize('property_name',['pv_retention','pv_exposure_seconds'])
def test_terminal_partial_environment_bound_even_without_a_full_month(tmp_path,property_name):
    def edit(v):
        for e in(v['monthly_environment'][0],v['monthly_actual'][0]['lifetime_environment']):
            e['environment']['end'][property_name]=.1
    p=tmp_path/'bad-partial.zip';actual_bundle(p,edit)
    with pytest.raises(ValueError,match='partial environment'):inspect_result(p)


def bundle_v2(path,edit=None):
    """Synthetic new read-only DATA; never a current-source measured mission."""
    import json
    from dataclasses import asdict
    from ops_sim.v5.lifecycle_document import loads_root
    from ops_sim.v5.project_store import runtime_identity
    from ops_sim.v5.lifetime_policy import admit_policy,LifetimeCampaignPolicyV2,METHOD_V2
    from ops_sim.v5.lifetime_execution_authority import make_authority,backend_binding
    from ops_sim.v5.lifetime_result import FORMAT_V2
    from ops_sim.v5.lifetime_portable import FORMAT_V2 as CONTRACT_V2
    old=path.with_name(path.stem+'-old.zip');bundle(old)
    with zipfile.ZipFile(old)as archive:payload={name:archive.read(name)for name in archive.namelist()if name!='MANIFEST.json'}
    raw=payload['input.json'];root=loads_root(raw)
    c=json.loads(payload['execution-contract.json']);plan=json.loads(payload['plan.json']);view=json.loads(payload['view.json'])
    oldpolicy=admit_policy(plan['policy']);policy=LifetimeCampaignPolicyV2(**dict(asdict(oldpolicy),method=METHOD_V2))
    c.update(format=CONTRACT_V2,producer='M8_B63_PREPARED_CURRENT_SOURCE_PRODUCER_V2',
        runtime=runtime_identity(),backend_binding=backend_binding(),native_build=None,
        execution_authority='B63_IMMUTABLE_PILOT_OR_GENUINE_LONG_V1',
        publication_work='B63_BOUNDED_STATUS_DETAILS_PRECHARGED_V1')
    permission=make_authority(root,raw,c,policy)
    authority_raw=canonical(permission);contract_sha=digest(canonical(c));authority_sha=digest(authority_raw)
    plan.update(format='B63_ORIGINAL_ROOT_PREPARED_SERIAL_PLAN_V2',runtime=c['runtime'],
        policy=asdict(policy),policy_identity=policy.identity,execution_contract_sha256=contract_sha,
        execution_authority_sha256=authority_sha,backend_binding=c['backend_binding'],
        pool_inventory='B63_VERIFIED_IMMUTABLE_INITIAL_FILES_ONLY_V1')
    plan['plan_identity']=digest(canonical({k:v for k,v in plan.items()if k!='plan_identity'}))
    view.update(format=FORMAT_V2,execution_contract_sha256=contract_sha,plan_identity=plan['plan_identity'],
        execution_authority_sha256=authority_sha,backend_binding=c['backend_binding'])
    payload.update({'execution-contract.json':canonical(c),'plan.json':canonical(plan),
                    'view.json':canonical(view),'execution-authority.json':authority_raw})
    if edit:edit(payload)
    manifest={name:dict(bytes=len(data),sha256=digest(data))for name,data in payload.items()}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as archive:
        archive.writestr('MANIFEST.json',canonical(dict(format=FORMAT_V2,files=manifest)))
        for name,data in payload.items():archive.writestr(name,data)
    return view


def test_new_readonly_result_data_has_no_backend_or_dispatch_authority(tmp_path,monkeypatch):
    from ops_sim.v5 import lifetime_execution_authority as authority,lifecycle_backend
    called=[]
    def forbidden(*args,**kwargs):called.append((args,kwargs));raise AssertionError('read-only attempted execution admission')
    monkeypatch.setattr(authority,'admit_long_evidence',forbidden)
    monkeypatch.setattr(lifecycle_backend,'admit_native_build',forbidden)
    path=tmp_path/'readonly-v2.zip';view=bundle_v2(path)
    assert inspect_result(path)==view and view['native_execution_rights']is False
    assert called==[]


@pytest.mark.parametrize('edit',[
    lambda payload:payload.__setitem__('execution-authority.json',b'{}'),
    lambda payload:payload.__setitem__('native.pyd',b'not an executable authority'),
    lambda payload:payload.__setitem__('execution-contract.json',payload['execution-contract.json'].replace(b'"native_build":null',b'"native_build":true')),
])
def test_new_readonly_rehashed_foreign_authorities_and_native_members_rejected(tmp_path,edit):
    path=tmp_path/'bad-v2.zip';bundle_v2(path,edit)
    with pytest.raises(ValueError):inspect_result(path)
