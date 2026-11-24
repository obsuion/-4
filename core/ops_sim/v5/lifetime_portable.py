"""New B62 execution identity over B61 V7/V8, never an old producer alias."""
from pathlib import Path
from .portable_job import canonical,digest,source_manifest,runtime_requirements,execution_contract as legacy_contract
from .lifecycle_document import dumps_root,loads_root
from .lifecycle_fast import FAST,REFERENCE

FORMAT='B62_B61_LIFETIME_EXECUTION_CONTRACT_V1'

def execution_contract(root,source,strategy):
    from .lifetime_source import SOURCE_PATHS
    from .lifetime_admission import resource_plan
    if strategy not in(FAST,REFERENCE):raise ValueError('B62 explicit execution strategy')
    m=source_manifest(source)
    if set(m)!=set(SOURCE_PATHS):raise ValueError('B62 frozen current producer membership')
    c=legacy_contract(root,source,strategy)
    c.update(format=FORMAT,producer='M8_B62_CURRENT_SOURCE_PRODUCER_V1',
        runtime=__import__(__package__+'.project_store',fromlist=['runtime_identity']).runtime_identity(),
        requirements=runtime_requirements(source),accounting_plan=resource_plan(root),
        environment_policy_identity=root.environment_ageing_policy.identity,
        environment_native_format='B61_EXPOSURE_THERMAL_CHECKPOINT_V8',
        dynamic_environment='NOT_CACHED_RETAINED_CAUSAL_STATE_ONLY',
        native_migration=False)
    return c

def admit_execution_contract(contract,raw,source):
    expected=execution_contract(loads_root(raw),source,contract.get('strategy'))
    if canonical(contract)!=canonical(expected):raise ValueError('B62 execution/source/runtime/input contract drift')
    return contract


# New producer and package identity.  The B62 functions and SOURCE_PATHS754
# contract above are intentionally not aliases of these successors.
FORMAT_V2='B63_PREPARED_LIFETIME_EXECUTION_CONTRACT_V2'
JOB_V2='B63_PORTABLE_PREPARED_LIFETIME_INITIAL_V2'


def _load_bound_root_v2(raw,contract):
    from .lifecycle_backend import load_root_for_backend
    if type(contract)is not dict or type(contract.get('backend_binding'))is not dict:
        raise ValueError('B63 explicit input codec binding')
    return load_root_for_backend(raw,contract['backend_binding'].get('selection'))


def execution_contract_v2(root,source,strategy,*,backend='REFERENCE',build=None):
    from .lifetime_source import B63_SOURCE_PATHS
    from .lifetime_admission import resource_plan
    from .lifetime_execution_authority import backend_binding
    from .project_store import runtime_identity
    if strategy not in(FAST,REFERENCE):raise ValueError('B63 explicit static/cache strategy')
    manifest=source_manifest(source)
    if set(manifest)!=set(B63_SOURCE_PATHS):raise ValueError('B63 frozen current producer membership')
    binding=backend_binding(backend,build)
    if build is not None:
        artifact=build['artifact'];declared=manifest.get(artifact['path'])
        if declared!=dict(bytes=artifact['bytes'],sha256=artifact['sha256']):
            raise ValueError('B63 actual build artifact/current source manifest binding')
    result=legacy_contract(root,source,strategy)
    result.update(format=FORMAT_V2,producer='M8_B63_PREPARED_CURRENT_SOURCE_PRODUCER_V2',
        runtime=runtime_identity(),requirements=runtime_requirements(source),
        accounting_plan=resource_plan(root),environment_policy_identity=root.environment_ageing_policy.identity,
        environment_native_format='B61_EXPOSURE_THERMAL_CHECKPOINT_V8',
        dynamic_environment='NOT_CACHED_RETAINED_CAUSAL_STATE_ONLY',native_migration=False,
        backend_binding=binding,native_build=None if build is None else __import__('json').loads(canonical(build)),
        execution_authority='B63_IMMUTABLE_PILOT_OR_GENUINE_LONG_V1',
        publication_work='B63_BOUNDED_STATUS_DETAILS_PRECHARGED_V1')
    return result


