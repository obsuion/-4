"""Current bound build + named initial inputs; no mission advancement here."""
from pathlib import Path
from dataclasses import replace
import json
import pytest
from test_spacecraft_design import common,specification
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.spacecraft_project_v2 import SpacecraftProjectV2,materialize_lifecycle_project
from ops_sim.v5.spacecraft_project_v2_document import dumps_project
from ops_sim.v5.general_project_job import GeneralProjectExecution,dumps_named_project,loads_named_project
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.lifecycle_document import dumps_root


@pytest.fixture(scope='module')
def project(common,specification):
    return SpacecraftProjectV2(common,specification,project_source_identity(),'B67 named native project')


@pytest.fixture(scope='module')
def execution():
    raw=(Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes()
    policy=LifetimeCampaignPolicyV2(mode=QUALIFICATION,maximum_primary_segments=2,
        reserved_diagnostic_slots=2,hard_seconds=60,soft_seconds=30,finalization_seconds=30,
        maximum_observed_primary_seconds=124,maximum_diagnostic_seconds=124,maximum_journal_records=128)
    return GeneralProjectExecution(policy,raw)


def test_complete_initial_named_envelope_is_canonical(project,execution):
    raw=dumps_named_project(project,execution)
    p,e=loads_named_project(raw)
    assert dumps_named_project(p,e)==raw
    assert dumps_project(p)==dumps_project(project)
    assert e==execution


@pytest.mark.parametrize('field',('project','backend','extra','version','checkpoint'))
def test_named_envelope_refuses_substitution(project,execution,field):
    value=json.loads(dumps_named_project(project,execution))
    if field=='project':value['project_document']=value['project_document'].replace(project.title,'foreign')
    elif field=='backend':value['execution']['backend']='REFERENCE'
    elif field=='extra':value['execution']['command']=['arbitrary.exe']
    elif field=='version':value['version']=True
    else:value['checkpoint']={'clock':370}
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf8')
    with pytest.raises((ValueError,TypeError)):loads_named_project(raw)


def test_live_native_store_retains_complete_project_and_no_numeric_entry(tmp_path,project,execution):
    from ops_sim.v5.project_store import ProjectStore
    from ops_sim.v5.lifecycle_application import LifecycleWorkspace
    from ops_sim.v5.portable_job import worker_contract
    from ops_sim.v5.lifecycle_typed_platform import admit_typed_build
    native=admit_typed_build(json.loads(execution.build_bytes))
    before=native.native_entry_counts()['total']
    projects=ProjectStore(tmp_path/'projects',project.reference,create=True)
    rec=projects.create(project);projects.preview(rec['project_id'],rec['revision'])
    folder=tmp_path/'workspace';workspace=LifecycleWorkspace(folder,project_store=projects)
    snap=workspace.create_design_project(dict(project_id=rec['project_id'],revision=rec['revision']),execution=execution)
    store=workspace.store(snap['root_identity'])
    expected,_,_=materialize_lifecycle_project(project,ConstructorLedger())
    assert dumps_root(store.root_input)==dumps_root(expected)
    assert store.path('design-project-input.json').read_bytes()==dumps_project(project).encode('utf8')
    assert store.runner_policy==execution.policy
    assert worker_contract(store.directory,Path(__file__).resolve().parents[1])['backend_binding']['selection']==execution.backend
    assert store.jobs()==[] and native.native_entry_counts()['total']==before
    workspace.close()
    reopened=LifecycleWorkspace(folder)
    assert reopened.store(expected.identity).meta['project']==store.meta['project']
    assert reopened.active is None and native.native_entry_counts()['total']==before
    reopened.close()


def test_mutable_or_noncanonical_build_data_cannot_be_execution_option(execution):
    with pytest.raises(ValueError):GeneralProjectExecution(execution.policy,bytearray(execution.build_bytes))
    with pytest.raises(ValueError):GeneralProjectExecution(execution.policy,execution.build_bytes+b'\n')


def test_serial_recipe_requires_exact_nonfast_flags_and_dependency_binding(execution):
    from ops_sim.v5.lifecycle_typed_platform import admit_build_data,SERIAL_BUILD_FORMAT,DEPENDENCIES_PATH
    build=json.loads(execution.build_bytes)
    assert build['format']==SERIAL_BUILD_FORMAT
    assert DEPENDENCIES_PATH in build['support_sources']
    changed=json.loads(execution.build_bytes);changed['compiler']['flags'].remove('-ffp-contract=off')
    with pytest.raises(ValueError):admit_build_data(changed)
    changed=json.loads(execution.build_bytes);changed['support_sources'].pop(DEPENDENCIES_PATH)
    with pytest.raises(ValueError):admit_build_data(changed)


def test_serial_domain_restore_monitor_refuses_nonzero_or_unbalanced_counts(execution):
    from ops_sim.v5.lifecycle_typed_platform import admit_typed_build,admit_native_counts,native_restore_proof
    build=json.loads(execution.build_bytes);native=admit_typed_build(build)
    counts=native.native_entry_counts()
    assert native_restore_proof(counts,counts,build,'b'*64)['total_delta']==0
    changed=json.loads(json.dumps(counts));changed['total']+=1
    with pytest.raises(ValueError):admit_native_counts(changed,build)
    name=next(iter(changed['counts']));changed['counts'][name]+=1
    with pytest.raises(ValueError,match='RESTORE'):native_restore_proof(counts,changed,build,'b'*64)
