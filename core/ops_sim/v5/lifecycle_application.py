"""Pinned local lifecycle jobs, direct continuation and bounded owned dispatch.

Stores are separate from B51 jobs. Immutable request and status publications
avoid replacing a metadata file that a Windows reader may hold open. Reopening
never reconstructs ownership from a PID and never launches a calculation.
"""
from .lifetime_io_accounting import fsync as _io_fsync
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from fractions import Fraction
import argparse,csv,datetime,io,json,math,os,re,sys,threading,time,traceback,uuid,zipfile
from .experiment_codec import object_fields,parse_json
from .lifecycle_contract import METHOD,METHOD53,METHOD55,canonical,integer,identity,static_admission
from .project_store import ProjectStore,identifier,file_sha,runtime_identity
from .spacecraft_project import project_source_identity
from .lifecycle_runner_policy import (LifecycleRunnerStorePolicy,STORE_V2,
    admit_runner_store_metadata,requested_runner_policy)
from .lifetime_campaign import LifetimeCampaignPolicy, is_typed_campaign_policy, store_format
from .lifecycle_stream import (ChunkedStreamWriter,IncrementalStreamReader,StatusStream,read_latest_status,
    CheckpointCatalog,checkpoint_page,lookup_checkpoint,verify_stream)
from .lifecycle_compact import (PublicationProfile,admit_profile,INTENT as PROFILE_INTENT,STORE as PROFILE_STORE,
    CompactStreamWriter,FRONTIER as COMPACT_FRONTIER)

STORE='B52_PINNED_LIFECYCLE_STORE_V1'
JOB='B52_OWNED_LIFECYCLE_JOB_V1'
INTENT='B52_DURABLE_LIFECYCLE_INTENT_V1'
JOURNAL='B52_VALIDATED_COMMITTED_LIFECYCLE_JOURNAL_V1'
# Source-pinned wrapper choice. A compiled activation requires the separate
# plain same-root comparison gate; legacy roots always keep baseline admission.
PRODUCTION_EXECUTION_MODE='B54_FROZEN_INPUT_ADMISSION_V1'
TERMINAL=('COMPLETED','INCOMPLETE','CANCELLED','PROCESS_FAILED','REFUSED','UNKNOWN')
INTENT_FIELDS=('format','idempotency_key','root_identity','mode','parent_job_id','snapshot_sha256','window_end_seconds','execution_seconds','maximum_output_bytes')
MAX_METADATA=256*1024
MAX_EXPORT=128*2**20
MAX_JOBS=4
MAX_STATUS=4096
# Full hydrated jobs are transient handoff data, not a lifetime history cache.
LIFETIME_HYDRATED_CACHE_LIMIT=2
PUBLICATION='B52_CUMULATIVE_EXTERNAL_PUBLICATION_LEDGER_V1'
PUBLICATION_FIELDS=('admission_attempts','checkpoint_encoding_reserved_units','checkpoint_storage_reserved_bytes',
    'publication_metadata_reserved_bytes','restore_validation_reserved_units')
PUBLICATION53='B53_CUMULATIVE_CHUNKED_PUBLICATION_LEDGER_V1'
PUBLICATION_FIELDS53=(*PUBLICATION_FIELDS,'stream_encoded_bytes_reserved','stream_publication_attempts','stream_validation_bytes_reserved')
PUBLICATION54='B54_CHECKPOINT_PUBLICATION_PREFIX_V2'
SETTLED_PUBLICATION54='B54_SETTLED_ATTEMPT_PUBLICATION_WORK_V1'
STREAM_NAMES54=('progress','events','months','details')
SERVICE_CHECKPOINT_KINDS=('SERVICE_SAFE','SERVICE_POWER_OFF','SERVICE_RECOVERY')
SETTLED_SCOPE54='WHOLE_SETTLED_ATTEMPT_WRAPPER_COSTS_SEPARATE_FROM_SELECTED_NATIVE_STATE'
SETTLED_RECEIPT_BYTES=16384
PARENT_COST=__import__('struct').Struct('>QQ')


def _utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def _bytes(value):return canonical(value).encode('utf-8')


class _InvocationTiming:
    """Disjoint public-call timers; observational and never restart authority."""
    def __init__(self,wall=None,cpu=None):
        self.wall=time.perf_counter_ns if wall is None else wall
        self.cpu=time.process_time_ns if cpu is None else cpu
        self.origin_wall=self.wall();self.origin_cpu=self.cpu()
        self.rows={name:dict(attempted=0,returned=0,raised=0,wall_ns=0,worker_cpu_ns=0)
            for name in ('start','restore','step')}
    def call(self,name,function,*args,**kwargs):
        row=self.rows[name];row['attempted']+=1;wall=self.wall();cpu=self.cpu()
        try:
            result=function(*args,**kwargs)
        except BaseException:
            row['raised']+=1;raise
        else:
            row['returned']+=1;return result
        finally:
            row['worker_cpu_ns']+=self.cpu()-cpu;row['wall_ns']+=self.wall()-wall
    def snapshot(self):
        total_wall=self.wall()-self.origin_wall;total_cpu=self.cpu()-self.origin_cpu
        for row in self.rows.values():
            if any(type(v)is not int or v<0 for v in row.values()) or row['returned']+row['raised']!=row['attempted']:
                raise ValueError('observational call timing balance')
        measured=sum(row['wall_ns']for row in self.rows.values())
        if total_wall<measured or total_cpu<0:raise ValueError('disjoint observational timing clocks')
        return dict(method='B54_DISJOINT_PUBLIC_CALL_TIMING_V1',units='ns',
            scope='CURRENT_WORKER_AFTER_PUBLICATION_SETUP_BEFORE_RECORD_ENCODING',
            clock_sources=['perf_counter_ns','actual_worker_process_time_ns'],calls=deepcopy(self.rows),
            observed_wall_ns=total_wall,observed_worker_cpu_ns=total_cpu,unclassified_wall_ns=total_wall-measured,
            interpretation='WALL_REMAINDER_INCLUDES_WRAPPER_IO_CONTROL_AND_UNCLASSIFIED_WORK_NOT_PURE_OVERHEAD_OR_NUMERICAL_OPERATION_COST',
            restart_authority=False)


_MEMORY_READER=None
def _memory_sample():
    """Read only this worker's working set; never change process/OS settings."""
    global _MEMORY_READER
    try:
        if sys.platform.startswith('linux'):
            from .lifecycle_process import memory_sample
            return memory_sample()
        if os.name!='nt':raise OSError('process working-set API unavailable on this runtime')
        if _MEMORY_READER is None:
            import ctypes
            from ctypes import wintypes
            size=ctypes.c_size_t
            class Counters(ctypes.Structure):
                _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),('PeakWorkingSetSize',size),('WorkingSetSize',size),
                    ('QuotaPeakPagedPoolUsage',size),('QuotaPagedPoolUsage',size),('QuotaPeakNonPagedPoolUsage',size),('QuotaNonPagedPoolUsage',size),('PagefileUsage',size),('PeakPagefileUsage',size)]
            kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
            get_current_process=kernel.GetCurrentProcess;get_current_process.argtypes=[];get_current_process.restype=wintypes.HANDLE
            query=psapi.GetProcessMemoryInfo;query.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD];query.restype=wintypes.BOOL
            def read():
                counters=Counters();counters.cb=ctypes.sizeof(counters)
                if not query(get_current_process(),ctypes.byref(counters),counters.cb):raise ctypes.WinError(ctypes.get_last_error())
                return int(counters.WorkingSetSize),int(counters.PeakWorkingSetSize)
            _MEMORY_READER=read
        current,peak=_MEMORY_READER()
        return dict(status='AVAILABLE',method='WINDOWS_OWN_PROCESS_WORKING_SET',current_rss_bytes=current,peak_rss_bytes=peak,error=None)
    except (OSError,AttributeError) as error:
        return dict(status='UNAVAILABLE',method='WINDOWS_OWN_PROCESS_WORKING_SET',current_rss_bytes=None,peak_rss_bytes=None,error=type(error).__name__+': '+str(error))


def _read(path,cap=MAX_METADATA):
    ProjectStore._reject_links(path)
    if path.stat().st_size>cap:raise ValueError('lifecycle bounded artifact')
    return parse_json(path.read_text(encoding='utf-8'))


