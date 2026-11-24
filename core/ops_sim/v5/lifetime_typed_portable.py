"""Explicit B64 typed V3 packages; old B62/B63 containers are not aliases.

Initial packages contain raw original-root input only. A private current-process
input admission can be handed to the worker's job factory once, never persisted
or inferred from the returned DATA receipt.
"""
from dataclasses import asdict,dataclass
from pathlib import Path
import json
import os
import sys
import threading
from types import FunctionType
import zipfile

from .portable_job import canonical,digest,source_manifest,runtime_requirements
from .lifecycle_fast import FAST,REFERENCE
from .lifetime_io_accounting import fsync as _io_fsync

FORMAT_V3='B64_TYPED_LIFETIME_EXECUTION_CONTRACT_V3'
FORMAT_V4='B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4'
JOB_V4='B65_PORTABLE_TYPED_LIFETIME_INITIAL_V4'
PLAN_V4='B65_ORIGINAL_ROOT_TYPED_SERIAL_PLAN_V4'
PRODUCER_V4='M8_B65_TYPED_CURRENT_SOURCE_PRODUCER_V4'
NEW_DOMAIN='B65_TYPED_EXECUTION_V2'
JOB_V3='B64_PORTABLE_TYPED_LIFETIME_INITIAL_V3'
PLAN_V3='B64_ORIGINAL_ROOT_TYPED_SERIAL_PLAN_V3'
PRODUCER='M8_B64_TYPED_CURRENT_SOURCE_PRODUCER_V3'
PREPARATION='B64_OWNED_PREPARED_JOB_V1'
PREPARATION_V2='B69_OWNED_PREPARED_JOB_V2'

def _preparation_method(build):
    if type(build)is not dict or type(build.get('execution_domain'))is not str or type(build.get('support_sources'))is not dict:raise ValueError('B69 exact declared preparation build DATA')
    return PREPARATION_V2 if build['execution_domain']==NEW_DOMAIN and 'ops_sim/v5/lifecycle_exact_guards.py'in build['support_sources']else PREPARATION
JOB_FIELDS=('format','contract','intent','horizon','requirements','limits','entrypoint',
    'native_import','lifetime_policy','execution_authority')


def _job_shell(job):
    from .portable_job import fields
    fields(job,JOB_FIELDS)
    if (type(job['format'])is not str or job['format']not in(JOB_V3,JOB_V4) or type(job['entrypoint'])is not str or
            job['entrypoint']!='ops_sim.v5.lifecycle_application:worker' or job['native_import']is not False):
        raise ValueError('B64 exact typed initial package format/entrypoint')
    new=job['format']==JOB_V4
    if (job['contract'].get('format')!=(FORMAT_V4 if new else FORMAT_V3) or
            (job['contract'].get('backend_binding',{}).get('selection')==NEW_DOMAIN)!=new):raise ValueError('B65 package/contract/domain family mismatch')


def _manifest_build(manifest,build):
    from .lifecycle_typed_backend import admit_build_data
    build=admit_build_data(build)
    for item in (build['artifact'],build['engine_source'],build['generated_c'],*build['support_sources'].values()):
        if manifest.get(item['path'])!=dict(bytes=item['bytes'],sha256=item['sha256']):
            raise ValueError('B64 typed build/current source manifest raw binding')
    return build


def execution_contract_v3(root,source,strategy,*,backend,build):
    from .lifetime_source import B64_SOURCE_PATHS,B65_SOURCE_PATHS
    from .lifetime_admission import resource_plan
    from .lifetime_execution_authority import typed_backend_binding
    from .lifecycle_typed_backend import admit_build_data
    from .lifecycle_backend import runtime_binding
    from .project_store import runtime_identity
    from .lifecycle_document import dumps_root
    if type(strategy)is not str or strategy not in (FAST,REFERENCE):raise ValueError('B64 explicit typed static strategy')
    manifest=source_manifest(source)
    if set(manifest)!=set(B65_SOURCE_PATHS if backend==NEW_DOMAIN else B64_SOURCE_PATHS):raise ValueError('B64 frozen current producer membership')
    build=_manifest_build(manifest,build);binding=typed_backend_binding(backend,build)
    if build['runtime']!=runtime_binding():raise ValueError('B64 typed preparation runtime/ABI')
    result=dict(format=FORMAT_V4 if backend==NEW_DOMAIN else FORMAT_V3,producer=PRODUCER_V4 if backend==NEW_DOMAIN else PRODUCER,strategy=strategy,source_manifest=manifest,
        source_manifest_sha256=digest(canonical(manifest)),root_identity=root.identity,input_sha256=digest(dumps_root(root)),
        cache_bytes=64*2**20,cache_entries=128,physical_work='B61_LEGACY_LEAVES_PLUS_SEPARATE_AGEING_RESERVATIONS_V1',
        static_work='B65_LOGICAL_PREPAYMENT_PLUS_GENERATION_COUNTS_V1' if backend==NEW_DOMAIN else 'ACTUAL_HITS_MISSES_GUARDS_FULL_OPERATIONS_CURRENT_PROCESS',
        contract_pin='B60_SAME_EXECUTION_CONTRACT_JOB_PIN_V1',publication_work='B63_BOUNDED_STATUS_DETAILS_PRECHARGED_V1',
        restart='RECONSTRUCT_STATIC_CACHE_ONLY_NO_PHYSICAL_PREFIX',runtime_scope='SAME_RUNTIME_NATIVE_ONLY',
        runtime=runtime_identity(),requirements=runtime_requirements(source),accounting_plan=resource_plan(root),
        environment_policy_identity=root.environment_ageing_policy.identity,environment_native_format='B61_EXPOSURE_THERMAL_CHECKPOINT_V8',
        dynamic_environment='NOT_CACHED_RETAINED_CAUSAL_STATE_ONLY',native_migration=False,
        backend_binding=binding,native_build=build,execution_authority='B63_IMMUTABLE_PILOT_OR_GENUINE_LONG_V1',
        job_preparation=_preparation_method(build))
    admit_execution_contract_data_v3(result)
    return result


def admit_execution_contract_data_v3(value):
    """New exact DATA container, without binary imports/root reconstruction."""
    from .portable_job import fields
    from .lifetime_portable import admit_execution_contract_data_v2,FORMAT_V2
    from .lifetime_execution_authority import typed_backend_binding,backend_binding
    names={'format','strategy','source_manifest','source_manifest_sha256','root_identity','input_sha256',
        'cache_bytes','cache_entries','physical_work','static_work','contract_pin','publication_work',
        'restart','runtime_scope','environment_policy_identity','environment_native_format',
        'dynamic_environment','producer','runtime','requirements','accounting_plan','native_migration',
        'backend_binding','native_build','execution_authority','job_preparation'}
    fields(value,names)
    if any(type(value[n])is not str or value[n]!=v for n,v in
            (('format',FORMAT_V4 if value.get('backend_binding',{}).get('selection')==NEW_DOMAIN else FORMAT_V3),('producer',PRODUCER_V4 if value.get('backend_binding',{}).get('selection')==NEW_DOMAIN else PRODUCER),('job_preparation',_preparation_method(value['native_build'])))):
        raise ValueError('B64 exact typed execution contract version/preparation')
    # Reuse the already strict common physical/resource DATA checks only. The
    # local projection is never returned or accepted as a B63 execution job.
    common=dict(value);common.pop('job_preparation')
    if value['format']==FORMAT_V4:
        if value['static_work']!='B65_LOGICAL_PREPAYMENT_PLUS_GENERATION_COUNTS_V1':raise ValueError('B65 validation control contract')
        common['static_work']='ACTUAL_HITS_MISSES_GUARDS_FULL_OPERATIONS_CURRENT_PROCESS'
    common.update(format=FORMAT_V2,producer='M8_B63_PREPARED_CURRENT_SOURCE_PRODUCER_V2',
        backend_binding=backend_binding('REFERENCE'),native_build=None)
    admit_execution_contract_data_v2(common)
    build=_manifest_build(value['source_manifest'],value['native_build'])
    binding=value['backend_binding']
    if type(binding)is not dict or canonical(binding)!=canonical(typed_backend_binding(binding.get('selection'),build)):
        raise ValueError('B64 typed DATA backend/build domain binding')
    if len(canonical(value))>2**20:raise ValueError('B64 bounded typed execution contract DATA')
    return value


