"""B60 offline initial-input jobs and read-only result bundles.

ZIP contents never supply commands. Dispatch uses the installed, hash-matching
fixed runner. Result import is inspection only, with no native execution rights.
"""
from pathlib import Path,PurePosixPath
from hashlib import sha256
import json,os,stat,sys,unicodedata,zipfile,struct
from .lifecycle_fast import REFERENCE,FAST

JOB='B60_PORTABLE_INITIAL_JOB_V1'
RESULT='B60_READ_ONLY_RESULT_V1'
LIFETIME_JOB='B62_PORTABLE_B61_LIFETIME_INITIAL_V1'
LIFETIME_JOB_V2='B63_PORTABLE_PREPARED_LIFETIME_INITIAL_V2'
LIFETIME_JOB_V3='B64_PORTABLE_TYPED_LIFETIME_INITIAL_V3'
LIFETIME_JOB_V4='B65_PORTABLE_TYPED_LIFETIME_INITIAL_V4'
CONTRACT='B60_EXECUTION_WORK_CONTRACT_V1'
MAX_MEMBERS=4096
MAX_PACKAGE=512*2**20
MAX_SOURCE=64*2**20
MAX_MANIFEST=2**20
MAX_MEMBER=64*2**20

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
def digest(b):return sha256(b).hexdigest()
def file_digest(path):
    h=sha256()
    with Path(path).open('rb')as f:
        for part in iter(lambda:f.read(2**20),b''):h.update(part)
    return h.hexdigest()
def fields(v,names):
    if type(v)is not dict or set(v)!=set(names):raise ValueError('B60_EXACT_FIELDS')
def integer(v,lo,hi):
    if type(v)is not int or not lo<=v<=hi:raise ValueError('B60_FINITE_INTEGER')
def identity(v):
    if type(v)is not str or len(v)!=64 or any(c not in '0123456789abcdef'for c in v):raise ValueError('B60_SHA256')
def parse(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('B60_DUPLICATE_KEY')
            d[k]=v
        return d
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('B60_NONFINITE')))
def safe(name):
    if (type(name)is not str or not name or len(name)>240 or '\\'in name or ':'in name or
        unicodedata.normalize('NFC',name)!=name or any(ord(c)<32 for c in name)):
        raise ValueError('B60_PACKAGE_PATH')
    p=PurePosixPath(name)
    if p.is_absolute() or any(x in ('','.','..')for x in name.split('/')):raise ValueError('B60_PACKAGE_PATH')
    if any(x.rstrip(' .')!=x or x.split('.')[0].upper()in {'CON','PRN','AUX','NUL',*(f'COM{i}'for i in range(10)),*(f'LPT{i}'for i in range(10))}for x in p.parts):raise ValueError('B60_PORTABLE_PATH')
    return name

def source_manifest(source):
    source=Path(source).resolve();result={}
    files=[];total=0
    for p in sorted(source.rglob('*')):
        if p.is_symlink():raise ValueError('B60_SOURCE_LINK')
        if not p.is_file():continue
        name=p.relative_to(source).as_posix()
        if any(x in ('.git','.venv','__pycache__','.pytest_cache')for x in p.relative_to(source).parts):continue
        safe(name);total+=p.stat().st_size;files.append((name,p))
        if len(files)>1024 or total>MAX_SOURCE:raise ValueError('B60_SOURCE_BYTES_BEFORE_READ')
    for name,p in files:
        b=p.read_bytes();result[name]=dict(bytes=len(b),sha256=digest(b))
    integer(len(result),1,1024)
    if sum(x['bytes']for x in result.values())>MAX_SOURCE:raise ValueError('B60_SOURCE_BYTES')
    return result