def _write_new(path,value,cap=MAX_METADATA):
    raw=value if type(value) is bytes else _bytes(value)
    if len(raw)>cap:raise ValueError('lifecycle prospective publication bytes')
    from .lifetime_physical_storage import register_producer_path
    register_producer_path(path,additional_bytes=len(raw))
    ProjectStore._reject_links(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(raw);f.flush();_io_fsync(f.fileno())
    return dict(file=path.name,sha256=sha256(raw).hexdigest(),bytes=len(raw))


class _BoundedExport:
    def __init__(self,path,cap):
        from .lifetime_physical_storage import register_producer_path
        register_producer_path(path)
        self.file=path.open('xb');self.cap=cap
    def write(self,raw):
        if self.file.tell()+len(raw)>self.cap:raise ValueError('prospective compressed ZIP byte cap')
        return self.file.write(raw)
    def tell(self):return self.file.tell()
    def seek(self,*args):
        result=self.file.seek(*args)
        if result>self.cap:raise ValueError('ZIP seek beyond output cap')
        return result
    def flush(self):self.file.flush()
    def close(self):self.file.close()


def _budget(intent):
    from .lifecycle_execution_budget import INTENT as BUDGET_INTENT,admit_budget
    return admit_budget(intent['execution_budget'],execution_seconds=intent['execution_seconds']) if intent['format'] in (BUDGET_INTENT,PROFILE_INTENT) and intent.get('execution_budget') is not None else None


def _job_format(intent):
    from .lifecycle_execution_budget import JOB as BUDGET_JOB
    return JOB if _budget(intent) is None else BUDGET_JOB


def _write_stop_request(marker,job):
    value=dict(format='B52_COOPERATIVE_STOP_REQUEST_V1',job_id=job['job_id'],root_identity=job['root_identity'],requested_utc=_utc())
    if _budget(job['intent']) is None:return _write_new(marker,value)
    pending=marker.with_suffix('.pending')
    result=_write_new(pending,value)
    if marker.exists():raise ValueError('stop request already published')
    from .lifetime_physical_storage import register_producer_path,retire_producer_path
    register_producer_path(marker)
    os.rename(pending,marker) # NEW immutable filename; no replacement of held readers.
    retire_producer_path(pending)
    return result


def _admit_execution_terminal(job,result):
    from .lifecycle_execution_budget import admit_receipt
    policy=_budget(job['intent'])
    if 'typed_terminal'in result:
        from .battery_terminal import admit_bound_terminal
        admit_bound_terminal(result['typed_terminal'],job,result)
    if result.get('format')!=_job_format(job['intent']):raise ValueError('terminal execution format binding')
    if policy is None:
        if 'execution_budget_receipt' in result:raise ValueError('legacy terminal acquired budget fields')
    else:
        receipt=admit_receipt(result['execution_budget_receipt'],policy)
        if (result['application_status']=='INCOMPLETE_BUDGET_STOP') != (receipt['stop_cause']=='BUDGET'):
            raise ValueError('terminal budget cause disagreement')


def _admit_backend_terminal(store,job,result):
    """Saved DATA validation only: declaration is not actual backend evidence."""
    from .lifetime_policy import is_v2
    if not is_v2(store.runner_policy):return
    from .portable_job import worker_contract_for_store
    from .lifecycle_backend import admit_backend_receipt
    contract=worker_contract_for_store(store,Path(__file__).resolve().parents[2])
    receipt=result.get('backend_execution')
    admit_backend_receipt(receipt,contract)
    path=store.path('jobs',job['job_id'],'backend-execution.json')
    size=path.stat().st_size
    if not 0<size<=65536:raise ValueError('B63 bounded saved backend execution receipt')
    store._parent_codec_charge(job['job_id'],16*size+65536)
    with path.open('rb')as stream:content=stream.read(size+1)
    if len(content)!=size or content!=_bytes(receipt):raise ValueError('B63 backend terminal/saved receipt exact raw binding')


def _profile(intent):
    if intent.get('format')!=PROFILE_INTENT:return None
    if intent['publication_profile'] is None:
        if intent['publication_profile_identity'] is not None:raise ValueError('raw profile has no compact identity')
        return None
    return admit_profile(intent['publication_profile'],intent['publication_profile_identity'])


def _job_profile(job):
    # Bare historical journal adapters have only these labels and cannot grant
    # store, source, checkpoint or continuation authority. Full jobs always use
    # the existing strict intent/store admission before reaching this reader.
    if 'intent' not in job:
        if not {'job_id','root_identity'}<=set(job) or set(job)-{'job_id','root_identity','runtime'}:raise ValueError('exact bare legacy journal metadata')
        return None
    intent=job['intent']
    from .lifecycle_execution_budget import INTENT as BUDGET_INTENT
    if type(intent) is not dict or type(intent.get('format')) is not str or intent['format'] not in (INTENT,BUDGET_INTENT,PROFILE_INTENT):raise ValueError('known journal intent format')
    return _profile(intent)


def _stream_writer(directory,policy,maximum_bytes,*,profile=None,codec_charge=None,buffered=False,**kwargs):
    if profile is None:return ChunkedStreamWriter(directory,policy,maximum_bytes,**kwargs)
    return CompactStreamWriter(directory,policy,maximum_bytes,profile=profile,codec_charge=codec_charge,buffered=buffered,**kwargs)


def validate_intent(value):
    from .lifecycle_execution_budget import INTENT as BUDGET_INTENT,admit_budget
    profile_bound=type(value) is dict and value.get('format')==PROFILE_INTENT
    selected=type(value) is dict and value.get('format') in (BUDGET_INTENT,PROFILE_INTENT)
    object_fields(value,(*INTENT_FIELDS,*(('execution_budget','execution_budget_identity') if selected else ()),*(('publication_profile','publication_profile_identity') if profile_bound else ())))
    if type(value['format']) is not str or value['format'] not in (INTENT,BUDGET_INTENT,PROFILE_INTENT):raise ValueError('lifecycle intent method')
    if profile_bound:_profile(value)
    if selected and not (profile_bound and value['execution_budget'] is None):
        policy=admit_budget(value['execution_budget'],execution_seconds=value['execution_seconds'])
        if type(value['execution_budget_identity']) is not str or value['execution_budget_identity']!=policy.identity:raise ValueError('execution budget identity')
    if profile_bound and value['execution_budget'] is None and value['execution_budget_identity'] is not None:raise ValueError('absent execution budget identity')
    identifier(value['idempotency_key']);identity(value['root_identity'])
    if type(value['mode']) is not str or value['mode'] not in ('MAIN','DIAGNOSTIC_NORMAL','DIAGNOSTIC_VERBOSE'):raise ValueError('lifecycle intent mode')
    integer(value['execution_seconds'],'owned execution seconds',1,1800)
    integer(value['maximum_output_bytes'],'job output bytes',2**20,512*2**20)
    parent=value['parent_job_id'];snapshot=value['snapshot_sha256'];end=value['window_end_seconds']
    if parent is None:
        if snapshot is not None or end is not None or value['mode']!='MAIN':raise ValueError('initial lifecycle intent cannot borrow advanced state')
    else:
        identifier(parent);identity(snapshot)
        if value['mode']=='MAIN':
            if end is not None:raise ValueError('main resume completes original immutable horizon')
        else:integer(end,'diagnostic window end',1,2**40)
    return deepcopy(value)


def make_intent(root_identity,*,key=None,parent_job_id=None,snapshot_sha256=None,mode='MAIN',window_end_seconds=None,execution_seconds=420,maximum_output_bytes=128*2**20,execution_budget=None,publication_profile=None,profile_bound=False):
    from .lifecycle_execution_budget import ExecutionBudget,INTENT as BUDGET_INTENT
    if execution_budget is not None and type(execution_budget) is not ExecutionBudget:raise TypeError('exact execution budget policy')
    if publication_profile is not None and type(publication_profile) is not PublicationProfile:raise TypeError('exact immutable publication profile')
    bound=profile_bound or publication_profile is not None
    extra={} if execution_budget is None and not bound else dict(execution_budget=None if execution_budget is None else asdict(execution_budget),execution_budget_identity=None if execution_budget is None else execution_budget.identity)
    if bound:extra.update(publication_profile=None if publication_profile is None else asdict(publication_profile),publication_profile_identity=None if publication_profile is None else publication_profile.identity)
    return validate_intent(dict(format=PROFILE_INTENT if bound else INTENT if execution_budget is None else BUDGET_INTENT,idempotency_key=uuid.uuid4().hex if key is None else key,root_identity=root_identity,
        mode=mode,parent_job_id=parent_job_id,snapshot_sha256=snapshot_sha256,window_end_seconds=window_end_seconds,
        execution_seconds=execution_seconds,maximum_output_bytes=maximum_output_bytes,**extra))


def _requested_inputs(policy_data,scenario_data,study_preset,ageing_multiplier,output_data,*,battery_port=False,environment_ageing=False):
    from dataclasses import replace
    from .lifecycle_contract import LifecycleRoot,LifecyclePolicy,LifecycleScenario
    from .lifecycle_stream import LifecycleStreamPolicy
    from .lifecycle_quiet import QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy
    if type(policy_data) is not dict or type(scenario_data) is not dict:raise TypeError('explicit lifecycle policy/scenario objects')
    policy_data=deepcopy(policy_data)
    if policy_data.get('quiet_solver') is not None:
        if type(policy_data['quiet_solver']) is not dict:raise TypeError('explicit quiet solver input object')
        policy_data['quiet_solver']=(EnvironmentQuietIntegrationPolicy if environment_ageing else BatteryQuietIntegrationPolicy if battery_port else QuietIntegrationPolicy)(**policy_data['quiet_solver'])
    if type(study_preset) is not str or study_preset not in ('LEGACY','COMMON_ASSUMED_V1'):raise ValueError('declared long study preset')
    study=None
    if study_preset=='COMMON_ASSUMED_V1':
        from .lifecycle_study import common_study_input
        if type(ageing_multiplier) not in (int,float) or ageing_multiplier not in (.5,1.,2.):raise ValueError('predeclared ageing sensitivity .5/1/2')
        study=common_study_input();study=replace(study,ageing_multiplier=float(ageing_multiplier),latency_seconds=policy_data.get('latency_seconds',study.latency_seconds))
        policy_data['latency_seconds']=study.latency_seconds
    elif type(ageing_multiplier) not in (int,float) or ageing_multiplier!=1.:raise ValueError('legacy input cannot acquire hidden study sensitivity')
    if output_data is not None:
        if type(output_data) is not dict:raise TypeError('explicit output policy object')
        output_data=deepcopy(output_data)
        if type(output_data.get('publication_minimum_wall_seconds')) is int:output_data['publication_minimum_wall_seconds']=float(output_data['publication_minimum_wall_seconds'])
    output=None if output_data is None else LifecycleStreamPolicy(**output_data)
    return LifecyclePolicy(**policy_data),LifecycleScenario(**scenario_data),study,output


def requested_lifecycle_root(base,duration_seconds,policy_data,scenario_data,sun_mode,*,study_preset='LEGACY',ageing_multiplier=1.0,output_data=None,service_policy='LEGACY',energy_attitude_policy='LEGACY',battery_port_policy='LEGACY',environment_ageing_policy='LEGACY'):
    """Shared CLI/HTTP immutable input compiler, never advanced-state reuse."""
    from .lifecycle_contract import LifecycleRoot
    from .lifecycle_service import requested_service_policy
    service=requested_service_policy(service_policy)
    from .solar_attitude import requested_energy_policy
    solar=requested_energy_policy(energy_attitude_policy)
    from .battery_port import requested_port_policy
    port=requested_port_policy(battery_port_policy)
    policy,scenario,study,output=_requested_inputs(policy_data,scenario_data,study_preset,ageing_multiplier,output_data,battery_port=port is not None,environment_ageing=environment_ageing_policy!='LEGACY')
    if study is not None:
        from .lifecycle_study import compile_study_base
        base=compile_study_base(base,study)
    from .environment_ageing_document import requested_policy
    env=requested_policy(environment_ageing_policy,base.model.simulation_inputs.spacecraft_configuration.thermal.network)
    return LifecycleRoot(base,duration_seconds,policy,scenario,sun_mode,study=study,output_policy=output,service_policy=service,energy_attitude_policy=solar,battery_port_policy=port,environment_ageing_policy=env)


def _publication_ledger(value,extended=False):
    names=PUBLICATION_FIELDS53 if extended else PUBLICATION_FIELDS
    if extended and 'stream_codec_reserved_units' in value:names=(*names,'stream_codec_reserved_units')
    object_fields(value,names)
    for name in names:integer(value[name],name,0,2**56)
    return value


def _stream_charges(value):
    object_fields(value,STREAM_NAMES54)
    for row in value.values():
        object_fields(row,('encoded_bytes_reserved','reservation_attempts',*(('codec_reserved_units',) if 'codec_reserved_units' in row else ())))
        for name,item in row.items():integer(item,name,0,2**56)
        if row['encoded_bytes_reserved']<row['reservation_attempts']:raise ValueError('stream reservation byte/call balance')
    return value


def _advance_publication_work(base,before,after,extended):
    """Exact derived reservation delta, never a loose monotonic comparison."""
    _publication_ledger(base,extended);_stream_charges(before);_stream_charges(after)
    new='stream_codec_reserved_units' in base
    delta={name:0 for name in ('encoded_bytes_reserved','reservation_attempts',*(('codec_reserved_units',) if new else ()))}
    for stream in STREAM_NAMES54:
        for name in delta:
            difference=after[stream][name]-before[stream][name]
            if difference<0:raise ValueError('stream reservation refund')
            delta[name]+=difference
    result=deepcopy(base)
    if extended:
        result['stream_encoded_bytes_reserved']+=delta['encoded_bytes_reserved']
        result['stream_publication_attempts']+=delta['reservation_attempts']
        if new:result['stream_codec_reserved_units']+=delta['codec_reserved_units']
    elif any(delta.values()):raise ValueError('legacy plain publication cannot charge chunk streams')
    return _publication_ledger(result,extended)


def _publication_document(directory,checkpoint,root):
    from .lifecycle_checkpoint import admit_checkpoint_transport
    admit_checkpoint_transport(checkpoint)
    entry=checkpoint['publication'];object_fields(entry,('file','sha256','bytes'))
    if not re.fullmatch(r'checkpoint-[0-9]{8}-publication\.json',entry['file']):raise ValueError('checkpoint publication filename')
    identity(entry['sha256']);integer(entry['bytes'],'publication bytes',1,16384)
    path=directory/entry['file'];ProjectStore._reject_links(path);raw=path.read_bytes()
    if len(raw)!=entry['bytes'] or sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('checkpoint publication binding')
    value=parse_json(raw.decode('utf-8'));extended=root.output_policy is not None
    current=value.get('format')==PUBLICATION54
    names=('format','root_identity','native_checkpoint_sha256','application_work',*(('stream_frontiers',) if extended else ()),*(('stream_charges','scope') if current else ()))
    request=_read(directory/'request.json');bound=request['intent']['format']==PROFILE_INTENT
    if bound:names=(*names,'publication_profile_identity')
    object_fields(value,names)
    if bound and (value['publication_profile_identity']!=request['intent']['publication_profile_identity'] or 'stream_codec_reserved_units' not in value['application_work']):raise ValueError('checkpoint profile authority')
    if value['format']!=(PUBLICATION54 if current else PUBLICATION53 if extended else PUBLICATION) or value['root_identity']!=root.identity or value['native_checkpoint_sha256']!=checkpoint['sha256'] or _bytes(value)!=raw:raise ValueError('checkpoint publication authority')
    _publication_ledger(value['application_work'],extended)
    if current:
        if value['scope']!='BEFORE_CHECKPOINT_PROGRESS_PUBLICATION':raise ValueError('checkpoint publication scope')
        _stream_charges(value['stream_charges'])
    if extended:
        from .lifecycle_stream import admit_frontier
        object_fields(value['stream_frontiers'],('events','months','details'))
        for name,frontier in value['stream_frontiers'].items():
            admit_frontier(frontier,root.output_policy)
            if bound and frontier['writer_failed']:raise ValueError('failed publication frontier is not continuation authority')
            expected=_profile(request['intent'])
            if (frontier['format']==COMPACT_FRONTIER)!=(expected is not None) or expected is not None and frontier['profile_identity']!=expected.identity:raise ValueError('checkpoint stream/profile disagreement')
    return value


def _settled_publication_work(directory,root,job,document=None,*,include_static=False):
    """Admit the immutable receipt written AFTER all stream finalization.

    The record snapshot and final snapshot are linked by exact per-stream
    reservation deltas. The receipt itself has an upfront fixed metadata
    reservation, so it creates no self-referential stream charge.
    """
    receipt=_read(directory/'application-work-final.json',SETTLED_RECEIPT_BYTES)
    bound=job['intent']['format']==PROFILE_INTENT
    object_fields(receipt,('format','scope','root_identity','source_identity','job_id','record','application_work','stream_charges','stream_work','publication_closed',*(('publication_profile_identity','stream_codec_work') if bound else ())))
    if bound:
        if receipt['publication_profile_identity']!=job['intent']['publication_profile_identity']:raise ValueError('settled profile identity')
        object_fields(receipt['stream_codec_work'],STREAM_NAMES54)
    if receipt['format']!=SETTLED_PUBLICATION54 or receipt['scope']!=SETTLED_SCOPE54 or receipt['root_identity']!=root.identity or receipt['root_identity']!=job['root_identity'] or receipt['source_identity']!=job['source_identity'] or receipt['job_id']!=job['job_id'] or receipt['publication_closed'] is not True:raise ValueError('settled publication authority/closure')
    binding=object_fields(receipt['record'],('file','sha256','bytes'))
    if binding['file'] not in ('terminal.json','failure.json'):raise ValueError('settled record filename')
    identity(binding['sha256']);integer(binding['bytes'],'settled record bytes',1,MAX_METADATA)
    path=directory/binding['file'];raw=path.read_bytes()
    if len(raw)!=binding['bytes'] or sha256(raw).hexdigest()!=binding['sha256']:raise ValueError('settled record SHA/size')
    saved=parse_json(raw.decode('utf-8'))
    if document is not None and saved!=document:raise ValueError('settled record/document disagreement')
    if saved.get('static_admission_merge_failed',False) is not False or saved.get('observation_errors',{}):raise ValueError('settled static-admission accounting incomplete')
    wrapper=_static_admission_accounting(saved['static_admission_wrapper'],job,
        required=_production_execution_mode(root)!='BASELINE')
    extended=root.output_policy is not None
    checkpoint=saved['checkpoint'] if binding['file']=='terminal.json' else saved['last_checkpoint']
    if checkpoint is None:raise ValueError('settled attempt lacks an admitted native paid-prefix checkpoint')
    prefix=_publication_document(directory,checkpoint,root)
    if prefix['format']!=PUBLICATION54:raise ValueError('settled attempt requires explicit prefix publication version')
    expected_record=_advance_publication_work(prefix['application_work'],prefix['stream_charges'],saved['stream_charges'],extended)
    if expected_record!=saved['application_work']:raise ValueError('settled record exact checkpoint-prefix ledger delta')
    _publication_ledger(receipt['application_work'],extended);_stream_charges(receipt['stream_charges'])
    object_fields(receipt['stream_work'],STREAM_NAMES54)
    for name,work in receipt['stream_work'].items():
        if work is None:
            if any(receipt['stream_charges'][name].values()):raise ValueError('missing charged stream owner')
            continue
        object_fields(work,('record_attempts','records_completed','encoded_bytes_reserved','bytes_published','index_records'))
        for key,item in work.items():integer(item,key,0,2**56)
        if work['encoded_bytes_reserved']!=receipt['stream_charges'][name]['encoded_bytes_reserved'] or work['bytes_published']>work['encoded_bytes_reserved'] or work['records_completed']!=work['record_attempts'] or receipt['stream_charges'][name]['reservation_attempts']!=(receipt['stream_codec_work'][name]['frames_completed'] if bound and receipt['stream_codec_work'][name] is not None else work['records_completed'])+work['index_records']+1:raise ValueError('settled native stream reservation balance')
        # finish() reserves its own immutable manifest AFTER taking its
        # frontier snapshot. Reconcile that final reservation exactly.
        from .lifecycle_stream import admit_frontier
        manifest_path=directory/(name+'53')/'manifest.json'
        manifest_raw=manifest_path.read_bytes()
        if len(manifest_raw)>65536:raise ValueError('settled stream manifest byte cap')
        frontier=parse_json(manifest_raw.decode('utf-8'));admit_frontier(frontier,root.output_policy)
        if _bytes(frontier)!=manifest_raw:raise ValueError('settled stream manifest canonical bytes')
        if bound:
            codec=receipt['stream_codec_work'][name]
            if codec!=frontier.get('codec') or receipt['stream_charges'][name]['codec_reserved_units']!=(0 if codec is None else codec['codec_reserved_units']):raise ValueError('settled codec accounting binding')
        expected_native=deepcopy(frontier['work']);expected_native['encoded_bytes_reserved']+=len(manifest_raw)
        if work!=expected_native:raise ValueError('settled native manifest/last reservation mismatch')
    expected=_advance_publication_work(saved['application_work'],saved['stream_charges'],receipt['stream_charges'],extended)
    if expected!=receipt['application_work']:raise ValueError('settled exact publication ledger delta')
    work=deepcopy(receipt['application_work'])
    return (work,deepcopy(wrapper)) if include_static else work


def _admit_publication(directory,checkpoint,root,*,settled=False,include_static=False):
    value=_publication_document(directory,checkpoint,root)
    if settled and value['format']==PUBLICATION54:
        request=_read(directory/'request.json')
        return _settled_publication_work(directory,root,request,include_static=include_static)
    work=deepcopy(value['application_work'])
    return (work,None) if include_static else work


def _admit_failure_publication(directory,checkpoint,root,failure,job):
    value=_publication_document(directory,checkpoint,root)
    if value['format']!=PUBLICATION54:
        if value['application_work']!=failure['application_work']:raise ValueError('historical failure paid-prefix publication ledger')
        return deepcopy(failure['application_work'])
    expected=_advance_publication_work(value['application_work'],value['stream_charges'],failure['stream_charges'],root.output_policy is not None)
    if expected!=failure['application_work']:raise ValueError('failure exact checkpoint publication ledger delta')
    return _settled_publication_work(directory,root,job,failure)


def _verify_checkpoint_streams(directory,checkpoint,root,*,reserve):
    if root.output_policy is None:return
    value=_read(directory/checkpoint['publication']['file'],16384)
    frontiers=value['stream_frontiers']
    # Pay the complete read/hash bound once before reading. This is wrapper
    # validation work, never a force/thermal/forecast prefix replay.
    bound=sum(f['work']['bytes_published']+f.get('codec',{}).get('decoded_bytes_completed',0)*4 for f in frontiers.values())
    reserve(bound)
    for name,frontier in frontiers.items():verify_stream(directory/(name+'53'),frontier,root.output_policy)


class LifecycleStore:
    def __init__(self,directory,root=None,*,create=False,project=None,runner_policy=None,publication_profile=None,execution_authority=None,project_document=None,parent_contract_operation=None):
        from .lifecycle_document import dumps_root,loads_root
        if create and parent_contract_operation is not None:raise ValueError('YEAR_V4 parent reopen admission cannot create a store')
        self.directory=Path(directory).absolute();self.lock=threading.RLock();self._cache={};self._status_writers={};self._catalogs={};self._parent_work={};self._status_read_work=0;self._lifetime_retirement_failed=False;self._lifetime_publications_closed=False
        self._design_lineage_pin=None
        ProjectStore._reject_links(self.directory)
        if any((p/'.git').exists() for p in (self.directory,*self.directory.parents)):raise ValueError('lifecycle store must be outside repositories')
        self.source_identity=project_source_identity();self.runtime=runtime_identity()
        from .finite_campaign import FiniteCampaignPolicy,STORE as FINITE_STORE
        from .lifetime_policy import LifetimeCampaignPolicyV2,is_v2
        if runner_policy is not None:
            if type(runner_policy) not in (LifecycleRunnerStorePolicy,FiniteCampaignPolicy,LifetimeCampaignPolicy,LifetimeCampaignPolicyV2):raise TypeError('exact runner-store policy required')
            runner_policy.__post_init__()
        if execution_authority is not None and not is_v2(runner_policy):raise ValueError('B63 execution authority requires explicit new store version')
        if publication_profile is not None and type(publication_profile) is not PublicationProfile:raise TypeError('immutable publication profile')
        if create:
            if is_v2(runner_policy):
                from .lifetime_execution_authority import admit_authority_data
                execution_authority=admit_authority_data(execution_authority)
            if publication_profile is not None and root.output_policy is None:raise ValueError('compact requires existing bounded stream policy')
            if root is None or self.directory.exists():raise ValueError('new immutable lifecycle store required')
            if is_v2(runner_policy) and root.output_policy is None:raise ValueError('B63 status envelope requires existing bounded output policy')
            if is_typed_campaign_policy(runner_policy) and (root.battery_port_policy is None or root.energy_attitude_policy is None):raise ValueError('B59 finite battery/solar root required')
            static_admission(root);raw=dumps_root(root)
            if type(raw) is not bytes:raise TypeError('lifecycle root document bytes')
            from .lifetime_policy import physical_storage
            if physical_storage(runner_policy):
                from .lifetime_physical_storage import prepare_owner,register_producer_path
                prepare_owner(self.directory,runner_policy,dict(root_identity=root.identity,
                    source_identity=self.source_identity,input_sha256=sha256(raw).hexdigest(),
                    policy_identity=runner_policy.identity,store_name=self.directory.name))
                register_producer_path(self.directory/'input.json')
            self.directory.mkdir(parents=True)
            _write_new(self.directory/'input.json',raw,16*2**20)
            if project_document is not None:
                if type(project_document)is not str or type(project)is not dict or project.get('format')not in ('B66_BOUND_DESIGN_PROJECT_LINEAGE_V1','B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'):
                    raise ValueError('B66 exact immutable design document lineage')
                project_raw=project_document.encode('utf8')
                if sha256(project_raw).hexdigest()!=project.get('document_sha256'):raise ValueError('B66 design document raw binding')
                _write_new(self.directory/'design-project-input.json',project_raw,16*2**20)
            meta=dict(format=STORE,root_identity=root.identity,source_identity=self.source_identity,runtime=self.runtime,
                input_sha256=sha256(raw).hexdigest(),input_bytes=len(raw),created_utc=_utc(),project=project,
                admission=static_admission(root),maximum_jobs=MAX_JOBS)
            if runner_policy is not None:
                meta.update(format=store_format(runner_policy) if is_typed_campaign_policy(runner_policy) else STORE_V2,maximum_jobs=runner_policy.maximum_jobs,
                    runner_policy=asdict(runner_policy),runner_policy_identity=runner_policy.identity)
            if is_v2(runner_policy):
                authority_raw=_bytes(execution_authority)
                if len(authority_raw)>65536:raise ValueError('B63 bounded immutable execution authority')
                _write_new(self.directory/'execution-authority.json',authority_raw,65536)
                meta['execution_authority_sha256']=sha256(authority_raw).hexdigest()
            if publication_profile is not None:meta.update(base_store_format=meta['format'],format=PROFILE_STORE,publication_profile=asdict(publication_profile),publication_profile_identity=publication_profile.identity)
            _write_new(self.directory/'store.json',meta)
        self.meta=_read(self.directory/'store.json')
        self.publication_profile=admit_profile(self.meta['publication_profile'],self.meta['publication_profile_identity']) if self.meta['format']==PROFILE_STORE else None
        if publication_profile is not None and self.publication_profile!=publication_profile:raise ValueError('immutable store profile mismatch')
        self._store_metadata_sha256=file_sha(self.directory/'store.json')
        self.runner_policy,self.maximum_jobs,self.maximum_lineage_jobs,self.maximum_reserved_job_output_bytes=admit_runner_store_metadata(self.meta)
        if runner_policy is not None and runner_policy!=self.runner_policy:raise ValueError('saved runner-store policy differs; stores are not migrated')
        if self.meta['source_identity']!=self.source_identity or self.meta['runtime']!=self.runtime:raise ValueError('lifecycle source/runtime/store mismatch; historical stores are not migrated')
        raw=(self.directory/'input.json').read_bytes()
        if len(raw)!=self.meta['input_bytes'] or sha256(raw).hexdigest()!=self.meta['input_sha256']:raise ValueError('lifecycle immutable input drift')
        if is_v2(self.runner_policy):
            # Authority DATA selects a pure input codec only. The common full
            # execution gate still runs before claims, reservations or launch.
            from .lifetime_execution_authority import admit_authority_data
            from .lifecycle_backend import load_root_for_backend
            authority_path=self.path('execution-authority.json')
            authority=admit_authority_data(_read(authority_path,16384))
            if file_sha(authority_path)!=self.meta['execution_authority_sha256']:
                raise ValueError('B63 store authority raw binding before input admission')
            if parent_contract_operation is not None:
                from .lifetime_typed_portable import parent_operation_root
                self.root_input=parent_operation_root(parent_contract_operation,self.directory,Path(__file__).resolve().parents[2],raw)
            else:self.root_input=load_root_for_backend(raw,authority['binding']['backend_binding']['selection'])
        else:
            if parent_contract_operation is not None:raise ValueError('YEAR_V4 typed parent admission cannot open a legacy store')
            self.root_input=loads_root(raw)
        if self.root_input.identity!=self.meta['root_identity'] or root is not None and dumps_root(root)!=raw:raise ValueError('lifecycle immutable root mismatch')
        identity(self.meta['root_identity']);identity(self.meta['input_sha256'])
        integer(self.meta['input_bytes'],'immutable input bytes',1,16*2**20)
        if self.meta['admission']!=static_admission(self.root_input):raise ValueError('lifecycle stored admission drift')
        if self.meta['project'] is not None:
            if self.meta['project'].get('format')in ('B66_BOUND_DESIGN_PROJECT_LINEAGE_V1','B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'):
                self._admit_design_lineage()
                project=self.meta['project']
            else:project=object_fields(self.meta['project'],('project_id','revision','title'))
            identifier(project['project_id']);identifier(project['revision'],revision=True)
            if type(project['title']) is not str or not 1<=len(project['title'])<=120:raise ValueError('lifecycle project label')
        from .lifetime_policy import physical_storage
        if physical_storage(self.runner_policy):
            from .lifetime_physical_storage import initialize_store
            initialize_store(self)
        if parent_contract_operation is not None:parent_contract_operation.validate_store(self)

    def _admit_design_lineage(self):
        """Strict preparation once, then exact bytes plus immutable scalar pins.

        The repeat path never dispatches a cached project's mutable Python
        methods or constructors. Actual root graph/callable guards remain owned
        by the existing lifecycle transaction; these are additional store pins.
        """
        route=self.meta['project'].get('format')=='B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'
        extra=('declaration_identity','thermal_method','model_identity')if route else ()
        project=object_fields(self.meta['project'],('format','project_id','revision','title','document_sha256',
            'source_identity','specification_identity','common_identity','compiled_root_identity')+extra)
        if project['format']not in ('B66_BOUND_DESIGN_PROJECT_LINEAGE_V1','B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'):raise ValueError('exact project lineage family')
        for name in ('revision','document_sha256','source_identity','specification_identity','common_identity','compiled_root_identity'):
            identity(project[name])
        path=self.path('design-project-input.json')
        if path.stat().st_size>16*2**20:raise ValueError('B66 bounded design document')
        raw=path.read_bytes()
        if sha256(raw).hexdigest()!=project['document_sha256']:raise ValueError('B66 immutable design document changed')
        current_pin=(_bytes(project),project['document_sha256'],self.source_identity,self.root_input.identity)
        if self._design_lineage_pin is not None:
            if current_pin!=self._design_lineage_pin:raise ValueError('B66 immutable admitted project lineage drift')
            return None
        from .spacecraft_project_v2 import SpacecraftProjectV2
        from .spacecraft_project_v3 import SpacecraftProjectV3
        from .spacecraft_project_document import loads_project
        admitted=loads_project(raw.decode('utf8'),expected_identity=project['revision'],expected_source_identity=self.source_identity)
        if (type(admitted)is not (SpacecraftProjectV3 if route else SpacecraftProjectV2) or admitted.source_identity!=project['source_identity'] or
                admitted.specification.identity!=project['specification_identity'] or admitted.common.identity!=project['common_identity'] or
                admitted.title!=project['title'] or project['compiled_root_identity']!=self.root_input.identity):
            raise ValueError('B66 exact project/source/specification/common/compiled-root lineage')
        # An editable self-hash is not evidence that this specification produced
        # this plant. Recompute the supported static composition once on initial
        # preparation/reopen; subsequent pins remain hash-only. This paid static
        # constructor does not evolve a spacecraft or replay any mission prefix.
        from .spacecraft_design import admit_compiled_design
        from .design_repair import ConstructorLedger
        if route:
            from .spacecraft_route_thermal import admit_compiled_design_v2 as admit_compiled_design, METHOD as ROUTE_METHOD
            from .rolling_physics import digest as model_digest
            if (project['declaration_identity']!=admitted.specification.declaration_identity or project['thermal_method']!=ROUTE_METHOD or project['model_identity']!=model_digest(self.root_input.base.model)):raise ValueError('B68 route declaration/model lineage')
        from .spacecraft_project import constructor_compile_bound
        constructor=ConstructorLedger(maximum_compiles=constructor_compile_bound(admitted))
        admit_compiled_design(admitted.specification,admitted.common,self.root_input,constructor)
        self._design_lineage_constructor_work=asdict(constructor)
        self._design_lineage_pin=current_pin
        return None

    def path(self,*parts):
        if any(type(p) is not str or p in ('','.','..') or '/' in p or '\\' in p or ':' in p for p in parts):raise ValueError('lifecycle fixed path')
        result=self.directory.joinpath(*parts);ProjectStore._reject_links(result)
        if not result.resolve().is_relative_to(self.directory.resolve()):raise ValueError('lifecycle path containment')
        return result

    def _pinned(self):
        if self.meta['source_identity']!=project_source_identity() or self.meta['runtime']!=runtime_identity():raise ValueError('lifecycle runtime/source mismatch before work')
        if file_sha(self.path('input.json'))!=self.meta['input_sha256']:raise ValueError('lifecycle input changed before work')
        if self.meta['project'] is not None and self.meta['project'].get('format')in ('B66_BOUND_DESIGN_PROJECT_LINEAGE_V1','B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'):self._admit_design_lineage()
        if self.runner_policy is not None or self.publication_profile is not None:
            if file_sha(self.path('store.json'))!=self._store_metadata_sha256:raise ValueError('immutable runner-store metadata drift')
            if admit_runner_store_metadata(self.meta)!=(self.runner_policy,self.maximum_jobs,self.maximum_lineage_jobs,self.maximum_reserved_job_output_bytes):raise ValueError('runner-store admission limits drift')

    def jobs(self):
        with self.lock:
            folder=self.path('jobs')
            names=[] if not folder.exists() else [p.name for p in folder.iterdir()]
            if len(names)>self.maximum_jobs:raise ValueError('lifecycle job population')
            for name in names:identifier(name)
            from .lifetime_policy import is_v2
            if is_v2(self.runner_policy):
                jobs=[]
                for jid in sorted(names):
                    row=self._lifetime_index(jid)
                    self._retire_lifetime_resources(jid,row)
                    jobs.append(row)
            elif type(self.runner_policy)is LifetimeCampaignPolicy:
                from .lifetime_policy import compact_index
                jobs=compact_index(self,names)
            else:jobs=[self.job(jid) for jid in sorted(names)]
            if self.runner_policy is not None and sum(j['intent']['maximum_output_bytes'] for j in jobs)>self.maximum_reserved_job_output_bytes:raise ValueError('lifecycle saved store output reservation')
            return jobs

    def _lifetime_index(self,jid):
        """Read the admitted compact head without hydrating historical details."""
        from .lifetime_status import read_envelope,index
        binding=self._status_binding(jid)
        envelope,proof=read_envelope(self.path('jobs',jid,'status63'),binding,self.root_input.output_policy,profile=self.publication_profile)
        self._status_read_charge(proof.get('read_validation_reserved_units',65536))
        return index(envelope,binding)

    def _admit_lifetime_cache_slot(self,jid):
        from .lifetime_policy import is_v2
        if is_v2(self.runner_policy) and jid not in self._cache and len(self._cache)>=LIFETIME_HYDRATED_CACHE_LIMIT:
            raise ValueError('bounded lifetime hydrated job cache')

    def _reject_lifetime_terminal_writer(self,jid):
        """A durable terminal head can be read again, never reopened for append."""
        from .lifetime_policy import is_v2
        if not is_v2(self.runner_policy):return
        if getattr(self,'_lifetime_publications_closed',False):raise ValueError('lifetime publications closed; no writer reopen')
        previous=self._cache.get(jid)
        if previous is None and self.path('jobs',jid,'status63','head').exists():
            previous=self._lifetime_index(jid)
        if previous is not None and previous['status'] in TERMINAL:
            raise ValueError('immutable terminal lifetime publication; no writer reopen')

    def _retire_lifetime_resources(self,jid,row):
        """Drop only local resources after an owned durable terminal handoff.

        The full job/checkpoints remain immutable on disk. Closing failures are
        independent application failures, never permission to append a new head
        or reconstruct ownership. Both resources are attempted even on failure.
        """
        from .lifetime_policy import is_v2
        if not is_v2(self.runner_policy) or row['status'] not in TERMINAL or row['ownership_valid'] is not True:return
        from .lifetime_status import close_all
        getattr(self,'_cache',{}).pop(jid,None)
        resources=[]
        writer=getattr(self,'_status_writers',{}).pop(jid,None)
        catalog=getattr(self,'_catalogs',{}).pop(jid,None)
        if writer is not None:resources.append(('status:'+jid,writer))
        if catalog is not None:resources.append(('catalog:'+jid,catalog))
        try:
            errors=close_all(resources)
            if errors:self._lifetime_resource_failure(jid,row,errors)
        finally:
            # Finalization may lawfully append paid stream/index costs through
            # the parent charge callback. Retire only its reloadable cache,
            # after every close and independent error-publication attempt.
            getattr(self,'_parent_work',{}).pop(jid,None)

    def _lifetime_resource_failure(self,jid,row,errors):
        # Latch before error reporting: a failed independent channel must not
        # make a settled store dispatchable again. Never rewrite an old latch.
        self._lifetime_retirement_failed=True
        quarantine=self.path('dispatch-quarantine.json')
        reporting=[]
        try:
            if not quarantine.exists():
                _write_new(quarantine,dict(format='B63_UNSETTLED_APPLICATION_DISPATCH_QUARANTINE_V1',job_id=jid,
                    root_identity=row['root_identity'],source_identity=row['source_identity'],
                    reason_sha256=sha256(_bytes([name+': '+repr(error)for name,error in errors])).hexdigest(),
                    scientific_authority=False,automatic_replay=False),16384)
        except BaseException as error:reporting.append(error)
        try:self.parent_error(jid,'TERMINAL_PUBLICATION_RETIREMENT',errors[0][1],secondary=[error for _,error in errors[1:]]+reporting)
        except BaseException as error:reporting.append(error)
        failure=RuntimeError('lifetime terminal resource retirement failed')
        failure.close_failures=errors;failure.reporting_failures=reporting
        raise failure from errors[0][1]

    def retire_lifetime_job(self,jid):
        """Retire a committed terminal's local handles, without changing its tip."""
        from .lifetime_policy import is_v2
        if not is_v2(self.runner_policy):return
        with self.lock:self._retire_lifetime_resources(identifier(jid),self._lifetime_index(jid))

    def _status_binding(self,jid):
        from .lifetime_status import make_binding
        request=self.path('jobs',identifier(jid),'request.json')
        value=_read(request)
        return make_binding(value,file_sha(request),None if self.publication_profile is None else self.publication_profile.identity,self.runner_policy.identity)

    def _admit_request_job(self,value,jid):
        """Immutable request fields cannot acquire a different mutable view."""
        path=self.path('jobs',identifier(jid),'request.json')
        if not path.is_file()or path.stat().st_size>MAX_METADATA:raise ValueError('B63 bounded immutable job request')
        content=path.read_bytes();request=parse_json(content.decode('utf-8'))
        names=('format','job_id','intent','root_identity','source_identity','runtime','input_sha256','resume')
        object_fields(request,names)
        if _bytes(request)!=content or any(name not in value for name in names)or _bytes({name:value[name]for name in names})!=content:
            raise ValueError('B63 full job immutable request disagreement')

    def _status_read_charge(self,n):
        # Bounded read-only reservation; never appends to a reopened store or
        # changes model/actual/forecast work. Publications prepay this read domain.
        integer(n,'B63 saved status read validation',0,2**40)
        if self._status_read_work+n>self.root_input.policy.max_control_units:raise ValueError('B63 finite saved status read reservation')
        self._status_read_work+=n

    def parent_error(self,jid,stage,error,*,traceback_text='',secondary=()):
        from .lifetime_policy import is_v2
        if not is_v2(self.runner_policy):return None
        from .lifetime_status import ParentErrorChannel
        return ParentErrorChannel(self.path('jobs',jid,'status63'),self._status_binding(jid)).record(stage,error,traceback_text=traceback_text,secondary=secondary)

    def _parent_charge(self,jid,n):
        """Serialize the entire paid append with the store's existing writers."""
        with self.lock:return self._parent_charge_locked(jid,n)

    def _parent_charge_locked(self,jid,n):
        """Task-owned append-only paid byte journal; no cumulative refund."""
        integer(n,'prospective parent publication bytes',0,2**30)
        path=self.path('jobs',jid,'parent-publication-work.bin')
        if jid not in self._parent_work:
            size=path.stat().st_size if path.exists() else 0
            if size%PARENT_COST.size:raise ValueError('incomplete parent publication ledger; preserve')
            if size:
                with path.open('rb') as stream:stream.seek(size-PARENT_COST.size);seq,total=PARENT_COST.unpack(stream.read(PARENT_COST.size))
                if seq!=size//PARENT_COST.size:raise ValueError('parent publication cost sequence')
            else:seq=total=0
            self._parent_work[jid]=[seq,total]
        seq,total=self._parent_work[jid];policy=self.root_input.output_policy
        from .finite_campaign import FiniteCampaignPolicy
        if policy is None and self.path('portable-execution.json').exists():
            # New B60 raw wrapper only. All status records and the owned receipt
            # fit this reservation; worker capacity is reduced by the same8MiB.
            allowance=8*2**20+65536;index_allowance=65536
        else:
            allowance=policy.status_total_bytes+4*policy.max_index_bytes+MAX_METADATA+(65536 if is_typed_campaign_policy(self.runner_policy) else 0)
            index_allowance=policy.max_index_bytes
        charged=n+PARENT_COST.size
        if total+charged>allowance or (seq+1)*PARENT_COST.size>index_allowance:raise ValueError('prospective parent publication output allowance')
        from .lifetime_policy import physical_storage
        if physical_storage(self.runner_policy):
            from .lifetime_physical_storage import reserve_parent_metadata
            reserve_parent_metadata(self,jid,path.name,PARENT_COST.size)
        try:
            with path.open('ab') as stream:
                if stream.write(PARENT_COST.pack(seq+1,total+charged))!=PARENT_COST.size:raise OSError('incomplete parent publication append; preserve')
                stream.flush();_io_fsync(stream.fileno())
        except BaseException:
            # The append may have reached disk even when flush/fsync failed.
            # Keep its physical reservation and bytes; never reuse a stale tip.
            self._parent_work.pop(jid,None)
            raise
        self._parent_work[jid]=[seq+1,total+charged]

    def checkpoint_catalog(self,jid):
        if self.root_input.output_policy is None:return None
        self._reject_lifetime_terminal_writer(jid)
        if jid not in self._catalogs:
            self._catalogs[jid]=CheckpointCatalog(self.path('jobs',jid,'checkpoint-index'),self.root_input.output_policy.max_index_bytes,charge=lambda n:self._parent_charge(jid,n))
        return self._catalogs[jid]

    def _parent_codec_charge(self,jid,n):
        """Append-only wrapper units for active monitor/status codec work.

        This never changes model work or authorizes a prefix. A read-only reopen
        reports its own bounded decode reservation in the status-head proof.
        """
        with self.lock:return self._parent_codec_charge_locked(jid,n)

    def _parent_codec_charge_locked(self,jid,n):
        integer(n,'parent codec reservation',0,2**40)
        path=self.path('jobs',jid,'parent-codec-work.bin')
        size=path.stat().st_size if path.exists() else 0
        if size%PARENT_COST.size or size>self.root_input.output_policy.max_index_bytes:raise ValueError('parent codec ledger bound/tail')
        seq=total=0
        if size:
            with path.open('rb') as stream:stream.seek(size-PARENT_COST.size);seq,total=PARENT_COST.unpack(stream.read(PARENT_COST.size))
            if seq!=size//PARENT_COST.size:raise ValueError('parent codec ledger sequence')
        if total+n>self.root_input.policy.max_control_units:raise ValueError('parent codec control cap')
        self._parent_charge(jid,PARENT_COST.size)
        from .lifetime_policy import physical_storage
        if physical_storage(self.runner_policy):
            from .lifetime_physical_storage import reserve_parent_metadata
            reserve_parent_metadata(self,jid,path.name,PARENT_COST.size)
        with path.open('ab') as stream:stream.write(PARENT_COST.pack(seq+1,total+n));stream.flush();_io_fsync(stream.fileno())

    def _reserve_saved_read(self,jid,n):
        integer(n,'stream prefix validation bytes',0,2**40)
        path=self.path('jobs',jid,'parent-validation-work.bin');size=path.stat().st_size if path.exists() else 0
        if size%PARENT_COST.size or size>self.root_input.output_policy.max_index_bytes:raise ValueError('parent validation ledger bound/tail')
        seq=total=0
        if size:
            with path.open('rb') as stream:stream.seek(size-PARENT_COST.size);seq,total=PARENT_COST.unpack(stream.read(PARENT_COST.size))
            if seq!=size//PARENT_COST.size:raise ValueError('parent validation work sequence')
        if total+n>self.root_input.policy.max_control_units:raise ValueError('cumulative saved-data validation quota')
        self._parent_charge(jid,PARENT_COST.size)
        from .lifetime_policy import physical_storage
        if physical_storage(self.runner_policy):
            from .lifetime_physical_storage import reserve_parent_metadata
            reserve_parent_metadata(self,jid,path.name,PARENT_COST.size)
        with path.open('ab') as stream:stream.write(PARENT_COST.pack(seq+1,total+n));stream.flush();_io_fsync(stream.fileno())

    def find_checkpoint(self,jid,sha):
        if self.root_input.output_policy is None:
            options=[c for c in self.job(jid)['checkpoints'] if c['sha256']==sha]
            if not options:raise ValueError('retained checkpoint unavailable')
            return max(options,key=lambda c:c['file'])
        cp,proof=lookup_checkpoint(self.path('jobs',jid,'checkpoint-index'),sha)
        if not proof['raw_available']:raise ValueError('checkpoint raw bytes retired by declared policy')
        return cp

    def checkpoint_history(self,jid,*,before=None,limit=16):
        if self.root_input.output_policy is None:return dict(entries=[dict(checkpoint=c,raw_available=True) for c in self.job(jid)['checkpoints']],next_before=None)
        return checkpoint_page(self.path('jobs',jid,'checkpoint-index'),before=before,limit=limit)

    def job(self,jid):
        identifier(jid)
        with self.lock:
            if jid not in self._cache:
                from .lifetime_policy import is_v2
                if is_v2(self.runner_policy):
                    from .lifetime_status import read_envelope,hydrate
                    binding=self._status_binding(jid)
                    envelope,proof=read_envelope(self.path('jobs',jid,'status63'),binding,self.root_input.output_policy,profile=self.publication_profile)
                    self._status_read_charge(proof.get('read_validation_reserved_units',65536))
                    value=hydrate(self.path('jobs',jid,'status63'),envelope,binding,read_charge=self._status_read_charge)
                    self._admit_request_job(value,jid)
                elif self.root_input.output_policy is not None:
                    value,proof=read_latest_status(self.path('jobs',jid,'status53'),self.root_input.output_policy,profile=self.publication_profile)
                    if proof['sequence']!=value['publication_sequence']:raise ValueError('status stream sequence binding')
                    if proof['incomplete_head_tail_bytes']:
                        value.update(status='UNKNOWN',ownership_valid=False,reason='INCOMPLETE_STATUS_HEAD_TAIL_NO_REPAIR')
                else:
                    folder=self.path('jobs',jid,'status');files=sorted(folder.glob('*.json'))
                    if not 1<=len(files)<=MAX_STATUS or any(not re.fullmatch(r'[0-9]{8}\.json',p.name) for p in files):raise ValueError('lifecycle status history')
                    last=files[-1];value=_read(last)
                    if value['publication_sequence']!=int(last.stem) or len(files)!=value['publication_sequence']:raise ValueError('lifecycle status sequence')
                if not (is_v2(self.runner_policy) and value['status'] in TERMINAL):
                    self._admit_lifetime_cache_slot(jid)
                    self._cache[jid]=value
            else:value=self._cache[jid]
            value=deepcopy(value)
            from .lifetime_policy import is_v2
            if is_v2(self.runner_policy):self._admit_request_job(value,jid)
            required=('format','job_id','intent','root_identity','source_identity','runtime','input_sha256','resume','publication_sequence','status','reason','progress','checkpoints','result','launch','ownership_valid','created_utc','worker_artifact_bytes')
            from .finite_campaign import FiniteCampaignPolicy
            allowed={'parent_failure','terminal_failure'}|({'typed_stop'} if is_typed_campaign_policy(self.runner_policy) else set())|({'last_actual_refusal'} if self.root_input.method!=METHOD else set())
            if type(value) is not dict or not set(required)<=set(value) or set(value)-set(required)-allowed:raise ValueError('lifecycle exact job schema')
            if 'typed_stop'in value:
                from .battery_terminal import admit_terminal
                admit_terminal(value['typed_stop'])
                if value['result'] is not None:
                    from .battery_terminal import admit_bound_terminal
                    if value['typed_stop']!=admit_bound_terminal(value['result']['typed_terminal'],value,value['result']):raise ValueError('saved job typed terminal disagreement')
            if 'last_actual_refusal' in value:_last_action(value['last_actual_refusal'],solar=self.root_input.energy_attitude_policy is not None)
            if value.get('format')!=_job_format(value['intent']) or value.get('job_id')!=jid or value.get('root_identity')!=self.meta['root_identity'] or value.get('source_identity')!=self.meta['source_identity'] or value.get('runtime')!=self.meta['runtime']:raise ValueError('lifecycle job binding')
            validate_intent(value['intent'])
            if value['intent']['root_identity']!=value['root_identity'] or value['input_sha256']!=self.meta['input_sha256']:raise ValueError('lifecycle job immutable authority')
            if type(value['status']) is not str or value['status'] not in (*TERMINAL,'QUEUED','ADMITTED','RUNNING','STOP_REQUESTED'):raise ValueError('lifecycle job status')
            integer(value['publication_sequence'],'job publication',1,MAX_STATUS if self.root_input.output_policy is None else self.root_input.output_policy.max_index_bytes//72)
            if value['ownership_valid'] is not None and type(value['ownership_valid']) is not bool:raise ValueError('lifecycle ownership flag')
            if type(value['checkpoints']) is not list or len(value['checkpoints'])>(self.root_input.month_rows+8 if self.root_input.output_policy is None else 8):raise ValueError('lifecycle retained checkpoint count')
            return value

    def update_job(self,value):
        with self.lock:
            jid=identifier(value['job_id']);previous=self._cache.get(jid)
            self._reject_lifetime_terminal_writer(jid)
            expected=0 if previous is None else previous['publication_sequence']
            if value['publication_sequence']!=expected:raise ValueError('stale lifecycle status update')
            prospective=deepcopy(value)
            from .lifetime_policy import is_v2
            if is_v2(self.runner_policy):
                from .lifetime_status import preflight,Publisher
                self._admit_request_job(prospective,jid)
                binding=self._status_binding(jid)
                from .lifetime_policy import object_storage,packed_storage
                plan=preflight(prospective,binding,object_store=object_storage(self.runner_policy),packed_store=packed_storage(self.runner_policy))
                if prospective['status'] not in TERMINAL:self._admit_lifetime_cache_slot(jid)
                if jid not in self._status_writers:
                    self._status_writers[jid]=Publisher(self.path('jobs',jid,'status63'),binding,self.root_input.output_policy,profile=self.publication_profile,charge=lambda n:self._parent_charge(jid,n),codec_charge=lambda n:self._parent_codec_charge(jid,n),object_store=object_storage(self.runner_policy),packed_store=packed_storage(self.runner_policy))
                if self._status_writers[jid].publish(plan)!=expected+1:raise ValueError('B63 status head frontier')
                prospective=plan.job
            elif self.root_input.output_policy is None:
                if expected>=MAX_STATUS:raise ValueError('lifecycle metadata publication quota')
                prospective['publication_sequence']=expected+1;raw=_bytes(prospective)
                if self.path('portable-execution.json').exists():self._parent_charge(jid,len(raw))
                _write_new(self.path('jobs',jid,'status',str(expected+1).zfill(8)+'.json'),raw)
            else:
                prospective['publication_sequence']=expected+1
                if jid not in self._status_writers:self._status_writers[jid]=StatusStream(self.path('jobs',jid,'status53'),self.root_input.output_policy,charge=lambda n:self._parent_charge(jid,n),profile=self.publication_profile,codec_charge=lambda n:self._parent_codec_charge(jid,n))
                if self._status_writers[jid].publish(prospective,terminal=prospective['status'] in TERMINAL)!=expected+1:raise ValueError('status stream publication frontier')
            if is_v2(self.runner_policy) and prospective['status'] in TERMINAL:self._cache.pop(jid,None)
            else:self._cache[jid]=deepcopy(prospective)
            value['publication_sequence']=prospective['publication_sequence']

    def close_publications(self):
        from .lifetime_status import close_all
        from .lifetime_policy import is_v2
        lifetime=is_v2(getattr(self,'runner_policy',None));retirement_errors=[]
        if lifetime:
            with self.lock:
                self._lifetime_publications_closed=True
                resources=[('status:'+jid,writer)for jid,writer in self._status_writers.items()]
                resources.extend(('catalog:'+jid,catalog)for jid,catalog in self._catalogs.items())
                self._status_writers.clear();self._catalogs.clear();self._cache.clear();self._parent_work.clear()
                try:
                    errors=close_all(resources)
                    if errors:self._lifetime_retirement_failed=True
                    groups={}
                    for name,error in errors:groups.setdefault(name.split(':',1)[1],[]).append((name,error))
                    for jid,failures in groups.items():
                        try:self._lifetime_resource_failure(jid,self.meta,failures)
                        except BaseException as error:retirement_errors.append(error)
                finally:self._parent_work.clear()
        else:
            resources=[('status:'+jid,writer)for jid,writer in self._status_writers.items() if not writer.head.closed]
            resources.extend(('catalog:'+jid,catalog)for jid,catalog in self._catalogs.items())
            errors=close_all(resources)
        if errors:
            failure=RuntimeError('lifecycle publication close failures: '+ '; '.join(name+': '+repr(error)for name,error in errors))
            failure.close_failures=errors;failure.retirement_failures=retirement_errors
            raise failure from errors[0][1]

    def reconcile(self,intent):
        from .lifetime_policy import is_lifetime
        intent=validate_intent(intent)
        for job in self.jobs():
            if job['intent']['idempotency_key']==intent['idempotency_key']:
                if job['intent']!=intent:raise ValueError('lifecycle durable intent body drift')
                return self.job(job['job_id'])if is_lifetime(self.runner_policy) else job
        return None

    def arm_pilot_stop(self,jid,minimum_partial_bits):
        from .lifecycle_pilot_stop import arm
        return arm(self,jid,minimum_partial_bits)

    def prepare_job(self,intent):
        from .lifetime_typed_portable import store_contract_operation
        with store_contract_operation(self,Path(__file__).resolve().parents[2],operation='LIFECYCLE_PREPARE_JOB'):
            return self._prepare_job_admitted(intent)

    def _prepare_job_admitted(self,intent):
        from .lifecycle_checkpoint import admit_checkpoint,make_bindings,checkpoint_file_bytes
        with self.lock:
            if getattr(self,'_lifetime_publications_closed',False):raise ValueError('lifetime publications closed; no direct preparation')
            if getattr(self,'_lifetime_retirement_failed',False) or self.path('dispatch-quarantine.json').exists():raise ValueError('lifecycle application outcome quarantined; no direct preparation')
            from .lifetime_execution_authority import admit_public_execution
            admit_public_execution(self)
            intent=validate_intent(intent);self._pinned()
            portable_contract=None
            if (self.path('portable-execution.json').exists() or self.path('portable-job.json').exists() or
                    any(self.path('jobs').glob('*/portable-contract-binding.json'))):
                from .portable_job import worker_contract_for_store,admit_job_pin
                portable_contract=worker_contract_for_store(self,Path(__file__).resolve().parents[2])
                for prior in self.jobs():admit_job_pin(self.directory,prior['job_id'],portable_contract)
            if self.publication_profile is not None and intent['format']!=PROFILE_INTENT:raise ValueError('compact store requires explicit bound job profile')
            if self.publication_profile is None and _profile(intent) is not None:raise ValueError('legacy store cannot silently acquire compact profile')
            if intent['root_identity']!=self.meta['root_identity']:raise ValueError('lifecycle intent root mismatch')
            old=self.reconcile(intent)
            if old is not None:return old,False
            jobs=self.jobs()
            from .lifetime_no_launch import validate_next_dispatch
            validate_next_dispatch(self,intent)
            if len(jobs)>=self.maximum_jobs or any(j['status'] not in TERMINAL or j['ownership_valid'] is not True for j in jobs):raise ValueError('lifecycle population/unknown ownership blocks dispatch')
            from .finite_campaign import FiniteCampaignPolicy
            if is_typed_campaign_policy(self.runner_policy) and intent['maximum_output_bytes']>self.runner_policy.maximum_output_bytes:raise ValueError('finite per-job output cap')
            if intent['maximum_output_bytes']>self.root_input.policy.max_task_output_bytes:raise ValueError('lifecycle output policy cap')
            if sum(j['intent']['maximum_output_bytes'] for j in jobs)+intent['maximum_output_bytes']>self.maximum_reserved_job_output_bytes:raise ValueError('lifecycle store output reservation')
            resume=None
            if intent['parent_job_id'] is not None:
                parent=self.job(intent['parent_job_id'])
                if is_typed_campaign_policy(self.runner_policy) and parent['result'] is None:raise ValueError('typed failure has no continuation authority')
                if is_typed_campaign_policy(self.runner_policy) and parent['result'] is not None:
                    from .battery_terminal import admit_bound_terminal
                    t=admit_bound_terminal(parent['result']['typed_terminal'],parent,parent['result'])
                    if t['kind'] not in ('RESOURCE_TIME','RESOURCE_OUTPUT','USER','TARGET'):raise ValueError('typed terminal forbids suffix retry')
                if parent['status'] not in TERMINAL or parent['ownership_valid'] is not True:raise ValueError('lifecycle parent must have settled owned cleanup')
                if intent['mode']=='MAIN' and parent['launch'] is not None and parent['launch'].get('forced_interruption') is True:raise ValueError('forced interruption has UNKNOWN paid work after last checkpoint; MAIN resume requires review, diagnostic is a new experiment')
                options=[self.find_checkpoint(parent['job_id'],intent['snapshot_sha256'])]
                # Re-publication at an unchanged boundary can have identical
                # native state bytes. Select the latest immutable publication
                # sidecar, retaining its greater cumulative wrapper charges.
                checkpoint=max(options,key=lambda c:c['file'])
                if intent['mode']=='MAIN' and parent['status']=='PROCESS_FAILED' and checkpoint['file']!=max(parent['checkpoints'],key=lambda c:c['file'])['file']:raise ValueError('failed job MAIN requires latest retained paid-prefix authority; older checkpoint is diagnostic-only')
                from .lifetime_policy import physical_storage
                path=self.path('jobs',parent['job_id'],checkpoint['file'])
                if physical_storage(self.runner_policy)or 'transport'in checkpoint:
                    raw=checkpoint_file_bytes(path,checkpoint,self.root_input,require_transport=physical_storage(self.runner_policy))
                else:
                    # Preserve the accepted legacy reader's metadata domain;
                    # its strict scientific owner still checks SHA/bindings.
                    raw=path.read_bytes()
                    if len(raw)!=checkpoint['bytes']:raise ValueError('lifecycle parent checkpoint bytes')
                if checkpoint['bindings']!=make_bindings(self.root_input,checkpoint['clock']):raise ValueError('lifecycle parent current source/runtime/grid/clock')
                _admit_publication(path.parent,checkpoint,self.root_input,settled=True)
                admit_checkpoint(raw,self.root_input,expected_sha256=checkpoint['sha256'],expected_bindings=checkpoint['bindings'])
                _verify_checkpoint_streams(path.parent,checkpoint,self.root_input,reserve=lambda n:self._reserve_saved_read(parent['job_id'],n))
                end=self.root_input.end_seconds if intent['window_end_seconds'] is None else intent['window_end_seconds']
                if not checkpoint['clock']<end<=self.root_input.end_seconds:raise ValueError('lifecycle direct window must be a forward covered-root interval')
                resume=dict(parent_job_id=parent['job_id'],checkpoint=checkpoint)
            if is_typed_campaign_policy(self.runner_policy):
                from .finite_campaign import admit_role_population
                from .lifetime_policy import is_lifetime
                if is_lifetime(self.runner_policy):
                    from .lifetime_campaign import admit_lifetime_role_population
                    admit_lifetime_role_population(self.runner_policy,intent,None if resume is None else parent,None if resume is None else checkpoint,jobs,self.root_input.end_seconds,store=self)
                else:admit_role_population(intent,None if resume is None else parent,None if resume is None else checkpoint,jobs,self.root_input.end_seconds)
            jid=uuid.uuid4().hex
            request=dict(format=_job_format(intent),job_id=jid,intent=intent,root_identity=self.meta['root_identity'],source_identity=self.meta['source_identity'],
                runtime=self.meta['runtime'],input_sha256=self.meta['input_sha256'],resume=resume)
            from .lifetime_policy import physical_storage
            if physical_storage(self.runner_policy):
                from .lifetime_physical_storage import reserve_for_intent
                reserve_for_intent(self,intent,job_id=jid,request_sha256=sha256(_bytes(request)).hexdigest())
            _write_new(self.path('jobs',jid,'request.json'),request)
            if portable_contract is not None:
                from .portable_job import job_pin
                _write_new(self.path('jobs',jid,'portable-contract-binding.json'),job_pin(portable_contract,jid),4096)
            job=dict(**request,publication_sequence=0,status='QUEUED',reason=None,progress=None,checkpoints=[],result=None,launch=None,ownership_valid=None,created_utc=_utc(),worker_artifact_bytes=None)
            self.update_job(job)
            return self.job(jid),True

    def snapshot(self):
        jobs=self.jobs()
        value=dict(root_identity=self.meta['root_identity'],source_identity=self.meta['source_identity'],method=self.root_input.method,
            start_seconds=self.root_input.start_seconds,end_seconds=self.root_input.end_seconds,admission=self.meta['admission'],
            policy=asdict(self.root_input.policy),scenario=asdict(self.root_input.scenario),sun_mode=self.root_input.sun_mode,project=self.meta['project'],jobs=jobs,
            output_policy=None if self.root_input.output_policy is None else asdict(self.root_input.output_policy),
            study=None if self.root_input.study is None else dict(identity=self.root_input.study.content_digest,
                preset='COMMON_ASSUMED_V1',ageing_multiplier=self.root_input.study.ageing_multiplier,
                latency_seconds=self.root_input.study.latency_seconds,provenance=self.root_input.study.provenance))
        if self.runner_policy is not None:
            reserved=sum(job['intent']['maximum_output_bytes'] for job in jobs)
            value.update(runner_policy=asdict(self.runner_policy),runner_policy_identity=self.runner_policy.identity,
                runner_store_format=self.meta['format'],remaining_job_slots=self.maximum_jobs-len(jobs),
                reserved_job_output_bytes=reserved,remaining_reserved_job_output_bytes=self.maximum_reserved_job_output_bytes-reserved)
        if self.root_input.service_policy is not None:
            value.update(service_policy=asdict(self.root_input.service_policy),service_policy_identity=self.root_input.service_policy.identity)
        if self.root_input.environment_ageing_policy is not None:
            value.update(environment_ageing_policy=asdict(self.root_input.environment_ageing_policy),environment_ageing_policy_identity=self.root_input.environment_ageing_policy.identity)
        if self.root_input.battery_port_policy is not None:
            value.update(battery_port_policy=asdict(self.root_input.battery_port_policy),battery_port_policy_identity=self.root_input.battery_port_policy.identity)
        if self.root_input.energy_attitude_policy is not None:
            value.update(energy_attitude_policy=asdict(self.root_input.energy_attitude_policy),energy_attitude_policy_identity=self.root_input.energy_attitude_policy.identity)
        if self.root_input.reduced_sun_policy is not None:
            value['reduced_sun_policy']=asdict(self.root_input.reduced_sun_policy)
        value.update(publication_profile=None if self.publication_profile is None else asdict(self.publication_profile),publication_profile_identity=None if self.publication_profile is None else self.publication_profile.identity)
        if self.meta['project'] is not None and self.meta['project'].get('format')in ('B66_BOUND_DESIGN_PROJECT_LINEAGE_V1','B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'):
            value['design_validation_preparation']=dict(scope='CURRENT_STORE_OBJECT_STATIC_CONSTRUCTOR_NOT_MISSION_EVOLUTION',
                work=dict(self._design_lineage_constructor_work))
        return value

    def stream_page(self,jid,name,*,after=0,limit=16):
        from .lifecycle_stream import iter_stream_records
        if name not in ('events','months','details'):raise ValueError('declared scientific stream name')
        integer(after,'record page after',0,2**48);integer(limit,'record page limit',1,32)
        job=self.job(jid)
        if job['status'] not in TERMINAL or job['ownership_valid'] is not True or job['result'] is None:raise ValueError('settled complete stream required for saved page')
        frontier=job['result']['streams'][name];rows=[];count=0;total_bytes=0
        self._reserve_saved_read(jid,frontier['work']['bytes_published']+4*frontier.get('codec',{}).get('decoded_bytes_completed',0))
        for record in iter_stream_records(self.path('jobs',jid,name+'53'),frontier,self.root_input.output_policy):
            count+=1
            if after<count<=after+limit:
                total_bytes+=len(_bytes(record))
                if total_bytes>2**20:raise ValueError('bounded scientific page bytes')
                rows.append(record)
        return dict(stream=name,records=rows,after=after,next_after=None if after+len(rows)>=count else after+len(rows),total_records=count,scope='SAVED_JOB_STREAM_NOT_PRIMARY_LINEAGE_TOTAL',profile_identity=job['intent'].get('publication_profile_identity'))

    def export(self,jid):
        from .lifetime_policy import physical_storage
        if physical_storage(self.runner_policy):
            raise ValueError('YEAR-V4 physical stores require lifetime_supervisor.export_result with a separately reserved EXPORT grant')
        job=self.job(jid)
        if job['status'] not in TERMINAL or job['ownership_valid'] is not True:raise ValueError('lifecycle export requires settled ownership')
        if self.root_input.output_policy is not None:
            writer=self._status_writers.get(jid)
            if writer is not None and not writer.head.closed:writer.close()
        files=[self.path('store.json'),self.path('input.json')];pending=[jid];seen=set()
        if self.meta['project'] is not None and self.meta['project'].get('format')in ('B66_BOUND_DESIGN_PROJECT_LINEAGE_V1','B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'):
            self._admit_design_lineage();files.append(self.path('design-project-input.json'))
        # Prefix month rows and the exact selected parent authority stay in a
        # self-contained export; the immutable policy's finite lineage cannot recurse
        # into unrelated stores or acquire a historical runtime implicitly.
        while pending:
            current=pending.pop()
            if current in seen:raise ValueError('lifecycle export lineage cycle')
            seen.add(current)
            if len(seen)>self.maximum_lineage_jobs:raise ValueError('lifecycle export lineage cap')
            ancestor=self.job(current)
            if ancestor['status'] not in TERMINAL or ancestor['ownership_valid'] is not True:raise ValueError('unsettled export ancestor')
            folder=self.path('jobs',current)
            for path in folder.rglob('*'):
                ProjectStore._reject_links(path)
                if path.is_file() and 'tmp' not in path.relative_to(folder).parts:
                    files.append(path)
                    if len(files)>16384:raise ValueError('portable export prospective member cap')
            if ancestor['resume'] is not None:pending.append(ancestor['resume']['parent_job_id'])
        chain_folder=self.path('chains')
        if chain_folder.exists():
            for chain in sorted(chain_folder.iterdir()):
                from .lifecycle_chain import LifecycleChain
                LifecycleChain(self,chain.name).snapshot()
                if (chain/'writer-owner.json').exists():raise ValueError('chain export requires settled writer')
                for path in sorted(chain.rglob('*')):
                    ProjectStore._reject_links(path)
                    if path.is_file():files.append(path)
                if len(files)>16384:raise ValueError('portable chain export member cap')
        total=sum(path.stat().st_size for path in files)
        raw_cap=MAX_EXPORT if self.root_input.output_policy is None else min(2**30,self.root_input.policy.max_task_output_bytes*len(seen))
        if total>raw_cap:raise ValueError('lifecycle portable export input cap')
        eid=uuid.uuid4().hex;target=self.path('exports',eid+'.zip')
        from .lifetime_physical_storage import register_producer_path
        register_producer_path(target)
        target.parent.mkdir(exist_ok=True)
        manifest={}
        sink=_BoundedExport(target,MAX_EXPORT)
        try:
            with zipfile.ZipFile(sink,'w',zipfile.ZIP_DEFLATED) as z:
                for path in sorted(files):
                    name=path.relative_to(self.directory).as_posix();before=path.stat();digest=sha256()
                    with path.open('rb') as stream:
                        for block in iter(lambda:stream.read(2**20),b''):digest.update(block)
                    z.write(path,name);after=path.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('export artifact changed during capture')
                    manifest[name]=dict(bytes=before.st_size,sha256=digest.hexdigest())
                z.writestr('MANIFEST.json',_bytes(manifest))
        finally:sink.close()
        if target.stat().st_size>MAX_EXPORT:raise ValueError('lifecycle portable ZIP cap')
        with zipfile.ZipFile(target) as z:
            if z.testzip() is not None:raise ValueError('lifecycle export CRC')
        return dict(export_id=eid,path=str(target),sha256=file_sha(target),bytes=target.stat().st_size,url='/api/lifecycle/export/'+self.meta['root_identity']+'/'+eid)


class ProgressReader:
    """Bounded incremental complete records; an incomplete tail is explicit."""
    def __init__(self,path,job,limit,*,output_policy=None,method=METHOD,service_policy_identity=None,solar_root=None,battery_root=None,environment_root=None,read_charge=None):
        self.path=path;self.job=job;self.limit=limit;self.offset=0;self.tail=b'';self.sequence=0;self.method=method;self.output_policy=output_policy
        if method==METHOD55:identity(service_policy_identity)
        elif service_policy_identity is not None:raise ValueError('legacy progress cannot acquire a service policy')
        self.service_policy_identity=service_policy_identity
        self.environment_root=environment_root
        self.battery_root=battery_root
        if battery_root is not None:
            from .lifecycle_contract import LifecycleRoot
            if type(battery_root)is not LifecycleRoot or battery_root.battery_port_policy is None or battery_root.identity!=job['root_identity']:raise ValueError('trusted caller port root')
        self.solar_root=solar_root
        if solar_root is not None:
            from .lifecycle_contract import LifecycleRoot
            if type(solar_root) is not LifecycleRoot or solar_root.energy_attitude_policy is None or solar_root.identity!=job['root_identity']:raise ValueError('trusted caller solar progress root binding')
        self.chunk_reader=None if output_policy is None else IncrementalStreamReader(path,output_policy,output_policy.progress_total_bytes,profile=_job_profile(job),read_charge=read_charge)
    def validate(self,record,sequence,**keywords):
        if self.method==METHOD55:keywords['service_policy_identity']=self.service_policy_identity
        if self.environment_root is not None:keywords['environment_root']=self.environment_root
        if self.battery_root is not None:keywords['battery_root']=self.battery_root
        if self.solar_root is not None:keywords['solar_root']=self.solar_root
        return _validate_progress(record,self.job,sequence,method=self.method,**keywords)
    def read(self):
        if self.chunk_reader is not None:
            result=[]
            for record in self.chunk_reader.read():
                result.append(self.validate(record,self.sequence+1,publication_minimum=self.output_policy.publication_minimum_wall_seconds));self.sequence+=1
            self.tail=self.chunk_reader.tail;return result
        if not self.path.exists():return []
        if self.path.stat().st_size>self.limit:raise ValueError('lifecycle progress journal cap')
        with self.path.open('rb') as f:f.seek(self.offset);raw=f.read(self.limit-self.offset+1)
        self.offset+=len(raw);lines=(self.tail+raw).split(b'\n');self.tail=lines.pop();result=[]
        if len(self.tail)>65536:raise ValueError('lifecycle incomplete record cap')
        for line in lines:
            if not line or len(line)>65536:raise ValueError('lifecycle progress record size')
            record=self.validate(parse_json(line.decode('utf-8')),self.sequence+1)
            self.sequence+=1;result.append(record)
        return result


def _validate_progress(record,job,sequence,*,method=METHOD,publication_minimum=1,service_policy_identity=None,solar_root=None,battery_root=None,environment_root=None):
    if environment_root is not None:
        from .lifecycle_contract import LifecycleRoot
        if type(environment_root)is not LifecycleRoot or environment_root.environment_ageing_policy is None or environment_root.identity!=job['root_identity']:raise ValueError('B61 progress caller root')
    if solar_root is not None:
        from .lifecycle_contract import LifecycleRoot
        if type(solar_root) is not LifecycleRoot or solar_root.energy_attitude_policy is None or solar_root.identity!=job['root_identity'] or method!=METHOD55:raise ValueError('trusted solar progress caller binding')
    if battery_root is not None:
        from .lifecycle_contract import LifecycleRoot
        if type(battery_root)is not LifecycleRoot or battery_root.battery_port_policy is None or battery_root.identity!=job['root_identity']or method!=METHOD55:raise ValueError('trusted port progress caller binding')
    if type(method) is not str or method not in (METHOD,METHOD53,METHOD55):raise ValueError('supported lifecycle progress method required')
    if method==METHOD55:identity(service_policy_identity)
    elif service_policy_identity is not None:raise ValueError('legacy progress cannot acquire a service policy')
    _job_profile(job) # admit legacy metadata separately from profile-bound full jobs
    object_fields(record,('format','sequence','job_id','root_identity','kind','data'))
    if record['format']!=JOURNAL or type(record['sequence']) is not int or record['sequence']!=sequence or record['job_id']!=job['job_id'] or record['root_identity']!=job['root_identity']:raise ValueError('lifecycle progress binding/sequence')
    if record['kind'] not in ('identity','boundary','checkpoint','retired_checkpoint','completed','stopped','failure'):raise ValueError('lifecycle progress kind')
    if type(record['data']) is not dict:raise ValueError('lifecycle progress payload')
    if record['kind']=='identity':
        object_fields(record['data'],('worker_PID','worker_PPID','runtime'))
        for name in ('worker_PID','worker_PPID'):integer(record['data'][name],name,1,2**32)
        if record['data']['runtime']!=job['runtime']:raise ValueError('lifecycle actual worker runtime')
    elif record['kind']=='boundary':
        data=record['data']
        extended=method!=METHOD
        object_fields(data,('method','status','clock','start_seconds','end_seconds','simulated_seconds','transitions','actions','decisions',
            'offered','active_requests','queued_packets','pending_intents','pending_action','partial_bits','credits','sealed_month_rows',
            'actual_cache','forecast_cache','actual_world','forecast_world','publication',*(('quiet','illumination','last_action') if extended else ()),*(('power_service',) if method==METHOD55 else ()),*(('solar_attitude',) if solar_root is not None else ()),*(('battery_port',) if battery_root is not None else ()),*(('environment_ageing',)if environment_root is not None else ())))
        if data['method']!=method or type(data['status']) is not str or not 1<=len(data['status'])<=128:raise ValueError('lifecycle progress method/status')
        for name in ('clock','start_seconds','end_seconds','simulated_seconds','transitions','actions','decisions','offered','active_requests','queued_packets','pending_intents','credits','sealed_month_rows'):integer(data[name],name,0,2**48)
        if not data['start_seconds']<=data['clock']<=data['end_seconds'] or data['simulated_seconds']!=data['clock']-data['start_seconds'] or data['credits']>data['offered']:raise ValueError('lifecycle displayed committed coverage')
        if data['active_requests']>16 or data['queued_packets']>128 or data['pending_intents']>16:raise ValueError('lifecycle displayed bounded active state')
        if data['pending_action'] is not None and data['pending_action'] not in (('POINT','CAPTURE','CONTACT','HOLD_UNTIL','SOLAR_POINT','SOLAR_HOLD') if solar_root is not None else ('POINT','CAPTURE','CONTACT','HOLD_UNTIL')):raise ValueError('lifecycle pending action')
        if type(data['partial_bits']) is not list or len(data['partial_bits'])>16 or any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in data['partial_bits']):raise ValueError('lifecycle actual partial bits')
        for role,prefix in (('ACTUAL','actual'),('FORECAST','forecast')):
            _cache_accounting(data[prefix+'_cache'],role)
            _world_accounting(data[prefix+'_world'],role,root_method=method,start=data['start_seconds'],clock=data['clock'])
        if data['actual_world']['api']!=data['forecast_world']['api']:raise ValueError('paired world accounting versions differ')
        if 'lighting_consumption' in data['actual_world']:
            actual_end=_hex_rational(data['actual_world']['lighting_consumption']['end_seconds'])
            forecast_end=_hex_rational(data['forecast_world']['lighting_consumption']['end_seconds'])
            if forecast_end>actual_end:raise ValueError('forecast lighting cannot consume future ACTUAL support')
        publication=object_fields(data['publication'],('minimum_wall_interval_seconds','policy_omitted_snapshots','last_checkpoint_bytes','memory',*(('resources',) if job.get('intent',{}).get('format')==PROFILE_INTENT else ())))
        if job.get('intent',{}).get('format')==PROFILE_INTENT:
            resources=object_fields(publication['resources'],('scope','current_energy_wh','minimum_energy_wh','offered','on_time_credits','expired','refused_actions','pending_dispositions','maximum_temperature_k'))
            if resources['scope']!='SELECTED_ACTUAL_REPORT_PREFIX_SAMPLED_EXTREMA':raise ValueError('resource display scope')
            for name in ('current_energy_wh','minimum_energy_wh'):
                v=resources[name]
                if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise ValueError('actual display energy')
            for name in ('offered','on_time_credits','expired','refused_actions','pending_dispositions'):integer(resources[name],name,0,2**48)
            if resources['offered']!=data['offered'] or resources['on_time_credits']!=data['credits'] or resources['minimum_energy_wh']>resources['current_energy_wh'] or resources['on_time_credits']+resources['expired']+resources['pending_dispositions']!=resources['offered']:raise ValueError('actual display population/energy balance')
            nodes=resources['maximum_temperature_k']
            if type(nodes) is not dict or not 1<=len(nodes)<=32 or any(type(k) is not str or not 1<=len(k)<=128 or type(v) not in (int,float) or not math.isfinite(v) or v<=0 for k,v in nodes.items()):raise ValueError('actual display sampled thermal nodes')
        if publication['minimum_wall_interval_seconds']!=publication_minimum:raise ValueError('lifecycle progress cadence')
        integer(publication['policy_omitted_snapshots'],'omitted observational snapshots',0,2**48)
        integer(publication['last_checkpoint_bytes'],'last encoded working state',1,64*2**20)
        memory=object_fields(publication['memory'],('status','method','current_rss_bytes','peak_rss_bytes','error'))
        if memory['method']!='WINDOWS_OWN_PROCESS_WORKING_SET':raise ValueError('worker memory measurement method')
        if memory['status']=='AVAILABLE':
            integer(memory['current_rss_bytes'],'worker working set',1,2**48);integer(memory['peak_rss_bytes'],'worker peak working set',memory['current_rss_bytes'],2**48)
            if memory['error'] is not None:raise ValueError('successful memory query has an error')
        elif memory['status']=='UNAVAILABLE':
            if memory['current_rss_bytes'] is not None or memory['peak_rss_bytes'] is not None or type(memory['error']) is not str or not memory['error']:raise ValueError('memory unavailable evidence')
        else:raise ValueError('worker memory status')
        if extended:
            _last_action(data['last_action'],solar=solar_root is not None)
            quiet_root=environment_root if environment_root is not None else battery_root if battery_root is not None else solar_root
            quiet_policy=None if quiet_root is None else quiet_root.policy.quiet_solver
            quiet_method='B53_PAID_QUIET_STEP_DOUBLING_V1' if quiet_policy is None else quiet_policy.method
            _quiet_accounting(data['quiet'],clock=data['clock'],elapsed=data['simulated_seconds'],expected_method=quiet_method,expected_policy=quiet_policy);light=data['illumination']
            _lighting_accounting(light,'ACTUAL',root_method=method,start=data['start_seconds'],clock=data['clock'])
            if light!=data['actual_world']['lighting_consumption']:raise ValueError('actual lighting projection/accounting disagreement')
        if method==METHOD55:
            _power_service_accounting(data['power_service'],clock=data['clock'],start=data['start_seconds'],policy_identity=service_policy_identity)
        if solar_root is not None:
            from .solar_lifecycle import validate_solar_progress
            validate_solar_progress(data['solar_attitude'],solar_root,data['clock'])
        if environment_root is not None:
            from .environment_lifecycle import validate_progress
            validate_progress(data['environment_ageing'],environment_root,data['clock'])
        if battery_root is not None:
            from .battery_port_reporting import validate_port_progress
            validate_port_progress(data['battery_port'],battery_root,data['clock'])
    elif record['kind']=='checkpoint':
        from .lifecycle_checkpoint import admit_checkpoint_transport
        cp=record['data'];admit_checkpoint_transport(cp)
        if method==METHOD55 and (type(cp['kind']) is not str or cp['kind'] not in ('INITIAL','RESTORED','WORKING','AUDIT_NAMED','MONTH_BOUNDARY','PENDING_PARTIAL_CONTACT','FINAL','FAILURE_PAID_PREFIX','APPLICATION_QUOTA_BOUNDARY','COOPERATIVE_STOP_PAID_PREFIX','MEMORY_TARGET_BOUNDARY','BUDGET_COOPERATIVE_PAID_PREFIX',*SERVICE_CHECKPOINT_KINDS)):raise ValueError('known B55 checkpoint kind')
        if not re.fullmatch(r'checkpoint-[0-9]{8}\.json',cp['file']):raise ValueError('lifecycle checkpoint filename')
        identity(cp['sha256']);integer(cp['bytes'],'checkpoint bytes',1,64*2**20);integer(cp['clock'],'checkpoint clock')
        if cp['bindings']['clock']!=cp['clock'] or cp['bindings']['root_identity']!=job['root_identity'] or cp['bindings']['source_identity']!=job['source_identity'] or cp['bindings']['runtime']!=job['runtime']:raise ValueError('lifecycle checkpoint progress bindings')
    elif record['kind'] in ('completed','stopped'):
        object_fields(record['data'],('terminal_sha256','clock'));identity(record['data']['terminal_sha256']);integer(record['data']['clock'],'terminal clock')
    return record


def _power_service_accounting(value,*,clock,start,policy_identity):
    """Strict selected ACTUAL prefix; an untrusted snapshot grants no service."""
    from .lifecycle_service import POWER_SERVICE_API,MODES,REASONS
    names=('api','policy_identity','mode','clock_seconds','entered_at_seconds','last_reason',
        'boot_progress_seconds','essential_serviceable','communications_serviceable',
        'low_rate_telemetry_serviceable','tx_fully_served','mode_durations_seconds',
        'receiving_energy_wh','boot_work_seconds','selected_steps','transitions',
        'service_interruptions','transition_reasons','pinned_requests','deferred_feedback')
    object_fields(value,names)
    if value['api']!=POWER_SERVICE_API or value['policy_identity']!=policy_identity:raise ValueError('selected service API/policy binding')
    if type(value['mode']) is not str or value['mode'] not in MODES or type(value['last_reason']) is not str or value['last_reason'] not in REASONS:raise ValueError('selected service mode/reason')
    through=_decimal_rational(value['clock_seconds']);entered=_decimal_rational(value['entered_at_seconds']);boot=_decimal_rational(value['boot_progress_seconds'])
    if through!=clock or not start<=entered<=through or boot>through-entered:raise ValueError('selected service clock/entry/boot support')
    if value['mode']!='RECOVERY' and boot:raise ValueError('boot progress outside RECOVERY')
    for name in ('essential_serviceable','communications_serviceable','low_rate_telemetry_serviceable','tx_fully_served'):
        if type(value[name]) is not bool:raise ValueError('exact service functional flag')
    if value['communications_serviceable']!=value['low_rate_telemetry_serviceable']:raise ValueError('legacy low-rate service alias differs')
    if (value['low_rate_telemetry_serviceable'] or value['tx_fully_served']) and (value['mode']!='NORMAL' or not value['essential_serviceable']):raise ValueError('unpowered mode cannot claim messaging or high-rate TX')
    times=object_fields(value['mode_durations_seconds'],MODES)
    durations={name:_decimal_rational(times[name]) for name in MODES}
    if sum(durations.values(),Fraction())!=clock-start:raise ValueError('selected service durations do not cover exact prefix')
    energy_fields=('desired_normal_load_wh','commanded_load_wh','served_receiving_load_wh','commanded_shed_demand_wh','essential_unserved_wh')
    energy=object_fields(value['receiving_energy_wh'],energy_fields)
    e={name:_decimal_rational(energy[name]) for name in energy_fields}
    desired=e['desired_normal_load_wh'];commanded=e['commanded_load_wh'];served=e['served_receiving_load_wh']
    if not served<=commanded<=desired or e['commanded_shed_demand_wh']!=desired-commanded or e['essential_unserved_wh']>commanded-served:raise ValueError('selected receiving energy scope balance')
    if _decimal_rational(value['boot_work_seconds'])>durations['RECOVERY']:raise ValueError('boot work exceeds selected recovery duration')
    for name in ('selected_steps','transitions','service_interruptions'):integer(value[name],name,0,2**48)
    for name in ('pinned_requests','deferred_feedback'):integer(value[name],name,0,16)
    if value['service_interruptions']>value['selected_steps'] or value['transitions']>value['selected_steps']:raise ValueError('selected service counters exceed selected work')
    reasons=value['transition_reasons']
    if type(reasons) is not list or len(reasons)>len(REASONS):raise ValueError('bounded service transition reasons')
    seen=[];count=0
    for item in reasons:
        if type(item) is not list or len(item)!=2 or type(item[0]) is not str or item[0] not in REASONS:raise ValueError('known service transition reason')
        integer(item[1],'service transition reason count',1,2**48);seen.append(item[0]);count+=item[1]
    if seen!=sorted(set(seen)) or count!=value['transitions']:raise ValueError('service transition reason count/order')


def _last_action(value,*,solar=False):
    if value is None:return
    object_fields(value,('action_id','kind','status','reason','refusal_detail'))
    for name in ('action_id','kind','status'):
        if type(value[name]) is not str or not 1<=len(value[name])<=200:raise ValueError('actual action identity')
    if value['kind'] not in (('POINT','CAPTURE','CONTACT','HOLD_UNTIL','SOLAR_POINT','SOLAR_HOLD') if solar else ('POINT','CAPTURE','CONTACT','HOLD_UNTIL')) or value['status'] not in ('completed','partial','refused'):raise ValueError('actual owner action kind/status')
    if value['reason'] is not None and (type(value['reason']) is not str or len(value['reason'])>400):raise ValueError('actual action reason')
    detail=value['refusal_detail']
    if detail is None:return
    if value['status']!='refused':raise ValueError('actual refusal detail requires refused action')
    object_fields(detail,('stage','code','owner','evaluated_calls','quantities','method'))
    if detail['method']!='B53_ACTUAL_ACQUISITION_REFUSAL_V1' or detail['stage'] not in ('VIEW','SETTLING','STORAGE'):raise ValueError('actual acquisition refusal method/stage')
    for name,limit in (('code',100),('owner',200)):
        if type(detail[name]) is not str or not 1<=len(detail[name])<=limit:raise ValueError('actual refusal identity')
    calls=detail['evaluated_calls'];quantities=detail['quantities']
    if type(calls) is not list or not 1<=len(calls)<=8 or type(quantities) is not list or len(quantities)>12:raise ValueError('bounded actual refusal evidence')
    for rows,counted in ((calls,True),(quantities,False)):
        names=[]
        for row in rows:
            if type(row) is not list or len(row)!=2 or type(row[0]) is not str or not 1<=len(row[0])<=100:raise ValueError('actual refusal evidence row')
            names.append(row[0]);item=row[1]
            if counted:integer(item,'actual evaluated owner calls',1,2)
            elif type(item) not in (str,int,float) or type(item) is str and len(item)>200 or type(item) in (int,float) and not math.isfinite(item):raise ValueError('finite actual refusal quantity')
        if len(set(names))!=len(names):raise ValueError('duplicate actual refusal evidence')


def _hex_rational(value):
    if type(value) is not list or len(value)!=2 or any(type(x) is not str or len(x)>68 for x in value):raise ValueError('lifecycle accounting rational')
    try:q=Fraction(int(value[0],16),int(value[1],16))
    except (ValueError,ZeroDivisionError):raise ValueError('lifecycle accounting rational') from None
    if [hex(q.numerator),hex(q.denominator)]!=value:raise ValueError('lifecycle accounting rational spelling')
    return q


def _decimal_rational(value):
    if type(value) is not list or len(value)!=2 or any(type(x) is not str or len(x)>1235 for x in value):raise ValueError('quiet decimal rational')
    try:q=Fraction(int(value[0]),int(value[1]))
    except (ValueError,ZeroDivisionError):raise ValueError('quiet decimal rational') from None
    if q<0 or [str(q.numerator),str(q.denominator)]!=value:raise ValueError('quiet decimal rational spelling/sign')
    return q


def _quiet_accounting(value,*,clock=None,elapsed=None,expected_method='B53_PAID_QUIET_STEP_DOUBLING_V1',expected_policy=None):
    from .lifecycle_quiet import (QUIET_METHOD,BATTERY_QUIET_METHOD,ENVIRONMENT_QUIET_METHOD,
        SHORT_QUIET_METHOD,SHORT_BATTERY_QUIET_METHOD,SHORT_ENVIRONMENT_QUIET_METHOD,
        QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy,
        QuietControllerState,ShortCircuitQuietWork,quiet_work_type)
    legacy=(QUIET_METHOD,BATTERY_QUIET_METHOD,ENVIRONMENT_QUIET_METHOD)
    modern=(SHORT_QUIET_METHOD,SHORT_BATTERY_QUIET_METHOD,SHORT_ENVIRONMENT_QUIET_METHOD)
    if type(expected_method)is not str or expected_method not in (*legacy,*modern):raise ValueError('quiet progress method')
    short=expected_method in modern
    if expected_policy is not None:
        if type(expected_policy)not in (QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy):raise TypeError('quiet progress exact policy authority')
        work_type=quiet_work_type(expected_policy)
        if expected_policy.method!=expected_method or (work_type is ShortCircuitQuietWork)!=short:raise ValueError('quiet progress policy/method binding')
    elif short:raise ValueError('new quiet progress requires exact declared policy')
    if value is None:
        if short:raise ValueError('new quiet progress work cannot be omitted')
        return
    object_fields(value,('method','controller','actual','forecast'))
    if type(value['method'])is not str or value['method']!=expected_method:raise ValueError('quiet progress method')
    controller=object_fields(value['controller'],('clock_seconds','next_step_seconds','last_step_seconds','last_error_norm','phase'))
    controller_clock=_decimal_rational(controller['clock_seconds']);last_step=_decimal_rational(controller['last_step_seconds']);integer(controller['next_step_seconds'],'quiet next step',1,120)
    if clock is not None and controller_clock!=clock:raise ValueError('quiet controller clock is stale')
    if type(controller['last_error_norm']) not in (int,float) or not math.isfinite(controller['last_error_norm']) or controller['last_error_norm']<0 or type(controller['phase'])is not str or controller['phase'] not in ('INITIAL','ACCEPTED','DETAILED_FALLBACK','DETAILED_ACTION'):raise ValueError('quiet controller displayed state')
    if controller['phase']=='ACCEPTED' and controller['last_error_norm']>1:raise ValueError('accepted quiet controller error outside admission')
    if short:
        QuietControllerState(controller_clock,controller['next_step_seconds'],last_step,
            controller['last_error_norm'],controller['phase'],expected_method).validate(expected_policy,clock=clock)
    counters=('proposed_macros','accepted_macros','rejected_macros','reserved_leaf_calls','returned_leaf_calls','refused_leaf_calls','unknown_leaf_calls',
        'full_trial_calls','half_trial_calls','detailed_fallback_calls','selected_parts','committed_parts','selected_step_le_1','selected_step_le_2','selected_step_le_4','selected_step_le_8','selected_step_le_16','selected_step_le_32','selected_step_gt_32')
    extra=('first_half_calls','second_half_calls','skipped_half_trial_calls','early_full_near','early_first_near','early_first_regime',
        'full_near_guard','first_near_guard','second_near_guard','full_first_regime_mismatch','full_second_regime_mismatch','first_second_regime_mismatch',
        'norm_evaluations','norm_rejections','norm_not_evaluated_early','minimum_macro_proposals','shortened_boundary_proposals','below_minimum_fallbacks','minimum_macro_fallbacks') if short else ()
    for scope in ('actual','forecast'):
        work=object_fields(value[scope],(*counters,'selected_seconds','committed_seconds','maximum_accepted_error_norm',*extra))
        for n in (*counters,*extra):integer(work[n],n,0,2**56)
        maximum=work['maximum_accepted_error_norm']
        if type(maximum) not in (int,float) or not math.isfinite(maximum) or not 0<=maximum<=1:raise ValueError('quiet maximum accepted error outside admission')
        if work['accepted_macros']==0 and maximum!=0:raise ValueError('quiet accepted error without accepted macro')
        selected=_decimal_rational(work['selected_seconds']);committed=_decimal_rational(work['committed_seconds'])
        if scope=='actual' and elapsed is not None and committed>elapsed:raise ValueError('quiet committed duration exceeds actual elapsed support')
        if work['returned_leaf_calls']+work['refused_leaf_calls']+work['unknown_leaf_calls']!=work['reserved_leaf_calls'] or work['full_trial_calls']+work['half_trial_calls']+work['detailed_fallback_calls']!=work['reserved_leaf_calls'] or work['accepted_macros']+work['rejected_macros']>work['proposed_macros'] or work['committed_parts']>work['selected_parts'] or committed>selected or sum(work[n] for n in counters if n.startswith('selected_step_'))!=work['selected_parts']:raise ValueError('quiet displayed work conservation')
        if short:
            exact=dict(work,selected_seconds=selected,committed_seconds=committed)
            ShortCircuitQuietWork(**exact).validate(expected_policy)
    if controller['phase']=='ACCEPTED' and controller['last_error_norm']>value['actual']['maximum_accepted_error_norm']:raise ValueError('quiet latest accepted error exceeds cumulative maximum')


def _cache_accounting(value,role):
    counters=('low_grid_index','high_grid_index','retained_grid','retained_tails','queries','cache_reads','full_steps','tail_steps','force_reserved','force_completed',
        'control_reserved','unknown_primitive_events','cache_records','peak_cache_records','grid_evictions','tail_evictions')
    object_fields(value,('method','identity','role','original_grid_step_seconds','retention_floor','failed',*counters))
    identity(value['identity'])
    if value['role']!=role or type(value['method']) is not str or not value['method'] or type(value['failed']) is not bool:raise ValueError('lifecycle orbit accounting role/method')
    if type(value['original_grid_step_seconds']) is not float or not math.isfinite(value['original_grid_step_seconds']) or value['original_grid_step_seconds']<=0:raise ValueError('lifecycle orbit fixed grid')
    _hex_rational(value['retention_floor'])
    for name in counters:integer(value[name],name,0,2**56)
    if value['low_grid_index']>value['high_grid_index'] or value['force_completed']>value['force_reserved']:raise ValueError('lifecycle orbit accounting balance')


def _lighting_accounting(value,role,*,root_method,start=None,clock=None):
    object_fields(value,('method','units','scope','start_seconds','end_seconds','covered_seconds','illuminated_seconds','occulted_seconds','unresolved_seconds','selected_commits','qualification'))
    expected_scope='SELECTED_ACTUAL_CONSUMED_SUPPORT' if role=='ACTUAL' else 'INHERITED_ACTUAL_PREFIX_ONLY_NO_FORECAST_CONSUMPTION'
    if value['method']!='B53_SELECTED_ACTUAL_SAMPLED_HELD_LIGHT_DURATION_V1' or value['units']!='s' or value['scope']!=expected_scope or value['qualification']!='NOMINAL_SAMPLED_HELD_GRID_NOT_CONTINUOUS_ECLIPSE_OR_EVENT_TIME':raise ValueError('selected lighting authority/units/role/scope')
    t={n:_hex_rational(value[n]) for n in ('start_seconds','end_seconds','covered_seconds','illuminated_seconds','occulted_seconds','unresolved_seconds')}
    integer(value['selected_commits'],'selected lighting commits',0,2**56)
    if any(q<0 for q in t.values()) or t['end_seconds']<t['start_seconds'] or t['covered_seconds']!=t['end_seconds']-t['start_seconds'] or sum(t[n] for n in ('illuminated_seconds','occulted_seconds','unresolved_seconds'))!=t['covered_seconds'] or (t['covered_seconds']==0)!=(value['selected_commits']==0):raise ValueError('selected lighting exact nonnegative partition')
    if start is not None and t['start_seconds']!=start:raise ValueError('lighting original anchor disagreement')
    if clock is not None and t['end_seconds']>clock:raise ValueError('lighting consumed future support')
    if role=='ACTUAL':
        if root_method in (METHOD53,METHOD55) and clock is not None and t['end_seconds']!=clock:raise ValueError('actual lighting must cover current committed prefix')
        if root_method==METHOD and (t['covered_seconds']!=0 or value['selected_commits']!=0):raise ValueError('legacy lifecycle declares only empty untracked lighting prefix')
    return t


def _world_accounting(value,role,*,root_method=METHOD,start=None,clock=None):
    counters=('controls','lookups','guards','sun_queries','lighting_evaluations','lighting_evictions','retained_lighting','peak_lighting_records','lighting_grid_seconds')
    if type(value) is not dict:raise ValueError('world accounting object required')
    extended=value.get('api')=='B54_LIFECYCLE_WORLD_ACCOUNTING_V2'
    object_fields(value,('api','identity','role','mode',*counters,'original_anchor','sun_authority','qualification',*(('lighting_consumption','lighting_tracking') if extended else ())))
    identity(value['identity']);anchor=_hex_rational(value['original_anchor'])
    if value['api'] not in ('B52_NOMINAL_LIFECYCLE_WORLD_V1','B54_LIFECYCLE_WORLD_ACCOUNTING_V2') or value['role']!=role or value['mode']!='NOMINAL_LONG' or value['sun_authority'] not in ('FULL_DOMAIN_SUPPLIED_TABLE','B52_ASSUMED_CIRCULAR_ANNUAL_SUN_V1') or value['qualification']!='NOMINAL_SAMPLED_NOT_CONTINUOUS_OR_PHYSICALLY_CALIBRATED':raise ValueError('lifecycle world accounting role/method')
    if anchor<0 or start is not None and anchor!=start:raise ValueError('world original anchor mismatch')
    for name in counters:integer(value[name],name,0,2**56)
    integer(value['lighting_grid_seconds'],'world lighting grid',1,120)
    if value['retained_lighting']>value['peak_lighting_records'] or value['retained_lighting']+value['lighting_evictions']>value['lighting_evaluations']:raise ValueError('world lighting cache accounting balance')
    if not extended and root_method!=METHOD:raise ValueError('new lifecycle requires versioned lighting accounting')
    if extended:
        if value['lighting_tracking']!='ONLY_EXPLICIT_SELECTED_SUPPORT_COMMITS':raise ValueError('lighting consumption tracking semantics')
        _lighting_accounting(value['lighting_consumption'],role,root_method=root_method,start=start,clock=clock)


def _service_partial_view(root,report,context,checkpoint):
    """Copied observational row; the native continuation report stays ACTIVE."""
    if root.method!=METHOD55 or context.simulation_time_seconds>=root.end_seconds:return None
    from .lifecycle_report import LifecycleReport,COUNTS
    current=report.state['current']
    if current is not None and current['end_seconds']==current['start_seconds'] and not any(current[name] for name in COUNTS) and report.state['sealed_totals'] is None:return None
    view=LifecycleReport(root,context,state=deepcopy(report.state))
    row=view.seal_partial_terminal(context) if view.state['status']=='ACTIVE' else None
    return dict(format='B55_OBSERVATIONAL_PARTIAL_TERMINAL_REPORT_V1',root_identity=root.identity,
        clock=context.simulation_time_seconds,native_checkpoint_sha256=checkpoint['sha256'],
        scope='COPIED_REPORT_VIEW_NOT_NATIVE_CONTINUATION_STATE',row=row,report=view.summary(),
        row_status='COPIED_ACTUAL_CURRENT_ROW' if row is not None else 'ALREADY_SEALED_BY_CAUSAL_OWNER_NO_DUPLICATE_ROW')


def _admit_service_partial_view(root,directory,manifest,checkpoint,clock):
    if manifest is None:return
    from .lifecycle_report import validate_report_summary,validate_partial_report_row
    object_fields(manifest,('file','sha256','bytes'));identity(manifest['sha256']);integer(manifest['bytes'],'partial report bytes',1,MAX_METADATA)
    if manifest['file']!='partial-terminal-row.json':raise ValueError('known observational partial report filename')
    path=directory/manifest['file']
    if path.stat().st_size!=manifest['bytes'] or file_sha(path)!=manifest['sha256']:raise ValueError('partial report file bytes/SHA')
    value=_read(path)
    object_fields(value,('format','root_identity','clock','native_checkpoint_sha256','scope','row','report','row_status'))
    if value['format']!='B55_OBSERVATIONAL_PARTIAL_TERMINAL_REPORT_V1' or value['root_identity']!=root.identity or type(value['clock']) is not int or value['clock']!=clock or value['native_checkpoint_sha256']!=checkpoint['sha256'] or value['scope']!='COPIED_REPORT_VIEW_NOT_NATIVE_CONTINUATION_STATE':raise ValueError('observational partial report native/root/clock binding')
    validate_report_summary(root,value['report'],clock)
    if value['row'] is not None:
        if value['row_status']!='COPIED_ACTUAL_CURRENT_ROW':raise ValueError('partial row publication scope')
        validate_partial_report_row(root,value['row'],clock)
    elif value['row_status']!='ALREADY_SEALED_BY_CAUSAL_OWNER_NO_DUPLICATE_ROW' or value['report']['sealed_count']==0:
        raise ValueError('missing computed partial row authority')


def _admit_service_terminal_reports(root,job,result,directory):
    """Source-fixed B55 report admission; no checkpoint or physics replay."""
    if root.method!=METHOD55:return
    from .lifecycle_report import validate_report_summary
    if result.get('method')!=METHOD55:raise ValueError('terminal service method binding')
    clock=integer(result['clock'],'service terminal clock',root.start_seconds,root.end_seconds)
    expected_start=root.start_seconds if job['resume'] is None else job['resume']['checkpoint']['clock']
    if type(result['start_clock']) is not int or result['start_clock']!=expected_start:raise ValueError('service terminal selected native prefix')
    validate_report_summary(root,result['report'],clock)
    _admit_service_partial_view(root,directory,result['partial_terminal_report'],result['checkpoint'],clock)
    window=result['window_report']
    if job['intent']['mode']=='MAIN':
        if window is not None:raise ValueError('MAIN cannot import a diagnostic suffix report')
    else:
        if type(window) is not dict or window.get('scope')!='DIAGNOSTIC_SUFFIX_ONLY_CARRY_IN_CREDITS_NOT_ADDED_TO_MAIN':raise ValueError('diagnostic report published scope')
        ordinary=dict(window);ordinary['scope']='WINDOW'
        validate_report_summary(root,ordinary,clock,window=True)
        if ordinary['start_seconds']!=expected_start:raise ValueError('diagnostic report must start at selected native checkpoint')


def _production_execution_mode(root):
    from .lifecycle_admission import BASELINE,COMPILED
    if type(PRODUCTION_EXECUTION_MODE) is not str or PRODUCTION_EXECUTION_MODE not in (BASELINE,COMPILED):
        raise ValueError('source-pinned lifecycle static admission mode')
    return PRODUCTION_EXECUTION_MODE if root.method in (METHOD53,METHOD55) else BASELINE


def _static_admission_snapshot(state):
    """Pure paid wrapper snapshot, outside all scientific/report projections."""
    if state is None or state.compiled_context is None:return None
    return state.compiled_context.to_data()


def _static_admission_accounting(value,job,*,required=False):
    if value is None:
        if required:raise ValueError('compiled lifecycle wrapper accounting required')
        return None
    from .lifecycle_admission import validate_wrapper_data
    validate_wrapper_data(value)
    if value['root_identity']!=job['root_identity'] or value['source_identity']!=job['source_identity']:
        raise ValueError('terminal static-admission wrapper root/source binding')
    return value


def _merge_static_admission_work(state,selected_prior,whole_parent):
    """Carry ALL settled-parent wrapper costs, adding fresh restore work once.

    The selected native state controls science. Its process-local wrapper
    counters are observational only and must not refund later parent work.
    Compute and admit both roles before mutating either live ledger.
    """
    current=_static_admission_snapshot(state)
    if current is None:
        if selected_prior is not None or whole_parent is not None:raise ValueError('baseline cannot inherit compiled wrapper authority')
        return None
    binding=dict(root_identity=state.root.identity,source_identity=state.compiled_context.source_identity)
    _static_admission_accounting(selected_prior,binding,required=True)
    _static_admission_accounting(whole_parent,binding,required=True)
    merged=deepcopy(current);delta={}
    for role in ('actual','forecast'):
        delta[role]={}
        for name,value in current[role].items():
            additional=value-selected_prior[role][name]
            if additional<0 or whole_parent[role][name]<selected_prior[role][name]:raise ValueError('static-admission lineage counter refund')
            delta[role][name]=additional
            merged[role][name]=whole_parent[role][name]+additional
    _static_admission_accounting(merged,binding,required=True)
    for role in ('actual','forecast'):
        ledger=getattr(state.compiled_context,role).work
        ledger.clear();ledger.update(merged[role])
    return dict(method='B54_EXACT_WHOLE_PARENT_STATIC_ADMISSION_MERGE_V1',
        scope='OBSERVATIONAL_WRAPPER_WORK_ONLY_NO_SCIENTIFIC_RUNTIME_WORK_CHANGE',
        selected_prior=deepcopy(selected_prior),whole_settled_parent=deepcopy(whole_parent),
        fresh_restore_delta=delta,merged=deepcopy(merged))


def _valid_owned_cleanup(cleanup,*,strict=False):
    if type(cleanup) is not dict:return False
    flags=('owned_job_empty','root_signaled','root_status_captured','handles_closed','cleanup_within_two_seconds')
    valid=(all(cleanup.get(name)is True for name in flags) and type(cleanup.get('errors'))is list and not cleanup['errors']
        and type(cleanup.get('root_exit_code'))is int and -(2**32)<=cleanup['root_exit_code']<2**32)
    if not valid or not strict:return valid
    if cleanup.get('root_reaped')is not True:return False
    names=('cleanup_started_monotonic','cleanup_wall_seconds','cleanup_deadline_monotonic')
    if any(type(cleanup.get(name))not in(int,float)or not math.isfinite(cleanup[name])or cleanup[name]<0 for name in names):return False
    start,wall,end=(cleanup[name]for name in names)
    if not 0<=wall<=2 or not start<=end or start+wall>end:return False
    if 'cleanup_within_deadline'in cleanup and cleanup['cleanup_within_deadline']is not True:return False
    return True


class LifecycleRunner:
    def __init__(self,store,*,job_factory=None,on_launch=None,on_finish=None):
        self.store=store;self.factory=job_factory;self.on_launch=on_launch;self.on_finish=on_finish
        self.lock=threading.RLock();self.active=None;self.thread=None;self.stop_event=threading.Event();self.closing=False
        self.lease=None;self.owned_authority=None;self.application_quarantined=False;self.parent_errors=[];self._last_job_id=None;self._active_execution_seconds=0
    def _claim_dispatch(self):
        if (self.application_quarantined or getattr(self.store,'_lifetime_retirement_failed',False)
                or getattr(self.store,'_lifetime_publications_closed',False)
                or self.store.path('dispatch-quarantine.json').exists()):raise ValueError('lifecycle application outcome quarantined; no new dispatch')
        value=dict(format='B52_EXCLUSIVE_DISPATCH_OWNER_V1',owner=uuid.uuid4().hex,PID=os.getpid(),source_identity=self.store.source_identity)
        try:_write_new(self.store.path('dispatch-owner.json'),value)
        except FileExistsError:raise ValueError('existing lifecycle dispatch owner requires reconciliation; no PID control or automatic retry') from None
        self.lease=value
        self.store._year_v3_dispatch_owner=value
    def _release_dispatch(self):
        if self.lease is None:return
        path=self.store.path('dispatch-owner.json')
        if _read(path)!=self.lease:raise RuntimeError('foreign lifecycle dispatch token; preserve it')
        path.unlink();self.lease=None
        from .lifetime_physical_storage import retire_producer_path
        retire_producer_path(path)
        self.store._year_v3_dispatch_owner=None
    def _parent_error(self,jid,stage,error,*,traceback_text='',secondary=()):
        """Independent bounded evidence; never retry a failed status writer."""
        receipt=None;reporting=[]
        try:receipt=self.store.parent_error(jid,stage,error,traceback_text=traceback_text,secondary=secondary)
        except BaseException as reporting_error:reporting.append(reporting_error)
        row=dict(stage=stage,primary_type=type(error).__name__,primary_message=str(error)[:1024],
            traceback_sha256=sha256(traceback_text.encode('utf-8')).hexdigest(),receipt=receipt,
            secondary=[dict(type=type(e).__name__,message=str(e)[:512])for e in (*secondary,*reporting)])
        if len(self.parent_errors)<8:self.parent_errors.append(row)
        return receipt
    def _quarantine_application(self,jid,error):
        self.application_quarantined=True
        path=self.store.path('dispatch-quarantine.json')
        if path.exists():return
        value=dict(format='B63_UNSETTLED_APPLICATION_DISPATCH_QUARANTINE_V1',job_id=jid,
            root_identity=self.store.meta['root_identity'],source_identity=self.store.meta['source_identity'],
            reason_sha256=sha256(str(error).encode('utf-8')).hexdigest(),
            scientific_authority=False,automatic_replay=False)
        try:_write_new(path,value,4096)
        except BaseException as secondary:self._parent_error(jid,'QUARANTINE_EVIDENCE',error,secondary=(secondary,))
    def _owned_valid(self,jid):
        authority=self.owned_authority
        if authority is None or authority['job_id']!=jid or authority['dispatch_token']!=self.lease:return False
        if authority['launch_attempted'] is False:return True
        return authority['ownership_valid'] is True
    def _remember_cleanup(self,jid,cleanup,valid):
        authority=self.owned_authority
        if authority is None or authority['job_id']!=jid or authority['dispatch_token']!=self.lease:raise RuntimeError('foreign in-memory owned cleanup authority')
        authority.update(cleanup=deepcopy(cleanup),ownership_valid=bool(valid))
    def submit(self,intent):
        with self.lock:
            from .lifetime_typed_portable import store_contract_operation
            with store_contract_operation(self.store,Path(__file__).resolve().parents[2],operation='RUNNER_SUBMIT_PREFLIGHT'):
                if self.closing:raise ValueError('lifecycle dispatch closed')
                from .lifetime_execution_authority import admit_public_execution
                admit_public_execution(self.store)
                old=self.store.reconcile(intent)
                if old is not None:return old
                if self.active is not None:raise ValueError('one owned lifecycle worker at a time')
                if self.thread is not None:
                    if self.thread.is_alive():raise ValueError('YEAR-V3 existing thread still alive')
                    self.thread=None
                self._claim_dispatch()
                try:job,new=self.store.prepare_job(intent)
                except BaseException:self._release_dispatch();raise
                if not new:self._release_dispatch();return job
                self._last_job_id=job['job_id'];self._active_execution_seconds=job['intent']['execution_seconds']
                self.owned_authority=dict(job_id=job['job_id'],dispatch_token=deepcopy(self.lease),launch_attempted=False,
                    handle=None,cleanup=None,ownership_valid=False,application_settled=False)
                from . import lifetime_no_launch as no_launch
                try:no_launch.begin(self,job)
                except BaseException as error:
                    self._quarantine_application(job['job_id'],error);raise
            if self.on_launch is not None:
                try:self.on_launch(deepcopy(job)if no_launch.enabled(self.store.runner_policy)else job)
                except BaseException as error:
                    if no_launch.enabled(self.store.runner_policy):
                        try:no_launch.refuse(self,job,error)
                        except BaseException as publication_error:
                            self._quarantine_application(job['job_id'],publication_error)
                            self._parent_error(job['job_id'],'NO_LAUNCH_PUBLICATION_FAILURE',error,secondary=(publication_error,))
                            raise publication_error from error
                    else:
                        job['status']='REFUSED';job['reason']='BEFORE_OWNED_LAUNCH:'+str(error);job['ownership_valid']=True;self.store.update_job(job);self._release_dispatch()
                    raise
            no_launch.attempt(self,job)
            self.active=job['job_id'];self.stop_event.clear()
            self.thread=threading.Thread(target=self._run,args=(job,),name='B52-owned-'+job['job_id'],daemon=False)
            try:self.thread.start()
            except BaseException as error:
                if no_launch.enabled(self.store.runner_policy):
                    job.update(status='UNKNOWN',ownership_valid=False,reason='THREAD_START_ATTEMPT_UNKNOWN')
                    self.store.update_job(job);self._quarantine_application(job['job_id'],error)
                    raise
                self.active=None;job['status']='REFUSED';job['ownership_valid']=True;job['reason']='PARENT_THREAD_NOT_STARTED';self.store.update_job(job);self._release_dispatch();raise
            return self.store.job(job['job_id'])
    def stop(self,jid):
        with self.lock:
            job=self.store.job(jid)
            if jid!=self.active:
                if job['status'] in TERMINAL:return job
                raise ValueError('no owned lifecycle handle')
            marker=self.store.path('jobs',jid,'stop-request.json')
            if not marker.exists():_write_stop_request(marker,job)
            else:
                previous=_read(marker)
                if previous.get('format')!='B52_COOPERATIVE_STOP_REQUEST_V1' or previous.get('job_id')!=jid or previous.get('root_identity')!=job['root_identity']:raise ValueError('foreign stop marker; preserve it')
            self.stop_event.set();job['status']='STOP_REQUESTED';self.store.update_job(job)
            return job
    def _run(self,job):
        try:self._execute(job)
        except BaseException as error:
            primary_trace=traceback.format_exc();jid=job['job_id'];secondary=[];valid=self._owned_valid(jid)
            if self.owned_authority is not None and self.owned_authority.get('application_settled')is True:
                # A later token/callback/reporting failure cannot rewrite an
                # already committed scientific/application terminal.
                self._parent_error(jid,'AFTER_COMMITTED_TERMINAL_PARENT_ERROR',error,traceback_text=primary_trace)
                self._quarantine_application(jid,error)
                return
            try:
                latest=self.store.job(jid);latest['status']='PROCESS_FAILED' if valid else 'UNKNOWN'
                latest['ownership_valid']=bool(valid);latest['reason']='PARENT_LIFECYCLE_FAILURE:'+str(error)[:512]
                latest['parent_failure']=primary_trace
                if is_typed_campaign_policy(self.store.runner_policy) and latest['result']is None:
                    from .battery_terminal import make_terminal
                    latest['typed_stop']=make_terminal('PROCESS_FAILURE' if valid else 'UNKNOWN',latest['reason'][:400],'PARENT_EXCEPTION','lifecycle_application',None)
                writer=self.store._status_writers.get(jid)
                if writer is not None and getattr(writer,'failed',False):raise ValueError('failed status writer quarantined; no second publication')
                self.store.update_job(latest)
            except BaseException as reporting_error:secondary.append(reporting_error)
            self._parent_error(jid,'PARENT_APPLICATION_FAILURE',error,traceback_text=primary_trace,secondary=secondary)
            self._quarantine_application(jid,error)
            with self.lock:
                if valid:
                    try:self._release_dispatch();self.active=None
                    except BaseException as release_error:self._parent_error(jid,'MATCHING_TOKEN_RELEASE',error,secondary=(release_error,))
    def _execute(self,job):
        from .finite_campaign import FiniteCampaignPolicy
        from .lifetime_policy import is_v2
        directory=self.store.path('jobs',job['job_id']);request=directory/'request.json'
        command=[sys.executable,'-B','-m','ops_sim.v5.lifecycle_application','worker','--store',str(self.store.directory),'--job',job['job_id'],'--request-sha256',file_sha(request)]
        output_policy=self.store.root_input.output_policy
        reader=ProgressReader(directory/('progress.jsonl' if output_policy is None else 'progress53'),job,self.store.root_input.policy.max_journal_bytes,output_policy=output_policy,method=self.store.root_input.method,service_policy_identity=None if self.store.root_input.service_policy is None else self.store.root_input.service_policy.identity,solar_root=self.store.root_input if self.store.root_input.energy_attitude_policy is not None else None,environment_root=self.store.root_input if self.store.root_input.environment_ageing_policy is not None else None,battery_root=self.store.root_input if self.store.root_input.battery_port_policy is not None else None,read_charge=lambda n:self.store._parent_codec_charge(job['job_id'],n))
        cleanup_deadline=None;logpipes=None
        child=None;cleanup=None;worker_identity=None;seen=set();unexpected=None;terminal=None;failure_record=None;stopped=False;timed_out=False;launch_attempted=False;forced_stop=False;stop_grace_deadline=None
        start=time.perf_counter();last_publication=start
        launch=dict(command=command,started_utc=_utc(),execution_seconds=job['intent']['execution_seconds'],cleanup_seconds=2)
        def publish_owned_status(status):
            # Stop and the launch thread share this lock. Never overwrite its
            # newer immutable publication or roll STOP_REQUESTED back to RUNNING.
            nonlocal job
            with self.lock:
                current=self.store.job(job['job_id']);job['publication_sequence']=current['publication_sequence']
                job['status']='STOP_REQUESTED' if self.stop_event.is_set() else status
                self.store.update_job(job)
        def finish_logs():
            nonlocal unexpected
            if logpipes is None:return
            try:logpipes.finish(cleanup_deadline)
            except BaseException as error:
                unexpected=unexpected or dict(type=type(error).__name__,reason=str(error),scope='bounded administrative log cleanup')
        def accept(records):
            nonlocal worker_identity,terminal,failure_record,last_publication,job
            changed=False;force=False
            for record in records:
                data=record['data'];kind=record['kind']
                if kind=='identity':worker_identity=data
                elif kind=='boundary':
                    if data['start_seconds']!=self.store.root_input.start_seconds or data['end_seconds']!=self.store.root_input.end_seconds:raise ValueError('lifecycle progress original horizon')
                    job['progress']=data;changed=True
                    action=data.get('last_action')
                    if action is not None and action['status']=='refused':job['last_actual_refusal']=deepcopy(action)
                elif kind=='checkpoint':
                    path=directory/data['file']
                    from .lifecycle_checkpoint import checkpoint_file_bytes
                    from .lifetime_policy import physical_storage
                    checkpoint_file_bytes(path,data,self.store.root_input,require_transport=physical_storage(self.store.runner_policy))
                    _admit_publication(directory,data,self.store.root_input)
                    if any(c['file']==data['file'] for c in job['checkpoints']):raise ValueError('duplicate lifecycle checkpoint publication')
                    if output_policy is not None:self.store.checkpoint_catalog(job['job_id']).append(data)
                    job['checkpoints'].append(data);changed=True;force=True
                    if output_policy is not None:job['checkpoints']=job['checkpoints'][-8:]
                elif kind=='retired_checkpoint':
                    if output_policy is None:
                        object_fields(data,('sha256','reason'));selected=[c for c in job['checkpoints'] if c['sha256']==data['sha256']]
                        if len(selected)!=1:raise ValueError('invalid lifecycle checkpoint retirement')
                        allowed_reason={'WORKING':'DECLARED_LAST_TWO_WORKING_RETENTION'}
                        if self.store.root_input.method==METHOD55:
                            allowed_reason.update({name:'DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS' for name in ('AUDIT_NAMED',*SERVICE_CHECKPOINT_KINDS)})
                        if allowed_reason.get(selected[0]['kind'])!=data['reason']:raise ValueError('invalid lifecycle checkpoint retirement')
                    else:
                        object_fields(data,('sha256','file','reason'));seq=int(Path(data['file']).stem.split('-')[-1])
                        entries=self.store.checkpoint_history(job['job_id'],before=seq+1,limit=1)['entries']
                        if not entries or entries[0]['sequence']!=seq:raise ValueError('retired checkpoint index not found')
                        selected=[entries[0]['checkpoint']]
                        valid_reason={'WORKING':'DECLARED_LAST_TWO_WORKING_RETENTION','AUDIT_NAMED':'DECLARED_LAST_TWO_AUDIT_PREDECESSORS'}
                        if self.store.root_input.method==METHOD55:
                            valid_reason.update({name:'DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS' for name in ('AUDIT_NAMED',*SERVICE_CHECKPOINT_KINDS)})
                        if selected[0]['file']!=data['file'] or selected[0]['sha256']!=data['sha256'] or valid_reason.get(selected[0]['kind'])!=data['reason']:raise ValueError('retired checkpoint catalog binding')
                        self.store.checkpoint_catalog(job['job_id']).retire(seq,data['reason'])
                    # Only this reader retires an already verified immutable
                    # publication. The child never races the reader's hashing.
                    from .lifetime_physical_storage import retire_producer_path
                    for leaf in (selected[0]['file'],selected[0]['publication']['file']):
                        retired_path=self.store.path('jobs',job['job_id'],leaf)
                        retired_path.unlink();retire_producer_path(retired_path)
                    job['checkpoints']=[c for c in job['checkpoints'] if c['file']!=selected[0]['file']];changed=True;force=True
                elif kind in ('completed','stopped'):terminal=(kind,data)
                elif kind=='failure':failure_record=data
            now=time.perf_counter()
            cadence=1 if output_policy is None else output_policy.publication_minimum_wall_seconds
            if changed and (force or now-last_publication>=cadence):
                with self.lock:
                    current=self.store.job(job['job_id']);job['publication_sequence']=current['publication_sequence']
                    if self.stop_event.is_set():job['status']='STOP_REQUESTED'
                    self.store.update_job(job);last_publication=now
        try:
            self.store._pinned();publish_owned_status('ADMITTED')
            factory=self.factory
            if factory is None:
                from .lifecycle_process import owned_factory
                factory=owned_factory()
            from .lifetime_physical_storage import register_producer_path
            temp=directory/'tmp';register_producer_path(temp,kind='DIRECTORY');temp.mkdir()
            from contextlib import ExitStack
            from .lifetime_policy import physical_storage
            with ExitStack() as log_stack:
                if physical_storage(self.store.runner_policy):
                    from .lifetime_bounded_logs import BoundedLogPipes
                    logpipes=BoundedLogPipes(directory)
                    log_stack.callback(logpipes.close_parent_writers)
                    out,err=logpipes.stdout,logpipes.stderr
                else:
                    register_producer_path(directory/'stdout.log');register_producer_path(directory/'stderr.log')
                    out=log_stack.enter_context((directory/'stdout.log').open('xb'))
                    err=log_stack.enter_context((directory/'stderr.log').open('xb'))
                if self.stop_event.is_set():stopped=True
                else:
                    source=Path(__file__).resolve().parents[2]
                    env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(source),TEMP=str(temp),TMP=str(temp),GIT_OPTIONAL_LOCKS='0')
                    authority=self.owned_authority
                    if authority is None or authority['job_id']!=job['job_id'] or authority['dispatch_token']!=self.lease:raise RuntimeError('missing matching parent launch authority')
                    launch_record=dict(format='B63_IMMUTABLE_PARENT_LAUNCH_AUTHORITY_V1',job_id=job['job_id'],root_identity=job['root_identity'],source_identity=job['source_identity'],runtime=job['runtime'],request_sha256=file_sha(request),dispatch_token=deepcopy(self.lease),command=command,started_utc=_utc())
                    from .lifetime_policy import is_v2
                    if is_v2(self.store.runner_policy):
                        launch_raw=_bytes(launch_record);self.store._parent_charge(job['job_id'],len(launch_raw));_write_new(directory/'parent-launch-authority.json',launch_raw,16384)
                    launch_attempted=True;authority['launch_attempted']=True
                    try:
                        child=factory(command,source,env,out,err)
                    finally:
                        if logpipes is not None:logpipes.close_parent_writers()
                    authority['handle']=child;launch.update(root_PID=child.pid,assigned_before_execution=child.assigned_before_resume)
                    publish_owned_status('RUNNING')
                    while True:
                        state=child.state();seen.update(state['job_active_PIDs']);code=child.poll();accept(reader.read())
                        if logpipes is not None:logpipes.check()
                        elif out.tell()+err.tell()>2**20:raise ValueError('lifecycle worker log cap')
                        elapsed=time.perf_counter()-start
                        if self.stop_event.is_set():
                            stopped=True
                            if stop_grace_deadline is None:stop_grace_deadline=min(start+job['intent']['execution_seconds'],time.perf_counter()+(1 if _budget(job['intent']) is None else _budget(job['intent']).finalization_reserve_seconds))
                            if code is not None and state['job_active_count']==0 and not getattr(reader.chunk_reader,'needs_another_poll',False):break
                            if time.perf_counter()>=stop_grace_deadline:forced_stop=True;break
                        if elapsed>=job['intent']['execution_seconds']:timed_out=True;break
                        if code is not None and state['job_active_count']==0 and not getattr(reader.chunk_reader,'needs_another_poll',False):break
                        time.sleep(min(.1,max(0,job['intent']['execution_seconds']-elapsed)))
                    cleanup_deadline=time.perf_counter()+2
                    cleanup=child.reap(kill=forced_stop or timed_out,max_seconds=2,cleanup_deadline=cleanup_deadline)
                    finish_logs()
                    if self.store.path('portable-execution.json').exists():
                        _write_new(directory/'backend-settlement.json',dict(format='B60_DURABLE_BACKEND_SETTLEMENT_V1',job_id=job['job_id'],root_identity=job['root_identity'],source_identity=job['source_identity'],launch_command=command,root_launch_PID=child.pid,worker_identity=worker_identity,owned_seen_PIDs=sorted(seen),execution_start_monotonic=start,envelope_to_completed_cleanup_seconds=cleanup['cleanup_started_monotonic']+cleanup['cleanup_wall_seconds']-start,scope='LAUNCH_TO_COMPLETED_OWNED_CLEANUP_NOT_LATER_PARENT_REPORTING',cleanup=cleanup),32768)
        except BaseException as error:
            unexpected=dict(type=type(error).__name__,reason=str(error),traceback=traceback.format_exc())
            if hasattr(error,'owned_cleanup'):
                unexpected['owned_launch_cleanup']=error.owned_cleanup
                cleanup_deadline=error.owned_cleanup.get('cleanup_deadline_monotonic')
                if type(cleanup_deadline)not in(int,float)or not math.isfinite(cleanup_deadline):cleanup_deadline=time.perf_counter()
                finish_logs()
                if _valid_owned_cleanup(error.owned_cleanup,strict=is_v2(self.store.runner_policy)):cleanup=error.owned_cleanup
                if self.store.path('portable-execution.json').exists():
                    try:_write_new(directory/'backend-launch-failure.json',dict(format='B60_DURABLE_FAILED_LAUNCH_V1',job_id=job['job_id'],cleanup=error.owned_cleanup),16384)
                    except BaseException as reporting_error:unexpected['cleanup_receipt_error']=repr(reporting_error)
            if child is not None and not child.closed:
                if cleanup_deadline is None:cleanup_deadline=time.perf_counter()+2
                cleanup=child.reap(kill=True,max_seconds=2,cleanup_deadline=cleanup_deadline)
                finish_logs()
        finally:
            if logpipes is not None:
                if cleanup_deadline is None:cleanup_deadline=time.perf_counter()+2
                if not logpipes.snapshot()['readers_joined']:finish_logs()
                try:_write_new(directory/'bounded-log-capture.json',logpipes.snapshot(),16384)
                except BaseException as error:
                    unexpected=unexpected or dict(type=type(error).__name__,reason=str(error),scope='bounded administrative log evidence')
            if self.store.path('portable-execution.json').exists() and cleanup is not None and not (directory/'backend-settlement.json').exists():
                try:_write_new(directory/'backend-settlement.json',dict(format='B60_DURABLE_BACKEND_SETTLEMENT_V1',job_id=job['job_id'],root_identity=job['root_identity'],source_identity=job['source_identity'],launch_command=command,root_launch_PID=child.pid,worker_identity=worker_identity,owned_seen_PIDs=sorted(seen),execution_start_monotonic=start,envelope_to_completed_cleanup_seconds=cleanup['cleanup_started_monotonic']+cleanup['cleanup_wall_seconds']-start,scope='LAUNCH_TO_COMPLETED_OWNED_CLEANUP_NOT_LATER_PARENT_REPORTING',cleanup=cleanup),32768)
                except BaseException as error:unexpected=unexpected or dict(type=type(error).__name__,reason=str(error),scope='durable backend settlement')
            try:accept(reader.read())
            except BaseException as error:unexpected=unexpected or dict(type=type(error).__name__,reason=str(error),scope='final reader')
            if output_policy is not None and child is not None and cleanup is not None and cleanup['root_exit_code'] in (0,1):
                try:verify_stream(directory/'progress53',policy=output_policy)
                except BaseException as error:unexpected=unexpected or dict(type=type(error).__name__,reason=str(error),scope='final chunked telemetry integrity')
            valid=_valid_owned_cleanup(cleanup,strict=is_v2(self.store.runner_policy))
            if child is None and not launch_attempted:valid=True
            if logpipes is not None:
                capture=logpipes.snapshot()
                if capture['readers_joined']is not True or capture['errors']or capture['truncated']:valid=False
            if worker_identity is not None and worker_identity['worker_PID'] not in seen:valid=False
            self._remember_cleanup(job['job_id'],cleanup,valid)
            admitted_result=None;terminal_error=None
            if terminal is not None and not reader.tail and cleanup is not None and cleanup['root_exit_code']==0:
                try:
                    kind,record=terminal;path=directory/'terminal.json'
                    if file_sha(path)!=record['terminal_sha256']:raise ValueError('lifecycle terminal hash')
                    admitted_result=_read(path)
                    if admitted_result['job_id']!=job['job_id'] or admitted_result['root_identity']!=job['root_identity'] or admitted_result['clock']!=record['clock']:raise ValueError('lifecycle terminal binding')
                    _admit_execution_terminal(job,admitted_result)
                    _admit_backend_terminal(self.store,job,admitted_result)
                    from .finite_campaign import FiniteCampaignPolicy
                    if is_typed_campaign_policy(self.store.runner_policy):
                        from .battery_terminal import admit_bound_terminal
                        typed=admit_bound_terminal(admitted_result['typed_terminal'],job,admitted_result)
                        from .lifecycle_checkpoint import admit_checkpoint,checkpoint_file_bytes
                        from .lifetime_policy import physical_storage
                        from .battery_terminal import admit_native_terminal
                        cp=admitted_result['checkpoint']
                        cp_raw=checkpoint_file_bytes(directory/cp['file'],cp,self.store.root_input,require_transport=physical_storage(self.store.runner_policy))
                        doc=admit_checkpoint(cp_raw,self.store.root_input,cp['sha256'],cp['bindings'])
                        admit_native_terminal(doc,typed,admitted_result)
                    _admit_service_terminal_reports(self.store.root_input,job,admitted_result,directory)
                    _static_admission_accounting(admitted_result['static_admission_wrapper'],job,
                        required=_production_execution_mode(self.store.root_input)!='BASELINE')
                    _settled_publication_work(directory,self.store.root_input,job,admitted_result)
                    if file_sha(directory/admitted_result['endpoint']['file'])!=admitted_result['endpoint']['sha256']:raise ValueError('lifecycle endpoint publication SHA')
                    if output_policy is not None:
                        manifests=object_fields(admitted_result['streams'],('events','months','details'))
                        for name,manifest in manifests.items():
                            self.store._reserve_saved_read(job['job_id'],manifest['work']['bytes_published'])
                            verified=verify_stream(directory/(name+'53'),manifest,output_policy)
                            if verified['records']!=manifest['records']:raise ValueError('terminal scientific stream count')
                except BaseException:
                    admitted_result=None;terminal_error=traceback.format_exc()
            failure_paid_prefix=False
            if failure_record is not None and not reader.tail and cleanup is not None and cleanup['root_exit_code']!=0:
                try:
                    saved_failure=_read(directory/'failure.json');cp=saved_failure['last_checkpoint']
                    if saved_failure['updated_paid_prefix_checkpoint'] is not True or saved_failure['failure_prefix_publication_error'] is not None or cp!=failure_record['last_checkpoint'] or cp['kind']!='FAILURE_PAID_PREFIX' or cp not in job['checkpoints']:raise ValueError('failure paid-prefix binding')
                    _static_admission_accounting(saved_failure['static_admission_wrapper'],job,
                        required=_production_execution_mode(self.store.root_input)!='BASELINE')
                    _admit_failure_publication(directory,cp,self.store.root_input,saved_failure,job)
                    failure_paid_prefix=True
                except BaseException:
                    unexpected=unexpected or dict(type='FailurePrefixAdmissionError',reason='failure paid-prefix not established',traceback=traceback.format_exc())
            cooperative_stop=bool(admitted_result is not None and admitted_result['application_status'] in ('INCOMPLETE_STOP','INCOMPLETE_BUDGET_STOP'))
            # A validated terminal or caught-error paid prefix is the only
            # authority for all work spent before child exit. A prior periodic
            # checkpoint alone cannot account for an interrupted native suffix.
            forced_interruption=bool(child is not None and (forced_stop or timed_out or unexpected is not None or admitted_result is None and not failure_paid_prefix))
            launch.update(cleanup=cleanup,worker_identity=worker_identity,owned_seen_PIDs=sorted(seen),ownership_valid=bool(valid),
                stopped=stopped,timeout=timed_out,incomplete_tail_bytes=len(reader.tail),reader_sequence=reader.sequence,unexpected=unexpected,
                cooperative_stop=cooperative_stop,forced_interruption=forced_interruption,stop_grace_seconds=1 if _budget(job['intent']) is None else _budget(job['intent']).finalization_reserve_seconds,
                native_work_after_last_checkpoint='UNKNOWN' if forced_interruption else 'PRESERVED_BY_VALIDATED_TERMINAL_PAID_PREFIX' if admitted_result is not None else 'PRESERVED_BY_VALIDATED_FAILURE_PAID_PREFIX' if failure_paid_prefix else 'NO_CHILD_EXECUTED',
                observed_envelope_seconds=time.perf_counter()-start,ended_utc=_utc())
            if is_typed_campaign_policy(self.store.runner_policy):
                receipt=dict(format='B59_PARENT_OWNED_SETTLEMENT_V1',job_id=job['job_id'],root_identity=job['root_identity'],launch=launch)
                encoded=_bytes(receipt)
                if len(encoded)+PARENT_COST.size>65536:raise ValueError('bounded owned settlement receipt')
                self.store._parent_charge(job['job_id'],len(encoded))
                _write_new(directory/'owned-settlement.json',encoded,65536-PARENT_COST.size)
            with self.lock:
                latest=self.store.job(job['job_id']);job['publication_sequence']=latest['publication_sequence']
                job['launch']=launch;job['ownership_valid']=bool(valid)
                job['worker_artifact_bytes']=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file() and not {'status','tmp'}.intersection(p.relative_to(directory).parts))
                if admitted_result is not None:job['result']=admitted_result
                if not valid:job['status']='UNKNOWN';job['reason']='OWNERSHIP_CLEANUP_UNRESOLVED'
                elif terminal_error is not None:job['status']='PROCESS_FAILED';job['reason']='TERMINAL_ADMISSION_FAILED';job['terminal_failure']=terminal_error
                elif stopped:
                    if admitted_result is not None and terminal[0]=='completed':job['status']='COMPLETED';job['reason']='STOP_ARRIVED_AFTER_SUPPORTED_ENDPOINT'
                    else:job['status']='CANCELLED';job['reason']='COOPERATIVE_STOP_PAID_PREFIX_SAVED' if cooperative_stop else 'FORCED_STOP_PAID_SUFFIX_UNKNOWN' if forced_interruption else 'STOP_BEFORE_CHILD_OR_AFTER_SETTLED_PREFIX'
                elif timed_out:job['status']='INCOMPLETE';job['reason']='EXECUTION_DEADLINE_NO_ENDPOINT'
                elif unexpected:job['status']='PROCESS_FAILED';job['reason']=unexpected['reason']
                elif cleanup['root_exit_code']!=0:job['status']='PROCESS_FAILED';job['reason']='WORKER_EXIT_'+str(cleanup['root_exit_code'])
                elif terminal is None or reader.tail:job['status']='INCOMPLETE';job['reason']='NO_VALID_TERMINAL_PUBLICATION'
                else:
                    if admitted_result is not None:job['status']='COMPLETED' if terminal[0]=='completed' else 'INCOMPLETE';job['reason']=admitted_result.get('reason')
                    else:job['status']='PROCESS_FAILED';job['reason']='TERMINAL_ADMISSION_FAILED';job['terminal_failure']=terminal_error
                if is_typed_campaign_policy(self.store.runner_policy):
                    from .battery_terminal import make_terminal,admit_bound_terminal
                    if admitted_result is not None:
                        job['typed_stop']=admit_bound_terminal(admitted_result['typed_terminal'],job,admitted_result)
                        job['reason']=job['typed_stop']['code']
                        if job['typed_stop']['kind']in ('PHYSICAL','MODEL','UNSUPPORTED'):job['status']='INCOMPLETE'
                    else:job['typed_stop']=make_terminal('UNKNOWN' if job['status']=='UNKNOWN' else 'PROCESS_FAILURE',str(job['reason'])[:400],'OWNED_PROCESS_SETTLEMENT','lifecycle_application',None)
                self.store.update_job(job)
                self.owned_authority['application_settled']=True
                if valid:self._release_dispatch();self.active=None
                from .lifetime_policy import is_v2
                if valid and is_v2(self.store.runner_policy):self.store.retire_lifetime_job(job['job_id'])
            if self.on_finish is not None:
                try:self.on_finish(job)
                except BaseException as callback_error:self._parent_error(job['job_id'],'AFTER_COMMITTED_TERMINAL_CALLBACK',callback_error,traceback_text=traceback.format_exc())
    def close(self):
        errors=[]
        with self.lock:
            self.closing=True;thread=self.thread
            try:
                if self.active is not None and thread is not None and thread.is_alive():self.stop(self.active)
            except BaseException as error:errors.append(error)
            self.stop_event.set()
        if thread is not None:
            wait=max(5,self._active_execution_seconds+3) if self.active is not None else 5
            thread.join(wait)
        if thread is not None and thread.is_alive() or self.active is not None:errors.append(RuntimeError('lifecycle owned shutdown unresolved'))
        try:self.store.close_publications()
        except BaseException as error:errors.append(error)
        if self.application_quarantined:errors.append(RuntimeError('lifecycle application outcome quarantined'))
        if errors:
            failure=RuntimeError('lifecycle close failures: '+'; '.join(repr(e)for e in errors));failure.close_failures=errors
            if self._last_job_id is not None:self._parent_error(self._last_job_id,'BEST_EFFORT_CLOSE',errors[0],secondary=errors[1:8])
            raise failure from errors[0]