def _admit_input(raw,contract,source):
    from .lifecycle_typed_platform import METHOD
    if contract.get('backend_binding',{}).get('selection')==METHOD:
        from .metadata_codec import admitted_metadata_scope
        with admitted_metadata_scope(contract['native_build']):
            return _admit_input_reference(raw,contract,source)
    return _admit_input_reference(raw,contract,source)


def _admit_input_reference(raw,contract,source):
    from .lifecycle_job_prepared import admit_job_root
    admit_execution_contract_data_v3(contract)
    manifest=source_manifest(source)
    if canonical(manifest)!=canonical(contract['source_manifest']):raise ValueError('B64 current source raw manifest drift')
    return admit_job_root(raw,digest(canonical(manifest)),build_binding=contract['native_build'])


def _admit_token(admission,root,raw,contract):
    from .lifecycle_job_prepared import JobInputAdmission
    if type(admission)is not JobInputAdmission:raise TypeError('B64 exact current-process raw input admission')
    admission._guard(root)
    if (admission._raw!=raw or admission.source_binding!=contract['source_manifest_sha256'] or
            admission._build_raw!=canonical(contract['native_build'])):
        raise ValueError('B64 private input admission raw/source/build drift')


def admit_execution_contract_v3(contract,raw,source,*,root=None,admission=None):
    admit_execution_contract_data_v3(contract)
    if root is None and admission is None:root,admission=_admit_input(raw,contract,source)
    elif root is None or admission is None:raise ValueError('B64 root and private admission must be supplied together')
    _admit_token(admission,root,raw,contract)
    expected=execution_contract_v3(root,source,contract['strategy'],
        backend=contract['backend_binding']['selection'],build=contract['native_build'])
    if canonical(contract)!=canonical(expected):raise ValueError('B64 typed execution/source/runtime/root/build contract drift')
    _admit_token(admission,root,raw,contract)
    return contract


def _job_metadata(job,root,source,raw):
    from .portable_job import fields
    from .lifetime_policy import admit_policy,is_v2
    from .lifetime_campaign import horizon_preflight,admit_intent_limits
    from .lifecycle_application import validate_intent
    from .lifetime_execution_authority import admit_authority
    _job_shell(job)
    policy=admit_policy(job['lifetime_policy'])
    if not is_v2(policy):raise ValueError('B64 typed package requires exact V2 lifetime policy')
    if canonical(job['horizon'])!=canonical(horizon_preflight(root,policy)) or canonical(job['requirements'])!=canonical(runtime_requirements(source)):
        raise ValueError('B64 typed package horizon/current requirements')
    limits=dict(rss_bytes=policy.maximum_rss_bytes,native_bytes=policy.maximum_native_bytes,
        job_bytes=policy.maximum_output_bytes,slots=policy.maximum_jobs)
    if canonical(job['limits'])!=canonical(limits):raise ValueError('B64 typed prospective package limits')
    intent=validate_intent(job['intent']);admit_intent_limits(policy,intent)
    from .lifecycle_compact import INTENT as PROFILE_INTENT
    if intent['format']!=PROFILE_INTENT:raise ValueError('B64 typed package requires explicit bound publication profile')
    if (intent['root_identity']!=root.identity or intent['parent_job_id']is not None or intent['snapshot_sha256']is not None or
            intent['mode']!='MAIN' or intent['window_end_seconds']is not None):
        raise ValueError('B64 initial package cannot import advanced state')
    contract=job['contract']
    authority=admit_authority(job['execution_authority'],root,raw,contract,policy,
        backend=contract['backend_binding']['selection'],build=contract['native_build'])
    return policy,authority


def prepare_lifetime_v3(path,root,source,policy,*,strategy=FAST,key='0'*32,backend,build,
        execution_mode='PILOT',acceptance=None):
    from .portable_job import _admit_manifest,MAX_MANIFEST,safe,file_digest
    from .lifetime_policy import is_v2
    from .lifetime_campaign import horizon_preflight
    from .lifecycle_document import dumps_root
    from .lifecycle_application import make_intent
    from .lifecycle_execution_budget import ExecutionBudget
    from .lifecycle_compact import PublicationProfile
    from .lifetime_execution_authority import make_authority
    if not is_v2(policy):raise TypeError('B64 exact V2 typed lifetime policy')
    if Path(path).resolve().is_relative_to(Path(source).resolve()):raise ValueError('B64 typed package outside source')
    raw=dumps_root(root);contract=execution_contract_v3(root,source,strategy,backend=backend,build=build)
    authority=make_authority(root,raw,contract,policy,mode=execution_mode,backend=backend,build=build,acceptance=acceptance)
    intent=make_intent(root.identity,key=key,execution_seconds=policy.hard_seconds,maximum_output_bytes=policy.maximum_output_bytes,
        execution_budget=ExecutionBudget(policy.hard_seconds,policy.soft_seconds,policy.finalization_seconds),publication_profile=PublicationProfile())
    job=dict(format=JOB_V4 if backend==NEW_DOMAIN else JOB_V3,contract=contract,intent=intent,horizon=horizon_preflight(root,policy),
        requirements=runtime_requirements(source),lifetime_policy=asdict(policy),
        limits=dict(rss_bytes=policy.maximum_rss_bytes,native_bytes=policy.maximum_native_bytes,job_bytes=policy.maximum_output_bytes,slots=policy.maximum_jobs),
        entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False,execution_authority=authority)
    _job_metadata(job,root,source,raw)
    payload={'job.json':canonical(job),'input.json':raw}
    for name,binding in contract['source_manifest'].items():
        data=(Path(source)/name).read_bytes()
        if dict(bytes=len(data),sha256=digest(data))!=binding:raise ValueError('B64 typed source drift before package write')
        payload['source/'+name]=data
    manifest={safe(name):dict(bytes=len(data),sha256=digest(data))for name,data in payload.items()}
    _admit_manifest(manifest);metadata=canonical(dict(format=job['format'],files=manifest))
    if len(payload['job.json'])>MAX_MANIFEST or len(metadata)>MAX_MANIFEST:raise ValueError('B64 typed package metadata cap')
    with Path(path).open('xb')as stream:
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED)as archive:
            archive.writestr('MANIFEST.json',metadata)
            for name,data in sorted(payload.items()):archive.writestr(name,data)
        stream.flush();_io_fsync(stream.fileno())
    return dict(path=str(Path(path).absolute()),sha256=file_digest(path),files=len(manifest))


def _admit_bundle(path,source):
    from .portable_job import read_bundle,parse,MAX_SOURCE,MAX_MANIFEST
    with zipfile.ZipFile(path)as archive:
        info=archive.getinfo('MANIFEST.json')
        if info.file_size>MAX_MANIFEST:raise ValueError('B65 manifest bytes')
        kind=parse(archive.read(info)).get('format')
    if kind not in(JOB_V3,JOB_V4):raise ValueError('B65 exact typed package family')
    payload=read_bundle(path,kind)
    if 'job.json'not in payload or 'input.json'not in payload or len(payload['job.json'])>MAX_MANIFEST or sum(len(v)for k,v in payload.items()if k.startswith('source/'))>MAX_SOURCE:
        raise ValueError('B64 bounded typed package required members')
    job=parse(payload['job.json']);_job_shell(job);contract=job['contract']
    root,admission=_admit_input(payload['input.json'],contract,source)
    admit_execution_contract_v3(contract,payload['input.json'],source,root=root,admission=admission)
    if set(payload)!={'job.json','input.json',*('source/'+name for name in contract['source_manifest'])}:
        raise ValueError('B64 typed package exact membership')
    if any(dict(bytes=len(payload['source/'+name]),sha256=digest(payload['source/'+name]))!=binding for name,binding in contract['source_manifest'].items()):
        raise ValueError('B64 typed package source bytes')
    _job_metadata(job,root,source,payload['input.json']);_admit_token(admission,root,payload['input.json'],contract)
    return job,root,payload['input.json'],admission


def admit_lifetime_job_v3(path,source):
    job,root,raw,_=_admit_bundle(path,source)
    return job,root,raw