def admit_execution_contract_v2(contract,raw,source):
    if type(contract)is not dict or type(contract.get('backend_binding'))is not dict:
        raise ValueError('B63 typed prepared execution contract')
    expected=execution_contract_v2(_load_bound_root_v2(raw,contract),source,contract.get('strategy'),
        backend=contract['backend_binding'].get('selection'),build=contract.get('native_build'))
    if canonical(contract)!=canonical(expected):raise ValueError('B63 execution/source/runtime/backend/build/input contract drift')
    return contract


def admit_execution_contract_data_v2(value):
    """Strict new contract DATA reader, without binary imports/model evaluation."""
    from .portable_job import fields,identity,_admit_manifest
    from .lifetime_execution_authority import backend_binding
    names={'format','strategy','source_manifest','source_manifest_sha256','root_identity','input_sha256',
        'cache_bytes','cache_entries','physical_work','static_work','contract_pin','publication_work',
        'restart','runtime_scope','environment_policy_identity','environment_native_format',
        'dynamic_environment','producer','runtime','requirements','accounting_plan','native_migration',
        'backend_binding','native_build','execution_authority'}
    fields(value,names)
    constants=dict(format=FORMAT_V2,producer='M8_B63_PREPARED_CURRENT_SOURCE_PRODUCER_V2',
        physical_work='B61_LEGACY_LEAVES_PLUS_SEPARATE_AGEING_RESERVATIONS_V1',
        static_work='ACTUAL_HITS_MISSES_GUARDS_FULL_OPERATIONS_CURRENT_PROCESS',
        contract_pin='B60_SAME_EXECUTION_CONTRACT_JOB_PIN_V1',
        publication_work='B63_BOUNDED_STATUS_DETAILS_PRECHARGED_V1',
        restart='RECONSTRUCT_STATIC_CACHE_ONLY_NO_PHYSICAL_PREFIX',runtime_scope='SAME_RUNTIME_NATIVE_ONLY',
        environment_native_format='B61_EXPOSURE_THERMAL_CHECKPOINT_V8',
        dynamic_environment='NOT_CACHED_RETAINED_CAUSAL_STATE_ONLY',
        execution_authority='B63_IMMUTABLE_PILOT_OR_GENUINE_LONG_V1')
    if any(type(value[k])is not str or value[k]!=v for k,v in constants.items())or value['strategy']not in(FAST,REFERENCE)or value['native_migration']is not False:
        raise ValueError('B63 exact versioned contract DATA')
    for name in ('source_manifest_sha256','root_identity','input_sha256','environment_policy_identity'):
        identity(value[name])
    if type(value['cache_bytes'])is not int or value['cache_bytes']!=64*2**20 or type(value['cache_entries'])is not int or value['cache_entries']!=128:
        raise ValueError('B63 exact static/cache finite contract DATA')
    _admit_manifest(value['source_manifest'])
    if digest(canonical(value['source_manifest']))!=value['source_manifest_sha256']or len(value['source_manifest'])>1024 or sum(x['bytes']for x in value['source_manifest'].values())>64*2**20:
        raise ValueError('B63 source manifest DATA binding')
    fields(value['runtime'],('python','platform','executable','interpreter_sha256'))
    if any(type(value['runtime'][k])is not str or not 0<len(value['runtime'][k].encode('utf8'))<=4096 for k in ('python','platform','executable')):
        raise ValueError('B63 runtime DATA text')
    identity(value['runtime']['interpreter_sha256'])
    requirements=value['requirements']
    fields(requirements,('python_major_minor','requirements_sha256','dependency_versions','dependencies'))
    if (type(requirements['python_major_minor'])is not list or len(requirements['python_major_minor'])!=2 or
            any(type(x)is not int or not 0<=x<=999 for x in requirements['python_major_minor'])or
            type(requirements['dependency_versions'])is not dict or not 1<=len(requirements['dependency_versions'])<=128 or
            any(type(k)is not str or type(v)is not str or not k or not v or len(k)>128 or len(v)>128 for k,v in requirements['dependency_versions'].items())or
            requirements['dependencies']!='PINNED_REQUIREMENTS_TXT_NOT_BUNDLED_OR_AUTOINSTALLED'):
        raise ValueError('B63 pinned requirement DATA')
    identity(requirements['requirements_sha256'])
    plan=value['accounting_plan']
    fields(plan,('format','root_identity','duration_seconds','target_seconds','offered','full_30day_buckets',
        'terminal_bucket_seconds','accounting','top_limits','physical_limits','orbit_limits',
        'environment_proposals','formulas','conditional_checks','conditional_assumptions','unknown_terms',
        'quota_completion_proof','cpu_seconds','qualification'))
    if plan['format']!='B62_SOURCE_DERIVED_LIFETIME_RESOURCE_PLAN_V1'or plan['root_identity']!=value['root_identity']or plan['accounting']!='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'or plan['quota_completion_proof']is not False or plan['cpu_seconds']!='UNKNOWN':
        raise ValueError('B63 bounded conditional accounting plan DATA')
    for name in ('duration_seconds','target_seconds','offered','full_30day_buckets','terminal_bucket_seconds','environment_proposals'):
        if type(plan[name])is not int or not 0<=plan[name]<=2**64:raise ValueError('B63 finite accounting plan DATA integer')
    if any(type(plan[name])is not dict for name in ('top_limits','physical_limits','orbit_limits','formulas'))or type(plan['conditional_checks'])is not list or len(plan['conditional_checks'])>128:
        raise ValueError('B63 conditional plan DATA collections')
    for row in plan['conditional_checks']:
        fields(row,('name','reservation','cap','pass_'))
        if type(row['name'])is not str or type(row['reservation'])is not int or type(row['cap'])is not int or not 0<=row['reservation']<=2**128 or not 0<=row['cap']<=2**128 or type(row['pass_'])is not bool or row['pass_']!=(row['reservation']<=row['cap']):
            raise ValueError('B63 exact conditional plan row')
    for name in ('conditional_assumptions','unknown_terms'):
        if type(plan[name])is not list or len(plan[name])>128 or any(type(x)is not str or len(x)>4096 for x in plan[name]):
            raise ValueError('B63 conditional plan assumptions DATA')
    if type(plan['qualification'])is not str or len(plan['qualification'])>4096:
        raise ValueError('B63 conditional plan qualification DATA')
    binding=value['backend_binding']
    if type(binding)is not dict or canonical(binding)!=canonical(backend_binding(binding.get('selection'),value['native_build'])):
        raise ValueError('B63 backend/build DATA binding')
    if value['native_build']is not None:
        artifact=value['native_build']['artifact']
        if value['source_manifest'].get(artifact['path'])!=dict(bytes=artifact['bytes'],sha256=artifact['sha256']):
            raise ValueError('B63 build/source manifest DATA binding')
    if len(canonical(value))>2**20:raise ValueError('B63 execution contract DATA byte limit')
    return value