class LifecycleWorkspace:
    """Small root registry; one owned runner across all immutable roots."""
    def __init__(self,directory,project_store=None):
        self.directory=Path(directory).absolute();self.projects=project_store;self.lock=threading.RLock();self.stores={};self.runners={};self.chains={};self.chain_threads={};self.selected=None
        ProjectStore._reject_links(self.directory)
        if any((p/'.git').exists() for p in (self.directory,*self.directory.parents)):raise ValueError('external lifecycle workspace required')
        self.directory.mkdir(parents=True,exist_ok=True)
        from .lifetime_physical_storage import workspace_physical_entries,binding_for_store
        from .lifetime_policy import physical_storage
        physical_entries,physical_bindings=workspace_physical_entries(self.directory)
        for path in sorted(self.directory.iterdir()):
            if path.name in physical_entries:continue
            if not path.is_dir():raise ValueError('unknown lifecycle workspace artifact')
            identity(path.name)
            if len(self.stores)>=16:raise ValueError('lifecycle root population')
            store=LifecycleStore(path)
            expected=physical_bindings.get(path.name)
            if physical_storage(store.runner_policy)!=(expected is not None) or expected is not None and binding_for_store(store)!=expected:
                raise ValueError('YEAR-V4 workspace physical store/source/input binding; no migration')
            self.stores[path.name]=store
            for job in store.jobs():
                if job['status'] not in TERMINAL:
                    if 'storage_view' in job:job=store.job(job['job_id'])
                    job['status']='UNKNOWN';job['reason']='REOPEN_HAS_NO_RECONSTRUCTIBLE_OWNERSHIP_HANDLE';job['ownership_valid']=False
                    from .finite_campaign import FiniteCampaignPolicy
                    if is_typed_campaign_policy(store.runner_policy):
                        from .battery_terminal import make_terminal
                        job['typed_stop']=make_terminal('UNKNOWN',job['reason'],'REOPEN_WITHOUT_OWNED_HANDLE','lifecycle_application',None)
                        # No reconstructible private Job handle: expose a read-only
                        # UNKNOWN view, never rewrite history or invent an endpoint.
                        store._cache[job['job_id']]=job
                    elif store.root_input.output_policy is None:store.update_job(job)
                    else:store._cache[job['job_id']]=job
    @property
    def active(self):
        active=next((r.active for r in self.runners.values() if r.active is not None),None)
        return active or ('CHAIN_BETWEEN_SETTLED_SEGMENTS' if any(t.is_alive() for t in self.chain_threads.values()) else None)
    def store(self,rid):
        identity(rid)
        if rid not in self.stores:raise ValueError('foreign lifecycle root')
        return self.stores[rid]
    def create(self,root,*,project=None,runner_policy=None,publication_profile=None,project_document=None):
        with self.lock:
            if root.identity in self.stores:
                store=self.stores[root.identity]
                if store.runner_policy!=runner_policy or store.publication_profile!=publication_profile:raise ValueError('existing immutable root store has another runner policy or publication profile; no migration')
                if project is not None and store.meta['project']!=project:raise ValueError('existing root has another immutable project lineage; no retagging')
                return store.snapshot()
            if len(self.stores)>=16:raise ValueError('lifecycle root population')
            store=LifecycleStore(self.directory/root.identity,root,create=True,project=project,runner_policy=runner_policy,publication_profile=publication_profile,project_document=project_document);self.stores[root.identity]=store
            return store.snapshot()
    def create_design_project(self,body,*,execution=None):
        """Compile the authored V2 project and retain its EXACT common mission.

        No UI preset can regenerate its policies, horizon, world or controller.
        Existing runner/Stop/checkpoint/direct-resume routes consume this root.
        """
        from .spacecraft_project_v2 import SpacecraftProjectV2
        from .spacecraft_project_v3 import SpacecraftProjectV3
        from .spacecraft_project import materialize_design_project as materialize_lifecycle_project,constructor_compile_bound
        from .spacecraft_project_document import dumps_project
        from .design_repair import ConstructorLedger
        object_fields(body,('project_id','revision'))
        if execution is not None:
            from .general_project_job import GeneralProjectExecution
            if type(execution)is not GeneralProjectExecution:raise TypeError('explicit general execution option')
            execution.__post_init__()
        if self.projects is None:raise ValueError('no constructor project authority attached')
        with self.lock,self.projects.lock:
            project=self.projects.load(body['project_id'],body['revision'])
            if type(project)not in (SpacecraftProjectV2,SpacecraftProjectV3):raise TypeError('explicit full V2/V3 design project required')
            if self.projects._project_record(body['project_id'])['current_revision']!=body['revision']:raise ValueError('lifecycle requires applied immutable design revision')
            if self.projects.current_preview(body['project_id'],body['revision']) is None:raise ValueError('lifecycle requires paid current design preview')
            for store in self.stores.values():
                lineage=store.meta['project']
                if lineage is not None and lineage.get('format')in ('B66_BOUND_DESIGN_PROJECT_LINEAGE_V1','B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1') and lineage['project_id']==body['project_id'] and lineage['revision']==body['revision']:
                    if execution is not None:
                        from .general_project_job import NATIVE_DOMAIN
                        selected=_read(store.path('portable-execution.json'))
                        if (selected['backend_binding']['selection']!=NATIVE_DOMAIN or
                                _bytes(selected['native_build'])!=execution.build_bytes or
                                store.runner_policy!=execution.policy):
                            raise ValueError('existing project execution binding differs; no migration')
                    store._pinned();return store.snapshot()
            before=dict(self.projects.meta['constructor']);reserved=ConstructorLedger(**before)
            for _ in range(constructor_compile_bound(project)):reserved.reserve()
            self.projects.meta['constructor']=asdict(reserved);self.projects.charge(2**20)
            actual=ConstructorLedger(**before);root,_,_=materialize_lifecycle_project(project,actual)
            if asdict(actual)!=asdict(reserved):raise ValueError('B66 paid design compilation work binding')
            document=dumps_project(project)
            lineage=dict(format='B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'if type(project)is SpacecraftProjectV3 else'B66_BOUND_DESIGN_PROJECT_LINEAGE_V1',project_id=body['project_id'],revision=project.identity,
                title=project.title,source_identity=project.source_identity,specification_identity=project.specification.identity,
                common_identity=project.common.identity,compiled_root_identity=root.identity,
                document_sha256=sha256(document.encode('utf8')).hexdigest())
            if type(project)is SpacecraftProjectV3:
                from .rolling_physics import digest as model_digest
                lineage.update(declaration_identity=project.specification.declaration_identity,thermal_method=project.specification.method,model_identity=model_digest(root.base.model))
            if execution is not None:
                from .general_project_job import create_native_store
                if root.identity in self.stores:raise ValueError('existing immutable root; no backend migration')
                if len(self.stores)>=16:raise ValueError('lifecycle root population')
                store=create_native_store(self.directory/root.identity,root,lineage,document,execution)
                self.stores[root.identity]=store
                return store.snapshot()
            return self.create(root,project=lineage,project_document=document)
    def create_project(self,body):
        from .lifecycle_contract import LifecycleRoot,LifecyclePolicy,LifecycleScenario,MAX_DURATION
        from .spacecraft_project import materialize_project
        from .design_repair import ConstructorLedger
        legacy_fields=('project_id','revision','duration_seconds','policy','scenario','sun_mode')
        runner_selection=type(body) is dict and 'runner_store_policy' in body
        service_selection=type(body) is dict and 'service_policy' in body
        solar_selection=type(body) is dict and 'energy_attitude_policy' in body
        environment_selection=type(body)is dict and 'environment_ageing_policy'in body
        environment_choice=body.get('environment_ageing_policy','LEGACY')if type(body)is dict else 'LEGACY'
        battery_selection=type(body)is dict and 'battery_port_policy'in body
        profile_selection=type(body) is dict and 'publication_profile' in body
        extended=type(body) is dict and set(body)-{'runner_store_policy','service_policy','energy_attitude_policy','publication_profile','battery_port_policy','environment_ageing_policy'}!=set(legacy_fields)
        object_fields(body,(*legacy_fields,*(('study_preset','ageing_multiplier','output_policy') if extended else ()),*(('runner_store_policy',) if runner_selection else ()),*(('service_policy',) if service_selection else ()),*(('energy_attitude_policy',) if solar_selection else ()),*(('publication_profile',) if profile_selection else ()),*(('battery_port_policy',) if battery_selection else ()),*(('environment_ageing_policy',)if environment_selection else ())))
        from .lifecycle_compact import requested_profile
        publication_profile=requested_profile(body['publication_profile'] if profile_selection else 'LEGACY_RAW')
        runner_policy=requested_runner_policy(body['runner_store_policy'] if runner_selection else 'LEGACY')
        from .lifecycle_service import requested_service_policy
        service_policy=requested_service_policy(body['service_policy'] if service_selection else 'LEGACY')
        from .solar_attitude import requested_energy_policy
        solar=requested_energy_policy(body['energy_attitude_policy'] if solar_selection else 'LEGACY')
        if self.projects is None:raise ValueError('no constructor project authority attached')
        from .battery_port import requested_port_policy
        port=requested_port_policy(body['battery_port_policy']if battery_selection else 'LEGACY')
        policy,scenario,study,output=_requested_inputs(body['policy'],body['scenario'],body['study_preset'] if extended else 'LEGACY',body['ageing_multiplier'] if extended else 1.,body['output_policy'] if extended else None,battery_port=port is not None,environment_ageing=environment_choice!='LEGACY')
        integer(body['duration_seconds'],'requested lifecycle horizon',1,MAX_DURATION)
        if type(body['sun_mode']) is not str or body['sun_mode'] not in ('REDUCED_ASSUMED_ANNUAL_V1','BOUND_SHORT_TABLE_V1'):raise ValueError('lifecycle Sun assumption')
        with self.projects.lock:
            project=self.projects.load(body['project_id'],body['revision'])
            from .spacecraft_project_v2 import SpacecraftProjectV2
            from .spacecraft_project_v3 import SpacecraftProjectV3
            if type(project)in (SpacecraftProjectV2,SpacecraftProjectV3):raise ValueError('V2/V3 design must retain its common mission; use /api/design/lifecycle')
            if self.projects._project_record(body['project_id'])['current_revision']!=body['revision']:raise ValueError('lifecycle requires applied immutable project revision')
            if self.projects.current_preview(body['project_id'],body['revision']) is None:raise ValueError('lifecycle requires paid current constructor preview')
            for store in self.stores.values():
                prior=store.meta['project'];root=store.root_input
                if prior is not None and prior['project_id']==body['project_id'] and prior['revision']==body['revision'] and root.duration_seconds==body['duration_seconds'] and root.policy==policy and root.scenario==scenario and root.sun_mode==body['sun_mode'] and root.study==study and root.output_policy==output and root.service_policy==service_policy and root.reduced_sun_policy is None and root.energy_attitude_policy==solar and root.battery_port_policy==port:
                    from .environment_ageing_document import requested_policy
                    env=requested_policy(environment_choice,root.base.model.simulation_inputs.spacecraft_configuration.thermal.network)
                    if root.environment_ageing_policy!=env:continue
                    if store.runner_policy!=runner_policy or store.publication_profile!=publication_profile:raise ValueError('existing immutable root store has another runner policy or publication profile; no migration')
                    return store.snapshot()
            before=dict(self.projects.meta['constructor']);ledger=ConstructorLedger(**before);ledger.reserve()
            self.projects.meta['constructor']=asdict(ledger);self.projects.charge(2**20)
            actual=ConstructorLedger(**before);base,_,_=materialize_project(project,actual)
            if asdict(actual)!=asdict(ledger):raise ValueError('lifecycle constructor work binding')
            if study is not None:
                from .lifecycle_study import compile_study_base
                base=compile_study_base(base,study)
            from .environment_ageing_document import requested_policy
            env=requested_policy(environment_choice,base.model.simulation_inputs.spacecraft_configuration.thermal.network)
            root=LifecycleRoot(base,body['duration_seconds'],policy,scenario,body['sun_mode'],study=study,output_policy=output,service_policy=service_policy,energy_attitude_policy=solar,battery_port_policy=port,environment_ageing_policy=env)
            return self.create(root,project=dict(project_id=body['project_id'],revision=body['revision'],title=project.title),runner_policy=runner_policy,publication_profile=publication_profile)
    def prepare_portable(self,rid,path,*,strategy='B60_SEALED_STATIC_V1',key='0'*32,execution_seconds=240):
        from .portable_job import prepare
        with self.lock:
            store=self.store(rid)
            from .lifetime_policy import physical_storage
            if physical_storage(store.runner_policy):
                raise ValueError('YEAR-V4 physical stores refuse the legacy portable-export route; use the versioned year job and reserved supervisor export')
            folder=store.path('exports');folder.mkdir(exist_ok=True)
            exports=list(folder.glob('*.zip'))
            if len(exports)>=4 or sum(p.stat().st_size for p in exports)+16*2**20>64*2**20:raise ValueError('B60_PORTABLE_EXPORT_COUNT_BYTES')
            # 1313MiB campaign reservations +64MiB portable exports <1536MiB.
            result=prepare(path,store.root_input,Path(__file__).resolve().parents[2],strategy=strategy,key=key,execution_seconds=execution_seconds)
            if Path(path).stat().st_size>16*2**20:raise ValueError('B60_PORTABLE_EXPORT_BYTES')
            return result
    def submit(self,body):
        with self.lock:
            intent=validate_intent(body);store=self.store(intent['root_identity'])
            old=store.reconcile(intent)
            if old is not None:return old
            if self.active is not None:raise ValueError('one lifecycle scientific worker at a time')
            total=sum(j['intent']['maximum_output_bytes'] for s in self.stores.values() for j in s.jobs())
            if total+intent['maximum_output_bytes']>2**31:raise ValueError('lifecycle workspace global output reservation')
            runner=self.runners.setdefault(intent['root_identity'],LifecycleRunner(store))
            return runner.submit(intent)
    def stop(self,rid,jid):
        with self.lock:
            store=self.store(rid);runner=self.runners.get(rid)
            if runner is None:
                job=store.job(jid)
                if job['status'] in TERMINAL:return job
                raise ValueError('no reconstructible owned lifecycle handle; no PID control')
            return runner.stop(jid)
    def chain(self,rid,cid):
        from .lifecycle_chain import LifecycleChain
        from .lifetime_policy import is_lifetime
        store=self.store(rid);identifier(cid);key=(rid,cid)
        if is_lifetime(store.runner_policy):raise ValueError('lifetime uses dedicated m8_lifetime_campaign_cli controller')
        if key not in self.chains:
            runner=self.runners.setdefault(rid,LifecycleRunner(store))
            if store.root_input.energy_attitude_policy is not None:
                from m8_battery_chain_cli import ResourceChain as BatteryResourceChain
                from m8_compact_chain_cli import ResourceChain
                if store.root_input.battery_port_policy is not None:ResourceChain=BatteryResourceChain
                from .finite_campaign import FiniteCampaignPolicy
                if is_typed_campaign_policy(store.runner_policy):
                    from m8_fast_campaign_cli import ResourceChain
                    if store.root_input.environment_ageing_policy is not None:
                        from m8_environment_campaign_cli import ResourceChain
                self.chains[key]=ResourceChain(store,cid,runner=runner)
            else:self.chains[key]=LifecycleChain(store,cid,runner=runner)
        return self.chains[key]
    def create_chain(self,body):
        from .lifecycle_chain import LifecycleChain,make_plan
        from .lifecycle_execution_budget import admit_budget
        from .lifetime_policy import is_lifetime
        object_fields(body,('root_identity','chain_id','execution_budget','maximum_primary_segments','maximum_output_bytes','maximum_observed_seconds'))
        with self.lock:
            if self.active is not None:raise ValueError('owned scientific worker already active')
            store=self.store(body['root_identity'])
            if is_lifetime(store.runner_policy):raise ValueError('B62 requires lifetime supervisor')
            policy=admit_budget(body['execution_budget'],execution_seconds=body['execution_budget']['hard_execution_seconds'])
            if store.root_input.energy_attitude_policy is not None:
                from m8_battery_chain_cli import create_for_store as battery_create_for_store
                from m8_compact_chain_cli import create_for_store
                if store.root_input.battery_port_policy is not None:create_for_store=battery_create_for_store
                from .finite_campaign import FiniteCampaignPolicy
                if is_typed_campaign_policy(store.runner_policy):
                    from m8_fast_campaign_cli import create_for_store
                    if store.root_input.environment_ageing_policy is not None:
                        from m8_environment_campaign_cli import create_for_store
                key=(body['root_identity'],body['chain_id']);runner=self.runners.setdefault(key[0],LifecycleRunner(store))
                self.chains[key]=create_for_store(store,key[1],policy,body['maximum_primary_segments'],body['maximum_output_bytes'],body['maximum_observed_seconds'],runner=runner)
                return self.chains[key].snapshot()
            plan=make_plan(store,chain_id=body['chain_id'],execution_budget=policy,maximum_primary_segments=body['maximum_primary_segments'],maximum_output_bytes=body['maximum_output_bytes'],maximum_observed_seconds=body['maximum_observed_seconds'])
            key=(body['root_identity'],body['chain_id'])
            runner=self.runners.setdefault(key[0],LifecycleRunner(store))
            self.chains[key]=LifecycleChain(store,key[1],plan=plan,runner=runner)
            return self.chains[key].snapshot()
    def continue_chain(self,body):
        object_fields(body,('root_identity','chain_id','command_key'));identifier(body['command_key'])
        with self.lock:
            key=(body['root_identity'],body['chain_id']);chain=self.chain(*key)
            state=chain.snapshot()['state']
            if body['command_key'] in state['command_keys']:return chain.snapshot()
            thread=self.chain_threads.get(key)
            if thread is not None and thread.is_alive():return chain.snapshot()
            if self.active is not None:raise ValueError('owned scientific worker already active')
            def run():
                try:chain.run(body['command_key'])
                except BaseException:traceback.print_exc() # durable BLOCKED reason remains authoritative.
            thread=threading.Thread(target=run,name='B55R2-chain-'+key[1],daemon=False)
            self.chain_threads[key]=thread;thread.start()
            return chain.snapshot()
    def stop_chain(self,body):
        object_fields(body,('root_identity','chain_id'))
        with self.lock:return self.chain(body['root_identity'],body['chain_id']).stop()
    def snapshot(self):
        value=dict(method=METHOD,roots=[s.snapshot() for s in self.stores.values()],active_job_id=self.active)
        chains=[]
        for rid,store in self.stores.items():
            folder=store.path('resource-chains' if store.root_input.energy_attitude_policy is not None else 'chains')
            for path in sorted(folder.iterdir()) if folder.exists() else ():
                chains.append(self.chain(rid,path.name).snapshot())
        if chains:value['chains']=chains
        return value
    def close(self):
        for key,thread in self.chain_threads.items():
            if thread.is_alive():self.chains[key].stop()
        for runner in self.runners.values():runner.close()
        for thread in self.chain_threads.values():
            thread.join(3)
            if thread.is_alive():raise RuntimeError('owned chain shutdown unresolved')


