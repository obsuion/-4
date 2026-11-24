"""Candidate server wrapper: finite original-root native continuation, no physics change.

This is a new store/policy identity. Old B59/B60 stores are never migrated.
Planning a fifteen-year input grants no numerical or physical qualification.
"""
from dataclasses import dataclass, asdict
from hashlib import sha256
import json

from .lifetime_policy import (LifetimeCampaignPolicy,LifetimeCampaignPolicyV2,is_lifetime,is_v2,STORE_V2,admit_policy,METHOD,STORE,is_finite as is_typed_campaign_policy)
JOB='B62_PORTABLE_B61_LIFETIME_INITIAL_V1'
PLAN='B62_ORIGINAL_ROOT_SERIAL_PLAN_V1'
JOB_V2='B63_PORTABLE_PREPARED_LIFETIME_INITIAL_V2'
PLAN_V2='B63_ORIGINAL_ROOT_PREPARED_SERIAL_PLAN_V2'
YEAR=31557600
MIB=2**20
GIB=2**30

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def store_format(value):
    from .finite_campaign import FiniteCampaignPolicy,STORE as FINITE
    from .lifetime_policy import physical_storage,STORE_PHYSICAL,packed_storage,STORE_PACKED
    if packed_storage(value):return STORE_PACKED
    if physical_storage(value):return STORE_PHYSICAL
    if type(value)is FiniteCampaignPolicy:return FINITE
    if is_v2(value):return STORE_V2
    if type(value)is LifetimeCampaignPolicy:return STORE
    raise TypeError('exact typed store policy')

def horizon_preflight(root, policy):
    if not is_lifetime(policy):
        raise TypeError('exact lifetime policy')
    policy.__post_init__()
    if type(root.duration_seconds)is not int or not 1<=root.duration_seconds<=15*YEAR:raise ValueError('B62 lifetime horizon')
    if policy.mode=='WINDOWS_ONLY_LOCAL_QUALIFICATION'and root.duration_seconds>86400:raise ValueError('B62 local qualification horizon is at most one day')
    from .lifetime_policy import WINDOWS_USER,is_v2
    if policy.mode==WINDOWS_USER and (not is_v2(policy) or root.duration_seconds>YEAR):raise ValueError('YEAR-V1 explicit V2 one-year experimental horizon')
    from .lifetime_admission import ACCOUNTING
    if root.policy.method!=ACCOUNTING:raise ValueError('B62 explicit cumulative accounting input required')
    if root.environment_ageing_policy is None:raise ValueError('B62 B61 environment policy required')
    if root.battery_port_policy is None or root.energy_attitude_policy is None:
        raise ValueError('lifetime requires explicit battery and solar state')
    if root.output_policy is None:
        raise ValueError('lifetime requires bounded streaming output')
    q = root.output_policy
    worker = (policy.maximum_output_bytes-q.status_total_bytes-
              4*q.max_index_bytes-256*1024-65536-53248)
    if worker <= root.policy.max_checkpoint_bytes+327680:
        raise ValueError('lifetime per-job output cannot reserve native/final evidence')
    if policy.maximum_output_bytes > root.policy.max_task_output_bytes:
        raise ValueError('lifetime output exceeds immutable numerical root allowance')
    return dict(format='B63_PREPARED_LIFETIME_ADMISSION_V2'if is_v2(policy)else'B62_B61_LIFETIME_ADMISSION_V1',
        root_identity=root.identity, original_anchor_seconds=root.start_seconds,
        target_seconds=root.end_seconds, duration_seconds=root.duration_seconds,
        policy_identity=policy.identity, maximum_jobs=policy.maximum_jobs,
        maximum_primary_segments=policy.maximum_primary_segments,
        maximum_reserved_job_output_bytes=policy.maximum_reserved_job_output_bytes,
        maximum_observed_primary_seconds=policy.maximum_observed_primary_seconds,
        admitted=True, qualification='CONDITIONAL_CUMULATIVE_ADMISSION_NOT_COMPLETION_OR_PHYSICAL_QUALIFICATION',
        lifetime_work='B62_EXPLICIT_ACCOUNTING_DERIVATION_REQUIRED',
        resource_plan=__import__(__package__+'.lifetime_admission',fromlist=['resource_plan']).resource_plan(root))