def dependency_requirements(source):
    import importlib.metadata,re
    path=Path(source)/'requirements.txt'
    if path.stat().st_size>65536:raise ValueError('B60_REQUIREMENTS_BYTES')
    data=path.read_bytes();text=data.decode('utf-16'if data.startswith((b'\xff\xfe',b'\xfe\xff'))else'utf-8-sig')
    result={}
    for line in text.splitlines():
        if not line.strip():continue
        if line.count('==')!=1:raise ValueError('B60_EXACT_PINNED_REQUIREMENT')
        name,version=line.split('==');name=name.lower().replace('_','-').replace('.','-')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,127}',name)or not re.fullmatch(r'[A-Za-z0-9_.+!-]{1,128}',version)or name in result:raise ValueError('B60_REQUIREMENT_SYNTAX')
        try:installed=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:raise ValueError('B60_DEPENDENCY_MISSING:'+name)from None
        if installed!=version:raise ValueError('B60_DEPENDENCY_VERSION:'+name)
        result[name]=version
    integer(len(result),1,128)
    return result


def runtime_requirements(source):
    return dict(python_major_minor=[sys.version_info.major,sys.version_info.minor],requirements_sha256=file_digest(Path(source)/'requirements.txt'),
        dependency_versions=dependency_requirements(source),dependencies='PINNED_REQUIREMENTS_TXT_NOT_BUNDLED_OR_AUTOINSTALLED')

def _admit_manifest(m):
    if type(m)is not dict:raise ValueError('B60_MANIFEST')
    integer(len(m),1,MAX_MEMBERS);total=0;keys=set()
    for n,v in m.items():
        safe(n);key=n.casefold()
        if key in keys:raise ValueError('B60_CASE_DUPLICATE')
        keys.add(key);fields(v,('bytes','sha256'));integer(v['bytes'],0,MAX_PACKAGE);identity(v['sha256']);total+=v['bytes']
        if total>MAX_PACKAGE:raise ValueError('B60_PACKAGE_TOTAL_BYTES')

def write_bundle(path,kind,payload):
    if kind not in (JOB,RESULT,LIFETIME_JOB):raise ValueError('B60_FORMAT')
    for n,b in payload.items():
        if n in ('MANIFEST.json','job.json','view.json'):integer(len(b),0,MAX_MANIFEST)
    m={safe(n):dict(bytes=len(b),sha256=digest(b))for n,b in payload.items()}
    _admit_manifest(m);manifest=canonical(dict(format=kind,files=m))
    if len(manifest)>MAX_MANIFEST:raise ValueError('B60_MANIFEST_BYTES')
    with Path(path).open('xb')as f:
        with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED)as z:
            z.writestr('MANIFEST.json',manifest)
            for n,b in sorted(payload.items()):z.writestr(n,b)
    return dict(path=str(Path(path).absolute()),sha256=file_digest(path),files=len(m))

def _admit_zip_directory(path):
    """Bound classic ZIP directory count/bytes before ZipFile builds ZipInfos.

    Producer limits do not need multipart, comments, SFX or ZIP64 containers.
    Input packages are immutable throughout admission; payload hashes remain
    independently checked below. At most16MiB directory,16385 entries.
    """
    size=path.stat().st_size
    if size<22:raise ValueError('B60_ZIP_DIRECTORY')
    with path.open('rb')as f:
        f.seek(size-22);end=f.read(22)
        sig,disk,start_disk,on_disk,count,cd_bytes,offset,comment=struct.unpack('<4s4H2LH',end)
        if sig!=b'PK\x05\x06'or disk or start_disk or comment or on_disk!=count:raise ValueError('B60_ZIP_DIRECTORY')
        integer(count,2,MAX_MEMBERS+1)
        if cd_bytes>16*2**20 or offset+cd_bytes!=size-22:raise ValueError('B60_ZIP_DIRECTORY_BYTES')
        f.seek(offset)
        for _ in range(count):
            header=f.read(46)
            if len(header)!=46 or header[:4]!=b'PK\x01\x02':raise ValueError('B60_ZIP_DIRECTORY_RECORD')
            name,extra,note=struct.unpack_from('<3H',header,28)
            if not 1<=name<=960 or f.tell()+name+extra+note>offset+cd_bytes:raise ValueError('B60_ZIP_DIRECTORY_RECORD')
            f.seek(name+extra+note,1)
        if f.tell()!=offset+cd_bytes:raise ValueError('B60_ZIP_DIRECTORY_COUNT')