def _job_metadata_v2(job,root,source):
    from dataclasses import asdict
    from .portable_job import fields
    from .lifetime_policy import admit_policy,is_v2
    from .lifetime_campaign import horizon_preflight,admit_intent_limits
    from .lifecycle_application import validate_intent
    from .lifetime_execution_authority import admit_authority
    fields(job,('format','contract','intent','horizon','requirements','limits','entrypoint',
                'native_import','lifetime_policy','execution_authority'))
    if job['format']!=JOB_V2 or job['entrypoint']!='ops_sim.v5.lifecycle_application:worker' or job['native_import']is not False:
        raise ValueError('B63 explicit initial prepared package format/entrypoint')
    policy=admit_policy(job['lifetime_policy'])
    if not is_v2(policy):raise ValueError('B63 initial package requires new lifetime policy')
    if canonical(job['horizon'])!=canonical(horizon_preflight(root,policy))or canonical(job['requirements'])!=canonical(runtime_requirements(source)):
        raise ValueError('B63 initial package horizon/runtime requirements')
    limits=dict(rss_bytes=policy.maximum_rss_bytes,native_bytes=policy.maximum_native_bytes,
                job_bytes=policy.maximum_output_bytes,slots=policy.maximum_jobs)
    if canonical(job['limits'])!=canonical(limits):raise ValueError('B63 exact prospective package limits')
    intent=validate_intent(job['intent']);admit_intent_limits(policy,intent)
    if intent['root_identity']!=root.identity or intent['parent_job_id']is not None or intent['snapshot_sha256']is not None or intent['mode']!='MAIN' or intent['window_end_seconds']is not None:
        raise ValueError('B63 portable input cannot import an advanced checkpoint')
    contract=job['contract']
    admit_authority(job['execution_authority'],root,dumps_root(root),contract,policy,
        backend=contract['backend_binding']['selection'],build=contract['native_build'])
    return policy


