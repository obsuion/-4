"""Parent operation reuse keeps full admission, live pins and fresh job checks.

The declared build is DATA only. These tests do not import a native artifact,
launch a worker, build a model or evolve a numerical prefix.
"""
from copy import copy, deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import pickle
import sys
import threading
import gc
import weakref

import pytest

from ops_sim.v5 import lifetime_typed_portable as owner, portable_job
from test_lifecycle_typed_backend import receipt
from lifetime_support import root_for


@pytest.fixture
def package(tmp_path, monkeypatch, request):
    from ops_sim.v5 import lifetime_source, lifecycle_backend
    from ops_sim.v5.lifecycle_application import LifecycleStore, make_intent, _write_new
    from ops_sim.v5.lifecycle_compact import PublicationProfile
    from ops_sim.v5.lifecycle_document import dumps_root
    from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
    from ops_sim.v5.lifetime_campaign import horizon_preflight
    from ops_sim.v5.lifetime_execution_authority import make_authority
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2, QUALIFICATION, METHOD_V2, METHOD_NO_LAUNCH
    source=tmp_path/'source';source.mkdir()
    build=receipt()
    for binding in (build['artifact'],build['engine_source'],build['generated_c'],*build['support_sources'].values()):
        path=source/binding['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x')
        binding['bytes']=1;binding['sha256']=sha256(b'x').hexdigest()
    (source/'requirements.txt').write_bytes(b'pytest==METADATA_ONLY\n')
    manifest=portable_job.source_manifest(source)
    requirements=dict(python_major_minor=[sys.version_info.major,sys.version_info.minor],
        requirements_sha256=portable_job.file_digest(source/'requirements.txt'),
        dependency_versions={'pytest':'METADATA_ONLY'},dependencies='PINNED_REQUIREMENTS_TXT_NOT_BUNDLED_OR_AUTOINSTALLED')
    def current_requirements(path):
        result=deepcopy(requirements)
        result['requirements_sha256']=portable_job.file_digest(Path(path)/'requirements.txt')
        return result
    monkeypatch.setattr(owner,'runtime_requirements',current_requirements)
    monkeypatch.setattr(portable_job,'runtime_requirements',current_requirements)
    monkeypatch.setattr(lifetime_source,'B64_SOURCE_PATHS',tuple(manifest))
    monkeypatch.setattr(lifecycle_backend,'runtime_binding',lambda:deepcopy(build['runtime']))
    root=root_for(600);raw=dumps_root(root)
    policy=LifetimeCampaignPolicyV2(method=METHOD_NO_LAUNCH if getattr(request,'param',None)=='NO_LAUNCH'else METHOD_V2,
        mode=QUALIFICATION,maximum_primary_segments=2,
        reserved_diagnostic_slots=1,hard_seconds=60,soft_seconds=8,finalization_seconds=52)
    contract=owner.execution_contract_v3(root,source,owner.FAST,backend=build['execution_domain'],build=build)
    authority=make_authority(root,raw,contract,policy,backend=build['execution_domain'],build=build)
    profile=PublicationProfile()
    intent=make_intent(root.identity,key='a'*32,execution_seconds=policy.hard_seconds,
        maximum_output_bytes=policy.maximum_output_bytes,
        execution_budget=ExecutionBudget(policy.hard_seconds,policy.soft_seconds,policy.finalization_seconds),
        publication_profile=profile)
    job=dict(format=owner.JOB_V3,contract=contract,intent=intent,horizon=horizon_preflight(root,policy),
        requirements=requirements,lifetime_policy=asdict(policy),
        limits=dict(rss_bytes=policy.maximum_rss_bytes,native_bytes=policy.maximum_native_bytes,
            job_bytes=policy.maximum_output_bytes,slots=policy.maximum_jobs),
        entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False,execution_authority=authority)
    store=LifecycleStore(tmp_path/'store',root,create=True,runner_policy=policy,
        publication_profile=profile,execution_authority=authority)
    _write_new(store.path('portable-execution.json'),contract)
    _write_new(store.path('portable-job.json'),job)
    _write_new(store.path('lifetime-native-build.json'),build)
    yield SimpleNamespace(store=store,source=source,raw=raw,contract=contract,job=job,build=build)
    store.close_publications()


def count_admissions(monkeypatch):
    original=owner._admit_input;calls=[]
    def counted(*args,**kwargs):
        calls.append(args[0])
        return original(*args,**kwargs)
    monkeypatch.setattr(owner,'_admit_input',counted)
    return calls


