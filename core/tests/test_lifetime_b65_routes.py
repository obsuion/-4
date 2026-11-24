"""Versioned B65 server/data routes; Linux fixtures do not claim execution."""
from pathlib import Path
from copy import deepcopy
import json
import pytest
from ops_sim.v5.lifecycle_backend import runtime_binding,canonical
from ops_sim.v5.lifecycle_typed_platform import (admit_build_data,admit_typed_build,LINUX,LINUX_FLAGS,LINUX_CYTHON_WHEEL_SHA256)
from ops_sim.v5 import lifetime_typed_portable as typed
from ops_sim.v5.lifetime_execution_authority import typed_backend_binding,_admit_backend_binding
from kit import serverctl
SOURCE=Path(__file__).resolve().parents[1]
def build():return json.loads((SOURCE/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes())

def linux_fixture():
    from hashlib import sha256
    b=build();r=b['runtime'];r.update(platform='linux',machine='x86_64',ext_suffix='.cpython-314-x86_64-linux-gnu.so',python='3.14.7 SYNTHETIC_CONTRACT_ONLY')
    b['profile']=LINUX;b['artifact']['path']='ops_sim/v5/_lifecycle_typed65'+r['ext_suffix']
    b['compiler']=dict(name='GCC',version='12.2.0',executable_sha256='a'*64,flags=list(LINUX_FLAGS),linker='SYNTHETIC DETACHED CONTRACT FIXTURE; NOT ACTUAL GCC')
    b['cython']['wheel_sha256']=LINUX_CYTHON_WHEEL_SHA256
    b['command']=['/synthetic/gcc',*LINUX_FLAGS,'-I','/synthetic/headers','/synthetic/source.c','-o','/synthetic/module.so']
    b['capabilities'].update(platform='linux',python_version=r['python'],module_basename=Path(b['artifact']['path']).name)
    b['capability_sha256']=sha256(canonical(b['capabilities'])).hexdigest()
    return b

def test_separate_linux_detached_profile_and_foreign_actual_runtime_refusal():
    fixture=linux_fixture();assert admit_build_data(fixture)['profile']==LINUX
    with pytest.raises(ValueError,match='ABI/runtime'):admit_typed_build(fixture)

@pytest.mark.parametrize('change',['wheel','flags','type','suffix','version','machine'])
def test_linux_fixture_requires_its_exact_contract(change):
    b=linux_fixture()
    if change=='wheel':b['cython']['wheel_sha256']='b'*64
    if change=='flags':b['compiler']['flags'].append('-ffast-math')
    if change=='type':b['runtime']['python']=3147
    if change=='suffix':b['runtime']['ext_suffix']='.so'
    if change=='version':b['compiler']['version']='11.0.0'
    if change=='machine':b['runtime']['machine']='aarch64'
    with pytest.raises(ValueError):admit_build_data(b)

def test_backend_binding_is_new_exact_family_and_cannot_masquerade_as_b64():
    b=build();v=typed_backend_binding('B65_TYPED_EXECUTION_V2',b)
    assert v['format']=='B65_TYPED_BACKEND_EXECUTION_BINDING_V2';_admit_backend_binding(v)
    v['format']='B64_TYPED_BACKEND_EXECUTION_BINDING_V1'
    with pytest.raises(ValueError):_admit_backend_binding(v)

def test_real_typed_server_capability_reports_actual_pilot_and_no_long_qualification():
    value=serverctl.typed_capability(SOURCE,build())
    assert value['backend']=='B65_TYPED_EXECUTION_V2'
    assert value['ready_for_pilot']==(value['doctor']['ready_for_engine_attempt']and build()['profile']==LINUX)
    assert value['long_dispatch']is False;assert value['checkpoint_migration']is False

def test_typed_package_shell_cannot_retag_family():
    shell=dict(format=typed.JOB_V4,entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False,
        contract=dict(format=typed.FORMAT_V4,backend_binding=dict(selection='B65_TYPED_EXECUTION_V2')))
    for k in typed.JOB_FIELDS:shell.setdefault(k,None)
    typed._job_shell(shell)
    shell['format']=typed.JOB_V3
    with pytest.raises(ValueError,match='family'):typed._job_shell(shell)

def test_linux_acceptance_has_no_manual_approved_flag(tmp_path):
    from ops_sim.v5.lifetime_typed_acceptance import admit
    p=tmp_path/'fake.json';p.write_text('{"approved":true}')
    with pytest.raises((ValueError,KeyError)):admit(p,dict(source_manifest_sha256='b'*64))

def test_typed_server_plan_roundtrips_current_accounted_initial_input(tmp_path):
    from dataclasses import asdict
    from lifetime_support import root_for
    from ops_sim.v5.lifecycle_document import dumps_root
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION
    source=tmp_path/'initial.json';source.write_bytes(dumps_root(root_for(600)))
    policy=LifetimeCampaignPolicyV2(mode=QUALIFICATION,maximum_primary_segments=2,reserved_diagnostic_slots=1,
        hard_seconds=60,soft_seconds=8,finalization_seconds=52,
        maximum_observed_primary_seconds=124,maximum_diagnostic_seconds=62)
    plan=tmp_path/'plan.json'
    value=serverctl.make_plan(SOURCE,source,plan,seconds=600,policy=asdict(policy),rate='0.1',currency='USD',max_cost='10',
        backend='B65_TYPED_EXECUTION_V2',build=build())
    assert value['format']==serverctl.FORMAT_V3
    assert serverctl.load_plan(plan,SOURCE)==value


def test_b65_v4_pilot_stop_contract_uses_typed_admission():
    from lifetime_support import root_for
    from ops_sim.v5.lifecycle_pilot_stop import _contract_binding
    root=root_for(600)
    contract=typed.execution_contract_v3(root,SOURCE,'B60_SEALED_STATIC_V1',backend='B65_TYPED_EXECUTION_V2',build=build())
    assert contract['format']==typed.FORMAT_V4
    binding=_contract_binding(contract,root)
    assert binding['root_identity']==root.identity
    assert binding['source_manifest_sha256']==contract['source_manifest_sha256']
    bad=deepcopy(contract);bad['backend_binding']['selection']='B64_TYPED_EXECUTION_V1'
    with pytest.raises(ValueError):_contract_binding(bad,root)
