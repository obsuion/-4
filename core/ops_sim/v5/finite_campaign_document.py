"""Finite, serial, durable consumer of settled chronological native states.

Opening a chain is read-only and never dispatches. A claimed writer is never
stolen on PID guesses. UNKNOWN suffixes are not continuation authorities.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json, os, threading, time, uuid
from .experiment_codec import object_fields
from .lifecycle_contract import integer, identity, canonical
from .project_store import identifier, file_sha
from .lifecycle_execution_budget import ExecutionBudget, admit_budget

PLAN='B59_EIGHT_PRIMARY_PLAN_V1'
STATE='B55R2_HASH_LINKED_CHAIN_STATE_V1'
FIELDS=('format','chain_id','root_identity','input_sha256','source_identity','runtime',
        'maximum_primary_segments','reserved_diagnostic_slots','maximum_output_bytes',
        'maximum_observed_seconds','execution_budget','execution_budget_identity',
        'late_predecessor_rule','plan_identity')
STATES=('READY','DISPATCHING','RUNNING','BUDGET_CONTINUING','USER_PAUSED',
        'COMPLETED','PLAN_EXHAUSTED','ADMISSION_STOP','BLOCKED')
STATE_FIELDS=('format','plan_identity','sequence','previous_sha256','state','segments',
              'pending_intent','command_keys','reason','observed_seconds','estimate','failed_attempt')

def encoded(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return sha256(encoded(v)).hexdigest()

def make_plan(store, *, chain_id, execution_budget, maximum_primary_segments=8,
              maximum_output_bytes=128*2**20, maximum_observed_seconds=9600):
    identifier(chain_id)
    if type(execution_budget) is not ExecutionBudget:raise TypeError('immutable execution budget')
    p=dict(format=PLAN,chain_id=chain_id,root_identity=store.meta['root_identity'],
        input_sha256=store.meta['input_sha256'],source_identity=store.meta['source_identity'],
        runtime=store.meta['runtime'],maximum_primary_segments=maximum_primary_segments,
        reserved_diagnostic_slots=2,maximum_output_bytes=maximum_output_bytes,
        maximum_observed_seconds=maximum_observed_seconds,execution_budget=asdict(execution_budget),
        execution_budget_identity=execution_budget.identity,
        late_predecessor_rule='LATEST_RETAINED_WORKING_STRICTLY_BEFORE_TARGET_WITH_SUFFIX_AT_MOST_256_TRANSITIONS')
    p['plan_identity']=digest(p)
    return admit_plan(p,store)

def admit_plan(value,store):
    from .finite_campaign import FiniteCampaignPolicy
    if type(store.runner_policy)is not FiniteCampaignPolicy:raise ValueError('new B59 store required; no migration')
    p=object_fields(value,FIELDS);identifier(p['chain_id'])
    if p['format']!=PLAN or p['plan_identity']!=digest({k:v for k,v in p.items() if k!='plan_identity'}):raise ValueError('immutable chain plan identity')
    for key in ('root_identity','input_sha256','source_identity','runtime'):
        if p[key]!=store.meta[key]:raise ValueError('chain '+key+' binding')
    integer(p['maximum_primary_segments'],'finite primary segments',1,8)
    integer(p['maximum_output_bytes'],'finite segment output',2**20,128*2**20)
    integer(p['maximum_observed_seconds'],'finite chain allowance',1,10800)
    if type(p['reserved_diagnostic_slots']) is not int or p['reserved_diagnostic_slots']!=2:raise ValueError('reserve MAIN and loupe slots')
    if p['late_predecessor_rule']!='LATEST_RETAINED_WORKING_STRICTLY_BEFORE_TARGET_WITH_SUFFIX_AT_MOST_256_TRANSITIONS':raise ValueError('declared late predecessor selection')
    b=admit_budget(p['execution_budget'],execution_seconds=p['execution_budget']['hard_execution_seconds'])
    if p['execution_budget_identity']!=b.identity:raise ValueError('chain budget identity')
    if store.runner_policy is None or p['maximum_primary_segments']+2>store.maximum_jobs:raise ValueError('finite V2 store required')
    if (p['maximum_primary_segments']+2)*p['maximum_output_bytes']>store.maximum_reserved_job_output_bytes:raise ValueError('chain/diagnostics output reservations')
    if p['maximum_output_bytes']>store.root_input.policy.max_task_output_bytes:raise ValueError('root output allowance')
    if store.root_input.output_policy is not None:
        q=store.root_input.output_policy
        worker=p['maximum_output_bytes']-q.status_total_bytes-4*q.max_index_bytes-256*2**10
        if worker<=store.root_input.policy.max_checkpoint_bytes+327680:raise ValueError('chain output allowance after parent/checkpoint reserve')
    # 128 immutable metadata records of at most 256 KiB, plus small plan/owner.
    if (p['maximum_primary_segments']+2)*p['maximum_output_bytes']+33*2**20>store.maximum_reserved_job_output_bytes:raise ValueError('chain metadata plus job reservation')
    if b.hard_execution_seconds!=1550 or b.soft_stop_seconds!=1250 or b.finalization_reserve_seconds!=300:raise ValueError('B59 primary time partition')
    return deepcopy(p)

class LifecycleChain:
    """Publish the immutable base reservation only. Execution uses B59 controller."""
    def __init__(self,store,chain_id,*,plan):
        from .lifecycle_application import _write_new
        admit_plan(plan,store)
        if store.jobs() or store.path('chains',chain_id).exists():raise ValueError('new empty B59 plan required')
        _write_new(store.path('chains',chain_id,'plan.json'),plan)
