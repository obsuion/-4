"""Immutable wrapper time policy. This module grants no scientific coverage.

The reserve is prospective engineering margin, not a bound on an unknown
model call or on host suspension. The parent still enforces its hard deadline.
"""
from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import time

METHOD = 'B55R2_WORKER_LOCAL_SOFT_BUDGET_V1'
INTENT = 'B55R2_DURABLE_BUDGET_INTENT_V2'
JOB = 'B55R2_OWNED_BUDGET_JOB_V2'
RECEIPT = 'B55R2_SETUP_INCLUSIVE_BUDGET_RECEIPT_V1'


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    hard_execution_seconds: int
    soft_stop_seconds: int
    finalization_reserve_seconds: int
    method: str = METHOD

    def __post_init__(self):
        if type(self.method) is not str or self.method != METHOD:
            raise ValueError('explicit worker-local budget method required')
        for name in ('hard_execution_seconds','soft_stop_seconds','finalization_reserve_seconds'):
            v=getattr(self,name)
            if type(v) is not int or not 1<=v<=1800:
                raise ValueError('exact finite execution budget integer required: '+name)
        if self.soft_stop_seconds+self.finalization_reserve_seconds!=self.hard_execution_seconds:
            raise ValueError('soft frontier and reserve must partition hard allowance')

    @property
    def identity(self):
        return sha256(json.dumps(asdict(self),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def admit_budget(value, *, execution_seconds):
    if type(value) is not dict or set(value)!=set(ExecutionBudget.__dataclass_fields__):
        raise ValueError('exact execution budget fields required')
    policy=ExecutionBudget(**value)
    if type(execution_seconds) is not int or execution_seconds!=policy.hard_execution_seconds:
        raise ValueError('budget hard allowance must bind the owned intent')
    return policy


class SoftBudgetGuard:
    """A worker-owned setup-inclusive monotonic guard; never polls a marker."""
    def __init__(self, policy, started, *, clock=time.perf_counter):
        if type(policy) is not ExecutionBudget:raise TypeError('exact immutable execution budget')
        policy.__post_init__()
        self.policy=policy;self.started=started;self.clock=clock
        self.cut_phase=None;self.cut_elapsed=None;self.last_elapsed=0.

    def boundary(self, phase):
        if phase not in ('BEFORE_TRANSITION','AFTER_COMMITTED_TRANSITION'):
            raise ValueError('only committed chronological boundaries may settle')
        elapsed=self.clock()-self.started
        if not isinstance(elapsed,(int,float)) or not 0<=elapsed<float('inf') or elapsed<self.last_elapsed:
            raise ValueError('finite nondecreasing monotonic worker clock')
        self.last_elapsed=elapsed
        if elapsed>=self.policy.soft_stop_seconds:
            if self.cut_phase is None:self.cut_phase=phase;self.cut_elapsed=elapsed
            return True
        return False

    def receipt(self):
        elapsed=self.clock()-self.started
        if not 0<=elapsed<float('inf') or elapsed<self.last_elapsed:raise ValueError('invalid final monotonic clock')
        return dict(format=RECEIPT,policy=asdict(self.policy),policy_identity=self.policy.identity,
                    clock_scope='WORKER_ENTRY_SETUP_INCLUSIVE_MONOTONIC',
                    cut_phase=self.cut_phase,cut_elapsed_seconds=self.cut_elapsed,
                    record_elapsed_seconds=elapsed,
                    stop_cause='BUDGET' if self.cut_phase is not None else 'NONE',
                    hard_deadline_guaranteed=False)


def admit_receipt(value, policy):
    fields=('format','policy','policy_identity','clock_scope','cut_phase','cut_elapsed_seconds',
            'record_elapsed_seconds','stop_cause','hard_deadline_guaranteed')
    if type(value) is not dict or set(value)!=set(fields):raise ValueError('exact worker budget receipt')
    if value['format']!=RECEIPT or value['policy']!=asdict(policy) or value['policy_identity']!=policy.identity or value['clock_scope']!='WORKER_ENTRY_SETUP_INCLUSIVE_MONOTONIC' or value['hard_deadline_guaranteed'] is not False:
        raise ValueError('worker budget receipt binding')
    elapsed=value['record_elapsed_seconds'];cut=value['cut_elapsed_seconds'];phase=value['cut_phase']
    if type(elapsed) not in (int,float) or not 0<=elapsed<float('inf'):raise ValueError('finite elapsed seconds')
    if phase is None:
        if cut is not None or value['stop_cause']!='NONE':raise ValueError('uncut receipt')
    elif phase not in ('BEFORE_TRANSITION','AFTER_COMMITTED_TRANSITION') or type(cut) not in (int,float) or not policy.soft_stop_seconds<=cut<=elapsed or value['stop_cause']!='BUDGET':
        raise ValueError('committed budget cut receipt')
    return value