def test_parent_reuses_one_strict_admission_and_returns_detached_contract_data(package, monkeypatch):
    calls=count_admissions(monkeypatch)
    with owner.parent_contract_operation(package.store.directory,package.source,operation='PARENT_PREFLIGHT') as operation:
        first=portable_job.worker_contract(package.store.directory,package.source,operation=operation)
        first['root_identity']='0'*64
        assert portable_job.worker_contract(package.store.directory,package.source,operation=operation)==package.contract
        assert owner.parent_operation_root(operation,package.store.directory,package.source,package.raw) is operation.root
        receipt_data=operation.receipt()
        assert receipt_data['raw_admissions']==1 and receipt_data['contract_reuses']==3
    assert len(calls)==1
    with pytest.raises(ValueError,match='parent operation'):
        portable_job.worker_contract(package.store.directory,package.source,operation=operation)
    with owner.parent_contract_operation(package.store.directory,package.source,operation='FRESH_REOPEN') as fresh:
        assert fresh is not operation
        assert portable_job.worker_contract(package.store.directory,package.source,operation=fresh)==package.contract
    assert len(calls)==2


def test_store_scope_is_explicit_nested_and_does_not_leave_a_cache(package, monkeypatch):
    calls=count_admissions(monkeypatch)
    with owner.store_contract_operation(package.store,package.source,operation='PARENT_SUBMIT') as operation:
        assert portable_job.worker_contract_for_store(package.store,package.source)==package.contract
        with owner.store_contract_operation(package.store,package.source,operation='PREPARE_JOB') as nested:
            assert nested is operation
            assert portable_job.worker_contract_for_store(package.store,package.source)==package.contract
        assert len(calls)==1
    assert package.store._parent_contract_local.operation is None
    assert portable_job.worker_contract_for_store(package.store,package.source)==package.contract
    assert len(calls)==2


@pytest.mark.parametrize('name',('input.json','portable-execution.json','portable-job.json',
    'store.json','execution-authority.json','lifetime-native-build.json'))
