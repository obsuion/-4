"""Strict detached B64 operational receipt DATA; grants no dispatch rights.

Preparation, codec, typed-static and world reservations remain reported costs.
They are separate ledgers, not deductions from or substitutes for scientific
work. This reader imports no native module and performs no model evaluation.
"""
from hashlib import sha256
import json

FORMAT='B64_TYPED_BACKEND_EXECUTION_RECEIPT_V1'
METHOD='B64_TYPED_EXECUTION_V1'
FULL=METHOD
SUPPORT='B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1'
JOB_METHOD='B64_OWNED_PREPARED_JOB_V1'
CONTROL_METHOD='B64_JOB_PREPARATION_CONTROL_V1'
JOB_METHOD_V2='B69_OWNED_PREPARED_JOB_V2'
CONTROL_METHOD_V2='B69_JOB_PREPARATION_CONTROL_V2'
TOP_WORK=('attempted','completed','boundaries','leaf_entries','quiet_entries','static_preparations',
    'derived_admissions','typed_static_control_units','world_preparation_control_units','world_preparations')
PROGRESS_TOP_WORK=('progress_summary_calls','progress_secondary_validations','progress_frontiers_completed')
JOB_WORK=('control_units_reserved','static_preparations','transaction_attempts','transaction_completed',
    'transaction_failed','transaction_exits','callback_checks','environment_requests','coefficient_realizations',
    'projections','report_parts','public_boundaries')
ROLE_WORK=('requests','failures','coefficient_attempts','coefficient_realizations','cache_hits','cache_misses',
    'cache_evictions','binding_refusals')
CODEC_WORK=('full_schema_scans','full_owner_checks','used_owner_checks','typed_roundtrips','adapter_nodes',
    'typed_guard_nodes','operational_checks')


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def fields(value,names):
    if type(value)is not dict or any(type(k)is not str for k in value)or set(value)!=set(names):
        raise ValueError('B64 exact returned operational receipt fields')


def literal(value,expected):
    if type(value)is not str or value!=expected:raise ValueError('B64 returned operational receipt identity/scope')


def integer(value,maximum,minimum=0):
    if type(value)is not int or not minimum<=value<=maximum:raise ValueError('B64 finite exact returned operational counter')


def identity(value):
    if type(value)is not str or len(value)!=64 or any(c not in '0123456789abcdef'for c in value):
        raise ValueError('B64 returned operational SHA256')


def errors(value):
    if type(value)is not list or len(value)>32 or any(type(s)is not str or len(s.encode('utf8'))>4096 for s in value):
        raise ValueError('B64 bounded returned secondary-error DATA')


def _preparation(value,job,contract):
    fields(value,('method','phase','raw_sha256','raw_bytes','source_binding','build_sha256','input_codec',
        'raw_admissions','model_build_attempts','model_build_completed','static_copy_attempts','static_copy_completed',
        'control_units_reserved','scope'))
    literal(value['method'],job['method']);literal(value['phase'],'CONSUMED')
    literal(value['scope'],'PROCESS_LOCAL_ADMISSION_DATA_NOT_AUTHORITY')
    for name in ('raw_sha256','source_binding','build_sha256'):
        identity(value[name])
        if value[name]!=job[name]:raise ValueError('B64 returned one-shot preparation binding')
    integer(value['raw_bytes'],16*2**20,1)
    for name in ('raw_admissions','model_build_attempts','model_build_completed','static_copy_attempts','static_copy_completed'):
        integer(value[name],1,1)
    integer(value['control_units_reserved'],2**48,value['raw_bytes']+2*2**19)
    codec=value['input_codec']
    fields(codec,('format','phase','counters','secondary_errors','scope'))
    literal(codec['format'],'B63_INVOCATION_LOCAL_INPUT_CODEC_V1');literal(codec['phase'],'CLOSED')
    literal(codec['scope'],'INPUT_ADMISSION_OPERATIONAL_CHECKS_NOT_SCIENTIFIC_WORK')
    counters=codec['counters'];fields(counters,CODEC_WORK)
    for item in counters.values():integer(item,2**24)
    if (counters['full_schema_scans']!=2 or counters['operational_checks']!=sum(counters[n]for n in CODEC_WORK if n!='operational_checks')):
        raise ValueError('B64 returned input codec exact accounting')
    errors(codec['secondary_errors'])
    if codec['secondary_errors']:raise ValueError('B64 successful root admission retained codec failure')


