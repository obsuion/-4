"""B60 bounded invocation-local immutable admission and identity memo.

No mutable state or numerical result is cached. Every hit checks all reachable
frozen field identities and Fraction internals. Reference is the default.
Work below counts real cache operations, never fabricated legacy calls.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import fields,is_dataclass
from fractions import Fraction
from enum import Enum
import math,sys

REFERENCE='REFERENCE_B59'
FAST='B60_SEALED_STATIC_V1'
ACTIVE=ContextVar('B60_FAST',default=None)
MAX_ENTRIES=128
MAX_NODES=16384
MAX_BYTES=64*2**20


def _seal(value):
    edges=[];scalars=[];seen=set();size=0
    def walk(v,depth=0):
        nonlocal size
        if depth>64 or len(edges)+len(scalars)>MAX_NODES:raise ValueError('B60_IMMUTABLE_GRAPH_LIMIT')
        t=type(v)
        if v is None or t in (str,int,bool):return
        if t is float:
            if not math.isfinite(v):raise ValueError('B60_NONFINITE_STATIC')
            return
        if t is Fraction:
            scalars.append((v,v.numerator,v.denominator));return
        if isinstance(v,Enum):
            if type(v.value) not in (str,int,float,bool):raise TypeError('B60_ENUM_VALUE')
            edges.append((v,t,tuple((n,getattr(v,n))for n in ('_name_','_value_')),None));return
        if t is tuple:
            for x in v:walk(x,depth+1)
            return
        if not is_dataclass(v) or not t.__dataclass_params__.frozen:raise TypeError('B60_ONLY_FROZEN_STATIC_RECORDS')
        if id(v) in seen:return
        seen.add(id(v));es=tuple((f.name,getattr(v,f.name))for f in fields(v))
        mapping=t.__dataclass_fields__;schema=(mapping,tuple((n,f)for n,f in mapping.items()))
        edges.append((v,t,es,schema));size+=sys.getsizeof(v)+sys.getsizeof(es)+sum(sys.getsizeof(e)for e in es)
        for _,x in es:walk(x,depth+1)
    walk(value)
    return tuple(edges),tuple(scalars),size+len(scalars)*128+len(edges)*256+1024


def _guard(seal):
    edges,scalars,_=seal
    for obj,owner,es,schema in edges:
        if schema is not None:
            mapping,items=schema
            if owner.__dataclass_fields__ is not mapping or len(mapping)!=len(items) or any(mapping.get(n)is not f or f.name!=n for n,f in items):raise ValueError('B60_STATIC_SCHEMA_DRIFT')
        if type(obj)is not owner:raise ValueError('B60_STATIC_TYPE_DRIFT')
        for name,old in es:
            if getattr(obj,name)is not old:raise ValueError('B60_STATIC_FIELD_DRIFT:'+name)
    for v,n,d in scalars:
        if type(v)is not Fraction or type(v.numerator)is not int or type(v.denominator)is not int or v.numerator!=n or v.denominator!=d:
            raise ValueError('B60_STATIC_FRACTION_DRIFT')


class StaticSession:
    def __init__(self,binding):
        if type(binding)is not str or len(binding)!=64 or any(c not in '0123456789abcdef'for c in binding):raise ValueError('B60_SOURCE_INPUT_BINDING')
        self.binding=binding;self.entries={};self.retained_bytes=0
        self.work=dict(method=FAST,binding=binding,hits=0,misses=0,guards=0,full_operations=0,evictions=0,retained_peak_bytes=0)
    def compute(self,key,authority,operation):
        e=self.entries.get(key)
        if e is not None:
            _guard(e[0]);self.work['guards']+=1;self.work['hits']+=1
            return e[1]
        self.work['misses']+=1;self.work['full_operations']+=1
        result=operation();seal=_seal(authority)
        if seal[2]>MAX_BYTES:raise ValueError('B60_STATIC_CACHE_BYTES')
        while self.entries and (len(self.entries)>=MAX_ENTRIES or self.retained_bytes+seal[2]>MAX_BYTES):
            oldest=next(iter(self.entries));self.retained_bytes-=self.entries.pop(oldest)[0][2];self.work['evictions']+=1
        self.entries[key]=(seal,result,authority);self.retained_bytes+=seal[2]
        self.work['retained_peak_bytes']=max(self.work['retained_peak_bytes'],self.retained_bytes)
        return result
    def snapshot(self):return dict(self.work,retained_bytes=self.retained_bytes,entries=len(self.entries),scope='CURRENT_PROCESS_STATIC_RECONSTRUCTION_NOT_PHYSICAL_WORK')


@contextmanager
def execution_strategy(strategy,binding):
    if strategy not in (REFERENCE,FAST):raise ValueError('B60_STRATEGY')
    if ACTIVE.get() is not None:raise ValueError('B60_NESTED_STRATEGY')
    session=None if strategy==REFERENCE else StaticSession(binding)
    token=ACTIVE.set(session)
    try:yield session
    finally:ACTIVE.reset(token)


def admit_policy(policy):
    session=ACTIVE.get();owner=type(policy);fn=owner.__post_init__
    if session is None:return fn(policy)
    return session.compute(('policy',id(policy),owner,fn),policy,lambda:fn(policy))


def authority_identity(value,operation):
    session=ACTIVE.get()
    if session is None:return operation()
    # Callers supply an exact tuple of frozen authority records/scalars.
    if type(value)is not tuple:raise TypeError('B60_AUTHORITY_TUPLE')
    key=('identity',tuple((type(x),id(x))for x in value))
    return session.compute(key,value,operation)