def create_lifetime_store_v3(package,directory,source):
    from .lifecycle_application import LifecycleStore,_write_new
    from .lifetime_policy import admit_policy
    from .lifecycle_compact import admit_profile
    if Path(directory).resolve().is_relative_to(Path(source).resolve()):raise ValueError('B64 typed store outside source')
    job,root,raw,_=_admit_bundle(package,source)
    profile=admit_profile(job['intent']['publication_profile'],job['intent']['publication_profile_identity'])
    store=LifecycleStore(directory,root,create=True,runner_policy=admit_policy(job['lifetime_policy']),
        publication_profile=profile,execution_authority=job['execution_authority'])
    try:
        _write_new(store.path('portable-execution.json'),job['contract'])
        _write_new(store.path('portable-job.json'),job)
        _write_new(store.path('lifetime-native-build.json'),job['contract']['native_build'],65536)
    except BaseException as primary:
        try:store.close_publications()
        except BaseException as secondary:
            primary.add_note('B64 secondary store close: '+repr(secondary));primary.secondary_close_failure=secondary
        raise
    return store,job['intent']


def _admit_worker_request(directory,contract,meta,policy,*,job_id=None,request_sha256=None):
    """Always admit current per-job bytes; a parent scope never caches requests."""
    from .portable_job import parse,admit_job_pin,fields
    from .lifetime_execution_authority import _regular
    from .lifecycle_application import validate_intent,_job_format
    from .lifetime_campaign import admit_intent_limits
    if job_id is None:
        if request_sha256 is not None:raise ValueError('B64 request SHA requires explicit job identity')
        return
    admit_job_pin(directory,job_id,contract)
    request=_regular(Path(directory)/'jobs'/job_id/'request.json',256*1024)
    if digest(request)!=request_sha256:raise ValueError('B64 typed worker exact request raw hash')
    value=parse(request)
    fields(value,('format','job_id','intent','root_identity','source_identity','runtime','input_sha256','resume'))
    intent=validate_intent(value['intent']);admit_intent_limits(policy,intent)
    if (canonical(value)!=request or value['job_id']!=job_id or value['root_identity']!=contract['root_identity'] or
            value['source_identity']!=meta['source_identity']or value['runtime']!=meta['runtime']or
            value['input_sha256']!=contract['input_sha256']or value['format']!=_job_format(intent)or
            intent['root_identity']!=contract['root_identity'] or intent.get('publication_profile_identity')!=meta['publication_profile_identity']or
            canonical(intent.get('publication_profile'))!=canonical(meta['publication_profile'])):
        raise ValueError('B64 typed worker exact request context')
    if value['resume']is None:
        if intent['parent_job_id']is not None:raise ValueError('B64 typed worker initial/resume disagreement')
    else:
        fields(value['resume'],('parent_job_id','checkpoint'))
        if (value['resume']['parent_job_id']!=intent['parent_job_id']or type(value['resume']['checkpoint'])is not dict or
                value['resume']['checkpoint'].get('sha256')!=intent['snapshot_sha256']):
            raise ValueError('B64 typed worker selected parent/checkpoint disagreement')
        admit_job_pin(directory,value['resume']['parent_job_id'],contract)


def admit_worker_package_v3(directory,source,*,job_id=None,request_sha256=None):
    """One root decode + full permission gate, before worker side effects.

    Returns (contract, root, private admission, authority DATA). Only the private
    admission is reusable by prepare_job_runtime; no native/model call occurs.
    """
    from .portable_job import parse,admit_job_pin
    from .project_store import ProjectStore,runtime_identity
    from .spacecraft_project import project_source_identity
    from .lifecycle_runner_policy import admit_runner_store_metadata
    from .lifecycle_contract import static_admission
    from .lifetime_policy import is_v2,PRODUCTION
    from .lifetime_execution_authority import admit_authority_data,_regular
    directory=Path(directory).absolute()
    def read(name,limit=2**20):
        path=directory/name;ProjectStore._reject_links(path)
        return _regular(path,limit)
    raw=read('input.json',16*2**20);contract_raw=read('portable-execution.json');job_raw=read('portable-job.json')
    contract=parse(contract_raw);job=parse(job_raw)
    _job_shell(job)
    if canonical(contract)!=contract_raw or canonical(job)!=job_raw or canonical(job['contract'])!=contract_raw:
        raise ValueError('B64 typed worker canonical package/contract binding')
    root,admission=_admit_input(raw,contract,source)
    admit_execution_contract_v3(contract,raw,source,root=root,admission=admission)
    policy,authority=_job_metadata(job,root,source,raw)
    meta_raw=read('store.json');meta=parse(meta_raw);saved=admit_runner_store_metadata(meta)[0]
    if canonical(meta)!=meta_raw or not is_v2(saved)or canonical(asdict(saved))!=canonical(asdict(policy)):
        raise ValueError('B64 exact typed worker store/policy metadata')
    if (meta['root_identity']!=root.identity or meta['input_sha256']!=digest(raw)or meta['input_bytes']!=len(raw)or
            meta['runtime']!=runtime_identity()or meta['runtime']!=contract['runtime']or
            meta['source_identity']!=project_source_identity()or meta['admission']!=static_admission(root)):
        raise ValueError('B64 typed worker actual root/input/source/runtime/admission metadata')
    if (meta.get('publication_profile_identity')!=job['intent']['publication_profile_identity']or
            canonical(meta.get('publication_profile'))!=canonical(job['intent']['publication_profile'])):
        raise ValueError('B64 typed worker store/package publication profile binding')
    authority_raw=read('execution-authority.json',16384);saved_authority=parse(authority_raw);admit_authority_data(saved_authority)
    if canonical(saved_authority)!=authority_raw or canonical(authority)!=authority_raw or digest(authority_raw)!=meta['execution_authority_sha256']:
        raise ValueError('B64 typed worker exact store/package/authority pin')
    if read('lifetime-native-build.json',65536)!=canonical(contract['native_build']):raise ValueError('B64 typed worker saved build receipt pin')
    _admit_worker_request(directory,contract,meta,policy,job_id=job_id,request_sha256=request_sha256)
    if policy.mode==PRODUCTION:
        from kit.serverctl import doctor
        if not doctor(Path(source))['ready_for_engine_attempt']:raise ValueError('B64 production Linux doctor prerequisite')
    _admit_token(admission,root,raw,contract)
    return contract,root,admission,authority


def worker_contract_v3(directory,source,*,job_id=None,request_sha256=None,operation=None):
    if operation is not None:
        return _operation_contract(operation,directory,source,job_id=job_id,request_sha256=request_sha256)
    return admit_worker_package_v3(directory,source,job_id=job_id,request_sha256=request_sha256)[0]


_CONTROL_FACTORY=object()
_CONTROL_FILES=(('input.json',16*2**20,True),('portable-execution.json',2**20,True),
    ('portable-job.json',2**20,True),('store.json',2**20,True),
    ('execution-authority.json',16384,True),('lifetime-native-build.json',65536,True),
    ('design-project-input.json',16*2**20,False),('lifetime-plan.json',2**20,False))


def _control_files(directory):
    from .lifetime_execution_authority import _regular
    from .project_store import ProjectStore
    result=[]
    for name,limit,required in _CONTROL_FILES:
        path=directory/name;ProjectStore._reject_links(path)
        raw=_regular(path,limit) if required or path.exists() else None
        result.append((name,limit,raw))
    return tuple(result)


def _control_runtime():
    return (os.getpid(),threading.current_thread(),threading.get_ident(),
        sys.implementation.name,sys.version,sys.executable,sys.implementation.cache_tag,sys.platform)


def _same_control_runtime(saved):
    if (type(saved)is not tuple or len(saved)!=8 or type(saved[0])is not int or
            type(saved[2])is not int or any(type(value)is not str for value in saved[3:])):
        return False
    current=_control_runtime()
    return (saved[1]is current[1] and saved[0]==current[0] and saved[2:]==current[2:])


def _refuse_parent(operation):
    generation=object.__getattribute__(operation,'_generation')
    object.__setattr__(operation,'_generation',generation+1 if type(generation)is int else 1)
    object.__setattr__(operation,'_phase','REFUSED')