def admit_lifetime_role_population(policy, intent, parent, checkpoint, jobs, target, *, store=None):
    from .lifetime_policy import admit_roles
    from .finite_campaign import intent_role
    admit_intent_limits(policy,intent)
    from .lifetime_no_launch import administrative_ids
    excluded=set()if store is None else administrative_ids(store)
    role=admit_roles(policy,intent,parent,checkpoint,jobs,target,administrative_job_ids=excluded)
    index={j['job_id']:j for j in jobs};spent={'PRIMARY':0.,'DIAGNOSTIC':0.}
    for job in jobs:
        previous=index.get(job['intent']['parent_job_id'])
        cp=None if job['resume']is None else job['resume']['checkpoint']
        r=intent_role(job['intent'],previous,cp,target)
        launch=job.get('launch');v=None if launch is None else launch.get('observed_envelope_seconds')
        if type(v)not in(int,float)or not 0<=v<float('inf'):v=policy.hard_seconds+policy.cleanup_seconds
        spent[r]+=v
    cap=policy.maximum_observed_primary_seconds if role=='PRIMARY'else policy.maximum_diagnostic_seconds
    if spent[role]+policy.hard_seconds+policy.cleanup_seconds>cap:raise ValueError('B62 full next-job wall reservation exhausted')
    return role


def admit_intent_limits(policy,intent):
    from .lifecycle_execution_budget import ExecutionBudget
    expected=ExecutionBudget(policy.hard_seconds,policy.soft_seconds,policy.finalization_seconds)
    if (intent['execution_seconds']!=policy.hard_seconds or
            intent['maximum_output_bytes']!=policy.maximum_output_bytes or
            intent.get('execution_budget')!=asdict(expected) or
            intent.get('execution_budget_identity')!=expected.identity):
        raise ValueError('lifetime intent must bind exact prospective worker allowance')
    return intent


def validate_settled_parent(store, job):
    """No UNKNOWN, forced suffix or journal summary becomes continuation authority."""
    from .battery_terminal import admit_bound_terminal, admit_native_terminal
    from .lifecycle_application import (_admit_execution_terminal, _settled_publication_work,
        _admit_publication, _verify_checkpoint_streams, _read, TERMINAL)
    from .lifecycle_checkpoint import admit_checkpoint, make_bindings
    if job['status']not in TERMINAL or job['ownership_valid'] is not True or job['result'] is None:
        raise ValueError('lifetime requires settled owned final native')
    launch=job['launch']
    if (launch is None or launch.get('forced_interruption') is not False or
            launch.get('timeout') is not False or launch.get('unexpected') is not None):
        raise ValueError('lifetime refuses uncertain paid suffix')
    result=job['result'];_admit_execution_terminal(job,result)
    terminal=admit_bound_terminal(result['typed_terminal'],job,result)
    cp=result['checkpoint'];directory=store.path('jobs',job['job_id'])
    settlement=_read(directory/'owned-settlement.json',65536)
    if settlement!=dict(format='B59_PARENT_OWNED_SETTLEMENT_V1',job_id=job['job_id'],
            root_identity=job['root_identity'],launch=launch):
        raise ValueError('lifetime durable owned settlement receipt binding')
    if (cp['kind'] != 'FINAL' or cp not in job['checkpoints'] or cp['clock'] != result['clock'] or
            cp['bindings'] != make_bindings(store.root_input, cp['clock'])):
        raise ValueError('lifetime final native binding')
    _settled_publication_work(directory,store.root_input,job,result)
    _admit_publication(directory,cp,store.root_input,settled=True)
    from .lifecycle_checkpoint import checkpoint_file_bytes
    from .lifetime_policy import physical_storage
    raw=checkpoint_file_bytes(directory/cp['file'],cp,store.root_input,
        require_transport=physical_storage(store.runner_policy))
    document=admit_checkpoint(raw,store.root_input,cp['sha256'],cp['bindings'])
    admit_native_terminal(document,terminal,result)
    _verify_checkpoint_streams(directory,cp,store.root_input,
        reserve=lambda n:store._reserve_saved_read(job['job_id'],n))
    elapsed=launch.get('observed_envelope_seconds')
    if type(elapsed) not in (int,float) or not 0 <= elapsed < float('inf'):
        raise ValueError('finite lifetime settled wall')
    return terminal, cp, elapsed
