"""Invocation-local dispatch to bound exact metadata loops; no result cache."""
from contextvars import ContextVar
from contextlib import contextmanager
from types import ModuleType
import os,threading

_ACTIVE=ContextVar('YEAR_V1_EXACT_METADATA',default=None)
_NAMES=('input_owner_signature_v1','scientific_output_v1','metadata_codec_counts_v1','canonical_encode_v2','canonical_decode_v2','schema_coverage_v2','canonical_codec_counts_v2','metadata_scope_check_v2')

class _Scope:
    __slots__=('native','calls','pid','thread','closed','pins','gate_code')
    def __init__(self,native):
        if type(native)is not ModuleType or native.__name__!='ops_sim.v5._lifecycle_typed65':raise TypeError('YEAR-V1 admitted native module')
        self.native=native;self.calls=tuple((n,getattr(native,n))for n in _NAMES)
        self.pid=os.getpid();self.thread=threading.get_ident();self.closed=False
        self.gate_code=self.calls[7][1].__code__
        self.pins=(native,self.calls,self.pid,self.thread,self.gate_code)
        self.check()
    def check(self):
        # Independent pre-call origin/code check; a Python or foreign native
        # function cannot stand in for this guard. The C loop then rechecks
        # EVERY original live binding and export, including itself.
        if type(self.calls)is not tuple or len(self.calls)!=8:raise ValueError('metadata scope call binding')
        gate=self.calls[7][1];t=type(gate)
        if (self.gate_code is not self.pins[4]or getattr(gate,'__code__',None)is not self.gate_code or
                t.__module__!='_cython_3_2_4'or t.__name__!='cython_function_or_method'or t.__flags__&384!=384 or
                getattr(gate,'__module__',None)!='ops_sim.v5._lifecycle_typed65'or
                getattr(gate,'__name__',None)!='metadata_scope_check_v2'or
                getattr(gate,'__globals__',None)is not self.native.__dict__ or
                getattr(self.native,'metadata_scope_check_v2')is not gate):
            raise ValueError('YEAR-V2 independent metadata guard origin drift')
        gate(self,os.getpid(),threading.get_ident())
    def __copy__(self):raise TypeError('metadata scope not copyable')
    def __deepcopy__(self,memo):raise TypeError('metadata scope not copyable')
    def __reduce_ex__(self,protocol):raise TypeError('metadata scope not persistent')

@contextmanager
def metadata_scope(native):
    current=_ACTIVE.get()
    if current is not None:
        if type(current)is not _Scope:raise TypeError('YEAR-V2 exact nested metadata scope')
        current.check()
        if current.native is not native:raise ValueError('YEAR-V1 foreign nested metadata implementation')
        try:yield current
        except BaseException as primary:
            try:current.check()
            except BaseException as secondary:primary.add_note('YEAR-V1 secondary nested metadata scope: '+repr(secondary))
            raise
        else:current.check()
        return
    scope=_Scope(native);token=_ACTIVE.set(scope)
    try:
        try:yield scope
        except BaseException as primary:
            try:scope.check()
            except BaseException as secondary:primary.add_note('YEAR-V1 secondary metadata scope: '+repr(secondary))
            raise
        else:scope.check()
    finally:scope.closed=True;_ACTIVE.reset(token)

@contextmanager
def admitted_metadata_scope(build):
    from .lifecycle_typed_platform import admit_typed_build
    native=admit_typed_build(build)
    with metadata_scope(native)as scope:yield scope


def owner_signature(owner):
    scope=_ACTIVE.get()
    if scope is None:return None
    if type(scope)is not _Scope:raise TypeError('YEAR-V2 exact metadata scope')
    scope.check();result=scope.calls[0][1](owner);scope.check();return result


def scientific(value,reference):
    scope=_ACTIVE.get()
    if scope is None:return reference(value)
    if type(scope)is not _Scope:raise TypeError('YEAR-V2 exact metadata scope')
    scope.check();result=scope.calls[1][1](value);scope.check();return result


def canonical_encode(value,reference,namespace):
    scope=_ACTIVE.get()
    if scope is None:return reference(value)
    if type(namespace)is not dict or namespace is not reference.__globals__:raise ValueError('YEAR-V2 canonical namespace')
    if type(scope)is not _Scope:raise TypeError('YEAR-V2 exact metadata scope')
    scope.check();result=scope.calls[3][1](value,namespace);scope.check();return result

def canonical_decode(value,reference,namespace):
    scope=_ACTIVE.get()
    if scope is None:return reference(value)
    if type(namespace)is not dict or namespace is not reference.__globals__:raise ValueError('YEAR-V2 canonical namespace')
    if type(scope)is not _Scope:raise TypeError('YEAR-V2 exact metadata scope')
    scope.check();result=scope.calls[4][1](value,namespace);scope.check();return result

def canonical_schema(records,field_function,reference):
    scope=_ACTIVE.get()
    if scope is None:return reference()
    if type(scope)is not _Scope:raise TypeError('YEAR-V2 exact metadata scope')
    scope.check();result=scope.calls[5][1](records,field_function);scope.check();return result