def read_bundle(path,kind):
    p=Path(path)
    if p.stat().st_size>MAX_PACKAGE:raise ValueError('B60_COMPRESSED_BYTES')
    _admit_zip_directory(p)
    total_cap=MAX_SOURCE+2*MAX_MANIFEST if kind in (JOB,LIFETIME_JOB,LIFETIME_JOB_V3,LIFETIME_JOB_V4) else MAX_PACKAGE+MAX_MANIFEST
    with zipfile.ZipFile(p)as z:
        infos=z.infolist();integer(len(infos),2,MAX_MEMBERS+1);names=set();total=0
        for i in infos:
            safe(i.filename)
            if i.filename.casefold()in names or i.is_dir()or stat.S_ISLNK(i.external_attr>>16)or i.flag_bits&1:raise ValueError('B60_ZIP_MEMBER')
            names.add(i.filename.casefold());integer(i.file_size,0,MAX_MANIFEST if i.filename in ('MANIFEST.json','job.json','view.json')else MAX_MEMBER);total+=i.file_size
            if total>total_cap:raise ValueError('B60_ZIP_TOTAL')
        mi=z.getinfo('MANIFEST.json')
        if mi.file_size>MAX_MANIFEST:raise ValueError('B60_MANIFEST_BYTES')
        m=parse(z.read(mi));fields(m,('format','files'))
        if m['format']!=kind:raise ValueError('B60_BUNDLE_VERSION')
        _admit_manifest(m['files'])
        if set(z.namelist())!=set(m['files'])|{'MANIFEST.json'}:raise ValueError('B60_MEMBERSHIP')
        result={}
        for n,v in m['files'].items():
            if z.getinfo(n).file_size!=v['bytes']:raise ValueError('B60_MEMBER_SIZE')
            b=z.read(n)
            if len(b)!=v['bytes']or digest(b)!=v['sha256']:raise ValueError('B60_MEMBER_HASH')
            result[n]=b
        return result

def horizon_preflight(root):
    from .lifecycle_contract import YEAR,MONTH
    d=root.duration_seconds
    # Fixed named plan qualifies only one 30-day campaign, not arbitrary years.
    supported=d<=MONTH
    p=root.policy;offers=root.offered_population
    return dict(format='B60_HORIZON_ADMISSION_V1',duration_seconds=d,calendar='FIXED_30_DAY_BUCKET_V1',
        full_buckets=d//MONTH,partial_bucket_seconds=d%MONTH,offered=offers,
        causal_end_seconds=root.end_seconds,original_anchor_seconds=root.start_seconds,
        max_primary_segments=8,max_late_segments=2,lifetime_controller_limit=p.max_controller_decisions,
        lifetime_transition_limit=p.max_transitions,lifetime_control_limit=p.max_control_units,
        reserved_store_bytes=1313*2**20,store_cap_bytes=1536*2**20,
        admitted=supported,reason='BOUNDED_30_DAY_PLAN'if supported else'YEAR_PLAN_AND_LIFETIME_WORK_DISK_SEGMENT_PROOF_NOT_IMPLEMENTED',
        year_seconds=YEAR,qualification='NO_YEAR_OR_15_YEAR_EXECUTION_OR_EXTRAPOLATION')

def execution_contract(root,source,strategy):
    if strategy not in (REFERENCE,FAST):raise ValueError('B60_STRATEGY')
    from .lifecycle_document import dumps_root
    m=source_manifest(source)
    return dict(format='B61_ENVIRONMENT_EXECUTION_CONTRACT_V1'if root.environment_ageing_policy is not None else CONTRACT,strategy=strategy,source_manifest=m,source_manifest_sha256=digest(canonical(m)),
        root_identity=root.identity,input_sha256=digest(dumps_root(root)),
        cache_bytes=64*2**20,cache_entries=128,
        physical_work='B61_LEGACY_LEAVES_PLUS_SEPARATE_AGEING_RESERVATIONS_V1'if root.environment_ageing_policy is not None else'UNCHANGED_LEGACY_CALL_RESERVATIONS_NO_FAKE_SKIPPED_CALLS',
        static_work='ACTUAL_HITS_MISSES_GUARDS_FULL_OPERATIONS_CURRENT_PROCESS',contract_pin='B60_SAME_EXECUTION_CONTRACT_JOB_PIN_V1',publication_work='B60_RAW_STATUS8M_INSIDE128M_STREAMED_UNCHANGED_V1',
        restart='RECONSTRUCT_STATIC_CACHE_ONLY_NO_PHYSICAL_PREFIX',runtime_scope='SAME_RUNTIME_NATIVE_ONLY',**(dict(environment_policy_identity=root.environment_ageing_policy.identity,environment_native_format='B61_EXPOSURE_THERMAL_CHECKPOINT_V8',dynamic_environment='NOT_CACHED_RETAINED_CAUSAL_STATE_ONLY')if root.environment_ageing_policy is not None else {}))

