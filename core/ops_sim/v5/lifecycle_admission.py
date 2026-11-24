"""B54 invocation-local static admission; never a physical-result cache.

Original inputs receive the full accepted canonical constructor admission.
Afterwards a bounded field-edge seal rechecks their frozen object graph without
decoding it again. Mutable contexts, snapshots, ledgers and physical results
are never sealed as immutable. Every checkpoint still captures/reconstructs/
restores all dynamic state. Exact typed data comparison retains int/float,
signed-zero and schema-5 round-trip distinctions without constructor-decoding
the already reconstructed snapshots twice more.

This is separately accounted wrapper work, not a numerical-method change.
The compiled objects are process local and are NEVER checkpoint authority.
"""
from dataclasses import fields, is_dataclass
from enum import Enum
from fractions import Fraction
from math import isfinite
import sys

from ._experiment_types import RECORD_FIELDS, ENUM_TYPES
from .experiment_codec import canonical_content, check_schema_coverage
from .checkpoint import CheckpointState
from .context import SimulationInputs, SimulationContext


BASELINE = 'BASELINE'
COMPILED = 'B54_FROZEN_INPUT_ADMISSION_V1'
MODES = (BASELINE, COMPILED)
MAX_GRAPH_NODES = 2**18
MAX_WRAPPER_UNITS = 2**48
WORK_FIELDS = ('full_input_admissions', 'guards_reserved', 'guards_completed',
    'guards_failed', 'control_units_reserved', 'dynamic_checkpoint_checks')


def _runtime_token():
    return (sys.version, sys.executable, sys.platform)


def _work(value=None):
    result = {name: 0 for name in WORK_FIELDS} if value is None else dict(value)
    if set(result) != set(WORK_FIELDS) or any(type(v) is not int or not 0 <= v <= MAX_WRAPPER_UNITS for v in result.values()):
        raise ValueError('strict B54 static-admission wrapper work')
    if result['guards_completed']+result['guards_failed'] != result['guards_reserved']:
        raise ValueError('static-admission guard balance')
    return result


def validate_wrapper_data(value):
    if (type(value) is not dict or set(value) != {'method', 'root_identity', 'source_identity', 'actual', 'forecast'} or
            type(value['method']) is not str or value['method'] != COMPILED):
        raise ValueError('exact B54 wrapper fields/method')
    for name in ('root_identity', 'source_identity'):
        v = value[name]
        if type(v) is not str or len(v) != 64 or any(c not in '0123456789abcdef' for c in v):
            raise ValueError('exact static-admission identity')
    for role in ('actual', 'forecast'):
        if type(value[role]) is not dict: raise TypeError('wrapper work object')
        _work(value[role])
    return value


def _tree(value, budget, depth=0):
    budget[0] += 1
    if budget[0] > MAX_GRAPH_NODES or depth > 64:
        raise ValueError('bounded exact checkpoint comparison')
    owner = type(value)
    if value is None: return ('none',)
    if owner in (bool, int, str): return (owner.__name__, value)
    if owner is float:
        if not isfinite(value): raise ValueError('finite checkpoint scalar')
        return ('float', value.hex())
    if owner is Fraction: return ('fraction', value.numerator, value.denominator)
    if owner is tuple: return ('tuple', tuple(_tree(x,budget,depth+1) for x in value))
    if owner is list: return ('list', tuple(_tree(x,budget,depth+1) for x in value))
    if owner is dict:
        if any(type(k) is not str for k in value): raise TypeError('exact checkpoint text keys')
        return ('map', tuple((k,_tree(value[k],budget,depth+1)) for k in sorted(value)))
    if owner in ENUM_TYPES:
        if value is not owner.__members__.get(value.name): raise ValueError('exact checkpoint enum')
        return ('enum', owner.__module__, owner.__name__, value.name)
    if owner not in RECORD_FIELDS: raise TypeError('unreviewed checkpoint comparison owner')
    return ('record', owner.__module__, owner.__name__,
        tuple((n,_tree(getattr(value,n),budget,depth+1)) for n in RECORD_FIELDS[owner]))