def _job(value,contract,build_sha,*,progress=False):
    extended=contract['job_preparation']==JOB_METHOD_V2
    required=('method','source_binding','root_identity','model_identity','raw_sha256','build_sha256',
        'preparation','control','roles','secondary_errors','scope')
    fields(value,(*required,'exact_guard')if extended else required)
    selected=JOB_METHOD_V2 if extended else JOB_METHOD
    literal(value['method'],selected)
    if extended:
        if contract['backend_binding']['selection']!='B65_TYPED_EXECUTION_V2' or 'ops_sim/v5/lifecycle_exact_guards.py'not in contract['native_build']['support_sources']:
            raise ValueError('B69 exact guard receipt requires declared current compiled domain')
        guard=value['exact_guard'];fields(guard,('method','counters'))
        literal(guard['method'],'B69_COMPILED_EXACT_GUARD_PLAN_V1')
        literal(guard['counters'],'SEPARATE_OPERATIONAL_STATISTICS_NOT_BINDING_RECEIPT')
    literal(value['scope'],'PAID_CURRENT_JOB_PREPARATION_NOT_SCIENTIFIC_WORK_OR_RESTART_AUTHORITY')
    for name in ('source_binding','root_identity','model_identity','raw_sha256','build_sha256'):identity(value[name])
    if (value['source_binding']!=contract['source_manifest_sha256']or value['root_identity']!=contract['root_identity']or
            value['raw_sha256']!=contract['input_sha256']or value['build_sha256']!=build_sha):
        raise ValueError('B64 returned owned job source/root/input/build binding')
    _preparation(value['preparation'],value,contract)
    job_work=(*JOB_WORK,'progress_frontiers')if progress else JOB_WORK
    control=value['control'];fields(control,('method',*job_work));literal(control['method'],CONTROL_METHOD_V2 if extended else CONTROL_METHOD)
    for name in job_work:integer(control[name],2**48)
    if (control['static_preparations']!=1 or control['control_units_reserved']<value['preparation']['control_units_reserved']or
            control['transaction_completed']+control['transaction_failed']>control['transaction_attempts']or
            control['transaction_exits']>control['transaction_attempts']or control['transaction_completed']>control['transaction_exits']):
        raise ValueError('B64 returned preparation/transaction accounting')
    fields(value['roles'],('ACTUAL','FORECAST'))
    for role,row in value['roles'].items():
        fields(row,('method','role','source_binding','root_identity','model_identity','cache_entries','cache_limit',*ROLE_WORK,'scope'))
        literal(row['method'],selected);literal(row['role'],role)
        literal(row['scope'],'ROLE_LOCAL_OPERATIONAL_DATA_NOT_SCIENTIFIC_WORK')
        for name in ('source_binding','root_identity','model_identity'):
            if type(row[name])is not str or row[name]!=value[name]:raise ValueError('B64 returned ACTUAL/FORECAST binding')
        integer(row['cache_entries'],8);integer(row['cache_limit'],8,8)
        for name in ROLE_WORK:integer(row[name],2**48)
        if (row['failures']>row['requests']or row['cache_hits']+row['cache_misses']>row['requests']or
                row['coefficient_realizations']>row['coefficient_attempts']or row['coefficient_attempts']>row['cache_misses']or
                row['cache_entries']+row['cache_evictions']>row['coefficient_realizations']or row['binding_refusals']>row['requests']):
            raise ValueError('B64 returned role cache/coefficient accounting')
    errors(value['secondary_errors'])