def admit_contract(c,raw,source):
    if type(c)is dict and c.get('format')in('B64_TYPED_LIFETIME_EXECUTION_CONTRACT_V3','B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4'):
        from .lifetime_typed_portable import admit_execution_contract_v3
        return admit_execution_contract_v3(c,raw,source)
    from .lifecycle_document import loads_root
    root=loads_root(raw)
    if c.get('format')=='B62_B61_LIFETIME_EXECUTION_CONTRACT_V1':
        from .lifetime_portable import admit_execution_contract
        return admit_execution_contract(c,raw,source)
    fields(c,('format','strategy','source_manifest','source_manifest_sha256','root_identity','input_sha256','cache_bytes','cache_entries','physical_work','static_work','contract_pin','publication_work','restart','runtime_scope',*(('environment_policy_identity','environment_native_format','dynamic_environment')if root.environment_ageing_policy is not None else ())))
    expected=execution_contract(root,source,c['strategy'])
    if canonical(c)!=canonical(expected):raise ValueError('B60_EXECUTION_CONTRACT_DRIFT')
    return c


def prepare(path,root,source,*,strategy=FAST,key='0'*32,execution_seconds=240):
    from .lifecycle_document import dumps_root
    from .lifecycle_application import make_intent
    from .lifecycle_execution_budget import ExecutionBudget
    from .lifecycle_compact import PublicationProfile
    if Path(path).resolve().is_relative_to(Path(source).resolve()):raise ValueError('B60_OUTPUT_OUTSIDE_SOURCE')
    h=horizon_preflight(root)
    if not h['admitted']:raise ValueError(h['reason'])
    integer(execution_seconds,35,1550)
    profile=PublicationProfile()if root.output_policy is not None else None
    intent=make_intent(root.identity,key=key,execution_seconds=execution_seconds,maximum_output_bytes=128*2**20,
        execution_budget=ExecutionBudget(execution_seconds,execution_seconds-30,30),publication_profile=profile)
    c=execution_contract(root,source,strategy)
    job=dict(format=JOB,contract=c,intent=intent,horizon=h,
        requirements=runtime_requirements(source),
        limits=dict(rss_bytes=768*2**20,native_bytes=64*2**20,job_bytes=128*2**20,slots=10),
        entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False)
    payload={'job.json':canonical(job),'input.json':dumps_root(root)}
    payload.update({'source/'+n:(Path(source)/n).read_bytes()for n in c['source_manifest']})
    return write_bundle(path,JOB,payload)