class _ControlCallables:
    """Retain the existing control consumers independently of their predicates."""
    __slots__=('modules','functions','classes','retained','signature','signature_code','pins')
    def __init__(self):
        from .lifecycle_job_prepared import _generation_function_state
        from . import (portable_job,lifetime_execution_authority,lifecycle_runner_policy,
            lifecycle_application,lifetime_campaign,lifecycle_backend,lifecycle_typed_backend,lifetime_policy)
        modules=(sys.modules[__name__],portable_job,lifetime_execution_authority,
            lifecycle_runner_policy,lifecycle_application,lifetime_campaign,
            lifecycle_backend,lifecycle_typed_backend,lifetime_policy)
        retained=[];declarations=[]
        for module in modules:
            declarations.extend((module,name,value) for name,value in vars(module).items() if type(value)is FunctionType)
        classes=(_ParentContractOperation,_ControlCallables,_StoreContractScope,lifecycle_application.LifecycleStore)
        for owner in classes:
            declarations.extend((owner,name,value) for name,value in vars(owner).items() if type(value)is FunctionType)
            for value in vars(owner).values():
                if type(value)is property:
                    declarations.extend((value,name,fn)for name in ('fget','fset','fdel')if type(fn:=getattr(value,name))is FunctionType)
        self.modules=tuple((module.__name__,module)for module in modules)
        self.classes=tuple((owner,owner.__bases__,owner.__mro__,tuple(vars(owner).items()))for owner in classes)
        self.functions=tuple((owner,name,fn,_generation_function_state(fn,retained))for owner,name,fn in declarations)
        self.retained=tuple(retained);self.signature=_generation_function_state;self.signature_code=_generation_function_state.__code__
        self.pins=(self.modules,self.functions,self.retained,self.signature,self.signature_code,self.classes)

    def guard(self):
        from . import lifecycle_job_prepared
        # Bypass any callback-added __getattribute__ until the class dictionaries
        # and inherited layout have been checked independently.
        pins=object.__getattribute__(self,'pins')
        classes=object.__getattribute__(self,'classes')
        if type(pins)is not tuple or len(pins)!=6 or classes is not pins[5]:
            raise ValueError('YEAR-V4 replaced parent class seal')
        for owner,bases,mro,entries in classes:
            current=tuple(vars(owner).items())
            if (owner.__bases__ is not bases or owner.__mro__ is not mro or len(current)!=len(entries) or
                    any(name!=expected_name or value is not expected for (name,value),(expected_name,expected) in zip(current,entries))):
                raise ValueError('YEAR-V4 parent class/layout/descriptor drift')
        if (self.modules is not self.pins[0] or self.functions is not self.pins[1] or
                self.retained is not self.pins[2] or self.signature is not self.pins[3] or
                self.signature_code is not self.pins[4] or
                lifecycle_job_prepared._generation_function_state is not self.signature or
                self.signature.__code__ is not self.signature_code):
            raise ValueError('YEAR-V4 replaced parent callable seal')
        if any(sys.modules.get(name)is not module for name,module in self.modules):
            raise ValueError('YEAR-V4 parent control module replacement')
        for owner,name,function,signature in self.functions:
            if getattr(owner,name,None)is not function or self.signature(function)!=signature:
                raise ValueError('YEAR-V4 parent control callable drift: '+name)