def test_current_immutable_file_drift_permanently_invalidates_even_after_bytes_restore(package,name):
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='PIN_CHECK').__enter__()
    path=package.store.directory/name;raw=path.read_bytes()
    try:
        path.write_bytes(raw+b' ')
        with pytest.raises(ValueError,match='immutable file bytes drift'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
        path.write_bytes(raw)
        with pytest.raises(ValueError,match='parent operation'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
    finally:
        path.write_bytes(raw);operation.close()


@pytest.mark.parametrize('change',('changed_source','extra_source','new_optional_metadata'))
def test_current_source_membership_and_optional_immutable_presence_are_live(package,change):
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='SOURCE_CHECK').__enter__()
    path=(package.source/package.build['engine_source']['path'] if change=='changed_source' else
        package.source/'unexpected.py' if change=='extra_source' else package.store.directory/'lifetime-plan.json')
    raw=path.read_bytes() if path.exists() else None
    try:
        path.write_bytes(b'changed')
        with pytest.raises(ValueError,match='source/build/runtime drift|immutable file bytes drift'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
    finally:
        if raw is None:path.unlink()
        else:path.write_bytes(raw)
        operation.close()


@pytest.mark.parametrize('change',('input_root','store_root','generation','consumer_code','callback_closure'))
def test_mutable_root_generation_or_callback_cannot_reuse_parent_admission(package,monkeypatch,change):
    from ops_sim.v5 import lifecycle_generation, lifecycle_application
    closure=None
    if change=='callback_closure':
        original=lifecycle_application.validate_intent
        def wrapper(value):return original(value)
        monkeypatch.setattr(lifecycle_application,'validate_intent',wrapper)
        closure=wrapper.__closure__[0]
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='DYNAMIC_CHECK').__enter__()
    operation.validate_store(package.store)
    restore=lambda:None
    try:
        if change=='input_root':
            root=operation._root;old=root.duration_seconds
            object.__setattr__(root,'duration_seconds',old+1)
            restore=lambda:object.__setattr__(root,'duration_seconds',old)
        elif change=='store_root':
            old=package.store.root_input;package.store.root_input=operation._root
            restore=lambda:setattr(package.store,'root_input',old)
        elif change=='generation':
            monkeypatch.setattr(lifecycle_generation._Generation,'cheap',lambda *args:True)
        elif change=='consumer_code':
            original=owner._ParentContractOperation._check.__code__
            owner._ParentContractOperation._check.__code__=(lambda self,directory,source:None).__code__
            restore=lambda:setattr(owner._ParentContractOperation._check,'__code__',original)
        else:
            original=closure.cell_contents;closure.cell_contents=lambda value:value
            restore=lambda:setattr(closure,'cell_contents',original)
        with pytest.raises((ValueError,TypeError),match='drift|generation|parent'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
    finally:restore();operation.close()


def test_callback_invalidation_is_permanent_and_never_falls_back(package):
    with owner.store_contract_operation(package.store,package.source,operation='CALLBACK_BOUNDARY') as operation:
        operation.invalidate()
        with pytest.raises(ValueError,match='parent operation'):
            portable_job.worker_contract_for_store(package.store,package.source)


@pytest.mark.parametrize('kind',('copy','deepcopy','pickle','saved_receipt','other_directory','other_source','raw_mismatch'))
def test_parent_authority_is_not_transferable_or_reconstructible(package,tmp_path,kind):
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='TRANSFER_CHECK').__enter__()
    try:
        with pytest.raises((ValueError,TypeError)):
            if kind=='copy':copy(operation)
            elif kind=='deepcopy':deepcopy(operation)
            elif kind=='pickle':pickle.dumps(operation)
            elif kind=='saved_receipt':portable_job.worker_contract(package.store.directory,package.source,operation=operation.receipt())
            elif kind=='other_directory':portable_job.worker_contract(tmp_path/'other',package.source,operation=operation)
            elif kind=='other_source':portable_job.worker_contract(package.store.directory,tmp_path/'other',operation=operation)
            else:owner.parent_operation_root(operation,package.store.directory,package.source,package.raw+b' ')
    finally:operation.close()


def test_other_thread_refuses_instead_of_borrowing_owner(package):
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='THREAD_CHECK').__enter__()
    errors=[]
    def foreign():
        try:portable_job.worker_contract(package.store.directory,package.source,operation=operation)
        except (ValueError,TypeError) as error:errors.append(error)
    thread=threading.Thread(target=foreign);thread.start();thread.join(10)
    try:
        assert not thread.is_alive() and len(errors)==1
        # A rejected foreign use revokes rather than turning into a main-thread
        # cached permission when the caller returns.
        with pytest.raises(ValueError,match='parent operation'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
    finally:operation.close()


def test_current_job_request_and_pin_are_never_cached(package):
    from ops_sim.v5.lifecycle_application import _job_format
    jid='b'*32;folder=package.store.directory/'jobs'/jid;folder.mkdir(parents=True)
    request=dict(format=_job_format(package.job['intent']),job_id=jid,intent=package.job['intent'],
        root_identity=package.contract['root_identity'],source_identity=package.store.meta['source_identity'],
        runtime=deepcopy(package.store.meta['runtime']),input_sha256=package.contract['input_sha256'],resume=None)
    raw=portable_job.canonical(request);(folder/'request.json').write_bytes(raw)
    (folder/'portable-contract-binding.json').write_bytes(portable_job.canonical(portable_job.job_pin(package.contract,jid)))
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='REQUEST_CHECK').__enter__()
    try:
        assert portable_job.worker_contract(package.store.directory,package.source,operation=operation,
            job_id=jid,request_sha256=sha256(raw).hexdigest())==package.contract
        request['runtime']['python']='swapped runtime'
        changed=portable_job.canonical(request);(folder/'request.json').write_bytes(changed)
        with pytest.raises(ValueError,match='exact request context'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation,
                job_id=jid,request_sha256=sha256(changed).hexdigest())
    finally:operation.close()


def test_missing_or_legacy_package_scope_does_not_change_legacy_worker_route(tmp_path):
    store=SimpleNamespace(directory=tmp_path)
    with owner.store_contract_operation(store,tmp_path,operation='LEGACY_READ') as operation:
        assert operation is None
    (tmp_path/'portable-job.json').write_bytes(portable_job.canonical(dict(format=portable_job.LIFETIME_JOB)))
    with owner.store_contract_operation(store,tmp_path,operation='LEGACY_READ') as operation:
        assert operation is None
    assert not hasattr(store,'_parent_contract_local')


def test_added_attribute_dispatch_cannot_intercept_the_guard(package,monkeypatch):
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='DESCRIPTOR_CHECK').__enter__()
    path=package.store.directory/'input.json';raw=path.read_bytes()
    def foreign_getattribute(self,name):
        if name=='_guard':return lambda *args:None
        return object.__getattribute__(self,name)
    try:
        monkeypatch.setattr(owner._ParentContractOperation,'__getattribute__',foreign_getattribute,raising=False)
        path.write_bytes(raw+b' ')
        with pytest.raises(ValueError,match='class/layout/descriptor drift'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
    finally:path.write_bytes(raw);operation.close()


def test_failed_store_binding_permanently_revokes_instead_of_rebinding(package):
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='STORE_CHECK').__enter__()
    try:
        with pytest.raises(TypeError,match='exact parent lifecycle store'):
            operation.validate_store(SimpleNamespace())
        with pytest.raises(ValueError,match='parent operation'):
            operation.validate_store(package.store)
    finally:operation.close()