def _admit_job_metadata(j,root,required_runtime):
    """Exact canonical types, shared by package and stored worker admission."""
    from .lifecycle_application import validate_intent
    long=j.get('format')==LIFETIME_JOB
    fields(j,('format','contract','intent','horizon','requirements','limits','entrypoint','native_import',*(('lifetime_policy',)if long else())))
    validate_intent(j['intent'])
    if long:
        from .lifetime_campaign import admit_policy,horizon_preflight as lifetime_preflight
        policy=admit_policy(j['lifetime_policy']);expected_horizon=lifetime_preflight(root,policy)
        from .lifetime_campaign import admit_intent_limits
        admit_intent_limits(policy,j['intent'])
        if j['intent']['parent_job_id']is not None or j['intent']['snapshot_sha256']is not None or j['intent']['mode']!='MAIN' or j['intent']['window_end_seconds']is not None:raise ValueError('lifetime initial package cannot import advanced state')
    else:expected_horizon=horizon_preflight(root)
    if (j['format'] not in (JOB,LIFETIME_JOB) or j['entrypoint']!='ops_sim.v5.lifecycle_application:worker' or
            j['native_import']is not False or canonical(j['horizon'])!=canonical(expected_horizon)or not expected_horizon['admitted']):
        raise ValueError('B60_JOB_AUTHORITY')
    if j['intent']['root_identity']!=root.identity:raise ValueError('B60_INTENT_ROOT')
    if canonical(j['requirements'])!=canonical(required_runtime):raise ValueError('B60_RUNTIME_REQUIREMENTS')
    expected_limits=dict(rss_bytes=768*2**20,native_bytes=64*2**20,job_bytes=policy.maximum_output_bytes if long else 128*2**20,slots=policy.maximum_jobs if long else 10)
    if canonical(j['limits'])!=canonical(expected_limits):raise ValueError('B60_JOB_LIMITS')


def admit_job(path,source):
    required_runtime=runtime_requirements(source)
    payload=read_bundle(path,JOB)
    if 'job.json'not in payload or 'input.json'not in payload:raise ValueError('B60_JOB_REQUIRED')
    j=parse(payload['job.json']);fields(j,('format','contract','intent','horizon','requirements','limits','entrypoint','native_import'))
    c=admit_contract(j['contract'],payload['input.json'],source)
    if set(payload)!={'job.json','input.json',*('source/'+n for n in c['source_manifest'])}:raise ValueError('B60_JOB_SCOPE')
    if any(digest(payload['source/'+n])!=v['sha256']for n,v in c['source_manifest'].items()):raise ValueError('B60_SOURCE_BINDING')
    from .lifecycle_document import loads_root
    root=loads_root(payload['input.json']);_admit_job_metadata(j,root,required_runtime)
    return j,root,payload['input.json']

def create_store(package,directory,source):
    if Path(directory).resolve().is_relative_to(Path(source).resolve()):raise ValueError('B60_STORE_OUTSIDE_SOURCE')
    j,root,raw=admit_job(package,source)
    from .lifecycle_application import LifecycleStore,_write_new
    from .finite_campaign import FiniteCampaignPolicy
    from .lifecycle_compact import PublicationProfile
    store=LifecycleStore(directory,root,create=True,runner_policy=FiniteCampaignPolicy(),publication_profile=PublicationProfile()if root.output_policy is not None else None)
    _write_new(store.path('portable-execution.json'),j['contract'])
    _write_new(store.path('portable-job.json'),j)
    return store,j['intent']

def prepare_lifetime(path,root,source,policy,*,strategy=FAST,key='0'*32,backend='REFERENCE',build=None,execution_mode='PILOT',acceptance=None):
    from .lifetime_policy import is_v2
    if type(backend)is str and backend in ('B64_TYPED_EXECUTION_V1','B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1','B65_TYPED_EXECUTION_V2'):
        if not is_v2(policy):raise TypeError('B64 typed execution requires exact V2 lifetime policy')
        from .lifetime_typed_portable import prepare_lifetime_v3
        return prepare_lifetime_v3(path,root,source,policy,strategy=strategy,key=key,backend=backend,build=build,execution_mode=execution_mode,acceptance=acceptance)
    if is_v2(policy):
        from .lifetime_portable import prepare_lifetime_v2
        return prepare_lifetime_v2(path,root,source,policy,strategy=strategy,key=key,backend=backend,build=build,execution_mode=execution_mode,acceptance=acceptance)
    if backend!='REFERENCE' or build is not None or execution_mode!='PILOT' or acceptance is not None:raise ValueError('B63 options require new policy')
    """New initial-input candidate contract; no B60 horizon refusal is weakened."""
    from dataclasses import asdict
    from .lifetime_campaign import LifetimeCampaignPolicy,horizon_preflight as lifetime_preflight
    from .lifecycle_document import dumps_root
    from .lifecycle_application import make_intent
    from .lifecycle_execution_budget import ExecutionBudget
    from .lifecycle_compact import PublicationProfile
    if type(policy)is not LifetimeCampaignPolicy:raise TypeError('exact lifetime policy')
    if Path(path).resolve().is_relative_to(Path(source).resolve()):raise ValueError('lifetime package outside source')
    h=lifetime_preflight(root,policy);profile=PublicationProfile()
    intent=make_intent(root.identity,key=key,execution_seconds=policy.hard_seconds,
        maximum_output_bytes=policy.maximum_output_bytes,
        execution_budget=ExecutionBudget(policy.hard_seconds,policy.soft_seconds,policy.finalization_seconds),
        publication_profile=profile)
    from .lifetime_portable import execution_contract as lifetime_execution_contract
    c=lifetime_execution_contract(root,source,strategy)
    job=dict(format=LIFETIME_JOB,contract=c,intent=intent,horizon=h,
        requirements=runtime_requirements(source),lifetime_policy=asdict(policy),
        limits=dict(rss_bytes=policy.maximum_rss_bytes,native_bytes=policy.maximum_native_bytes,
            job_bytes=policy.maximum_output_bytes,slots=policy.maximum_jobs),
        entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False)
    payload={'job.json':canonical(job),'input.json':dumps_root(root)}
    payload.update({'source/'+n:(Path(source)/n).read_bytes()for n in c['source_manifest']})
    return write_bundle(path,LIFETIME_JOB,payload)