class AdmittedInputs:
    """One role's cache and monotone observational wrapper ledger.

    All direct field edges are checked by identity, so a deep object.__setattr__
    edit cannot exploit cached hashes, overloaded equality, or an old root.
    Even an equal foreign replacement requires a NEW full admission.
    """
    def __init__(self, inputs, root_identity, source_identity, role, *, prior=None):
        if type(inputs) is not SimulationInputs or type(role) is not str or role not in ('ACTUAL','FORECAST'):
            raise TypeError('exact immutable inputs and explicit ownership required')
        for value in (root_identity,source_identity):
            if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('exact immutable root/source identity required')
        self.work = _work(prior)
        self.root_identity, self.source_identity, self.role = root_identity, source_identity, role
        self.runtime = _runtime_token()
        self.inputs = inputs
        self._binding=(inputs,root_identity,source_identity,role,self.runtime)
        if (self.work['control_units_reserved']+MAX_GRAPH_NODES>MAX_WRAPPER_UNITS or
                self.work['full_input_admissions']>=MAX_WRAPPER_UNITS):
            raise ValueError('B54_STATIC_ADMISSION_WRAPPER_QUOTA_BEFORE_WORK')
        self.work['control_units_reserved']+=MAX_GRAPH_NODES
        canonical_content(inputs)  # full original constructor/codec trust boundary
        self.work['full_input_admissions'] += 1
        self.edges=[]; self.scalar_seals=[]; visited=set(); count=0
        def capture(v, depth=0):
            nonlocal count
            count+=1
            if count > MAX_GRAPH_NODES or depth>64: raise ValueError('bounded immutable admission graph')
            t=type(v)
            if v is None or t in (str,int,float,bool): return
            if t is Fraction:
                self.scalar_seals.append(('fraction',v,v.numerator,v.denominator))
                return
            if t in ENUM_TYPES:
                if v is not t.__members__.get(v.name): raise ValueError('immutable enum member')
                if type(v.value) not in (str,int,float,bool):
                    raise TypeError('compiled enum requires an immutable built-in scalar value')
                self.scalar_seals.append(('enum',v,t,v.name,v.value))
                return
            if t is tuple:
                for x in v: capture(x,depth+1)
                return
            if t not in RECORD_FIELDS or not is_dataclass(v) or not t.__dataclass_params__.frozen:
                raise TypeError('compiled cache requires the fully frozen canonical input graph')
            if id(v) in visited:return
            visited.add(id(v))
            names=RECORD_FIELDS[t]
            fs=fields(t)
            if tuple(f.name for f in fs)!=names or any(not f.init for f in fs):
                raise ValueError('reviewed immutable fields required')
            edges=tuple((n,getattr(v,n)) for n in names)
            self.edges.append((v,t,t.__dataclass_fields__,edges))
            for _,x in edges:capture(x,depth+1)
        capture(inputs)
        self.node_count=count
        self.edges=tuple(self.edges)
        self.scalar_seals=tuple(self.scalar_seals)
        self._schema=tuple((owner,names,owner.__dataclass_fields__,len(owner.__dataclass_fields__),
            tuple((n,owner.__dataclass_fields__[n]) for n in names),getattr(owner,'prefix',None))
            for owner,names in RECORD_FIELDS.items())
        self.guard_units=self.node_count+1
        self.schema_units=sum(2+len(row[4]) for row in self._schema)

    def guard(self, inputs, *, root_identity=None, role=None, check_schema=False):
        if type(check_schema) is not bool:raise TypeError('exact schema guard flag')
        if type(self.work) is not dict:raise TypeError('exact static-admission wrapper work')
        _work(self.work)
        w=self.work; charge=self.guard_units+(self.schema_units if check_schema else 0)
        if w['control_units_reserved']+charge>MAX_WRAPPER_UNITS:
            raise ValueError('B54_STATIC_ADMISSION_WRAPPER_QUOTA_BEFORE_WORK')
        w['control_units_reserved']+=charge; w['guards_reserved']+=1
        try:
            if (inputs is not self.inputs or self.inputs is not self._binding[0] or
                    type(self.root_identity) is not str or self.root_identity!=self._binding[1] or
                    type(self.source_identity) is not str or self.source_identity!=self._binding[2] or
                    type(self.role) is not str or self.role!=self._binding[3] or
                    self.runtime != self._binding[4] or self.runtime != _runtime_token() or
                    root_identity is not None and (type(root_identity) is not str or root_identity != self.root_identity) or
                    role is not None and (type(role) is not str or role != self.role)):
                raise ValueError('foreign static input/root/runtime/role authority')
            # Preserve complete global codec-schema drift detection without the
            # repeated dataclasses.fields allocation used by the general codec.
            if check_schema:
                if len(RECORD_FIELDS)!=len(self._schema):raise ValueError('canonical schema changed')
                for owner,names,mapping,count,items,prefix in self._schema:
                    if RECORD_FIELDS.get(owner) is not names or owner.__dataclass_fields__ is not mapping:
                        raise ValueError('canonical schema replaced')
                    if len(mapping)!=count or getattr(owner,'prefix',None) is not prefix:
                        raise ValueError('canonical schema fields/class authority changed')
                    for name,field in items:
                        if mapping.get(name) is not field or field.name!=name or not field.init:
                            raise ValueError('canonical schema field changed')
            for obj,owner,mapping,edges in self.edges:
                if type(obj) is not owner or owner.__dataclass_fields__ is not mapping:
                    raise ValueError('immutable owner/schema changed')
                for name,original in edges:
                    if getattr(obj,name) is not original:
                        raise ValueError('immutable input field changed: '+name)
            for seal in self.scalar_seals:
                kind,value,*expected=seal
                if kind=='fraction':
                    if (type(value) is not Fraction or type(value.numerator) is not int or
                            type(value.denominator) is not int or
                            value.numerator!=expected[0] or value.denominator!=expected[1]):
                        raise ValueError('immutable Fraction authority changed')
                else:
                    owner,name,original=expected
                    if (type(value) is not owner or type(value.name) is not str or value.name is not name or
                            value.value is not original or owner.__members__.get(value.name) is not value):
                        raise ValueError('immutable enum authority changed')
        except BaseException:
            w['guards_failed']+=1
            raise
        w['guards_completed']+=1

    def checked_checkpoint(self, context):
        if type(context) is not SimulationContext:raise TypeError('exact completed context required')
        self.guard(context.inputs,check_schema=True)
        self.work['dynamic_checkpoint_checks']+=1
        snapshot=CheckpointState.from_context(context)
        reconstructed=CheckpointState.from_dict(snapshot.to_dict())
        if _tree(snapshot,[0]) != _tree(reconstructed,[0]):
            raise ValueError('runtime state is not losslessly representable by schema 5')
        reconstructed.restore(context.inputs)
        return reconstructed