def prepare_lifetime_v2(path,root,source,policy,*,strategy=FAST,key='0'*32,
                        backend='REFERENCE',build=None,execution_mode='PILOT',acceptance=None):
    """New initial input only; full permission admission precedes output writes."""
    import os,zipfile
    from dataclasses import asdict
    from .portable_job import (_admit_manifest,MAX_MANIFEST,safe,file_digest)
    from .lifetime_policy import is_v2
    from .lifetime_campaign import horizon_preflight
    from .lifecycle_application import make_intent
    from .lifecycle_execution_budget import ExecutionBudget
    from .lifecycle_compact import PublicationProfile
    from .lifetime_execution_authority import make_authority
    if not is_v2(policy):raise TypeError('B63 exact new lifetime policy')
    if Path(path).resolve().is_relative_to(Path(source).resolve()):raise ValueError('B63 package must be outside source')
    raw=dumps_root(root);contract=execution_contract_v2(root,source,strategy,backend=backend,build=build)
    authority=make_authority(root,raw,contract,policy,mode=execution_mode,
                              backend=backend,build=build,acceptance=acceptance)
    intent=make_intent(root.identity,key=key,execution_seconds=policy.hard_seconds,
        maximum_output_bytes=policy.maximum_output_bytes,
        execution_budget=ExecutionBudget(policy.hard_seconds,policy.soft_seconds,policy.finalization_seconds),
        publication_profile=PublicationProfile())
    job=dict(format=JOB_V2,contract=contract,intent=intent,horizon=horizon_preflight(root,policy),
        requirements=runtime_requirements(source),lifetime_policy=asdict(policy),
        limits=dict(rss_bytes=policy.maximum_rss_bytes,native_bytes=policy.maximum_native_bytes,
            job_bytes=policy.maximum_output_bytes,slots=policy.maximum_jobs),
        entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False,
        execution_authority=authority)
    _job_metadata_v2(job,root,source)
    payload={'job.json':canonical(job),'input.json':raw}
    payload.update({'source/'+n:(Path(source)/n).read_bytes()for n in contract['source_manifest']})
    if any(dict(bytes=len(payload['source/'+n]),sha256=digest(payload['source/'+n]))!=v for n,v in contract['source_manifest'].items()):
        raise ValueError('B63 source changed between admission and package write')
    manifest={safe(n):dict(bytes=len(b),sha256=digest(b))for n,b in payload.items()}
    _admit_manifest(manifest);metadata=canonical(dict(format=JOB_V2,files=manifest))
    if len(payload['job.json'])>MAX_MANIFEST or len(metadata)>MAX_MANIFEST:raise ValueError('B63 initial package metadata bytes')
    with Path(path).open('xb')as stream:
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED)as archive:
            archive.writestr('MANIFEST.json',metadata)
            for name,data in sorted(payload.items()):archive.writestr(name,data)
        stream.flush();os.fsync(stream.fileno())
    return dict(path=str(Path(path).absolute()),sha256=file_digest(path),files=len(manifest))