def admit_lifetime_job(path,source):
    _admit_zip_directory(Path(path))
    with zipfile.ZipFile(path) as z:
        info=z.getinfo('MANIFEST.json')
        if info.file_size>MAX_MANIFEST:raise ValueError('B63 manifest bytes')
        kind=parse(z.read(info)).get('format')
    if kind==LIFETIME_JOB_V2:
        from .lifetime_portable import admit_lifetime_job_v2
        return admit_lifetime_job_v2(path,source)
    if kind in(LIFETIME_JOB_V3,LIFETIME_JOB_V4):
        from .lifetime_typed_portable import admit_lifetime_job_v3
        return admit_lifetime_job_v3(path,source)
    """Bounded, exact new package; no arbitrary command and no advanced input state."""
    required=runtime_requirements(source);payload=read_bundle(path,LIFETIME_JOB)
    if 'job.json'not in payload or 'input.json'not in payload:raise ValueError('lifetime package required members')
    j=parse(payload['job.json'])
    if j.get('format')!=LIFETIME_JOB:raise ValueError('lifetime package format')
    c=admit_contract(j['contract'],payload['input.json'],source)
    if set(payload)!={'job.json','input.json',*('source/'+n for n in c['source_manifest'])}:raise ValueError('lifetime package scope')
    if any(digest(payload['source/'+n])!=v['sha256']for n,v in c['source_manifest'].items()):raise ValueError('lifetime package source bytes')
    from .lifecycle_document import loads_root
    root=loads_root(payload['input.json']);_admit_job_metadata(j,root,required)
    return j,root,payload['input.json']

def create_lifetime_store(package,directory,source):
    if Path(directory).resolve().is_relative_to(Path(source).resolve()):raise ValueError('lifetime store outside source')
    _admit_zip_directory(Path(package))
    with zipfile.ZipFile(package)as archive:
        info=archive.getinfo('MANIFEST.json')
        if info.file_size>MAX_MANIFEST:raise ValueError('B64 manifest bytes before routing')
        kind=parse(archive.read(info)).get('format')
    if kind in(LIFETIME_JOB_V3,LIFETIME_JOB_V4):
        from .lifetime_typed_portable import create_lifetime_store_v3
        return create_lifetime_store_v3(package,directory,source)
    j,root,raw=admit_lifetime_job(package,source)
    if j['format']==LIFETIME_JOB_V2:
        from .lifetime_portable import create_lifetime_store_v2
        return create_lifetime_store_v2(package,directory,source)
    from .lifecycle_application import LifecycleStore,_write_new
    from .lifetime_campaign import admit_policy
    from .lifecycle_compact import PublicationProfile
    policy=admit_policy(j['lifetime_policy'])
    store=LifecycleStore(directory,root,create=True,runner_policy=policy,publication_profile=PublicationProfile())
    _write_new(store.path('portable-execution.json'),j['contract'])
    _write_new(store.path('portable-job.json'),j)
    return store,j['intent']