class CompiledLifecycleContext:
    def __init__(self, root, model, *, source_identity=None, prior=None):
        if source_identity is None:
            from .spacecraft_project import project_source_identity
            source_identity=project_source_identity()
        if prior is not None:
            validate_wrapper_data(prior)
            if prior['root_identity']!=root.identity or prior['source_identity']!=source_identity:
                raise ValueError('foreign inherited wrapper root/source')
        self.root=root;self.root_identity=root.identity;self.source_identity=source_identity
        self.actual=AdmittedInputs(model.simulation_inputs,root.identity,source_identity,'ACTUAL',
            prior=None if prior is None else prior['actual'])
        self.forecast=AdmittedInputs(model.simulation_inputs,root.identity,source_identity,'FORECAST',
            prior=None if prior is None else prior['forecast'])

    def guard(self, root, model):
        if root is not self.root or root.identity!=self.root_identity:
            raise ValueError('foreign lifecycle compiled root')
        self.actual.guard(model.simulation_inputs,root_identity=root.identity,role='ACTUAL')
        self.forecast.guard(model.simulation_inputs,root_identity=root.identity,role='FORECAST')

    def to_data(self):
        return validate_wrapper_data(dict(method=COMPILED,root_identity=self.root_identity,
            source_identity=self.source_identity,actual=dict(self.actual.work),forecast=dict(self.forecast.work)))