class _Journal:
    def __init__(self,path,job,limit,remaining):self.file=path.open('xb');self.job=job;self.limit=limit;self.bytes=0;self.sequence=0;self.remaining=remaining
    def emit(self,kind,data,*,terminal=False):
        raw=_bytes(dict(format=JOURNAL,sequence=self.sequence+1,job_id=self.job['job_id'],root_identity=self.job['root_identity'],kind=kind,data=data))+b'\n'
        if len(raw)>65536 or self.bytes+len(raw)>self.limit-(0 if terminal else 65536):raise ValueError('lifecycle progress prospective byte cap')
        if self.bytes+len(raw)>self.remaining()-(0 if terminal else 262144):raise ValueError('lifecycle combined task output admission')
        self.file.write(raw);self.file.flush();self.bytes+=len(raw);self.sequence+=1
    def close(self):self.file.close()


class _ChunkChannel:
    """Compatibility adapter for one raw JSONL record; no hidden downsampling."""
    def __init__(self,writer):self.writer=writer;self.final=None
    def write(self,raw):
        if type(raw) is not bytes or not raw.endswith(b'\n'):raise ValueError('one canonical chunk channel record required')
        value=parse_json(raw[:-1].decode('utf-8'))
        if _bytes(value)+b'\n'!=raw:raise ValueError('channel canonical JSON record')
        self.writer.append(value);return len(raw)
    def flush(self):pass # append already flushes; checkpoint snapshot fsyncs.
    def snapshot(self):return self.final if self.final is not None else self.writer.snapshot()
    def finish(self):
        if self.final is None:self.final=self.writer.finish()
        return self.final
    def __enter__(self):return self
    def __exit__(self,kind,error,tb):
        if self.writer.closed:return False
        try:
            if self.writer.failed:self.writer.close()
            else:self.finish()
        except BaseException:
            if error is None:raise
            traceback.print_exc() # original scientific error remains primary.
        return False