@pytest.mark.parametrize('field',('_runtime','_phase','_generation'))
def test_foreign_comparison_objects_are_refused_without_running_equality(package,field):
    class Foreign:
        def __eq__(self,other):raise AssertionError('foreign equality dispatched')
        def __ne__(self,other):raise AssertionError('foreign equality dispatched')
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='SCALAR_CHECK').__enter__()
    saved=getattr(operation,field)
    try:
        setattr(operation,field,Foreign())
        with pytest.raises((ValueError,TypeError),match='parent operation'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
    finally:
        if field=='_runtime':operation._runtime=saved
        operation.close()


def test_shared_constructor_root_uses_the_existing_admission_seal(package,monkeypatch):
    from ops_sim.v5 import lifecycle_application as application
    # Keep the installed-source seam realistic while the build remains inert
    # DATA in this isolated source tree.
    monkeypatch.setattr(application,'__file__',str(package.source/'ops_sim/v5/lifecycle_application.py'))
    LifecycleStore=application.LifecycleStore
    with owner.parent_contract_operation(package.store.directory,package.source,operation='REOPEN') as operation:
        store=LifecycleStore(package.store.directory,parent_contract_operation=operation)
        try:
            operation.validate_store(store)
            assert store.root_input is operation._root
            assert operation._store_binding[2] is None
            assert portable_job.worker_contract(package.store.directory,package.source,operation=operation)==package.contract
        finally:store.close_publications()


@pytest.mark.parametrize('outcome',('normal','revoked','body_error'))
def test_parent_close_releases_private_graphs_without_cyclic_gc(package,outcome):
    from ops_sim.v5.lifecycle_application import LifecycleStore
    was_enabled=gc.isenabled();gc.disable()
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='RELEASE_CHECK').__enter__()
    try:
        # A second read-only view is owned only by the active operation after
        # this local is dropped; the fixture keeps its different original store.
        view=LifecycleStore(package.store.directory)
        operation.validate_store(view)
        store_ref=weakref.ref(view);del view
        admission=operation._admission
        root_seal_ref=weakref.ref(admission._root_seal)
        schema_ref=weakref.ref(admission._schema)
        assert store_ref() is not None and root_seal_ref() is not None
        if outcome=='revoked':operation.invalidate()
        primary=LookupError('body failure') if outcome=='body_error' else None
        assert operation.__exit__(None if primary is None else type(primary),primary,None) is False
        # Keep both retired capability objects alive: release must not depend
        # on their own destruction, gc.collect(), or the next collection cycle.
        assert operation._root is operation._admission is operation._callables is None
        assert operation._store_binding is None and operation._self is None and operation._pins==()
        assert admission._phase=='RETIRED_PARENT' and admission._self is None and admission._binding==()
        assert store_ref() is None and root_seal_ref() is None and schema_ref() is None
        with pytest.raises(ValueError,match='parent operation'):
            portable_job.worker_contract(package.store.directory,package.source,operation=operation)
        with pytest.raises(ValueError,match='input admission'):
            admission._guard(None)
        with pytest.raises(ValueError,match='entry scope'):
            operation.__enter__()
        operation.close() # Already closed cleanup remains safe and graph-free.
    finally:
        operation.close()
        if was_enabled:gc.enable()


def test_parent_entry_failure_releases_returned_admission(package,monkeypatch):
    original=owner.admit_worker_package_v3;observed=[]
    def admitted(*args,**kwargs):
        result=original(*args,**kwargs)
        observed.append((result[2],weakref.ref(result[2]._root_seal),weakref.ref(result[2]._schema)))
        return result
    def refuse_seal(self):raise LookupError('injected post-admission seal failure')
    monkeypatch.setattr(owner,'admit_worker_package_v3',admitted)
    monkeypatch.setattr(owner._ControlCallables,'__init__',refuse_seal)
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='ENTRY_RELEASE')
    with pytest.raises(LookupError,match='post-admission seal failure'):
        operation.__enter__()
    admission,root_seal_ref,schema_ref=observed[0]
    assert operation._phase=='CLOSED' and operation._admission is operation._root is None
    assert admission._phase=='RETIRED_PARENT' and admission._binding==() and admission._self is None
    assert root_seal_ref() is None and schema_ref() is None


