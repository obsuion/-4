"""Private B65 synchronous validation ownership; never codec/checkpoint DATA.

The outer transaction has full guards on both sides. No foreign callbacks may
run while the capability is CLOSED. Callback suspension forces full guards and
disallows reentrant transactions. This owns validation, not physical state.
"""
import os, threading
_KEY=object()
METHOD='B65_CLOSED_GENERATION_CONTROL_V1'

class _Generation:
    __slots__=('_job','_hook','_pins','_root','_phase','_epoch','_counts')
    def __init__(self,job,hook,key):
        if key is not _KEY:raise TypeError('B65 private generation factory')
        self._job=job;self._hook=hook;self._root=None;self._phase='IDLE';self._epoch=0
        self._pins=(self,job,hook,os.getpid(),threading.get_ident(),job._binding,job.source_binding,job._admission_pins)
        self._counts=dict(full_requests=0,closed_requests=0,activations=0,callback_suspensions=0,invalidations=0,machine_world_steps=0,reference_world_steps=0)
    def cheap(self,expected_job=None):
        p=self._pins;j=self._job
        if (expected_job is not None and expected_job is not j or type(self)is not _Generation or p[0]is not self or p[1]is not j or p[2]is not self._hook or
                p[3]!=os.getpid()or p[4]!=threading.get_ident()or p[5]is not j._binding or p[6]!=j.source_binding or
                p[7]is not j._admission_pins or j._validation is not self or j._validation_pin is not self or j._closed or
                type(self._epoch)is not int or not 0<=self._epoch<=2**40 or type(self._counts)is not dict or
                set(self._counts)!={'full_requests','closed_requests','activations','callback_suspensions','invalidations','machine_world_steps','reference_world_steps'}or
                any(type(v)is not int or not 0<=v<2**40 for v in self._counts.values())):
            raise ValueError('B65 foreign/thread/generation/control drift')
        if self._phase not in('IDLE','CLOSED','CALLBACK','BOUNDARY','INVALID'):raise ValueError('B65 generation phase')
        if self._phase=='INVALID':raise ValueError('B65 invalidated generation')
        return self
    def closed(self,transaction=None):
        self.cheap();j=self._job;t=j._active
        if self._phase!='CLOSED':return False
        if (self._root is None or self._root._phase!='ACTIVE'or t is None or t._phase!='ACTIVE'or
                t._job is not j or not 0<self._root._generation<=t._generation<=j._generation or
                transaction is not None and transaction is not t):raise ValueError('B65 stale closed generation')
        cursor=t
        while cursor is not self._root:
            cursor=cursor._parent
            if cursor is None:raise ValueError('B65 unrelated transaction generation')
        return True
    def activate(self,transaction):
        self.cheap()
        if self._phase!='IDLE'or self._root is not None or self._job._active is not transaction:raise ValueError('B65 generation activation')
        self._epoch+=1;self._root=transaction;self._phase='CLOSED';self._counts['activations']+=1
    def boundary(self):
        self.cheap();self._phase='BOUNDARY'
    def verify_boundary(self):
        self.cheap()
        if self._phase!='BOUNDARY':raise ValueError('B66 full validation requires boundary phase')
        self._hook()
    def callback_begin(self):
        if not self.closed():raise ValueError('B65 callback outside closed generation')
        self._phase='CALLBACK';self._counts['callback_suspensions']+=1
        self._hook()
    def callback_end(self):
        self.cheap()
        if self._phase not in('CALLBACK','BOUNDARY'):raise ValueError('B65 callback boundary phase')
        self._hook();self._epoch+=1;self._phase='CLOSED'
    def finish(self,failed):
        self._counts['invalidations']+=1;self._root=None;self._phase='IDLE';self._epoch+=1
    def snapshot(self):
        self.cheap()
        return dict(method=METHOD,epoch=self._epoch,phase=self._phase,**self._counts,
            scientific_work='UNCHANGED',legacy_control='UNCHANGED_LOGICAL_BOUNDARY_PREPAYMENT_NOT_CPU_INSTRUCTIONS',
            scope='PROCESS_LOCAL_STATIC_VALIDATION_ONLY_NO_DYNAMIC_RESULTS')
    def __copy__(self):raise TypeError('B65 generation cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('B65 generation cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('B65 generation cannot be persisted')

def enable(job,hook):
    from .lifecycle_job_prepared import PreparedJobRuntime,_guard_generation_owner
    _guard_generation_owner()
    if type(job)is not PreparedJobRuntime or job._active is not None or job._validation is not None or not callable(hook):raise ValueError('B65 once-only current-job generation')
    job._full_guard();value=_Generation(job,hook,_KEY);job._validation=value;job._validation_pin=value
    return value