class _ChunkJournal:
    def __init__(self,directory,job,policy,charge,*,codec_charge=None):
        self.writer=_stream_writer(directory,policy,policy.progress_total_bytes,charge=charge,profile=_job_profile(job),codec_charge=codec_charge);self.job=job;self.sequence=0
    @property
    def bytes(self):return self.writer.work['bytes_published']
    @property
    def regular_capacity(self):return self.writer.maximum_bytes-self.bytes-4*65536-4096
    def emit(self,kind,data,*,terminal=False):
        record=dict(format=JOURNAL,sequence=self.sequence+1,job_id=self.job['job_id'],root_identity=self.job['root_identity'],kind=kind,data=data)
        if not terminal and len(_bytes(record))+1>self.regular_capacity:raise ValueError('prospective progress terminal reserve')
        self.writer.append(record);self.sequence+=1
    def close(self):
        if self.writer.closed:return
        if self.writer.failed:self.writer.close()
        else:self.writer.finish()


def _worker_report_summary(state):
    """Return selected report DATA only after the current job boundary passes.

    Prepared leaves never create authority or open their own transactions.
    The public worker owns this report operation; the legacy call is unchanged.
    """
    from .lifecycle_typed_context import TypedBackendContext
    context=state.backend_context
    if type(context)is TypedBackendContext:
        with context.transaction():
            context.guard(state.root,state.model)
            return state.report.summary(prepared_runtime=state.physical.prepared_runtime)
    return state.report.summary(prepared_runtime=state.physical.prepared_runtime)