def test_parent_exit_preserves_primary_when_close_also_fails(package,monkeypatch):
    operation=owner.parent_contract_operation(package.store.directory,package.source,operation='CLOSE_FAILURE').__enter__()
    original_close=owner._ParentContractOperation.close
    primary=LookupError('original body failure')
    def refuse_close(self):raise OSError('injected secondary release failure')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(owner._ParentContractOperation,'close',refuse_close)
            assert operation.__exit__(LookupError,primary,None) is False
        assert isinstance(primary.secondary_close_failure,OSError)
        assert any('secondary parent close failure' in note for note in primary.__notes__)
    finally:original_close(operation)


@pytest.fixture
def control_package(package,monkeypatch):
    from ops_sim.v5 import lifetime_supervisor
    from ops_sim.v5.lifecycle_application import _write_new
    plan=lifetime_supervisor._plan(package.store,package.contract)
    _write_new(package.store.path('lifetime-plan.json'),plan)
    monkeypatch.setattr(lifetime_supervisor,'source_root',lambda:package.source)
    # The isolated declared-build fixture deliberately has a tiny fake source.
    # Its real manifest/build hashes remain checked; display identity comes
    # from the store created by the actual constructor fixture.
    monkeypatch.setattr(owner,'_metadata_source_identity',lambda manifest:package.store.meta['source_identity'])
    return package


def forbid_scientific_control_admission(monkeypatch):
    from ops_sim.v5 import lifecycle_document,lifecycle_execution,lifetime_execution_authority,lifetime_supervisor
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append(True)
        raise AssertionError('public DATA control performed scientific admission')
    for module,name in ((owner,'_admit_input'),(owner,'admit_worker_package_v3'),
            (lifecycle_document,'loads_root'),(lifecycle_execution,'build_model'),
            (lifetime_execution_authority,'admit_authority'),(lifetime_execution_authority,'admit_store_execution'),
            (lifetime_supervisor,'_store')):
        monkeypatch.setattr(module,name,forbidden)
    return calls


def saved_control_job(package,*,jid='b'*32,intent=None,status='RUNNING',clock=None,launch=None,checkpoint_method=None):
    """Publish real compact control DATA; no native graph or model is made."""
    from ops_sim.v5 import lifecycle_application as application,lifetime_status,lifecycle_compact
    from ops_sim.v5.battery_terminal import make_terminal,bind_terminal
    intent=deepcopy(package.job['intent']if intent is None else intent)
    folder=package.store.path('jobs',jid);folder.mkdir(parents=True)
    request=dict(format=application._job_format(intent),job_id=jid,intent=intent,
        root_identity=package.contract['root_identity'],source_identity=package.store.meta['source_identity'],
        runtime=deepcopy(package.store.meta['runtime']),input_sha256=package.contract['input_sha256'],resume=None)
    if intent['parent_job_id']is not None:
        request['resume']=dict(parent_job_id=intent['parent_job_id'],checkpoint=dict(sha256=intent['snapshot_sha256'],clock=300))
    raw=portable_job.canonical(request);(folder/'request.json').write_bytes(raw)
    (folder/'portable-contract-binding.json').write_bytes(portable_job.canonical(portable_job.job_pin(package.contract,jid)))
    job=dict(request,publication_sequence=0,status=status,reason=None,progress=None,checkpoints=[],result=None,
        launch=launch,ownership_valid=None,created_utc='2026-10-24T00:00:00Z',worker_artifact_bytes=None)
    if clock is not None:
        root=package.store.root_input;profile=package.store.publication_profile;policy=root.output_policy
        frontier=dict(format=lifecycle_compact.FRONTIER,profile=asdict(profile),profile_identity=profile.identity,
            policy=asdict(policy),policy_identity=policy.identity,maximum_bytes=policy.events_total_bytes,
            start_record=0,end_record=0,records=0,sealed_chunks=0,sealed_bytes=0,sealed_decoded_bytes=0,
            index_bytes=0,index_sha256=sha256(b'').hexdigest(),index_chain='0'*64,current=None,writer_failed=False,
            work=dict.fromkeys(lifecycle_compact.WORK,0),codec=dict(dict.fromkeys(lifecycle_compact.CODEC,0),codec_reserved_units=65536))
        checkpoint=dict(file='checkpoint-00000001.json',sha256='e'*64,bytes=1,clock=clock,kind='FINAL',
            bindings=dict(root_identity=root.identity,source_identity=job['source_identity'],runtime=deepcopy(job['runtime']),
                method=root.method if checkpoint_method is None else checkpoint_method,input_sha256=job['input_sha256'],clock=clock,grid_identity='f'*64))
        publication=dict(format=application.PUBLICATION54,root_identity=root.identity,native_checkpoint_sha256=checkpoint['sha256'],
            application_work=dict.fromkeys((*application.PUBLICATION_FIELDS53,'stream_codec_reserved_units'),0),
            stream_charges={name:dict(encoded_bytes_reserved=0,reservation_attempts=0,codec_reserved_units=0)for name in application.STREAM_NAMES54},
            scope='BEFORE_CHECKPOINT_PROGRESS_PUBLICATION',publication_profile_identity=profile.identity,
            stream_frontiers={name:deepcopy(frontier)for name in ('events','months','details')})
        content=portable_job.canonical(publication);leaf='checkpoint-00000001-publication.json';(folder/leaf).write_bytes(content)
        checkpoint['publication']=dict(file=leaf,sha256=sha256(content).hexdigest(),bytes=len(content))
        terminal=make_terminal('TARGET','BOUND_TARGET_REACHED','COMMITTED_BOUNDARY','lifecycle_execution',clock)
        result=dict(checkpoint=checkpoint,clock=clock,actual_end_seconds=clock,target_seconds=clock,
            application_status='COMPLETED_WINDOW',status='COMPLETE',reason=terminal['code'])
        result['typed_terminal']=bind_terminal(terminal,job,checkpoint)
        job.update(status='COMPLETED',reason=terminal['code'],result=result,typed_stop=terminal)
    binding=lifetime_status.make_binding(request,sha256(raw).hexdigest(),package.store.publication_profile.identity,package.store.runner_policy.identity)
    writer=lifetime_status.Publisher(folder/'status63',binding,package.store.root_input.output_policy,profile=package.store.publication_profile)
    try:writer.publish(lifetime_status.preflight(job,binding))
    finally:writer.close()
    return job