def worker_contract(directory,source,*,job_id=None,request_sha256=None,operation=None):
    if operation is not None:
        from .lifetime_typed_portable import _operation_contract
        return _operation_contract(operation,directory,source,job_id=job_id,request_sha256=request_sha256)
    directory=Path(directory)
    for name in ('portable-execution.json','portable-job.json'):
        from .project_store import ProjectStore
        path=directory/name;ProjectStore._reject_links(path)
        if not path.is_file()or path.stat().st_size>MAX_MANIFEST:raise ValueError('bounded public worker contract metadata')
    c=parse((directory/'portable-execution.json').read_bytes())
    j=parse((directory/'portable-job.json').read_bytes())
    if type(j)is dict and j.get('format')in(LIFETIME_JOB_V3,LIFETIME_JOB_V4):
        from .lifetime_typed_portable import worker_contract_v3
        return worker_contract_v3(directory,source,job_id=job_id,request_sha256=request_sha256)
    if j.get('format')==LIFETIME_JOB_V2:
        from .lifetime_portable import worker_contract_v2
        return worker_contract_v2(directory,source,job_id=job_id,request_sha256=request_sha256)
    fields(j,('format','contract','intent','horizon','requirements','limits','entrypoint','native_import',*(('lifetime_policy',)if j.get('format')==LIFETIME_JOB else())))
    if j['format'] not in (JOB,LIFETIME_JOB) or j['native_import']is not False or j['entrypoint']!='ops_sim.v5.lifecycle_application:worker' or canonical(j['contract'])!=canonical(c):
        raise ValueError('B60_WORKER_PACKAGE_CONTRACT_BINDING')
    from .lifecycle_document import loads_root
    _admit_job_metadata(j,loads_root((directory/'input.json').read_bytes()),runtime_requirements(source))
    c=admit_contract(c,(directory/'input.json').read_bytes(),source)
    if j['format']==LIFETIME_JOB:
        from .lifecycle_runner_policy import admit_runner_store_metadata
        from .lifetime_campaign import LifetimeCampaignPolicy
        from dataclasses import asdict
        meta=parse((directory/'store.json').read_bytes());policy=admit_runner_store_metadata(meta)[0]
        if type(policy)is not LifetimeCampaignPolicy or canonical(asdict(policy))!=canonical(j['lifetime_policy']):raise ValueError('lifetime store/package prospective policy drift')
    if job_id is not None:
        admit_job_pin(directory,job_id,c)
        request=directory/'jobs'/job_id/'request.json'
        if request.stat().st_size>256*1024 or digest(request.read_bytes())!=request_sha256:raise ValueError('B60_WORKER_REQUEST_PIN')
        r=parse(request.read_bytes())
        if r.get('job_id')!=job_id or r.get('root_identity')!=c['root_identity']:raise ValueError('B60_WORKER_PIN_CONTEXT')
        if r.get('resume')is not None:admit_job_pin(directory,r['resume']['parent_job_id'],c)
    return c


def worker_contract_for_store(store,source,*,job_id=None,request_sha256=None):
    """Use only an explicitly active parent operation on this store/thread."""
    import threading
    local=getattr(store,'_parent_contract_local',None)
    if local is not None and type(local)is not threading.local:
        raise TypeError('YEAR-V4 exact store thread-local contract owner')
    operation=None if local is None else getattr(local,'operation',None)
    if operation is not None:
        from .lifetime_typed_portable import _ParentContractOperation
        if (type(operation)is not _ParentContractOperation or operation._store_binding is None or
                operation._store_binding[0]is not store):
            raise ValueError('YEAR-V4 parent contract belongs to another store')
    return worker_contract(store.directory,source,job_id=job_id,request_sha256=request_sha256,operation=operation)