def admit_backend_receipt(value,contract):
    """Validate complete returned DATA using only its pinned current contract."""
    from .lifetime_typed_portable import admit_execution_contract_data_v3
    admit_execution_contract_data_v3(contract)
    new=contract.get('format')=='B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4'
    if new:
        original_generation=_generation_receipt(value.get('validation_control'))
        if value.get('format')!='B65_TYPED_BACKEND_EXECUTION_RECEIPT_V2'or value.get('method')!='B65_TYPED_EXECUTION_V2':raise ValueError('B65 returned receipt identity')
        value=dict(value);value.pop('validation_control');value.update(format=FORMAT,method=METHOD)
    # Current closed producer membership declares the B71 progress extension.
    # Historical contracts retain their exact old DATA shape. These are paid
    # observational statistics, never dispatch/restart authority.
    progress='B71_PROGRESS_FRONTIER.md'in contract['source_manifest']
    top_work=(*TOP_WORK,*PROGRESS_TOP_WORK)if progress else TOP_WORK
    fields(value,('format','method','selection','source_binding','runtime','build_sha256','capability_sha256',
        *top_work,'owned_job','quiet_scope','scope'))
    literal(value['format'],FORMAT);literal(value['method'],METHOD)
    literal(value['scope'],'OPERATIONAL_EXECUTION_NOT_PHYSICAL_MODEL_WORK')
    build=contract['native_build'];binding=contract['backend_binding']
    fields(value['runtime'],build['runtime'])
    if any(type(v)is not str for v in value['runtime'].values()):raise ValueError('B64 exact returned runtime text')
    if (type(value['selection'])is not str or value['selection']!=binding['selection']or value['selection']!=build['execution_domain']or
            type(value['source_binding'])is not str or value['source_binding']!=contract['source_manifest_sha256']or
            canonical(value['runtime'])!=canonical(build['runtime'])or value['build_sha256']!=binding['build_sha256']or
            value['capability_sha256']!=binding['capability_sha256']):
        raise ValueError('B64 returned backend source/runtime/build/domain binding')
    identity(value['build_sha256']);identity(value['capability_sha256'])
    literal(value['quiet_scope'],'CALLBACK_FREE' if value['selection']in(FULL,'B65_TYPED_EXECUTION_V2') else 'EXPLICIT_LEGACY_QUIET_CONTROL_H05_INCOMPLETE')
    for name in top_work:integer(value[name],2**40)
    if value['attempted']!=1 or value['completed']!=1 or value['boundaries']<1 or value['static_preparations']>1:
        raise ValueError('B64 returned typed preparation balance')
    reserve=value['typed_static_control_units']
    if (reserve and (reserve<6400 or reserve%16))or value['static_preparations']and not reserve:
        raise ValueError('B64 returned prepaid indexed-static control units')
    if value['world_preparations']and not value['world_preparation_control_units']:
        raise ValueError('B64 returned unpaid world preparation')
    _job(value['owned_job'],contract,value['build_sha256'],progress=progress)
    if progress:
        attempted=value['owned_job']['control']['progress_frontiers']
        if not (value['progress_frontiers_completed']<=value['progress_summary_calls']<=attempted and
                value['progress_secondary_validations']<=value['progress_summary_calls']):
            raise ValueError('B72 returned progress frontier accounting')
    if len(canonical(value))>65536:raise ValueError('B64 returned backend receipt byte cap')
    if new:
        value.update(format='B65_TYPED_BACKEND_EXECUTION_RECEIPT_V2',method='B65_TYPED_EXECUTION_V2',validation_control=original_generation)
    return json.loads(canonical(value))


def _generation_receipt(value):
    fields(value,('method','epoch','phase','full_requests','closed_requests','activations','callback_suspensions','invalidations','machine_world_steps','reference_world_steps','scientific_work','legacy_control','scope'))
    literal(value['method'],'B65_CLOSED_GENERATION_CONTROL_V1')
    literal(value['scientific_work'],'UNCHANGED')
    literal(value['legacy_control'],'UNCHANGED_LOGICAL_BOUNDARY_PREPAYMENT_NOT_CPU_INSTRUCTIONS')
    literal(value['scope'],'PROCESS_LOCAL_STATIC_VALIDATION_ONLY_NO_DYNAMIC_RESULTS')
    if type(value['phase'])is not str or value['phase']not in('IDLE','CLOSED'):raise ValueError('B65 returned generation phase')
    for key in ('epoch','full_requests','closed_requests','activations','callback_suspensions','invalidations','machine_world_steps','reference_world_steps'):integer(value[key],2**40)
    if value['invalidations']>value['activations']:raise ValueError('B65 generation accounting balance')
    return json.loads(canonical(value))