def test_public_status_repeated_reads_never_decode_root_or_write(control_package,monkeypatch):
    from ops_sim.v5 import year_project
    calls=forbid_scientific_control_admission(monkeypatch)
    directory=control_package.store.directory
    before={p.relative_to(directory).as_posix():p.read_bytes()for p in directory.rglob('*')if p.is_file()}
    values=[year_project.status(directory)for _ in range(3)]
    assert values[0]==values[1]==values[2] and values[0]['jobs']==0
    assert values[0]['execution_authority']is False
    assert values[0]['control_view']=='YEAR_V4_BOUNDED_METADATA_ONLY_NEVER_EXECUTION_AUTHORITY'
    assert {p.relative_to(directory).as_posix():p.read_bytes()for p in directory.rglob('*')if p.is_file()}==before
    assert calls==[]


def test_metadata_scope_reuse_and_close_do_not_grant_execution(control_package,monkeypatch):
    from ops_sim.v5.lifecycle_application import LifecycleStore
    from ops_sim.v5.lifecycle_contract import LifecycleRoot
    calls=forbid_scientific_control_admission(monkeypatch)
    with owner.metadata_control_operation(control_package.store.directory,control_package.source)as view:
        assert owner.metadata_control_snapshot(view)==owner.metadata_control_snapshot(view)
        assert type(view)is not LifecycleStore and type(view.root_input)is not LifecycleRoot
        assert not hasattr(view,'prepare_job')and not hasattr(view,'_parent_contract_local')
        with pytest.raises(TypeError):copy(view)
        with pytest.raises(TypeError):pickle.dumps(view)
    assert view.root_input is None and view._contract is None and view._gate is None
    with pytest.raises(ValueError,match='closed'):owner.metadata_control_snapshot(view)
    assert calls==[]


def test_public_stop_initial_and_owned_active_marker_is_idempotent(control_package,monkeypatch):
    from ops_sim.v5 import year_project
    directory=control_package.store.directory
    calls=forbid_scientific_control_admission(monkeypatch)
    first=year_project.stop(directory);marker=directory/'operator-pause.json';raw=marker.read_bytes()
    assert first['requested']is True and first['settled']is False and first['status']['jobs']==0
    marker_owner=dict(format='B52_EXCLUSIVE_DISPATCH_OWNER_V1',owner='d'*32,PID=12345,
        source_identity=control_package.store.meta['source_identity'])
    (directory/'dispatch-owner.json').write_bytes(portable_job.canonical(marker_owner))
    saved_control_job(control_package)
    second=year_project.stop(directory)
    assert second['requested']is True and second['settled']is False and second['status']['jobs']==1
    assert marker.read_bytes()==raw and calls==[]