def _reference_execute_worker(directory,jid,expected_request_sha256,*,backend_contract=None,admitted_package=None):
    """Exactly one production chronological run, called only by owned dispatch."""
    worker_entry=time.perf_counter()
    backend_options={}
    if backend_contract is not None:
        from .lifecycle_backend import admit_native_build
        b=backend_contract['backend_binding'];build=backend_contract['native_build']
        if b['selection']=='PREPARED_NATIVE':admit_native_build(build)
        backend_options=dict(backend=b['selection'],source_binding=sha256(_bytes(backend_contract['source_manifest'])).hexdigest(),backend_build=build)
    from .lifecycle_execution_budget import SoftBudgetGuard
    from .lifecycle_document import loads_root
    from .lifecycle_checkpoint import checkpoint_bytes,make_bindings,restore_checkpoint,checkpoint_file_bytes,CONTROL_ALLOWANCE
    from .lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection,progress_frontier_projection
    from .lifecycle_report import LifecycleReport
    directory=Path(directory).absolute();identifier(jid);ProjectStore._reject_links(directory)
    jobdir=directory/'jobs'/jid;requestpath=jobdir/'request.json'
    if file_sha(requestpath)!=expected_request_sha256:raise ValueError('lifecycle frozen request SHA')
    request=_read(requestpath);object_fields(request,('format','job_id','intent','root_identity','source_identity','runtime','input_sha256','resume'))
    intent=validate_intent(request['intent']);policy_budget=_budget(intent)
    budget_guard=None if policy_budget is None else SoftBudgetGuard(policy_budget,worker_entry,clock=time.perf_counter)
    raw=(directory/'input.json').read_bytes()
    if request['format']!=_job_format(intent) or request['job_id']!=jid or request['source_identity']!=project_source_identity() or request['runtime']!=runtime_identity() or request['input_sha256']!=sha256(raw).hexdigest():raise ValueError('lifecycle worker source/runtime/input admission')
    meta=_read(directory/'store.json');admit_runner_store_metadata(meta)
    if any(meta[k]!=request[k] for k in ('source_identity','runtime','root_identity','input_sha256')):raise ValueError('worker store/request authority')
    if intent['format']==PROFILE_INTENT and meta['format']!=PROFILE_STORE and _profile(intent) is not None:raise ValueError('worker profile/store authority')
    if admitted_package is not None:
        from .lifecycle_job_prepared import JobInputAdmission
        if type(admitted_package)is not tuple or len(admitted_package)!=4 or admitted_package[0]is not backend_contract:raise TypeError('B64 exact current worker admission tuple')
        _,root,job_admission,_=admitted_package
        if type(job_admission)is not JobInputAdmission:raise TypeError('B64 exact private input admission')
        job_admission._guard(root)
        if job_admission.raw_sha256!=sha256(raw).hexdigest():raise ValueError('B64 worker input changed after one-shot admission')
        backend_options['job_admission']=job_admission
    elif backend_contract is None:root=loads_root(raw)
    else:
        from .lifecycle_backend import load_root_for_backend,TYPED_SELECTIONS
        if backend_contract['backend_binding']['selection']in TYPED_SELECTIONS:raise ValueError('B64 worker requires a fresh complete typed package admission')
        root=load_root_for_backend(raw,backend_contract['backend_binding']['selection'])
    if root.identity!=request['root_identity'] or intent['root_identity']!=root.identity:raise ValueError('lifecycle worker root binding')
    from .project_offline_guard import block_network
    block_network()
    pilot_rule=None
    if (jobdir/'pilot-stop-rule.json').exists():
        if backend_contract is None:raise ValueError('B63 PILOT stop rule requires new execution contract')
        from .lifecycle_pilot_stop import admit_rule
        pilot_rule=admit_rule(directory,jid,expected_request_sha256,backend_contract,root)
    streamed=root.output_policy is not None;stream_policy=root.output_policy
    published=0;output_cap=min(intent['maximum_output_bytes'],root.policy.max_task_output_bytes)
    if streamed:output_cap-=stream_policy.status_total_bytes+4*stream_policy.max_index_bytes+MAX_METADATA
    from .finite_campaign import FiniteCampaignPolicy
    if is_typed_campaign_policy(admit_runner_store_metadata(meta)[0]):output_cap-=65536
    if (directory/'portable-execution.json').exists():
        output_cap-=53248 # B60 backend32KiB + static-work16KiB + contract-pin4KiB, unchanged total cap
        if not streamed:output_cap-=8*2**20 # B60 parent raw status allowance
    from .lifetime_policy import physical_storage
    from .checkpoint_transport import MAX_FRAMING_BYTES,encode_checkpoint
    transport_checkpoints=physical_storage(admit_runner_store_metadata(meta)[0])
    checkpoint_file_limit=root.policy.max_checkpoint_bytes+(MAX_FRAMING_BYTES if transport_checkpoints else 0)
    if output_cap<=checkpoint_file_limit+327680:raise ValueError('worker/checkpoint allowance after parent output reservation')
    profile=_profile(intent);bound_profile=intent['format']==PROFILE_INTENT
    application_work={name:0 for name in (PUBLICATION_FIELDS53 if streamed else PUBLICATION_FIELDS)}
    if bound_profile:application_work['stream_codec_reserved_units']=0
    # The final receipt is outside the stream it settles. Reserve its fixed
    # metadata bound before any work; writing it never recursively charges a
    # stream or refunds a failed reservation.
    application_work['publication_metadata_reserved_bytes']+=SETTLED_RECEIPT_BYTES
    if bound_profile:application_work['publication_metadata_reserved_bytes']+=262144 # one bounded observational45003 projection
    stream_charges={name:dict(encoded_bytes_reserved=0,reservation_attempts=0,**({'codec_reserved_units':0} if bound_profile else {})) for name in STREAM_NAMES54}
    def codec_charge(name,n):
        application_work['stream_codec_reserved_units']+=n;stream_charges[name]['codec_reserved_units']+=n
        if application_work['stream_codec_reserved_units']>root.policy.max_control_units:raise ValueError('prospective wrapper codec control cap')
    def stream_charge(name,n):
        nonlocal published
        stream_charges[name]['encoded_bytes_reserved']+=n;stream_charges[name]['reservation_attempts']+=1
        application_work['stream_encoded_bytes_reserved']+=n;application_work['stream_publication_attempts']+=1
        if published+n>output_cap-262144:raise ValueError('prospective combined worker output bytes')
        published+=n
    journal=(_ChunkJournal(jobdir/'progress53',request,stream_policy,lambda n:stream_charge('progress',n),codec_charge=lambda n:codec_charge('progress',n)) if streamed else
        _Journal(jobdir/'progress.jsonl',request,root.policy.max_journal_bytes,lambda:output_cap-published))
    def spent():return published if streamed else published+journal.bytes
    channels={}
    backend_receipt=None
    state=None;last_cp=None;cp_sequence=0;retained_working=[];retained_named=[];retained=[];retained_count=0;started=time.perf_counter();cpu=time.process_time()
    window=None;restore_proof=None;start_clock=root.start_seconds;substantive=False;events_count=0;event_bytes=0;month_bytes=0;details_bytes=0;quota_stop=None;settled_record=None
    whole_parent_static=None;selected_prior_static=None;static_merge_failed=False;worker_failed=False
    last_progress_wall=None;omitted_snapshots=0;max_checkpoint_bytes=0
    call_timing=_InvocationTiming()
    def write(name,value,cap):
        nonlocal published
        raw=value if type(value) is bytes else _bytes(value)
        if spent()+len(raw)>output_cap-262144:raise ValueError('lifecycle task output prospective admission')
        manifest=_write_new(jobdir/name,raw,cap);published+=len(raw);return manifest
    def checkpoint(kind):
        nonlocal cp_sequence,last_cp,published,max_checkpoint_bytes,retained_count
        if kind in ('FINAL','FAILURE_PAID_PREFIX','APPLICATION_QUOTA_BOUNDARY',
                'COOPERATIVE_STOP_PAID_PREFIX','MEMORY_TARGET_BOUNDARY','BUDGET_COOPERATIVE_PAID_PREFIX'):
            # Packed stores reserved this namespace before the child. The
            # legacy owner is a no-op; this is not new execution permission.
            from .lifetime_physical_storage import activate_terminal_for_job_directory
            activate_terminal_for_job_directory(jobdir)
        # Source-derived native traversal/byte allowance is reserved before
        # encoding. These are wrapper units, not CPU operations/model credit.
        if application_work['checkpoint_encoding_reserved_units']+application_work['restore_validation_reserved_units']+CONTROL_ALLOWANCE>root.policy.max_control_units:raise ValueError('lifecycle publication control admission')
        application_work['checkpoint_encoding_reserved_units']+=CONTROL_ALLOWANCE
        application_work['publication_metadata_reserved_bytes']+=16384
        for channel in channels.values():
            if isinstance(channel.writer,CompactStreamWriter):channel.writer.flush()
        bindings=make_bindings(root,state.clock);raw=checkpoint_bytes(state,bindings)
        if len(raw)>root.policy.max_checkpoint_bytes:raise ValueError('lifecycle checkpoint policy size')
        max_checkpoint_bytes=max(max_checkpoint_bytes,len(raw))
        payload=raw;transport=None
        if transport_checkpoints:
            payload,transport=encode_checkpoint(raw,bindings,kind,maximum_decoded_bytes=min(root.policy.max_checkpoint_bytes,root.policy.max_working_bytes))
        application_work['checkpoint_storage_reserved_bytes']+=len(payload)
        cp_sequence+=1;name='checkpoint-'+str(cp_sequence).zfill(8)+'.json'
        cp=write(name,payload,checkpoint_file_limit)
        if transport is not None:
            if cp['sha256']!=transport['encoded_sha256'] or cp['bytes']!=transport['encoded_bytes']:raise ValueError('checkpoint producer encoded receipt binding')
            cp.update(sha256=sha256(raw).hexdigest(),bytes=len(raw),transport=transport)
        publication=dict(format=PUBLICATION54,root_identity=root.identity,native_checkpoint_sha256=cp['sha256'],application_work=deepcopy(application_work),
            stream_charges=deepcopy(stream_charges),scope='BEFORE_CHECKPOINT_PROGRESS_PUBLICATION')
        if bound_profile:publication['publication_profile_identity']=intent['publication_profile_identity']
        if streamed:publication['stream_frontiers']={n:c.snapshot() for n,c in channels.items()}
        sidecar=write('checkpoint-'+str(cp_sequence).zfill(8)+'-publication.json',publication,16384)
        cp.update(clock=state.clock,bindings=bindings,kind=kind,publication=sidecar)
        retained.append(cp);retained_count+=1;journal.emit('checkpoint',cp,terminal=streamed and kind in ('FINAL','FAILURE_PAID_PREFIX','APPLICATION_QUOTA_BOUNDARY','COOPERATIVE_STOP_PAID_PREFIX','MEMORY_TARGET_BOUNDARY','BUDGET_COOPERATIVE_PAID_PREFIX'));last_cp=cp
        if streamed:retained[:]=retained[-8:]
        if kind=='WORKING':
            retained_working.append(cp)
            if len(retained_working)>2:
                old=retained_working.pop(0)
                if old in retained:retained.remove(old)
                retired=dict(sha256=old['sha256'],reason='DECLARED_LAST_TWO_WORKING_RETENTION')
                if streamed:retired['file']=old['file']
                journal.emit('retired_checkpoint',retired);retained_count-=1
        if kind=='AUDIT_NAMED' or root.method==METHOD55 and kind in SERVICE_CHECKPOINT_KINDS:
            retained_named.append(cp)
            if len(retained_named)>2:
                old=retained_named.pop(0)
                if old in retained:retained.remove(old)
                retired=dict(sha256=old['sha256'],reason='DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS' if root.method==METHOD55 else 'DECLARED_LAST_TWO_AUDIT_PREDECESSORS')
                if streamed:retired['file']=old['file']
                journal.emit('retired_checkpoint',retired);retained_count-=1
        if retained_count>root.month_rows+8:raise ValueError('lifecycle finite checkpoint retention')
        return cp
    try:
        journal.emit('identity',dict(worker_PID=os.getpid(),worker_PPID=os.getppid(),runtime=runtime_identity()))
        resume=request['resume']
        if resume is None:state=call_timing.call('start',start_lifecycle,root,execution_mode=_production_execution_mode(root),**backend_options)
        else:
            cp=resume['checkpoint'];parent=identifier(resume['parent_job_id']);p=directory/'jobs'/parent/cp['file']
            resume_raw=checkpoint_file_bytes(p,cp,root,require_transport=transport_checkpoints)
            initial_application_work=application_work
            application_work,whole_parent_static=_admit_publication(p.parent,cp,root,settled=True,include_static=True)
            for n,v in initial_application_work.items():application_work[n]+=v
            application_work['restore_validation_reserved_units']+=CONTROL_ALLOWANCE
            if application_work['restore_validation_reserved_units']+application_work['checkpoint_encoding_reserved_units']>root.policy.max_control_units:raise ValueError('lifecycle prospective restore control admission')
            if streamed:
                def reserve_read(n):
                    application_work['stream_validation_bytes_reserved']+=n
                    if application_work['stream_validation_bytes_reserved']>root.policy.max_control_units:raise ValueError('stream validation read allowance')
                _verify_checkpoint_streams(p.parent,cp,root,reserve=reserve_read)
            prepared_restore=None
            if backend_contract is not None:
                from .lifecycle_checkpoint import prepare_checkpoint_restore
                # Full original static input/backend admission is paid here,
                # before the separately observed direct DATA restoration. The
                # token is one-shot, exact-PID/root/source/CP bound, never saved.
                prepared_restore=prepare_checkpoint_restore(resume_raw,root,cp['sha256'],cp['bindings'],**({'job_admission':job_admission}if admitted_package is not None else {}))
            if prepared_restore is None:
                state,restore_proof=call_timing.call('restore',restore_checkpoint,resume_raw,root,expected_sha256=cp['sha256'],expected_bindings=cp['bindings'])
            else:
                state,restore_proof=call_timing.call('restore',restore_checkpoint,resume_raw,root,expected_sha256=cp['sha256'],expected_bindings=cp['bindings'],prepared=prepared_restore)
            if backend_contract is not None:
                saved=state.backend_context
                if saved is None or saved.selection!=backend_options['backend'] or saved.source_binding!=backend_options['source_binding']:raise ValueError('B63 restore backend/source binding')
            selected_prior_static=restore_proof['retained_prior_static_admission_wrapper']
            try:restore_proof['static_admission_merge']=_merge_static_admission_work(state,selected_prior_static,whole_parent_static)
            except BaseException:static_merge_failed=True;raise
            if state.terminal is not None:raise ValueError('typed model/physical terminal is not continuation authority')
            if state.status in ('INCOMPLETE_PENDING_PHYSICAL_REFUSAL','INCOMPLETE_ACTION_AT_HORIZON') and state.clock<root.end_seconds:
                if root.method==METHOD55 and state.report.state['status']=='PARTIAL_TERMINAL':raise ValueError('sealed B55 model-terminal report is not an ACTIVE continuation authority')
                restore_proof['explicit_new_intent_prior_status']=state.status;state.status='ACTIVE'
            start_clock=state.clock;write('direct-restore.json',restore_proof,MAX_METADATA)
        application_work['admission_attempts']+=1;_publication_ledger(application_work,streamed)
        if intent['mode']!='MAIN':window=LifecycleReport(root,state.physical.context,window=True,offered_frontier=state.next_occurrence,environment_ageing_state=state.physical.environment_ageing_state)
        target=root.end_seconds if intent['window_end_seconds'] is None else intent['window_end_seconds']
        checkpoint_period=64 if not streamed else stream_policy.working_checkpoint_every_events
        publication_cadence=1 if not streamed else stream_policy.publication_minimum_wall_seconds
        next_named=None if not streamed else root.start_seconds+((state.clock-root.start_seconds)//stream_policy.named_checkpoint_every_seconds+1)*stream_policy.named_checkpoint_every_seconds
        if streamed:
            channels={name:_ChunkChannel(_stream_writer(jobdir/(name+'53'),stream_policy,cap,start_record=start,charge=lambda n,name=name:stream_charge(name,n),profile=profile,codec_charge=lambda n,name=name:codec_charge(name,n),buffered=True))
                for name,cap,start in (('events',stream_policy.events_total_bytes,state.transition_count),('months',(root.month_rows+1)*65536,state.report.state['sealed_count']),('details',stream_policy.details_total_bytes,state.transition_count))}
        checkpoint('INITIAL' if resume is None else 'RESTORED')
        with (channels['events'] if streamed else (jobdir/'events.jsonl').open('xb')) as events,(channels['months'] if streamed else (jobdir/'months.jsonl').open('xb')) as months,(channels['details'] if streamed else (jobdir/'details.jsonl').open('xb')) as details:
            while state.status=='ACTIVE' and state.clock<target:
                if budget_guard is not None and budget_guard.boundary('BEFORE_TRANSITION'):
                    checkpoint('BUDGET_COOPERATIVE_PAID_PREFIX');quota_stop='WORKER_LOCAL_SOFT_BUDGET_PAID_PREFIX';break
                marker=jobdir/'stop-request.json'
                if marker.exists():
                    stop=object_fields(_read(marker),('format','job_id','root_identity','requested_utc'))
                    if stop['format']!='B52_COOPERATIVE_STOP_REQUEST_V1' or stop['job_id']!=jid or stop['root_identity']!=root.identity:raise ValueError('lifecycle invalid cooperative stop marker')
                    checkpoint('COOPERATIVE_STOP_PAID_PREFIX');quota_stop='USER_COOPERATIVE_STOP_BEFORE_NEXT_MODEL_TRANSITION';break
                # Preserve enough admitted capacity for a complete maximum
                # native failure-prefix checkpoint plus terminal evidence.
                emergency=checkpoint_file_limit+327680
                event_limit=root.policy.max_journal_bytes if not streamed else stream_policy.events_total_bytes
                if spent()+emergency+(0 if profile is None else 131184*3)>output_cap or (event_bytes if profile is None else channels['events'].writer.work['bytes_published'])+65536>event_limit or streamed and journal.regular_capacity<65536:
                    checkpoint('APPLICATION_QUOTA_BOUNDARY');quota_stop='PROSPECTIVE_OUTPUT_ADMISSION_BEFORE_NEXT_MODEL_TRANSITION';break
                memory=_memory_sample()
                if memory['status']=='AVAILABLE' and memory['current_rss_bytes']>768*2**20:
                    checkpoint('MEMORY_TARGET_BOUNDARY');quota_stop='OBSERVED_WORKER_RSS_EXCEEDS_768_MIB_BEFORE_NEXT_MODEL_TRANSITION';break
                before_clock=state.clock;before_offers=state.report.state['offered_frontier']
                prior_service_mode=None if root.method!=METHOD55 else state.physical.service_state.mode
                state,event,sealed=call_timing.call('step',step_lifecycle,state)
                if not before_clock<=state.clock<=root.end_seconds:raise ValueError('lifecycle returned clock outside original authority')
                if bound_profile and state.transition_count==45003:
                    write('reference-prefix-45003.json',scientific_projection(state),262144)
                encoded=_bytes(event)+b'\n'
                if (event_bytes if profile is None else channels['events'].writer.work['bytes_published'])+len(encoded)>event_limit or spent()+len(encoded)>output_cap-262144:raise ValueError('lifecycle event journal prospective cap')
                events.write(encoded);events.flush();event_bytes+=len(encoded);events_count+=1
                if not streamed:published+=len(encoded)
                if window is not None:
                    # Newly offered suffix population; carried-in receipts are
                    # separately counted by the explicit window report owner.
                    for offer in event.get('new_offers',()):window.offer(offer['ordinal'],offer['priority'])
                    carry=window.consume(state.last_outcome,state.physical.context,window.state['next_transition'],credits=event.get('credits',()),expired=event.get('expired_count',0),**({'lifetime_work':__import__(__package__+'.lifecycle_execution',fromlist=['lifetime_work_snapshot']).lifetime_work_snapshot(state)}if root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else {}))
                    if state.clock==window.boundary:window.seal(state.physical.context,terminal=state.clock>=target or state.status!='ACTIVE',carry=carry)
                if intent['mode']=='DIAGNOSTIC_VERBOSE':
                    from .project_diagnostics import returned_detail
                    from .long_mission_continuation import _scientific
                    detail=_bytes(dict(clock=state.clock,scope='ACTUAL_RETURNED_COMMITTED_PARTS_NOT_FORECAST_OR_REJECTED_TRIALS',event=event,
                        actual=returned_detail(state.last_outcome,state.physical.context),attitude=_scientific(state.physical.attitude)))+b'\n'
                    if len(detail)>2**20:raise ValueError('lifecycle verbose record policy cap')
                    detail_limit=root.policy.max_journal_bytes if not streamed else stream_policy.details_total_bytes
                    if details_bytes+len(detail)>detail_limit or spent()+len(detail)>output_cap-262144:raise ValueError('lifecycle verbose actual output cap')
                    details.write(detail);details.flush();details_bytes+=len(detail)
                    if not streamed:published+=len(detail)
                partial_bits=[x.transmitted_equivalent_bits for x in state.physical.context.ground_data_delivery_state.partial_transfers]
                partial=not substantive and any(x>0 for x in partial_bits)
                if pilot_rule is not None:
                    from .lifecycle_pilot_stop import matches,trigger_receipt
                    if matches(pilot_rule,state):
                        write('pilot-stop-trigger.json',trigger_receipt(pilot_rule,state),16384)
                        marker=jobdir/'stop-request.json'
                        if not marker.exists():
                            try:_write_stop_request(marker,request)
                            except FileExistsError:pass
                        saved_stop=object_fields(_read(marker),('format','job_id','root_identity','requested_utc'))
                        if saved_stop['format']!='B52_COOPERATIVE_STOP_REQUEST_V1' or saved_stop['job_id']!=jid or saved_stop['root_identity']!=root.identity:raise ValueError('B63 foreign concurrent Stop marker')
                        checkpoint('COOPERATIVE_STOP_PAID_PREFIX');quota_stop='USER_COOPERATIVE_STOP_BEFORE_NEXT_MODEL_TRANSITION';break
                service_mode=None if root.method!=METHOD55 else state.physical.service_state.mode
                service_changed=service_mode is not None and service_mode!=prior_service_mode
                service_kind='SERVICE_'+service_mode if service_changed and service_mode in ('SAFE','POWER_OFF','RECOVERY') else None
                now=time.perf_counter()
                critical=sealed is not None or bool(event.get('credits')) or partial or service_changed or events_count%checkpoint_period==0 or state.clock>=target or state.status!='ACTIVE' or streamed and state.last_outcome.status=='refused'
                if last_progress_wall is None or now-last_progress_wall>=publication_cadence or critical:
                    # Gate before constructing/encoding cache/world snapshots.
                    frontier_data=progress_frontier_projection(state,resources=bool(bound_profile))
                    progress,totals=frontier_data if bound_profile else (frontier_data,None)
                    progress['publication']=dict(minimum_wall_interval_seconds=publication_cadence,policy_omitted_snapshots=omitted_snapshots,
                        last_checkpoint_bytes=last_cp['bytes'],memory=memory)
                    if bound_profile:
                        r=state.report.state
                        expired=totals['expired']+r['pending_boundary_expired']
                        progress['publication']['resources']=dict(scope='SELECTED_ACTUAL_REPORT_PREFIX_SAMPLED_EXTREMA',
                            current_energy_wh=state.physical.context.spacecraft_state.battery.energy_wh,minimum_energy_wh=totals['minimum_energy_wh'],
                            offered=progress['offered'],on_time_credits=progress['credits'],expired=expired,refused_actions=totals['refused_actions'],
                            pending_dispositions=progress['offered']-progress['credits']-expired,maximum_temperature_k=totals['maximum_temperature_k'])
                    journal.emit('boundary',progress);last_progress_wall=now
                else:omitted_snapshots+=1
                sealed_rows=([sealed] if sealed is not None else [])+([event['additional_terminal_row']] if 'additional_terminal_row' in event else [])
                for row in sealed_rows:
                    rowraw=_bytes(row)+b'\n'
                    if spent()+len(rowraw)>output_cap-262144:raise ValueError('lifecycle monthly output admission')
                    months.write(rowraw);months.flush();month_bytes+=len(rowraw)
                    if not streamed:published+=len(rowraw)
                if state.clock<target:
                    # Observational checkpoint at an already selected boundary;
                    # this never inserts a physical cut. Service/audit points
                    # share the existing two-name retention allowance.
                    if service_kind is not None:checkpoint(service_kind)
                    if sealed is not None:checkpoint('MONTH_BOUNDARY')
                    elif partial:checkpoint('PENDING_PARTIAL_CONTACT')
                    elif service_kind is not None:pass
                    elif next_named is not None and state.clock>=next_named:checkpoint('AUDIT_NAMED')
                    elif events_count%checkpoint_period==0:checkpoint('WORKING')
                if next_named is not None and state.clock>=next_named:next_named=root.start_seconds+((state.clock-root.start_seconds)//stream_policy.named_checkpoint_every_seconds+1)*stream_policy.named_checkpoint_every_seconds
                if partial:substantive=True
                if budget_guard is not None and state.status=='ACTIVE' and state.clock<target and budget_guard.boundary('AFTER_COMMITTED_TRANSITION'):
                    checkpoint('BUDGET_COOPERATIVE_PAID_PREFIX');quota_stop='WORKER_LOCAL_SOFT_BUDGET_PAID_PREFIX';break
            stream_manifests={n:c.finish() for n,c in channels.items()} if streamed else None
            checkpoint('FINAL')
            projection=scientific_projection(state);endpoint=write('endpoint.json',projection,root.policy.max_working_bytes)
            report=_worker_report_summary(state);write('report.json',report,MAX_METADATA)
            partial_terminal_report=None
            if root.method==METHOD55:
                partial_view=_service_partial_view(root,state.report,state.physical.context,last_cp)
                if partial_view is not None:partial_terminal_report=write('partial-terminal-row.json',partial_view,MAX_METADATA)
            if window is not None:
                if window.state['status']=='ACTIVE':window.seal(state.physical.context,terminal=True)
                summary=window.summary();summary['scope']='DIAGNOSTIC_SUFFIX_ONLY_CARRY_IN_CREDITS_NOT_ADDED_TO_MAIN';write('window-report.json',summary,MAX_METADATA)
            result=dict(format=_job_format(intent),job_id=jid,root_identity=root.identity,method=root.method,clock=state.clock,start_clock=start_clock,
                status=state.status,application_status='INCOMPLETE_BUDGET_STOP' if quota_stop=='WORKER_LOCAL_SOFT_BUDGET_PAID_PREFIX' else 'INCOMPLETE_STOP' if quota_stop=='USER_COOPERATIVE_STOP_BEFORE_NEXT_MODEL_TRANSITION' else 'INCOMPLETE_APPLICATION_ADMISSION' if quota_stop else 'COMPLETED_WINDOW' if state.clock>=target else 'INCOMPLETE_MODEL_STATUS',reason=quota_stop,target_seconds=target,actual_end_seconds=state.clock,
                diagnostic_end_policy='FIRST_SUPPORTED_COMMITTED_BOUNDARY_AT_OR_AFTER_REQUEST_NO_INTERPOLATION',endpoint=endpoint,report=report,window_report=None if window is None else summary,
                checkpoint=last_cp,restoration=restore_proof,events_count=events_count,event_bytes=event_bytes,month_bytes=month_bytes,details_bytes=details_bytes,
                output_published_bytes=spent(),output_byte_scope='BEFORE_TERMINAL_AND_FINAL_JOURNAL_RECORD',output_reserved_bytes=intent['maximum_output_bytes'],wall_seconds=time.perf_counter()-started,worker_cpu_seconds=time.process_time()-cpu,
                model_work=asdict(state.work),prefix_scope='DIRECT_GENERATED_STATE_NO_PREFIX_NUMERICAL_RECONSTRUCTION' if resume else 'ORIGINAL_INITIAL_AUTHORITY')
            from .finite_campaign import FiniteCampaignPolicy
            if is_typed_campaign_policy(admit_runner_store_metadata(meta)[0]):
                from .battery_terminal import terminal_for_state,bind_terminal
                t=terminal_for_state(state,quota_stop,target)
                if t['kind'] in ('PHYSICAL','MODEL','UNSUPPORTED'):result['application_status']='INCOMPLETE_MODEL_STATUS'
                result['reason']=t['code']
                result['typed_terminal']=bind_terminal(t,request,last_cp)
            if budget_guard is not None:result['execution_budget_receipt']=budget_guard.receipt()
            result['application_work']=deepcopy(application_work)
            if root.method==METHOD55:result['partial_terminal_report']=partial_terminal_report
            result['stream_charges']=deepcopy(stream_charges)
            result['static_admission_wrapper']=_static_admission_snapshot(state)
            result['execution_timing']=call_timing.snapshot()
            if streamed:result.update(streams=stream_manifests,stream_policy=asdict(stream_policy),retained_checkpoint_count=retained_count)
            result['progress_policy']=dict(minimum_wall_interval_seconds=publication_cadence,policy_omitted_snapshots=omitted_snapshots,scientific_events_omitted=0,
                scope='OPPORTUNISTIC_WRAPPER_BOUNDARY_SNAPSHOTS_NOT_A_HEARTBEAT')
            if state.backend_context is not None:
                backend_receipt=state.backend_context.receipt();result['backend_execution']=backend_receipt
            if (jobdir/'pilot-stop-trigger.json').exists():result['pilot_stop_trigger']=dict(file='pilot-stop-trigger.json',sha256=file_sha(jobdir/'pilot-stop-trigger.json'),bytes=(jobdir/'pilot-stop-trigger.json').stat().st_size)
            result['memory']=_memory_sample();result['max_checkpoint_bytes']=max_checkpoint_bytes
            terminal=write('terminal.json',result,MAX_METADATA)
            settled_record=terminal
            journal.emit('completed' if state.clock>=target and ('typed_terminal'not in result or result['typed_terminal']['terminal']['kind']=='TARGET') else 'stopped',dict(terminal_sha256=terminal['sha256'],clock=state.clock),terminal=True)
    except BaseException as error:
        worker_failed=True
        original_traceback=traceback.format_exc()
        prefix_error=None;updated_prefix=False
        if state is not None:
            try:checkpoint('FAILURE_PAID_PREFIX');updated_prefix=True
            except BaseException:prefix_error=traceback.format_exc()
        failure=dict(type=type(error).__name__,reason=str(error),traceback=original_traceback,last_checkpoint=last_cp,
            actual_coverage=None if state is None else dict(start_seconds=start_clock,end_seconds=state.clock),
            status='INCOMPLETE_ERROR',complete_endpoint='NOT_ESTABLISHED',published_bytes=published,updated_paid_prefix_checkpoint=updated_prefix,
            failure_prefix_publication_error=prefix_error,application_work=deepcopy(application_work),
            paid_model_work=None if state is None else asdict(state.work),
            paid_actual_runtime_work=None if state is None else asdict(state.physical.runtime_work),
            paid_forecast_runtime_work=None if state is None else asdict(state.forecast_runtime))
        if root.method==METHOD55:
            failure['partial_terminal_report']=None;failure['partial_terminal_report_error']=None
            if state is not None and last_cp is not None:
                try:
                    partial_view=_service_partial_view(root,state.report,state.physical.context,last_cp)
                    if partial_view is not None:
                        if not (jobdir/'partial-terminal-row.json').exists():failure['partial_terminal_report']=write('partial-terminal-row.json',partial_view,MAX_METADATA)
                        else:
                            path=jobdir/'partial-terminal-row.json';prior_view=_read(path)
                            if prior_view.get('native_checkpoint_sha256')!=last_cp['sha256']:
                                failure['partial_terminal_report_error']='Existing observational partial view pins prior native checkpoint '+str(prior_view.get('native_checkpoint_sha256'))+'; preserved without retagging as failure checkpoint '+last_cp['sha256']
                            else:failure['partial_terminal_report']=dict(file=path.name,sha256=file_sha(path),bytes=path.stat().st_size)
                except BaseException:failure['partial_terminal_report_error']=traceback.format_exc()
            failure['published_bytes']=published
            failure['published_byte_scope']='BEFORE_FAILURE_RECORD_AND_SETTLED_RECEIPT_AFTER_PARTIAL_VIEW_ATTEMPT'
            failure['application_work']=deepcopy(application_work)
        failure['observation_errors']={}
        for name,observe in (('static_admission_wrapper',lambda:_static_admission_snapshot(state)),('execution_timing',call_timing.snapshot)):
            try:failure[name]=observe()
            except BaseException:
                failure[name]=None;failure['observation_errors'][name]=traceback.format_exc()
        failure['static_admission_merge_failed']=static_merge_failed
        failure['whole_parent_static_admission_wrapper']=whole_parent_static
        failure['selected_prior_static_admission_wrapper']=selected_prior_static
        failure['stream_charges']=deepcopy(stream_charges)
        try:
            failure_raw=_bytes(failure)
            if spent()+len(failure_raw)+SETTLED_RECEIPT_BYTES>output_cap:raise ValueError('failure/settled receipt prospective bytes')
            settled_record=_write_new(jobdir/'failure.json',failure_raw,131072);published+=len(failure_raw)
            journal.emit('failure',dict(type=type(error).__name__,reason=str(error),last_checkpoint=last_cp),terminal=True)
        except BaseException:traceback.print_exc()
        raise
    finally:
        original_error=worker_failed;close_error=None;backend_error=None
        if state is not None and state.backend_context is not None:
            try:
                if backend_receipt is None:backend_receipt=state.backend_context.receipt()
                write('backend-execution.json',backend_receipt,65536)
            except BaseException:
                backend_error=sys.exc_info();original_error=True;traceback.print_exc()
        try:journal.close()
        except BaseException:close_error=sys.exc_info();traceback.print_exc()
        if settled_record is not None:
            try:
                owners={name:(journal.writer if name=='progress' else channels[name].writer if name in channels else None)
                    for name in STREAM_NAMES54} if streamed else {name:None for name in STREAM_NAMES54}
                closed=close_error is None and all(owner is None or owner.closed and not owner.failed for owner in owners.values())
                receipt=dict(format=SETTLED_PUBLICATION54,scope=SETTLED_SCOPE54,root_identity=root.identity,source_identity=request['source_identity'],job_id=jid,
                    record=settled_record,application_work=deepcopy(application_work),stream_charges=deepcopy(stream_charges),
                    stream_work={name:None if owner is None else deepcopy(owner.work)for name,owner in owners.items()},publication_closed=closed)
                if bound_profile:receipt.update(publication_profile_identity=intent['publication_profile_identity'],stream_codec_work={name:None if owner is None else deepcopy(getattr(owner,'codec',None)) for name,owner in owners.items()})
                encoded=_bytes(receipt)
                if spent()+len(encoded)>output_cap:raise ValueError('settled receipt output cap')
                _write_new(jobdir/'application-work-final.json',encoded,SETTLED_RECEIPT_BYTES);published+=len(encoded)
            except BaseException:
                if not original_error and close_error is None:raise
                traceback.print_exc() # Retain the original worker failure.
        if state is not None and state.backend_context is not None:
            from .lifecycle_typed_context import TypedBackendContext
            if type(state.backend_context)is TypedBackendContext:
                try:
                    state.backend_context.job.close()
                    write('prepared-job-retired.json',dict(format='B64_PRIVATE_JOB_RETIRED_V1',
                        authority_revoked=True,PID=os.getpid(),source_binding=state.backend_context.source_binding,
                        scope='AFTER_FINAL_RECEIPT_AND_SETTLED_PUBLICATION_NOT_SCIENTIFIC_WORK'),4096)
                except BaseException:
                    retired_error=sys.exc_info();traceback.print_exc()
                    try:write('prepared-job-retirement-error.json',dict(format='B64_PRIVATE_JOB_RETIREMENT_ERROR_V1',
                        error_type=type(retired_error[1]).__name__,message=str(retired_error[1])[:2048],
                        traceback=''.join(traceback.format_exception(*retired_error))[-10000:]),16384)
                    except BaseException:traceback.print_exc()
                    if backend_error is None and close_error is None:backend_error=retired_error
        if backend_error is not None and not worker_failed:raise backend_error[1].with_traceback(backend_error[2])
        if close_error is not None and not worker_failed:raise close_error[1].with_traceback(close_error[2])


def execute_worker(directory,jid,expected_request_sha256):
    from .lifetime_execution_authority import admit_worker_execution
    contract=Path(directory)/'portable-execution.json'
    typed_package=None
    if contract.is_file():
        from .lifetime_typed_portable import FORMAT_V3,FORMAT_V4,admit_worker_package_v3
        if _read(contract).get('format')in(FORMAT_V3,FORMAT_V4):
            typed_package=admit_worker_package_v3(directory,Path(__file__).resolve().parents[2],job_id=jid,request_sha256=expected_request_sha256)
    if typed_package is None:admit_worker_execution(directory)
    if not contract.exists() and not (Path(directory)/'portable-job.json').exists() and not (Path(directory)/'jobs'/jid/'portable-contract-binding.json').exists():return _reference_execute_worker(directory,jid,expected_request_sha256)
    from .portable_job import worker_contract,canonical
    from .lifecycle_fast import execution_strategy
    c=typed_package[0]if typed_package is not None else worker_contract(directory,Path(__file__).resolve().parents[2],job_id=jid,request_sha256=expected_request_sha256)
    binding=sha256(canonical(c)).hexdigest()
    # Keep exact metadata publication inside the SAME admitted worker scope.
    # Per-kernel transactions end before checkpoint/report/header encoding;
    # the original B65 contract and every physical guard are still admitted.
    from contextlib import nullcontext
    metadata=nullcontext()
    if typed_package is not None and c['backend_binding']['selection']=='B65_TYPED_EXECUTION_V2':
        from .metadata_codec import admitted_metadata_scope
        metadata=admitted_metadata_scope(c['native_build'])
    with metadata,execution_strategy(c['strategy'],binding)as session:
        failed=False
        try:return _reference_execute_worker(directory,jid,expected_request_sha256,backend_contract=c if c.get('format')in ('B63_PREPARED_LIFETIME_EXECUTION_CONTRACT_V2','B64_TYPED_LIFETIME_EXECUTION_CONTRACT_V3','B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4') else None,admitted_package=typed_package)
        except BaseException:
            failed=True;raise
        finally:
            work=dict(format='B60_STATIC_EXECUTION_RECEIPT_V1',contract_sha256=binding,strategy=c['strategy'],
                cache_work=None if session is None else session.snapshot(),physical_prefix_replayed=0,
                scope='STATIC_CACHE_WORK_RECONSTRUCTED_THIS_PROCESS_NOT_SCIENTIFIC_NATIVE_LEDGER')
            try:_write_new(Path(directory)/'jobs'/jid/'execution-work.json',work,16384)
            except BaseException:
                if failed:traceback.print_exc()
                else:raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    worker=sub.add_parser('worker');worker.add_argument('--store',type=Path,required=True);worker.add_argument('--job',required=True);worker.add_argument('--request-sha256',required=True)
    args=p.parse_args(argv)
    execute_worker(args.store,args.job,args.request_sha256)


if __name__=='__main__':main()