class _ParentContractOperation:
    """One parent operation; never a worker or persisted execution capability.

    Full package/root/authority admission occurs on entry. Each use keeps the
    original root and callable seals, rehashes source/current immutable bytes,
    and admits the current request and pins. No numerical or dynamic checkpoint
    state is cached here. Reopen, foreign thread, callback invalidation and exit
    cannot reuse this capability.
    """
    __slots__=('_directory','_source','_operation','_factory','_self','_phase',
        '_generation','_runtime','_files','_contract_raw','_authority_raw','_meta_raw',
        '_policy_raw','_root','_admission','_callables','_pins','_store_binding','_uses','_busy')
    def __init__(self,directory,source,operation,key):
        if key is not _CONTROL_FACTORY:raise TypeError('YEAR-V4 parent operation factory')
        if type(operation)is not str or not 0<len(operation)<=128:raise ValueError('YEAR-V4 explicit bounded parent operation')
        self._directory=Path(directory).absolute();self._source=Path(source).resolve()
        self._operation=operation;self._factory=key;self._self=self;self._phase='NEW'
        self._generation=0;self._runtime=_control_runtime();self._store_binding=None;self._uses=0;self._busy=False
        self._files=self._pins=();self._root=self._admission=self._callables=None
        self._contract_raw=self._authority_raw=self._meta_raw=self._policy_raw=None

    def __copy__(self):raise TypeError('YEAR-V4 parent operation cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('YEAR-V4 parent operation cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('YEAR-V4 parent operation is not persistent DATA')

    def __enter__(self):
        if type(self._phase)is not str or self._phase!='NEW' or not _same_control_runtime(self._runtime):raise ValueError('YEAR-V4 parent operation entry scope')
        self._phase='ENTERING'
        try:
            self._files=_control_files(self._directory)
            contract,root,admission,authority=admit_worker_package_v3(self._directory,self._source)
            # Adopt immediately: every failure after the unchanged full gate
            # returns can release this unused parent-only admission explicitly.
            self._root=root;self._admission=admission
            from .portable_job import parse
            from .lifetime_policy import admit_policy
            self._contract_raw=canonical(contract);self._authority_raw=canonical(authority)
            saved=dict((name,raw)for name,limit,raw in self._files)
            self._meta_raw=saved['store.json']
            self._policy_raw=canonical(asdict(admit_policy(parse(saved['portable-job.json'])['lifetime_policy'])))
            if self._contract_raw!=saved['portable-execution.json'] or self._authority_raw!=saved['execution-authority.json']:
                raise ValueError('YEAR-V4 parent entry bytes changed during full admission')
            self._callables=_ControlCallables()
            self._pins=(self,self._directory,self._source,self._operation,self._factory,
                self._runtime,self._files,self._contract_raw,self._authority_raw,self._meta_raw,
                self._policy_raw,root,admission,self._callables,self._store_binding)
            self._phase='ACTIVE';self._guard(self._directory,self._source)
        except BaseException as primary:
            self._phase='FAILED'
            try:self.close()
            except BaseException as secondary:_parent_close_secondary(primary,secondary)
            raise
        return self

    def _guard(self,directory,source):
        if type(self._busy)is not bool or self._busy:
            _refuse_parent(self)
            raise ValueError('YEAR-V4 reentrant parent operation')
        self._busy=True
        try:
            self._check(directory,source)
            if type(self._phase)is not str or self._phase!='ACTIVE' or type(self._generation)is not int or self._generation!=0:
                raise ValueError('YEAR-V4 parent operation invalidated during validation')
        except BaseException:
            _refuse_parent(self)
            raise
        finally:self._busy=False

    def _check(self,directory,source):
        from .portable_job import parse,runtime_requirements
        from .project_store import ProjectStore,runtime_identity
        from .spacecraft_project import project_source_identity
        from .lifecycle_backend import runtime_binding
        from .lifecycle_job_prepared import _guard_generation_owner
        if (type(self)is not _ParentContractOperation or self._self is not self or
                self._factory is not _CONTROL_FACTORY or type(self._phase)is not str or self._phase!='ACTIVE' or
                type(self._generation)is not int or self._generation!=0 or
                type(self._pins)is not tuple or len(self._pins)!=15 or
                any(actual is not expected for actual,expected in zip(self._pins,
                    (self,self._directory,self._source,self._operation,self._factory,self._runtime,
                     self._files,self._contract_raw,self._authority_raw,self._meta_raw,self._policy_raw,
                     self._root,self._admission,self._callables,self._store_binding)))):
            raise ValueError('YEAR-V4 foreign/closed/stale parent operation')
        if not _same_control_runtime(self._runtime):raise ValueError('YEAR-V4 parent operation process/thread/runtime drift')
        if Path(directory).absolute()!=self._directory or Path(source).resolve()!=self._source:
            raise ValueError('YEAR-V4 parent directory/source scope drift')
        self._callables.guard();_guard_generation_owner()
        ProjectStore._reject_links(self._directory);ProjectStore._reject_links(self._source)
        if _control_files(self._directory)!=self._files:raise ValueError('YEAR-V4 parent immutable file bytes drift')
        contract=parse(self._contract_raw);meta=parse(self._meta_raw)
        _admit_token(self._admission,self._root,self._admission._raw,contract)
        if (canonical(source_manifest(self._source))!=canonical(contract['source_manifest']) or
                canonical(runtime_requirements(self._source))!=canonical(contract['requirements']) or
                canonical(runtime_identity())!=canonical(contract['runtime']) or
                contract['native_build']['runtime']!=runtime_binding() or
                meta['source_identity']!=project_source_identity()):
            raise ValueError('YEAR-V4 parent current source/build/runtime drift')
        from .lifetime_execution_authority import LONG,admit_authority
        authority=parse(self._authority_raw)
        if authority['mode']==LONG:
            # Genuine LONG evidence is external and can change independently of
            # this store. Its existing complete gate remains live on every use.
            from .lifetime_policy import admit_policy
            admit_authority(authority,self._root,self._admission._raw,contract,admit_policy(parse(self._policy_raw)),
                backend=contract['backend_binding']['selection'],build=contract['native_build'])
        from .lifetime_policy import admit_policy,PRODUCTION
        policy=admit_policy(parse(self._policy_raw))
        if policy.mode==PRODUCTION:
            from kit.serverctl import doctor
            if not doctor(self._source)['ready_for_engine_attempt']:raise ValueError('B64 production Linux doctor prerequisite')
        if self._store_binding is not None:
            store,root,seal=self._store_binding
            if (store.root_input is not root or Path(store.directory).absolute()!=self._directory or
                    canonical(store.meta)!=self._meta_raw or canonical(asdict(store.runner_policy))!=self._policy_raw):
                raise ValueError('YEAR-V4 parent bound store/root/policy drift')
            if seal is not None:seal.guard()
        if type(self._uses)is not int or not 0<=self._uses<2**20:raise ValueError('YEAR-V4 finite parent operation reuse')

    @property
    def root(self):
        self._guard(self._directory,self._source)
        return self._root

    def validate_store(self,store):
        try:self._bind_store(store)
        except BaseException:
            _refuse_parent(self)
            raise

    def _bind_store(self,store):
        self._guard(self._directory,self._source)
        from .lifecycle_application import LifecycleStore
        if type(store)is not LifecycleStore:raise TypeError('YEAR-V4 exact parent lifecycle store')
        if self._store_binding is not None:
            if self._store_binding[0]is not store:raise ValueError('YEAR-V4 one parent store per operation')
            return
        from .lifecycle_document import dumps_root
        from .lifecycle_prepared import _Seal
        if (Path(store.directory).absolute()!=self._directory or canonical(store.meta)!=self._meta_raw or
                canonical(asdict(store.runner_policy))!=self._policy_raw or
                dumps_root(store.root_input)!=self._admission._raw):
            raise ValueError('YEAR-V4 parent operation/store input binding')
        self._store_binding=(store,store.root_input,None if store.root_input is self._root else _Seal(store.root_input))
        self._pins=(*self._pins[:-1],self._store_binding)
        self._guard(self._directory,self._source)

    def contract(self,directory,source,*,job_id=None,request_sha256=None):
        try:return self._contract(directory,source,job_id=job_id,request_sha256=request_sha256)
        except BaseException:
            _refuse_parent(self)
            raise

    def _contract(self,directory,source,*,job_id=None,request_sha256=None):
        self._guard(directory,source)
        from .portable_job import parse
        from .lifetime_policy import admit_policy
        contract=parse(self._contract_raw)
        _admit_worker_request(self._directory,contract,parse(self._meta_raw),admit_policy(parse(self._policy_raw)),
            job_id=job_id,request_sha256=request_sha256)
        self._uses+=1
        return contract

    def receipt(self):
        self._guard(self._directory,self._source)
        return dict(format='YEAR_V4_PARENT_CONTRACT_OPERATION_V1',operation=self._operation,
            raw_admissions=1,contract_reuses=self._uses,root_identity=self._root.identity,
            contract_sha256=digest(self._contract_raw),generation=self._generation,
            scope='PROCESS_THREAD_OPERATION_LOCAL_DATA_NOT_WORKER_AUTHORITY')

    def invalidate(self):
        if not _same_control_runtime(self._runtime):raise ValueError('YEAR-V4 parent invalidation thread/process')
        _refuse_parent(self);self._phase='REVOKED'

    def close(self):
        if not _same_control_runtime(self._runtime):raise ValueError('YEAR-V4 parent close thread/process')
        _refuse_parent(self);self._phase='CLOSED'
        admission=self._admission
        from .lifecycle_job_prepared import JobInputAdmission
        if (type(admission)is JobInputAdmission and type(admission._phase)is str and
                admission._phase=='ADMITTED'):
            # This token was never supplied to the worker/job runtime. Break
            # both of its own self-cycles as well as its retained static graph.
            # A consumed token belongs to its existing job owner and is untouched.
            admission._phase='RETIRED_PARENT';admission._self=None;admission._binding=()
            admission.root=None;admission._schema=admission._root_seal=None
            admission._raw=admission._build_raw=b'';admission._factory=None
            admission._codec_receipt=b'{}';admission._work={}
        self._self=None;self._pins=();self._store_binding=None
        self._root=self._admission=self._callables=None;self._files=()
        self._contract_raw=self._authority_raw=self._meta_raw=self._policy_raw=None

    def __exit__(self,kind,error,traceback):
        if error is not None:
            try:self.close()
            except BaseException as secondary:_parent_close_secondary(error,secondary)
            return False
        try:
            if type(self._phase)is str and self._phase=='ACTIVE':self._guard(self._directory,self._source)
        except BaseException as primary:
            try:self.close()
            except BaseException as secondary:_parent_close_secondary(primary,secondary)
            raise
        self.close()
        return False


def parent_contract_operation(directory,source,*,operation):
    """Create an explicit single-use parent scope; entering performs full admission."""
    return _ParentContractOperation(directory,source,operation,_CONTROL_FACTORY)


def _parent_close_secondary(primary,secondary):
    """Record cleanup failure without replacing the already active exception."""
    try:
        BaseException.add_note(primary,'YEAR-V4 secondary parent close failure: '+repr(secondary))
        primary.secondary_close_failure=secondary
    except BaseException:
        pass


def _operation_contract(operation,directory,source,*,job_id=None,request_sha256=None,
        _owner=_ParentContractOperation,_consumer=_ParentContractOperation.contract,
        _seal_type=_ControlCallables,_seal_guard=_ControlCallables.guard,
        _seal_code=_ControlCallables.guard.__code__):
    if type(operation)is not _owner or _owner.contract is not _consumer:
        raise TypeError('YEAR-V4 exact parent operation consumer')
    phase=object.__getattribute__(operation,'_phase')
    if type(phase)is not str or phase!='ACTIVE':
        if type(phase)is not str or phase!='CLOSED':_refuse_parent(operation)
        raise ValueError('YEAR-V4 foreign/closed/stale parent operation')
    if (type(object.__getattribute__(operation,'_callables'))is not _seal_type or
            _seal_type.guard is not _seal_guard or _seal_guard.__code__ is not _seal_code):
        raise TypeError('YEAR-V4 exact parent operation consumer')
    try:
        _seal_guard(object.__getattribute__(operation,'_callables'))
        return _consumer(operation,directory,source,job_id=job_id,request_sha256=request_sha256)
    except BaseException:
        _refuse_parent(operation)
        raise


def parent_operation_root(operation,directory,source,raw):
    """Reuse only this operation's exact admitted bytes on a parent reopen.

    The caller retains its complete store metadata/static/lineage admission.
    This does not return the worker's one-shot private input admission.
    """
    _operation_contract(operation,directory,source)
    if type(raw)is not bytes or raw!=operation._admission._raw:
        operation.invalidate()
        raise ValueError('YEAR-V4 parent reopen exact admitted input bytes')
    return operation._root


class _StoreContractScope:
    """Attach only the current thread's explicitly opened operation to one store."""
    __slots__=('store','source','operation','local','owner','created')
    def __init__(self,store,source,operation):
        self.store=store;self.source=source;self.operation=operation
        self.local=self.owner=None;self.created=False
    def __enter__(self):
        from .portable_job import parse
        from .lifetime_execution_authority import _regular
        path=Path(self.store.directory)/'portable-job.json'
        if not path.exists():return None
        job=parse(_regular(path,2**20))
        if type(job)is not dict or job.get('format')not in(JOB_V3,JOB_V4):return None
        local=getattr(self.store,'_parent_contract_local',None)
        if local is None:
            local=threading.local();self.store._parent_contract_local=local
        if type(local)is not threading.local:raise TypeError('YEAR-V4 exact store thread-local scope')
        self.local=local;self.owner=getattr(local,'operation',None)
        if self.owner is not None:
            self.owner.validate_store(self.store)
            return self.owner
        owner=parent_contract_operation(self.store.directory,self.source,operation=self.operation)
        owner.__enter__()
        try:owner.validate_store(self.store)
        except BaseException:
            owner.close();raise
        self.owner=owner;self.created=True;local.operation=owner
        return owner
    def __exit__(self,kind,error,traceback):
        if self.created:
            try:self.owner.__exit__(kind,error,traceback)
            finally:self.local.operation=None


def store_contract_operation(store,source,*,operation):
    """Explicit parent operation context; legacy packages retain their old path."""
    return _StoreContractScope(store,source,operation)


def _metadata_source_identity(manifest):
    """Pure counterpart of the existing Python-owner/assets source identity."""
    names=sorted(name for name in manifest if name.startswith(('ops_sim/','examples/')) and
        name.endswith('.py') and name.rsplit('/',1)[-1]!='scenario_inputs.py')
    if not 1<=len(names)<=1024:raise ValueError('YEAR-V4 bounded control source population')
    python_identity=digest('\n'.join(name+':'+manifest[name]['sha256']for name in names).encode())
    prefix='ops_sim/v5/workbench_assets/'
    assets=sorted(name for name in manifest if name.startswith(prefix)and '/'not in name[len(prefix):])
    return digest((python_identity+'\n'+'\n'.join(name[len(prefix):]+':'+manifest[name]['sha256']for name in assets)).encode())


def _metadata_runtime_identity():
    from .portable_job import file_digest
    return dict(python=sys.version,platform=sys.platform,executable=sys.executable,
        interpreter_sha256=file_digest(sys.executable))


def _metadata_files(directory):
    from .lifetime_execution_authority import _regular
    from .lifetime_status import _reject_links
    rows=[]
    for name,limit,required in _CONTROL_FILES:
        path=_reject_links(directory/name)
        rows.append((name,limit,_regular(path,limit)if required or path.exists()else None))
    return tuple(rows)


def _metadata_function_state(function,retained,depth=0):
    if type(function)is not FunctionType or depth>16:raise ValueError('YEAR-V4 bounded control callable')
    code=function.__code__;defaults=function.__defaults__;keywords=function.__kwdefaults__;closure=function.__closure__
    retained.extend((function,code,defaults,keywords,closure,*(defaults or ())))
    kw=tuple((name,id(value))for name,value in (keywords or {}).items())
    if keywords:retained.extend(keywords.values())
    cells=[]
    for cell in closure or ():
        retained.append(cell)
        try:value=cell.cell_contents
        except ValueError:cells.append((id(cell),'EMPTY'));continue
        retained.append(value)
        cells.append((id(cell),id(value),_metadata_function_state(value,retained,depth+1)if type(value)is FunctionType else None))
    return (id(function),id(code),id(defaults),tuple(id(value)for value in defaults or ()),id(keywords),kw,id(closure),tuple(cells))


class _MetadataControlPins:
    """Only DATA/control callables; no scientific generation/admission owner."""
    __slots__=('functions','classes','retained','modules','state','state_code','_pins')
    def __init__(self):
        from . import (portable_job,lifetime_supervisor,year_project,lifetime_status,lifecycle_stream,lifecycle_compact,
            lifetime_no_launch,lifetime_journal,lifetime_status_objects,finite_campaign,battery_terminal,
            lifecycle_checkpoint,lifetime_execution_authority,lifecycle_runner_policy,lifetime_policy,lifecycle_backend,
            lifecycle_application,lifecycle_execution_budget)
        modules=(sys.modules[__name__],portable_job,lifetime_supervisor,year_project,lifetime_status,lifecycle_stream,lifecycle_compact,
            lifetime_no_launch,lifetime_journal,lifetime_status_objects,finite_campaign,battery_terminal,
            lifecycle_checkpoint,lifetime_execution_authority,lifecycle_runner_policy,lifetime_policy,lifecycle_backend,
            lifecycle_application,lifecycle_execution_budget)
        classes=(_MetadataControlStore,_MetadataControlPins,_MetadataRootData,lifecycle_stream.LifecycleStreamPolicy,
            lifecycle_compact.PublicationProfile,lifetime_policy.LifetimeCampaignPolicy,lifetime_policy.LifetimeCampaignPolicyV2,
            lifetime_journal.Journal)
        retained=[];declarations=[]
        for module in modules:
            declarations.extend((module,name,fn)for name,fn in vars(module).items()if type(fn)is FunctionType)
        for cls in classes:
            declarations.extend((cls,name,fn)for name,fn in vars(cls).items()if type(fn)is FunctionType)
            for value in vars(cls).values():
                if type(value)is property:
                    declarations.extend((value,name,fn)for name in ('fget','fset','fdel')if type(fn:=getattr(value,name))is FunctionType)
        self.functions=tuple((module,name,fn,_metadata_function_state(fn,retained))for module,name,fn in declarations)
        self.classes=tuple((cls,cls.__bases__,cls.__mro__,tuple(vars(cls).items()))for cls in classes)
        self.retained=tuple(retained)
        self.modules=tuple((module.__name__,module)for module in modules)
        self.state=_metadata_function_state;self.state_code=_metadata_function_state.__code__
        self._pins=(self.functions,self.classes,self.retained,self.modules,self.state,self.state_code)
    def guard(self):
        pins=object.__getattribute__(self,'_pins')
        names=('functions','classes','retained','modules','state','state_code')
        if type(pins)is not tuple or len(pins)!=len(names)or any(object.__getattribute__(self,name)is not saved for name,saved in zip(names,pins)):
            raise ValueError('YEAR-V4 metadata control seal drift')
        state=object.__getattribute__(self,'state')
        if state is not _metadata_function_state or state.__code__ is not object.__getattribute__(self,'state_code'):
            raise ValueError('YEAR-V4 metadata control signature origin')
        for name,module in object.__getattribute__(self,'modules'):
            if sys.modules.get(name)is not module:raise ValueError('YEAR-V4 metadata control module drift: '+name)
        for cls,bases,mro,entries in object.__getattribute__(self,'classes'):
            current=tuple(vars(cls).items())
            if cls.__bases__ is not bases or cls.__mro__ is not mro or len(current)!=len(entries)or any(n!=old or value is not prior for(n,value),(old,prior)in zip(current,entries)):
                raise ValueError('YEAR-V4 metadata control class/descriptor drift')
        for module,name,function,binding in object.__getattribute__(self,'functions'):
            if getattr(module,name,None)is not function or state(function,[])!=binding:
                raise ValueError('YEAR-V4 metadata control callable drift: '+name)


@dataclass(frozen=True,slots=True)
class _MetadataRootData:
    """Saved display coordinates, deliberately NOT a LifecycleRoot."""
    identity:str
    start_seconds:int
    end_seconds:int
    method:str
    output_policy:object


class _MetadataControlStore:
    """Bounded public read/Stop view. NEVER_EXECUTION_AUTHORITY.

    Hashes and plain JSON DATA are admitted; no typed root decoder, model,
    checkpoint restore, scientific permission gate or worker token is used.
    The existing status head/index and summary consumers retain their guards.
    """
    __slots__=('directory','source','meta','runner_policy','publication_profile','root_input','plan',
        '_contract','_files','_runtime','_phase','_gate','_binding','_reading','_read_units','_max_read_units','_output_raw','_coordinates')
    def __init__(self,directory,source):
        self.directory=Path(directory).absolute();self.source=Path(source).resolve()
        self._runtime=_control_runtime();self._phase='NEW';self._reading=False;self._read_units=0
        self._gate=None;self._binding=();self._files=();self._contract=None
    def __copy__(self):raise TypeError('YEAR-V4 metadata control is operation-local')
    def __deepcopy__(self,memo):raise TypeError('YEAR-V4 metadata control is operation-local')
    def __reduce_ex__(self,protocol):raise TypeError('YEAR-V4 metadata control is not execution DATA')
    def __enter__(self):
        if type(self._phase)is not str or self._phase!='NEW' or not _same_control_runtime(self._runtime):raise ValueError('YEAR-V4 metadata control entry scope')
        try:
            self._load();self._gate=_MetadataControlPins()
            self._binding=(self.directory,self.source,self.meta,self.runner_policy,self.publication_profile,self.root_input,self.plan,self._contract,self._files,self._runtime,self._gate,self._output_raw,self._coordinates)
            self._phase='ACTIVE'
        except BaseException:
            self.close();raise
        return self
    def _load(self):
        from .portable_job import parse,fields,identity
        from .lifecycle_runner_policy import admit_runner_store_metadata
        from .lifecycle_compact import admit_profile
        from .lifecycle_stream import LifecycleStreamPolicy
        from .lifecycle_backend import runtime_binding
        from .lifetime_execution_authority import admit_authority_data,domain_from_document
        from .lifetime_policy import is_v2
        from .lifetime_source import B64_SOURCE_PATHS,B65_SOURCE_PATHS
        self._files=_metadata_files(self.directory);saved={name:raw for name,limit,raw in self._files}
        contract=parse(saved['portable-execution.json']);job=parse(saved['portable-job.json']);_job_shell(job)
        admit_execution_contract_data_v3(contract)
        if canonical(contract)!=saved['portable-execution.json']or canonical(job)!=saved['portable-job.json']or canonical(job['contract'])!=canonical(contract):
            raise ValueError('YEAR-V4 metadata canonical package/contract binding')
        current=source_manifest(self.source);expected=contract['source_manifest']
        allowed=set(B65_SOURCE_PATHS if contract['format']==FORMAT_V4 else B64_SOURCE_PATHS)
        differences=sorted(name for name in set(current)|set(expected)if current.get(name)!=expected.get(name))
        if set(current)!=allowed or differences:
            raise ValueError('YEAR-V4 control codeview allowlist/source bytes drift: expected='+contract['source_manifest_sha256']+' actual='+digest(canonical(current))+' changed='+repr(differences[:8])+' unexpected='+repr(sorted(set(current)-allowed)[:8]))
        self.meta=parse(saved['store.json']);policy=admit_runner_store_metadata(self.meta)[0]
        if not is_v2(policy)or canonical(self.meta)!=saved['store.json']or canonical(asdict(policy))!=canonical(job['lifetime_policy']):
            raise ValueError('YEAR-V4 metadata store/policy DATA binding')
        actual_source=_metadata_source_identity(current)
        if self.meta['source_identity']!=actual_source:
            raise ValueError('YEAR-V4 control source identity drift: saved='+self.meta['source_identity']+' current='+actual_source)
        raw=saved['input.json'];document=parse(raw)
        fields(document,('format','version','inputs','digest'))
        if (canonical(document)!=raw or document['format']!='B61_EXPLICIT_ENVIRONMENT_AGEING_INPUT_V7'or document['version']!=7 or
                digest(canonical({name:value for name,value in document.items()if name!='digest'}))!=document['digest'] or
                len(raw)!=self.meta['input_bytes']or digest(raw)!=self.meta['input_sha256']or digest(raw)!=contract['input_sha256']or
                self.meta['root_identity']!=contract['root_identity']):raise ValueError('YEAR-V4 metadata exact input/root bytes')
        inputs=document['inputs'];admission=self.meta['admission'];duration=inputs['duration_seconds'];target=admission['end_seconds']
        if type(duration)is not int or not 1<=duration<=15*31557600 or type(target)is not int or target<duration:
            raise ValueError('YEAR-V4 metadata finite horizon')
        anchor=target-duration;accounting=contract['accounting_plan']
        if (admission['duration_seconds']!=duration or accounting['duration_seconds']!=duration or accounting['target_seconds']!=target or
                canonical(accounting['top_limits'])!=canonical(inputs['policy'])):raise ValueError('YEAR-V4 metadata accounting/horizon binding')
        self.runner_policy=policy
        self.publication_profile=admit_profile(self.meta['publication_profile'],self.meta['publication_profile_identity'])
        output=LifecycleStreamPolicy(**inputs['output_policy'])
        self._output_raw=canonical(inputs['output_policy'])
        self.root_input=_MetadataRootData(contract['root_identity'],anchor,target,inputs['method'],output)
        self._coordinates=(contract['root_identity'],anchor,target,inputs['method'])
        self._max_read_units=inputs['policy']['max_control_units']
        if type(self._max_read_units)is not int or not 1<=self._max_read_units<=2**64:raise ValueError('YEAR-V4 metadata finite read allowance')
        requirements=runtime_requirements(self.source);runtime=_metadata_runtime_identity()
        if (canonical(runtime)!=canonical(contract['runtime'])or canonical(runtime)!=canonical(self.meta['runtime'])or
                canonical(requirements)!=canonical(contract['requirements'])or canonical(requirements)!=canonical(job['requirements'])or
                contract['native_build']['runtime']!=runtime_binding()or saved['lifetime-native-build.json']!=canonical(contract['native_build'])):
            raise ValueError('YEAR-V4 metadata current runtime/build/requirements drift')
        authority=admit_authority_data(parse(saved['execution-authority.json']))
        if (canonical(authority)!=saved['execution-authority.json']or canonical(authority)!=canonical(job['execution_authority'])or
                digest(saved['execution-authority.json'])!=self.meta['execution_authority_sha256']):raise ValueError('YEAR-V4 metadata authority DATA pin')
        expected_authority=dict(root_identity=contract['root_identity'],input_sha256=digest(raw),source_manifest_sha256=contract['source_manifest_sha256'],
            runtime=runtime,execution_contract_sha256=digest(canonical(contract)),policy_identity=policy.identity,backend_binding=contract['backend_binding'],
            domain_identity=domain_from_document(document,anchor),original_anchor_seconds=anchor,duration_seconds=duration)
        if canonical(authority['binding'])!=canonical(expected_authority):raise ValueError('YEAR-V4 metadata authority context DATA')
        self._contract=contract;self.plan=parse(saved['lifetime-plan.json'])
        from .lifetime_supervisor import _plan
        if canonical(_plan(self,contract))!=saved['lifetime-plan.json']:raise ValueError('YEAR-V4 metadata immutable plan binding')
        for name in ('root_identity','source_identity','input_sha256'):identity(self.meta[name])
    def _basic(self):
        if (type(self)is not _MetadataControlStore or type(self._phase)is not str or self._phase!='ACTIVE'or
                not _same_control_runtime(self._runtime)or type(self._binding)is not tuple or len(self._binding)!=13 or
                any(value is not saved for value,saved in zip((self.directory,self.source,self.meta,self.runner_policy,self.publication_profile,self.root_input,self.plan,self._contract,self._files,self._runtime,self._gate,self._output_raw,self._coordinates),self._binding))):
            raise ValueError('YEAR-V4 foreign/closed metadata control scope')
        self._gate.guard()
        saved={name:raw for name,limit,raw in self._files}
        coordinates=(self.root_input.identity,self.root_input.start_seconds,self.root_input.end_seconds,self.root_input.method)
        if any(type(value)is not exact or value!=expected for value,expected,exact in zip(coordinates,self._coordinates,(str,int,int,str))):
            raise ValueError('YEAR-V4 metadata display coordinates drift')
        if (canonical(self.meta)!=saved['store.json']or canonical(self.plan)!=saved['lifetime-plan.json']or
                canonical(self._contract)!=saved['portable-execution.json']or
                canonical(asdict(self.runner_policy))!=canonical(self.meta['runner_policy'])or
                canonical(asdict(self.publication_profile))!=canonical(self.meta['publication_profile'])or
                self.root_input.identity!=self.meta['root_identity']or
                self.root_input.end_seconds!=self.meta['admission']['end_seconds']or
                self.root_input.start_seconds!=self.root_input.end_seconds-self.meta['admission']['duration_seconds']or
                canonical(asdict(self.root_input.output_policy))!=self._output_raw):
            raise ValueError('YEAR-V4 mutable metadata control DATA drift')
        if (type(self._reading)is not bool or type(self._read_units)is not int or self._read_units<0 or
                type(self._max_read_units)is not int or self._max_read_units!=self._contract['accounting_plan']['top_limits']['max_control_units']):
            raise ValueError('YEAR-V4 finite metadata control read state')
    def _pinned(self):
        self._basic()
        if self._reading:return
        if _metadata_files(self.directory)!=self._files:raise ValueError('YEAR-V4 metadata immutable file bytes drift')
        if canonical(source_manifest(self.source))!=canonical(self._contract['source_manifest']):raise ValueError('YEAR-V4 metadata current source bytes drift')
        if canonical(_metadata_runtime_identity())!=canonical(self.meta['runtime']):raise ValueError('YEAR-V4 metadata current runtime drift')
        from .lifecycle_backend import runtime_binding
        if (canonical(runtime_requirements(self.source))!=canonical(self._contract['requirements'])or
                runtime_binding()!=self._contract['native_build']['runtime']):
            raise ValueError('YEAR-V4 metadata current build/requirements drift')
    def path(self,*parts):
        if any(type(part)is not str or part in ('','.','..')or any(char in part for char in '/\\:')for part in parts):raise ValueError('YEAR-V4 metadata fixed path')
        result=self.directory.joinpath(*parts)
        if not result.resolve().is_relative_to(self.directory.resolve()):raise ValueError('YEAR-V4 metadata path containment')
        from .lifetime_status import _reject_links
        _reject_links(result)
        return result
    def job(self,jid):
        self._basic()
        from .portable_job import parse,identity
        from .lifetime_execution_authority import _regular
        from .lifetime_status import make_binding,read_envelope,index
        admitted_raw=_regular(self.path('jobs',jid,'request.json'),256*1024)
        _admit_worker_request(self.directory,self._contract,self.meta,self.runner_policy,job_id=jid,request_sha256=digest(admitted_raw))
        raw=_regular(self.path('jobs',jid,'request.json'),256*1024)
        if raw!=admitted_raw:raise ValueError('YEAR-V4 metadata request changed during admission')
        request=parse(raw)
        binding=make_binding(request,digest(raw),self.publication_profile.identity,self.runner_policy.identity)
        envelope,proof=read_envelope(self.path('jobs',jid,'status63'),binding,self.root_input.output_policy,profile=self.publication_profile)
        self._read_units+=proof.get('read_validation_reserved_units',65536)
        if self._read_units>self._max_read_units:raise ValueError('YEAR-V4 metadata read allowance exhausted')
        row=index(envelope,binding)
        if canonical({name:row[name]for name in request})!=raw:raise ValueError('YEAR-V4 metadata immutable request/current head disagreement')
        launch=row['launch']
        if launch is not None:
            from .portable_job import fields
            fields(launch,('observed_envelope_seconds','forced_interruption','timeout','unexpected'))
            observed=launch['observed_envelope_seconds'];unexpected=launch['unexpected']
            if (observed is not None and (type(observed)not in(int,float)or not 0<=observed<float('inf'))or
                    any(value is not None and type(value)is not bool for value in (launch['forced_interruption'],launch['timeout']))):
                raise ValueError('YEAR-V4 metadata current launch projection')
            if unexpected is not None:
                fields(unexpected,('type','reason'))
                if any(value is not None and(type(value)is not str or len(value)>limit)for value,limit in ((unexpected['type'],128),(unexpected['reason'],512))):
                    raise ValueError('YEAR-V4 metadata current launch failure projection')
        if row['result']is not None:
            from .battery_terminal import admit_bound_terminal
            from .lifecycle_checkpoint import admit_checkpoint_transport
            from .lifetime_policy import physical_storage
            from .portable_job import fields
            result=row['result'];cp=result['checkpoint'];terminal=admit_bound_terminal(result['typed_terminal'],row,result)
            receipt=admit_checkpoint_transport(cp)
            target=self.root_input.end_seconds if request['intent']['window_end_seconds']is None else request['intent']['window_end_seconds']
            if (type(result['clock'])is not int or type(cp['clock'])is not int or cp['kind']!='FINAL'or
                    not self.root_input.start_seconds<=result['clock']<=target<=self.root_input.end_seconds or
                    result['target_seconds']!=target or cp['clock']!=result['clock']or
                    physical_storage(self.runner_policy)and receipt is None):
                raise ValueError('YEAR-V4 metadata terminal clock/frontier')
            bindings=cp['bindings']
            fields(bindings,('root_identity','source_identity','runtime','method','input_sha256','clock','grid_identity'))
            if (any(canonical(bindings[name])!=canonical(self.meta[name])for name in ('root_identity','source_identity','runtime','input_sha256'))or
                    bindings['clock']!=cp['clock']or bindings['method']!=self.root_input.method):
                raise ValueError('YEAR-V4 metadata checkpoint frontier binding')
            for name in ('sha256',):identity(cp[name])
            identity(bindings['grid_identity'])
            import re
            if type(cp['file'])is not str or re.fullmatch(r'checkpoint-[0-9]{8}\.json',cp['file'])is None:
                raise ValueError('YEAR-V4 metadata checkpoint filename')
            # Reuse the bounded publication/frontier DATA reader, without
            # checkpoint graph decode, stream replay or native state restore.
            from .lifecycle_application import _publication_document
            _publication_document(self.path('jobs',jid),cp,self.root_input)
            if row.get('typed_stop')is not None and canonical(row['typed_stop'])!=canonical(terminal):raise ValueError('YEAR-V4 metadata terminal/current head disagreement')
        return row
    def jobs(self):
        self._basic();folder=self.path('jobs');names=[]
        if folder.exists():
            for path in folder.iterdir():
                names.append(path.name)
                if len(names)>self.runner_policy.maximum_jobs:raise ValueError('YEAR-V4 metadata job population')
        names.sort()
        from .portable_job import job_pin
        for jid in names:job_pin(self._contract,jid)
        return [self.job(jid)for jid in names]
    def snapshot(self):
        try:return self._snapshot()
        except BaseException:
            self._phase='REFUSED'
            raise
    def _snapshot(self):
        self._pinned()
        if self._reading:raise ValueError('YEAR-V4 reentrant metadata control read')
        self._reading=True
        try:
            from .lifetime_supervisor import _summary
            result=_summary(self,self.plan)
        finally:self._reading=False
        self._pinned()
        result.update(control_view='YEAR_V4_BOUNDED_METADATA_ONLY_NEVER_EXECUTION_AUTHORITY',execution_authority=False)
        return result
    def close(self):
        if not _same_control_runtime(self._runtime):raise ValueError('YEAR-V4 metadata close thread/process')
        self._phase='CLOSED';self._binding=();self._gate=None;self._files=();self._contract=None
        self._output_raw=None;self._coordinates=None
        for name in ('meta','runner_policy','publication_profile','root_input','plan'):
            if hasattr(self,name):setattr(self,name,None)
    def __exit__(self,kind,error,traceback):
        try:self.close()
        except BaseException as secondary:
            if error is None:raise
            try:error.add_note('secondary metadata close failure: '+repr(secondary));error.secondary_close_failure=secondary
            except BaseException:pass
        return False


def metadata_control_operation(directory,source):
    """Public read/Stop DATA owner, never an execution admission or token."""
    return _MetadataControlStore(directory,source)


def metadata_control_snapshot(view,_owner=_MetadataControlStore,_consumer=_MetadataControlStore.snapshot,
        _gate=_MetadataControlPins.guard,_code=_MetadataControlPins.guard.__code__):
    """Check raw class/callable origins before dispatching view predicates."""
    if type(view)is not _owner or _owner.snapshot is not _consumer:raise TypeError('YEAR-V4 exact metadata control view')
    phase=object.__getattribute__(view,'_phase')
    if type(phase)is not str or phase!='ACTIVE':raise ValueError('YEAR-V4 closed metadata control view')
    seal=object.__getattribute__(view,'_gate')
    if type(seal)is not _MetadataControlPins or _MetadataControlPins.guard is not _gate or _gate.__code__ is not _code:
        raise ValueError('YEAR-V4 metadata control guard origin')
    try:
        _gate(seal)
        return _consumer(view)
    except BaseException:
        object.__setattr__(view,'_phase','REFUSED')
        raise