def admit_lifetime_job_v2(path,source):
    from .portable_job import read_bundle,parse,MAX_SOURCE,MAX_MANIFEST
    payload=read_bundle(path,JOB_V2)
    if 'job.json'not in payload or 'input.json'not in payload:raise ValueError('B63 initial package required members')
    if sum(len(v)for k,v in payload.items()if k.startswith('source/'))>MAX_SOURCE or len(payload['job.json'])>MAX_MANIFEST:
        raise ValueError('B63 initial package source/metadata bytes')
    job=parse(payload['job.json']);root=_load_bound_root_v2(payload['input.json'],job.get('contract'))
    contract=admit_execution_contract_v2(job.get('contract'),payload['input.json'],source)
    if set(payload)!={'job.json','input.json',*('source/'+n for n in contract['source_manifest'])}:
        raise ValueError('B63 initial package exact scope')
    if any(dict(bytes=len(payload['source/'+n]),sha256=digest(payload['source/'+n]))!=v for n,v in contract['source_manifest'].items()):
        raise ValueError('B63 initial package source raw bytes')
    _job_metadata_v2(job,root,source)
    return job,root,payload['input.json']


def create_lifetime_store_v2(package,directory,source):
    from .lifecycle_application import LifecycleStore,_write_new
    from .lifetime_policy import admit_policy
    from .lifecycle_compact import PublicationProfile
    if Path(directory).resolve().is_relative_to(Path(source).resolve()):raise ValueError('B63 store must be outside source')
    job,root,_=admit_lifetime_job_v2(package,source)
    policy=admit_policy(job['lifetime_policy'])
    store=LifecycleStore(directory,root,create=True,runner_policy=policy,
        publication_profile=PublicationProfile(),execution_authority=job['execution_authority'])
    try:
        _write_new(store.path('portable-execution.json'),job['contract'])
        _write_new(store.path('portable-job.json'),job)
        if job['contract']['native_build']is not None:
            _write_new(store.path('lifetime-native-build.json'),job['contract']['native_build'],65536)
    except BaseException:
        store.close_publications()
        raise
    return store,job['intent']


def worker_contract_v2(directory,source,*,job_id=None,request_sha256=None):
    """Exact new package/store/authority pin; does not launch or restore physics."""
    from dataclasses import asdict
    from .portable_job import parse,admit_job_pin,integer
    from .lifecycle_runner_policy import admit_runner_store_metadata
    from .lifetime_policy import is_v2
    from .lifetime_execution_authority import admit_authority_data
    from .project_store import ProjectStore
    directory=Path(directory)
    def read(name,limit=2**20):
        path=directory/name;ProjectStore._reject_links(path)
        if not path.is_file()or path.stat().st_size>limit:raise ValueError('B63 bounded regular worker metadata')
        return path.read_bytes()
    raw=read('input.json',8*2**20)
    contract=parse(read('portable-execution.json'));job=parse(read('portable-job.json'))
    if canonical(job.get('contract'))!=canonical(contract):raise ValueError('B63 worker package/contract binding')
    root=_load_bound_root_v2(raw,contract)
    admit_execution_contract_v2(contract,raw,source);policy=_job_metadata_v2(job,root,source)
    meta=parse(read('store.json'));saved=admit_runner_store_metadata(meta)[0]
    if not is_v2(saved)or canonical(asdict(saved))!=canonical(asdict(policy)):
        raise ValueError('B63 worker store/package prospective policy drift')
    authority_raw=read('execution-authority.json',16384);authority=parse(authority_raw)
    admit_authority_data(authority)
    if canonical(authority)!=authority_raw or canonical(authority)!=canonical(job['execution_authority'])or digest(authority_raw)!=meta['execution_authority_sha256']:
        raise ValueError('B63 worker exact authority/store/package pin')
    if meta['root_identity']!=root.identity or meta['input_sha256']!=digest(raw)or meta['runtime']!=contract['runtime']:
        raise ValueError('B63 worker exact root/input/runtime metadata binding')
    if contract['native_build']is not None:
        if read('lifetime-native-build.json',65536)!=canonical(contract['native_build']):
            raise ValueError('B63 worker actual build receipt pin')
    if job_id is not None:
        admit_job_pin(directory,job_id,contract)
        request=read('jobs/'+job_id+'/request.json',256*1024)
        if digest(request)!=request_sha256:raise ValueError('B63 worker request hash pin')
        value=parse(request)
        if value.get('job_id')!=job_id or value.get('root_identity')!=root.identity:
            raise ValueError('B63 worker request context')
        if value.get('resume')is not None:admit_job_pin(directory,value['resume']['parent_job_id'],contract)
    return contract