def test_public_status_keeps_target_and_diagnostic_role_classification(control_package,monkeypatch):
    from ops_sim.v5 import year_project
    parent=saved_control_job(control_package,clock=control_package.store.root_input.end_seconds)
    intent=deepcopy(control_package.job['intent'])
    intent.update(idempotency_key='c'*32,parent_job_id=parent['job_id'],snapshot_sha256='f'*64,
        mode='DIAGNOSTIC_NORMAL',window_end_seconds=400)
    saved_control_job(control_package,jid='c'*32,intent=intent,clock=400)
    calls=forbid_scientific_control_admission(monkeypatch)
    status=year_project.status(control_package.store.directory)
    assert status['primary_jobs']==1 and status['diagnostic_jobs']==1
    assert status['clock']==control_package.store.root_input.end_seconds
    assert status['parent_job_id']==parent['job_id']and status['typed_terminal']['kind']=='TARGET'
    assert calls==[]


@pytest.mark.parametrize('leaf',('input.json','lifetime-native-build.json','execution-authority.json','lifetime-plan.json'))
def test_public_control_refuses_changed_immutable_bytes_before_stop(control_package,monkeypatch,leaf):
    from ops_sim.v5 import year_project
    forbid_scientific_control_admission(monkeypatch)
    path=control_package.store.directory/leaf;path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises((ValueError,TypeError)):year_project.status(control_package.store.directory)
    with pytest.raises((ValueError,TypeError)):year_project.stop(control_package.store.directory)
    assert not(control_package.store.directory/'operator-pause.json').exists()


@pytest.mark.parametrize('change',('source_bytes','source_membership','runtime','requirements','build_runtime'))
def test_public_control_refuses_current_context_drift(control_package,monkeypatch,change):
    from ops_sim.v5 import year_project,lifecycle_backend
    forbid_scientific_control_admission(monkeypatch)
    if change=='source_bytes':(control_package.source/control_package.build['engine_source']['path']).write_bytes(b'y')
    elif change=='source_membership':(control_package.source/'unexpected.py').write_bytes(b'x')
    elif change=='runtime':monkeypatch.setattr(owner,'_metadata_runtime_identity',lambda:dict(python='FOREIGN'))
    elif change=='requirements':monkeypatch.setattr(owner,'runtime_requirements',lambda source:dict(python_major_minor=[0,0]))
    else:monkeypatch.setattr(lifecycle_backend,'runtime_binding',lambda:dict(foreign=True))
    with pytest.raises(ValueError):year_project.stop(control_package.store.directory)
    assert not(control_package.store.directory/'operator-pause.json').exists()


@pytest.mark.parametrize('change',('seal','property','module','descriptor','source','immutable'))
def test_metadata_live_scope_drift_permanently_refuses(control_package,monkeypatch,change):
    from ops_sim.v5.lifecycle_compact import PublicationProfile
    view=owner.metadata_control_operation(control_package.store.directory,control_package.source).__enter__()
    restore=None
    try:
        if change=='seal':view._gate.functions=()
        elif change=='property':
            getter=PublicationProfile.identity.fget;restore=(getter,getter.__code__)
            def replacement(self):return '0'*64
            getter.__code__=replacement.__code__
        elif change=='module':monkeypatch.setitem(sys.modules,'ops_sim.v5.battery_terminal',SimpleNamespace())
        elif change=='descriptor':monkeypatch.setattr(owner._MetadataControlStore,'__getattribute__',lambda self,name:object.__getattribute__(self,name),raising=False)
        elif change=='source':(control_package.source/'requirements.txt').write_bytes(b'foreign')
        else:
            path=control_package.store.directory/'input.json';path.write_bytes(path.read_bytes()+b' ')
        with pytest.raises((ValueError,TypeError)):owner.metadata_control_snapshot(view)
        assert view._phase=='REFUSED'
        if restore:restore[0].__code__=restore[1];restore=None
        with pytest.raises(ValueError,match='closed'):owner.metadata_control_snapshot(view)
    finally:
        if restore:restore[0].__code__=restore[1]
        view.close()


def test_metadata_scope_foreign_thread_revokes_and_fresh_scope_is_required(control_package):
    view=owner.metadata_control_operation(control_package.store.directory,control_package.source).__enter__();errors=[]
    def foreign():
        try:owner.metadata_control_snapshot(view)
        except (ValueError,TypeError)as error:errors.append(error)
    thread=threading.Thread(target=foreign);thread.start();thread.join(10)
    try:
        assert not thread.is_alive()and len(errors)==1 and view._phase=='REFUSED'
        with pytest.raises(ValueError):owner.metadata_control_snapshot(view)
    finally:view.close()
    with owner.metadata_control_operation(control_package.store.directory,control_package.source)as fresh:
        assert owner.metadata_control_snapshot(fresh)['jobs']==0