def job_pin(c,jid):
    if type(jid)is not str or len(jid)!=32 or any(x not in '0123456789abcdef'for x in jid):raise ValueError('B60_JOB_PIN_ID')
    return dict(format='B60_SAME_EXECUTION_CONTRACT_JOB_PIN_V1',job_id=jid,root_identity=c['root_identity'],
        input_sha256=c['input_sha256'],contract_sha256=digest(canonical(c)),strategy=c['strategy'])


def admit_job_pin(directory,jid,c):
    expected=job_pin(c,jid);path=Path(directory)/'jobs'/jid/'portable-contract-binding.json'
    from .project_store import ProjectStore
    ProjectStore._reject_links(path)
    if not path.is_file():raise ValueError('B60_MISSING_JOB_CONTRACT_PIN_NO_NATIVE_MIGRATION')
    if path.stat().st_size>4096 or canonical(parse(path.read_bytes()))!=canonical(expected):raise ValueError('B60_JOB_STRATEGY_CONTRACT_DRIFT')
    return expected


def export_result(store,path):
    # All result data is read-only. No copied native is continuation authority.
    store._pinned();payload={};files=[];total=0
    for p in sorted(store.directory.rglob('*')):
        if p.is_symlink():raise ValueError('B60_RESULT_LINK')
        if p.is_file()and 'tmp'not in p.relative_to(store.directory).parts:
            total+=p.stat().st_size;files.append(p)
            if total>MAX_PACKAGE-MAX_MANIFEST or len(files)>MAX_MEMBERS-1:raise ValueError('B60_RESULT_BYTES_BEFORE_READ')
    for p in files:payload['result/'+p.relative_to(store.directory).as_posix()]=p.read_bytes()
    jobs=store.jobs()
    if any(j['status']not in ('COMPLETED','INCOMPLETE','CANCELLED','REFUSED','PROCESS_FAILED','UNKNOWN')for j in jobs):raise ValueError('B60_RESULT_REQUIRES_SETTLED_STORE')
    payload['view.json']=canonical(dict(format=RESULT,root_identity=store.root_input.identity,jobs=jobs,
        read_only=True,native_execution_rights=False,credits_scope='DISPLAY_SAVED_ACTUAL_CREDITS_NEVER_MERGE_OR_DISPATCH',runtime=store.runtime))
    return write_bundle(path,RESULT,payload)

def inspect_result(path):
    path=Path(path)
    if path.stat().st_size>MAX_PACKAGE:raise ValueError('B60_COMPRESSED_BYTES')
    from .lifetime_result import inspect_result as lifetime_inspect
    # Both readers validate central-directory bounds before materializing data.
    # Try the new strict format; an old bundle is then admitted by its old codec.
    try:return lifetime_inspect(path)
    except ValueError as error:
        if str(error)!='B62 manifest schema/membership':raise
    p=read_bundle(path,RESULT)
    if 'view.json'not in p:raise ValueError('B60_VIEW_REQUIRED')
    v=parse(p['view.json']);fields(v,('format','root_identity','jobs','read_only','native_execution_rights','credits_scope','runtime'))
    if v['format']!=RESULT or v['read_only']is not True or v['native_execution_rights']is not False:raise ValueError('B60_READ_ONLY_VIEW')
    identity(v['root_identity'])
    if type(v['jobs'])is not list or len(v['jobs'])>10:raise ValueError('B60_RESULT_JOB_COUNT')
    seen=set()
    for j in v['jobs']:
        if type(j)is not dict or j.get('root_identity')!=v['root_identity']:raise ValueError('B60_RESULT_ROOT')
        jid=j.get('job_id')
        if type(jid)is not str or len(jid)!=32 or any(c not in '0123456789abcdef'for c in jid)or jid in seen:raise ValueError('B60_RESULT_JOB_ID')
        seen.add(jid)
        if j.get('status')not in ('COMPLETED','INCOMPLETE','CANCELLED','REFUSED','PROCESS_FAILED','UNKNOWN'):raise ValueError('B60_RESULT_NOT_SETTLED')
        if j.get('result')is not None:
            endpoint=j['result']['endpoint'];name='result/jobs/'+jid+'/'+safe(endpoint['file'])
            if name not in p or digest(p[name])!=endpoint['sha256']:raise ValueError('B60_RESULT_ENDPOINT_BINDING')
    return v