def test_metadata_request_read_race_refuses_before_status_or_stop(control_package,monkeypatch):
    from ops_sim.v5 import year_project
    saved_control_job(control_package);original=owner._admit_worker_request
    def swap_after_admission(*args,**kwargs):
        result=original(*args,**kwargs)
        path=control_package.store.directory/'jobs'/('b'*32)/'request.json'
        value=portable_job.parse(path.read_bytes());value['runtime']['python']='swapped after admission'
        path.write_bytes(portable_job.canonical(value));return result
    monkeypatch.setattr(owner,'_admit_worker_request',swap_after_admission)
    with pytest.raises(ValueError,match='request changed'):year_project.stop(control_package.store.directory)
    assert not(control_package.store.directory/'operator-pause.json').exists()


@pytest.mark.parametrize('change',('request','head','checkpoint_method','publication','launch'))
def test_metadata_current_job_corruption_refuses(control_package,monkeypatch,change):
    from ops_sim.v5 import year_project
    launch=None if change!='launch'else dict(observed_envelope_seconds=-1,forced_interruption=False,timeout=False,unexpected=None)
    job=saved_control_job(control_package,clock=600 if change in('checkpoint_method','publication')else None,
        checkpoint_method='FOREIGN'if change=='checkpoint_method'else None,launch=launch)
    folder=control_package.store.directory/'jobs'/job['job_id']
    if change=='request':
        path=folder/'request.json';value=portable_job.parse(path.read_bytes());value['runtime']['python']='foreign';path.write_bytes(portable_job.canonical(value))
    elif change=='head':
        path=folder/'status63'/'head'/'heads.bin';path.write_bytes(path.read_bytes()+b'x')
    elif change=='publication':
        path=folder/job['result']['checkpoint']['publication']['file'];path.write_bytes(path.read_bytes()+b'x')
    calls=forbid_scientific_control_admission(monkeypatch)
    with pytest.raises(ValueError):year_project.stop(control_package.store.directory)
    assert not(control_package.store.directory/'operator-pause.json').exists()and calls==[]


def test_public_stop_refuses_foreign_pause_marker(control_package):
    from ops_sim.v5 import year_project
    marker=control_package.store.directory/'operator-pause.json'
    marker.write_bytes(portable_job.canonical(dict(plan_identity='0'*64,token='d'*32)));before=marker.read_bytes()
    with pytest.raises(ValueError,match='foreign operator pause'):year_project.stop(control_package.store.directory)
    assert marker.read_bytes()==before


@pytest.mark.parametrize('family',('UNKNOWN',portable_job.LIFETIME_JOB_V2,None))
def test_public_control_malformed_or_downgraded_family_has_no_scientific_fallback(control_package,monkeypatch,family):
    from ops_sim.v5 import year_project
    path=control_package.store.directory/'portable-job.json'
    if family is None:path.unlink()
    else:
        value=portable_job.parse(path.read_bytes());value['format']=family;path.write_bytes(portable_job.canonical(value))
    calls=forbid_scientific_control_admission(monkeypatch)
    with pytest.raises(ValueError,match='family'):year_project.status(control_package.store.directory)
    assert calls==[]


def test_metadata_exit_preserves_primary_when_close_fails(control_package,monkeypatch):
    view=owner.metadata_control_operation(control_package.store.directory,control_package.source).__enter__()
    original=owner._MetadataControlStore.close;primary=LookupError('primary metadata read failure')
    def refuse_close(self):raise OSError('secondary metadata close failure')
    try:
        with monkeypatch.context()as patch:
            patch.setattr(owner._MetadataControlStore,'close',refuse_close)
            assert view.__exit__(LookupError,primary,None)is False
        assert isinstance(primary.secondary_close_failure,OSError)
        assert any('secondary metadata close failure'in note for note in primary.__notes__)
    finally:original(view)


@pytest.mark.parametrize('package',['NO_LAUNCH'],indirect=True)
def test_metadata_administrative_journal_corruption_refuses(control_package,monkeypatch):
    from ops_sim.v5 import year_project,lifetime_journal,lifetime_supervisor
    plan=lifetime_supervisor._read(control_package.store.directory/'lifetime-plan.json')
    lifetime_journal.Journal(control_package.store,plan).append('NO_LAUNCH_DISPOSITION',dict(foreign=True))
    calls=forbid_scientific_control_admission(monkeypatch)
    with pytest.raises(ValueError,match='administrative disposition'):year_project.status(control_package.store.directory)
    assert calls==[]
