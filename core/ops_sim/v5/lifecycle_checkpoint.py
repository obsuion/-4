"""Bounded direct lifecycle checkpoints, trusted only with an external SHA pin.

No pickle, executable payload type, dynamic import, or causal-prefix replay is
accepted. The local fixed graph registry is distinct from B51's registry. Only
known cached derived geometry uses its two dedicated data materializers.
Original trajectory authorities MUST remain caller-root references; their
numerical constructors cannot be invoked by an advanced-state payload.

Checkpoint encoding is pure relative to scientific state. New encoding/storage
allowances belong to the external publication ledger/manifest. Restore validation
work is returned separately and never rewrites the prior paid scientific ledger.
"""
from .lifetime_io_accounting import fsync as _io_fsync
from dataclasses import fields, is_dataclass, asdict
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from enum import Enum
from pathlib import Path
import json, math, os, uuid

from ._snapshot_records import (RECORD_FIELDS as BASE_RECORD_FIELDS,
    ENUMS as BASE_ENUMS, validate_schema as validate_base_schema,
    GroundPointGeometry, restore_ground_geometry,
    GroundVisibilityResult, restore_ground_visibility)
from .experiment_codec import parse_json, object_fields
from .rolling_cache import canonical_size
from .orbit_j2 import J2CartesianTrajectory
from .environment_forcing import ForcingProfileEntry, NodeForcing
from .lifecycle_orbit import LifecycleOrbitPolicy, LifecycleOrbitProvider
from .lifecycle_world import ReducedSunPolicy, LifecycleWorld, AcquiredLifecycleWorld
from .lifecycle_state import (LifecycleObservation, LifecycleIntent,
    LifecycleActiveRequest, LifecycleDeferredFeedback, LifecycleWork, LifecycleState, guard_lifecycle)
from .lifecycle_physics import (LifecyclePhysicsLimits, LifecycleConstructionLimits,
    LifecycleConstructionWork, LifecycleHarnessWork, LifecyclePhysicalModel,
    LifecyclePhysicalInputs, LifecycleConstructionBinding, LifecycleHarnessBinding,
    LifecycleReceipt, PendingLifecycleAction, LifecyclePhysicalState,
    LifecycleActionOutcome,LifecycleRefusalDetail)
from .lifecycle_contract import METHOD, METHOD53, METHOD55, identity, integer
from .lifecycle_service import (PowerServicePolicy,PowerServiceState,PowerServiceWork,PowerServiceDecision)
from .construction_service import (ConstructionServicePolicy,ConstructionServiceWork,
    ConstructionServiceDiagnostic,ConstructionServiceFailureDiagnostic,ConstructionServicePhysicalResult)
from .lifecycle_service_contact import ServiceContactOutcome,ServiceContactExecutionResult,ServiceContactResult
from .solar_attitude import EnergyAttitudePolicy,SolarTarget,SolarAction,SolarAttitudeState,SolarSpatialSlew
from .lifecycle_quiet import QuietIntegrationPolicy, QuietControllerState, QuietWork, ShortCircuitQuietWork, is_short_circuit_policy
from .battery_port import BatteryPortPolicy,BatteryPortState,BatteryPortWork,BatteryPortTransition,BatteryPortSolution
from .battery_port_construction import (PortEPSResult,PortConstructionEPSResult,PortCoupledResult,
    PortConstructionPhysicalResult,PortServiceDiagnostic,PortServiceFailureDiagnostic)
from .lifecycle_quiet import BatteryQuietIntegrationPolicy
from .lifecycle_document import dumps_root
from .environment_lifecycle import EnvironmentSolarTransition,EnvironmentCoupledResult
from .environment_ageing import EnvironmentAgeingPolicy,EnvironmentAgeingState,EnvironmentAgeingWork,EmissivityAgeing,ConductanceAgeing
from .lifecycle_quiet import EnvironmentQuietIntegrationPolicy
from .checkpoint import CheckpointState
from .long_mission import RuntimeWork
from .rolling_contract import ReleasedRequest, DeclaredContact


MAX_BYTES = 64*2**20
MAX_NODES = 131072
MAX_ITEMS = 65536
MAX_DEPTH = 64
FORMAT = 'B52_FIXED_ADVANCED_DAG_V1'
CHECKPOINT_FORMAT = 'B52_TRUSTED_COMPACT_CHECKPOINT_V1'
CHECKPOINT_FORMAT53 = 'B53_TRUSTED_QUIET_COMPACT_CHECKPOINT_V2'
CHECKPOINT_FORMAT54 = 'B54_COMPILED_WRAPPER_CHECKPOINT_V3'
CHECKPOINT_FORMAT55 = 'B55_POWER_SERVICE_CHECKPOINT_V4'
CHECKPOINT_FORMAT56 = 'B56_SOLAR_ATTITUDE_CHECKPOINT_V5'
CHECKPOINT_FORMAT58 = 'B59_TYPED_BATTERY_CHECKPOINT_V7'
CHECKPOINT_FORMAT61 = 'B61_EXPOSURE_THERMAL_CHECKPOINT_V8'
CHECKPOINT_FORMAT63 = 'B63_PREPARED_EXPOSURE_EXECUTION_CHECKPOINT_V1'
CHECKPOINT_FORMAT64 = 'B64_TYPED_EXPOSURE_EXECUTION_CHECKPOINT_V1'
CHECKPOINT_FORMAT65 = 'B65_TYPED_EXPOSURE_EXECUTION_CHECKPOINT_V2'
CHECKPOINT_FORMAT_YEAR5 = 'YEAR_V5_TYPED_SHORT_CIRCUIT_CHECKPOINT_V1'
MANIFEST_FORMAT = 'B52_IMMUTABLE_CHECKPOINT_MANIFEST_V1'
CONTROL_ALLOWANCE = 16*9*MAX_NODES+2*((MAX_BYTES+63)//64)

# These classes are chosen by SOURCE, never by payload imports. Existing B51
# schemas remain pinned exactly; new class field sets are bound to this source
# fingerprint and checked for init-only materialization before use.
NEW_RECORDS = (ForcingProfileEntry, NodeForcing, LifecycleOrbitPolicy,
    ReducedSunPolicy, LifecycleWorld, LifecycleObservation, LifecycleIntent,
    LifecycleActiveRequest, LifecycleDeferredFeedback, LifecycleWork, LifecyclePhysicsLimits,
    LifecycleConstructionLimits, LifecycleConstructionWork, LifecycleHarnessWork,
    LifecyclePhysicalModel, LifecyclePhysicalInputs, LifecycleConstructionBinding,
    LifecycleHarnessBinding, LifecycleReceipt, PendingLifecycleAction,
    LifecycleActionOutcome,LifecycleRefusalDetail,
    ReleasedRequest, DeclaredContact, QuietIntegrationPolicy, QuietControllerState, QuietWork, ShortCircuitQuietWork,
    PowerServicePolicy,PowerServiceState,PowerServiceWork,PowerServiceDecision,
    ConstructionServicePolicy,ConstructionServiceWork,ConstructionServiceDiagnostic,ConstructionServiceFailureDiagnostic,ConstructionServicePhysicalResult,
    ServiceContactOutcome,ServiceContactExecutionResult,ServiceContactResult,
    EnergyAttitudePolicy,SolarTarget,SolarAction,SolarAttitudeState,SolarSpatialSlew)
PORT_TYPES=(BatteryPortPolicy,BatteryPortState,BatteryPortWork,BatteryPortTransition,BatteryPortSolution,
    PortEPSResult,PortConstructionEPSResult,PortCoupledResult,PortConstructionPhysicalResult,
    PortServiceDiagnostic,PortServiceFailureDiagnostic,BatteryQuietIntegrationPolicy)
ENVIRONMENT_TYPES=(EnvironmentSolarTransition,EnvironmentCoupledResult,EnvironmentAgeingPolicy,EnvironmentAgeingState,EnvironmentAgeingWork,EmissivityAgeing,ConductanceAgeing,EnvironmentQuietIntegrationPolicy)
NEW_RECORDS=(*NEW_RECORDS,*PORT_TYPES,*ENVIRONMENT_TYPES)
RECORD_FIELDS = dict(BASE_RECORD_FIELDS)
RECORD_FIELDS.update({owner: tuple(f.name for f in fields(owner)) for owner in NEW_RECORDS})
RECORDS = {owner.__module__+'.'+owner.__name__: owner for owner in RECORD_FIELDS}
ENUMS = dict(BASE_ENUMS)
# The optional B55 Python attributes must not change a legacy graph's record
# wire. These are fixed source-owned omissions, never fields selected by data.
LEGACY_OMITTED_FIELDS={LifecycleObservation:('service_state','command_completed_at_seconds'),
    LifecyclePhysicalModel:('service_policy',),
    LifecycleActionOutcome:('service_work_before','service_work_after','service_state_after')}
SOLAR_OMITTED_FIELDS={LifecycleObservation:('solar_state','solar_pending'),
    LifecyclePhysicalModel:('energy_attitude_policy',),PendingLifecycleAction:('solar_target',),
    LifecycleActionOutcome:('solar_target','solar_state_before','solar_state_after')}
SOLAR_TYPES=(EnergyAttitudePolicy,SolarTarget,SolarAction,SolarAttitudeState,SolarSpatialSlew)
PORT_OMITTED_FIELDS={LifecycleObservation:('battery_port_state',),LifecyclePhysicalModel:('battery_port_policy',),
    LifecycleActionOutcome:('battery_port_state_before','battery_port_state_after'),ServiceContactResult:('battery_port_state',)}
ENVIRONMENT_OMITTED_FIELDS={LifecycleActionOutcome:('environment_ageing_state_before','environment_ageing_state_after'),LifecycleObservation:('environment_ageing_state',),LifecyclePhysicalModel:('environment_ageing_policy',),ServiceContactResult:('environment_ageing_state',)}
B58_RECORD_FIELDS={owner:tuple(n for n in names if n not in ENVIRONMENT_OMITTED_FIELDS.get(owner,()))for owner,names in RECORD_FIELDS.items()if owner not in ENVIRONMENT_TYPES}
for owner,names in ENVIRONMENT_OMITTED_FIELDS.items():LEGACY_OMITTED_FIELDS[owner]=(*LEGACY_OMITTED_FIELDS.get(owner,()),*names)
B56_RECORD_FIELDS={owner:tuple(n for n in names if n not in PORT_OMITTED_FIELDS.get(owner,())) for owner,names in B58_RECORD_FIELDS.items() if owner not in PORT_TYPES}
for owner,names in PORT_OMITTED_FIELDS.items():LEGACY_OMITTED_FIELDS[owner]=(*LEGACY_OMITTED_FIELDS.get(owner,()),*names)
B55_RECORD_FIELDS={owner:tuple(n for n in names if n not in SOLAR_OMITTED_FIELDS.get(owner,())) for owner,names in B56_RECORD_FIELDS.items() if owner not in SOLAR_TYPES}
for owner,names in SOLAR_OMITTED_FIELDS.items():LEGACY_OMITTED_FIELDS[owner]=(*LEGACY_OMITTED_FIELDS.get(owner,()),*names)
LEGACY_RECORD_FIELDS={owner:tuple(name for name in names if name not in LEGACY_OMITTED_FIELDS.get(owner,()))
    for owner,names in B56_RECORD_FIELDS.items() if owner not in SOLAR_TYPES}


def _record_fields(root):
    # Generic scalar/alias graph tests historically use a tuple of immutable
    # roots. Such graphs have no lifecycle policy and retain the legacy wire.
    if type(root)is tuple:return LEGACY_RECORD_FIELDS
    if root.environment_ageing_policy is not None:return RECORD_FIELDS
    if root.battery_port_policy is not None:return B58_RECORD_FIELDS
    return (B56_RECORD_FIELDS if root.energy_attitude_policy is not None else B55_RECORD_FIELDS) if root.method==METHOD55 else LEGACY_RECORD_FIELDS


def validate_schema():
    validate_base_schema()
    for owner in NEW_RECORDS:
        actual = fields(owner)
        if tuple(f.name for f in actual) != RECORD_FIELDS[owner] or any(not f.init for f in actual):
            raise ValueError('unreviewed lifecycle checkpoint record schema')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))


def _restore_record_data(owner, values, *, record_fields=None):
    """Materialize one source-pinned cached record without re-running inputs.

    This is exclusively the trusted generated advanced-state path, after the
    external byte SHA, source/runtime/root binding and bounded graph admission.
    It is not input admission or an independent reachability proof. The fixed
    field registry supplies every attribute; payloads select no Python object,
    import, method or constructor. The restored static model is subsequently
    compared with the caller-root model, the native context is strictly restored,
    and the complete active-state guard is applied before returning.

    Input constructors may copy nested configurations through old canonical
    decoders (and may indirectly admit an original trajectory). Repeating those
    constructors is therefore explicitly excluded from direct state restore.
    """
    if owner not in RECORD_FIELDS or owner is J2CartesianTrajectory or not is_dataclass(owner):
        raise ValueError('source-pinned nontrajectory cached record required')
    names = (RECORD_FIELDS if record_fields is None else record_fields)[owner]
    if tuple(values) != names:
        raise ValueError('exact source-pinned cached record fields required')
    result = object.__new__(owner)
    for name in names:
        object.__setattr__(result, name, values[name])
    for name in RECORD_FIELDS[owner]:
        if name not in names:
            if name not in LEGACY_OMITTED_FIELDS.get(owner,()):raise ValueError('unapproved legacy field omission')
            object.__setattr__(result,name,None)
    return result


class GraphCodec:
    def __init__(self, root):
        validate_schema()
        self.record_fields=_record_fields(root)
        self.roots={}; self.root_ids={}; self.visits=0
        def index(v, path, depth):
            self.visits+=1
            if self.visits>MAX_NODES or depth>32: raise ValueError('immutable root index bound')
            if type(v) in (str,int,float,bool,type(None),Fraction) or isinstance(v,Enum): return
            if is_dataclass(v) or type(v) is tuple:
                key=sha256(canonical(path).encode()).hexdigest()
                self.roots[key]=v; self.root_ids.setdefault(id(v),key)
                children=((f.name,getattr(v,f.name)) for f in fields(v)) if is_dataclass(v) else enumerate(v)
                for k,x in children:index(x,(*path,k),depth+1)
        index(root,('root',),0)
        self.units=0

    def encode(self, value):
        nodes=[]; memo={}; active=set(); self.units=0;prospective_bytes=0
        def charge(token):
            nonlocal prospective_bytes
            # Conservative construction precharge, distinct from exact final
            # byte length. Stops scalar growth before a large parent allocation.
            prospective_bytes+=len(canonical(token).encode())+4
            if prospective_bytes>MAX_BYTES:raise ValueError('snapshot construction byte allowance')
            return token
        def enc(v, depth):
            self.units+=1
            if self.units>8*MAX_NODES or depth>MAX_DEPTH:raise ValueError('snapshot traversal bound')
            t=type(v)
            if v is None:return charge(['none'])
            if t is bool:return charge(['bool',v])
            if t is int:
                if v.bit_length()>4096:raise ValueError('snapshot integer bound')
                return charge(['int',str(v)])
            if t is float:
                if not math.isfinite(v):raise ValueError('finite snapshot float')
                return charge(['float',v.hex()])
            if t is str:
                if len(v.encode('utf-8'))>2**20:raise ValueError('snapshot string bound')
                return charge(['str',v])
            if t is Fraction:return charge(['rational',str(v.numerator),str(v.denominator)])
            if isinstance(v,Enum):
                name=t.__module__+'.'+t.__name__
                if ENUMS.get(name) is not t:raise TypeError('snapshot enum allowlist')
                return charge(['enum',name,v.name])
            if id(v) in self.root_ids:return charge(['root',self.root_ids[id(v)]])
            if id(v) in active:raise ValueError('snapshot cycles forbidden')
            if id(v) in memo:return charge(['ref',memo[id(v)]])
            if len(nodes)>=MAX_NODES:raise ValueError('snapshot node bound')
            n=len(nodes);memo[id(v)]=n;nodes.append(None);active.add(id(v))
            charge(['node-overhead',n,t.__name__])
            if t in (tuple,list):
                if len(v)>MAX_ITEMS:raise ValueError('snapshot sequence bound')
                node=['tuple' if t is tuple else 'list',[enc(x,depth+1) for x in v]]
            elif t is dict:
                if len(v)>MAX_ITEMS or any(type(k) not in (str,int,Fraction) for k in v):raise ValueError('snapshot map bound/keys')
                pairs=[[enc(k,depth+1),enc(x,depth+1)] for k,x in v.items()]
                pairs.sort(key=lambda p:canonical(p[0]));node=['map',pairs]
            elif t in self.record_fields:
                names=self.record_fields[t]
                if any(getattr(v,name) is not None for name in LEGACY_OMITTED_FIELDS.get(t,()) if name not in names):raise ValueError('legacy graph cannot discard B55 service authority')
                node=['record',t.__module__+'.'+t.__name__,[enc(getattr(v,k),depth+1) for k in names]]
            else:raise TypeError('unsupported snapshot owner: '+str(t))
            active.remove(id(v));nodes[n]=node
            return charge(['ref',n])
        value=enc(value,0)
        graph=dict(format=FORMAT,version=1,value=value,nodes=nodes)
        canonical_size(graph,MAX_BYTES)
        return graph

    def decode(self, graph):
        object_fields(graph,('format','version','value','nodes'))
        if graph['format']!=FORMAT or type(graph['version']) is not int or graph['version']!=1:raise ValueError('snapshot graph version')
        nodes=graph['nodes']
        if type(nodes) is not list or len(nodes)>MAX_NODES:raise ValueError('snapshot node bound')
        done={};active=set();self.units=0
        def integer(s):
            if type(s) is not str or len(s)>1235:raise ValueError('snapshot integer spelling')
            v=int(s)
            if str(v)!=s or v.bit_length()>4096:raise ValueError('noncanonical integer')
            return v
        def dec(v,depth):
            self.units+=1
            if self.units>8*MAX_NODES or depth>MAX_DEPTH or type(v) is not list or not v or type(v[0]) is not str:raise ValueError('bounded snapshot token')
            tag=v[0]
            if tag=='none' and len(v)==1:return None
            if tag=='bool' and len(v)==2 and type(v[1]) is bool:return v[1]
            if tag=='int' and len(v)==2:return integer(v[1])
            if tag=='str' and len(v)==2 and type(v[1]) is str and len(v[1].encode())<=2**20:return v[1]
            if tag=='float' and len(v)==2 and type(v[1]) is str:
                x=float.fromhex(v[1])
                if not math.isfinite(x) or x.hex()!=v[1]:raise ValueError('noncanonical finite float')
                return x
            if tag=='rational' and len(v)==3:
                a,b=integer(v[1]),integer(v[2])
                if b<=0:raise ValueError('positive rational denominator')
                q=Fraction(a,b)
                if (q.numerator,q.denominator)!=(a,b):raise ValueError('noncanonical rational')
                return q
            if tag=='enum' and len(v)==3 and type(v[1]) is str and type(v[2]) is str and v[1] in ENUMS:
                return ENUMS[v[1]][v[2]]
            if tag=='root' and len(v)==2 and type(v[1]) is str and v[1] in self.roots:return self.roots[v[1]]
            if tag!='ref' or len(v)!=2 or type(v[1]) is not int or not 0<=v[1]<len(nodes):raise ValueError('snapshot token allowlist')
            n=v[1]
            if n in active:raise ValueError('snapshot cycle')
            if n in done:return done[n]
            active.add(n);node=nodes[n]
            if type(node) is not list or not node:raise ValueError('snapshot node schema')
            kind=node[0]
            if kind in ('tuple','list') and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
                xs=[dec(x,depth+1) for x in node[1]];result=tuple(xs) if kind=='tuple' else xs
            elif kind=='map' and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
                result={};last=None
                for pair in node[1]:
                    if type(pair) is not list or len(pair)!=2:raise ValueError('snapshot map pair')
                    order=canonical(pair[0])
                    if last is not None and order<=last:raise ValueError('snapshot map ordering')
                    k=dec(pair[0],depth+1)
                    if type(k) not in (str,int,Fraction) or k in result:raise ValueError('snapshot map duplicate/key')
                    result[k]=dec(pair[1],depth+1);last=order
            elif kind=='record' and len(node)==3 and type(node[1]) is str and node[1] in RECORDS and RECORDS[node[1]] in self.record_fields and type(node[2]) is list:
                owner=RECORDS[node[1]];names=self.record_fields[owner]
                if len(node[2])!=len(names):raise ValueError('snapshot record fields')
                values=dict(zip(names,(dec(x,depth+1) for x in node[2])))
                if owner is J2CartesianTrajectory:raise ValueError('original trajectory must be a caller-root reference, not reconstructed')
                elif owner is GroundPointGeometry:result=restore_ground_geometry(values)
                elif owner is GroundVisibilityResult:result=restore_ground_visibility(values)
                else:result=_restore_record_data(owner, values,record_fields=self.record_fields)
            else:raise ValueError('snapshot node allowlist')
            active.remove(n);done[n]=result;return result
        result=dec(graph['value'],0)
        if len(done)!=len(nodes):raise ValueError('unreachable snapshot nodes')
        return result

def parse_snapshot(raw):
    if type(raw) is not bytes or not 0<len(raw)<=MAX_BYTES:raise ValueError('snapshot bytes')
    value=parse_json(raw.decode('utf-8'))
    canonical_size(value,MAX_BYTES)
    if canonical(value).encode()!=raw:raise ValueError('noncanonical snapshot JSON')
    return value

def admit_graph_structure(graph,*,record_fields=None):
    """Data-only admission before compilation/dispatch; invokes no record owner."""
    object_fields(graph,('format','version','value','nodes'))
    if graph['format']!=FORMAT or type(graph['version']) is not int or graph['version']!=1 or type(graph['nodes']) is not list or len(graph['nodes'])>MAX_NODES:raise ValueError('snapshot graph structure/version')
    def token(v):
        if type(v) is not list or not v or type(v[0]) is not str:raise ValueError('snapshot structural token')
        tag=v[0]
        if tag=='ref' and len(v)==2 and type(v[1]) is int and 0<=v[1]<len(graph['nodes']):return
        if tag=='root' and len(v)==2 and type(v[1]) is str and len(v[1])==64 and all(c in '0123456789abcdef' for c in v[1]):return
        if tag=='none' and len(v)==1:return
        if tag=='bool' and len(v)==2 and type(v[1]) is bool:return
        if tag=='str' and len(v)==2 and type(v[1]) is str and len(v[1].encode())<=2**20:return
        if tag=='int' and len(v)==2 and type(v[1]) is str and len(v[1])<=1235 and str(int(v[1]))==v[1] and int(v[1]).bit_length()<=4096:return
        if tag=='float' and len(v)==2 and type(v[1]) is str:
            f=float.fromhex(v[1])
            if math.isfinite(f) and f.hex()==v[1]:return
        if tag=='rational' and len(v)==3 and all(type(x) is str and len(x)<=1235 for x in v[1:]):
            a,b=map(int,v[1:])
            if b>0 and [str(a),str(b)]==v[1:] and max(abs(a).bit_length(),b.bit_length())<=4096:
                q=Fraction(a,b)
                if (q.numerator,q.denominator)==(a,b):return
        if tag=='enum' and len(v)==3 and type(v[1]) is str and type(v[2]) is str and v[1] in ENUMS and v[2] in ENUMS[v[1]].__members__:return
        raise ValueError('noncanonical/unknown snapshot structural token')
    token(graph['value'])
    for node in graph['nodes']:
        if type(node) is not list or not node:raise ValueError('snapshot structural node')
        kind=node[0]
        if kind in ('list','tuple') and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
            for x in node[1]:token(x)
        elif kind=='map' and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
            last=None
            for pair in node[1]:
                if type(pair) is not list or len(pair)!=2:raise ValueError('snapshot map structural pair')
                for x in pair:token(x)
                if pair[0][0] not in ('str','int','rational'):raise ValueError('snapshot map structural key')
                key=canonical(pair[0])
                if last is not None and key<=last:raise ValueError('snapshot map structural order')
                last=key
        elif kind=='record' and len(node)==3 and type(node[1]) is str and node[1] in RECORDS and (record_fields is None or RECORDS[node[1]] in record_fields) and type(node[2]) is list and len(node[2]) in ({len(record_fields[RECORDS[node[1]]])} if record_fields is not None else {len(RECORD_FIELDS[RECORDS[node[1]]]),len(LEGACY_RECORD_FIELDS[RECORDS[node[1]]])}):
            for x in node[2]:token(x)
        else:raise ValueError('unknown snapshot structural node')
    # Bounded iterative cycle/depth/reachability check, without constructors.
    done=set();active=set();todo=[(graph['value'],0,False)]
    while todo:
        v,depth,leave=todo.pop()
        if depth>MAX_DEPTH:raise ValueError('snapshot graph structural depth')
        if v[0]!='ref':continue
        n=v[1]
        if leave:active.remove(n);done.add(n);continue
        if n in active:raise ValueError('snapshot graph structural cycle')
        if n in done:continue
        active.add(n);todo.append((v,depth,True));node=graph['nodes'][n]
        children=node[2] if node[0]=='record' else [x for pair in node[1] for x in pair] if node[0]=='map' else node[1]
        todo.extend((x,depth+1,False) for x in reversed(children))
    if len(done)!=len(graph['nodes']):raise ValueError('snapshot structural unreachable nodes')
    return graph


PHYSICAL_FIELDS = ('inputs', 'attitude', 'runtime_work', 'construction', 'harness',
    'acquisitions', 'receipts', 'consumed_through_seconds', 'transition_count',
    'completed_actions', 'pending', 'reported_through_seconds', 'quiet_controller', 'quiet_work')
STATE_FIELDS = ('knowledge', 'queued', 'active', 'intents', 'next_occurrence',
    'retired_frontier', 'next_action', 'transition_count', 'event_chain', 'recent', 'status', 'forecast_quiet_work')
PHYSICAL_SERVICE_FIELDS=('service_state','service_work','service_allocation_work','last_service_diagnostic')
STATE_SERVICE_FIELDS=('pinned_requests','deferred_feedback')


def _physical_fields(root):
    return PHYSICAL_FIELDS+(PHYSICAL_SERVICE_FIELDS if root.method==METHOD55 else ())+ (('solar_state',) if root.energy_attitude_policy is not None else ())+ (('battery_port_state','battery_port_work') if root.battery_port_policy is not None else ())+ (('environment_ageing_state','environment_ageing_work') if root.environment_ageing_policy is not None else ())


def _state_fields(root):
    return STATE_FIELDS+(STATE_SERVICE_FIELDS if root.method==METHOD55 else ())+ (('solar_forecast',) if root.energy_attitude_policy is not None else ())+ (('forecast_port_work','battery_port_forecast','terminal') if root.battery_port_policy is not None else ())+ (('forecast_environment_work','environment_forecast','environment_forecast_origin') if root.environment_ageing_policy is not None else ())
BINDING_FIELDS = ('root_identity', 'source_identity', 'runtime', 'method',
                  'input_sha256', 'clock', 'grid_identity')


def _builders():
    # Late import avoids an execution/checkpoint import cycle. These three
    # functions are immutable config construction only, with no model entry.
    from .lifecycle_execution import build_model, orbit_policy_for, grid_identity
    return build_model, orbit_policy_for, grid_identity


def make_bindings(root, clock):
    from .spacecraft_project import project_source_identity
    from .project_store import runtime_identity
    _, _, grid_identity = _builders()
    root.__post_init__()
    integer(clock, 'checkpoint clock', root.start_seconds, root.end_seconds)
    return dict(root_identity=root.identity, source_identity=project_source_identity(),
        runtime=runtime_identity(), method=root.method,
        input_sha256=sha256(dumps_root(root)).hexdigest(), clock=clock,
        grid_identity=grid_identity(root))


def checked_bindings(root, value, *, current=True):
    object_fields(value, BINDING_FIELDS)
    for name in ('root_identity', 'source_identity', 'input_sha256', 'grid_identity'):
        identity(value[name])
    if type(value['method']) is not str or value['method'] != root.method:
        raise ValueError('checkpoint lifecycle method')
    integer(value['clock'], 'checkpoint clock', root.start_seconds, root.end_seconds)
    runtime = object_fields(value['runtime'], ('python', 'platform', 'executable', 'interpreter_sha256'))
    if any(type(v) is not str or not v or len(v) > 8192 for v in runtime.values()):
        raise ValueError('checkpoint runtime field')
    identity(runtime['interpreter_sha256'])
    if value['root_identity'] != root.identity or value['input_sha256'] != sha256(dumps_root(root)).hexdigest():
        raise ValueError('checkpoint caller input/root identity')
    if current and value != make_bindings(root, value['clock']):
        raise ValueError('checkpoint current source/runtime/grid binding mismatch')
    return value


def _scope_data(provider, world):
    if world.provider is not provider or world.environment.trajectory != provider.trajectory:
        raise ValueError('checkpoint world/orbit scope wiring')
    return dict(policy=provider.policy, provider=provider.to_data(), world=world.to_data())


def checkpoint_bytes(state, bindings):
    from .lifecycle_typed_context import TypedBackendContext
    if type(state.backend_context)is TypedBackendContext:
        with state.backend_context.transaction():return _checkpoint_bytes(state,bindings)
    return _checkpoint_bytes(state,bindings)

def _checkpoint_bytes(state, bindings):
    """Pure bounded snapshot; newly incurred publication work is external DATA."""
    guard_lifecycle(state)
    checked_bindings(state.root, bindings)
    if bindings['clock'] != state.clock:
        raise ValueError('checkpoint committed clock mismatch')
    if state.actual_provider is state.forecast_provider or state.actual_world is state.forecast_world:
        raise ValueError('checkpoint actual/forecast scopes must be independent')
    if state.actual_provider.role != 'ACTUAL' or state.forecast_provider.role != 'FORECAST':
        raise ValueError('checkpoint cache scope ownership')
    codec = GraphCodec(state.root)
    payload = dict(context=CheckpointState.from_context(state.physical.context).to_dict(),
        model=state.model, physical={n: getattr(state.physical, n) for n in _physical_fields(state.root)},
        actual=_scope_data(state.actual_provider, state.actual_world),
        forecast=_scope_data(state.forecast_provider, state.forecast_world),
        forecast_runtime=state.forecast_runtime,
        state={n: getattr(state, n) for n in _state_fields(state.root)}, work=state.work,
        report=state.report.state)
    encoded = codec.encode(payload)
    extended=state.root.method in (METHOD53,METHOD55)
    compiled=state.compiled_context is not None
    service=state.root.method==METHOD55
    solar=state.root.energy_attitude_policy is not None
    if state.backend_context is not None and state.root.environment_ageing_policy is None:raise ValueError('B63 checkpoint supports declared exposure model only')
    from .lifecycle_typed_context import TypedBackendContext
    typed=type(state.backend_context)is TypedBackendContext
    document = dict(format=CHECKPOINT_FORMAT_YEAR5 if typed and is_short_circuit_policy(state.root.policy.quiet_solver) else CHECKPOINT_FORMAT65 if typed and state.backend_context.selection=='B65_TYPED_EXECUTION_V2' else CHECKPOINT_FORMAT64 if typed else CHECKPOINT_FORMAT63 if state.backend_context is not None else CHECKPOINT_FORMAT61 if state.root.environment_ageing_policy is not None else CHECKPOINT_FORMAT58 if state.root.battery_port_policy is not None else CHECKPOINT_FORMAT56 if solar else CHECKPOINT_FORMAT55 if service else CHECKPOINT_FORMAT54 if compiled else CHECKPOINT_FORMAT53 if extended else CHECKPOINT_FORMAT,
                    version=1 if state.backend_context is not None else 8 if state.root.environment_ageing_policy is not None else 7 if state.root.battery_port_policy is not None else 5 if solar else 4 if service else 3 if compiled else 2 if extended else 1, bindings=bindings, graph=encoded)
    if compiled:document['wrapper']=state.compiled_context.to_data()
    if state.backend_context is not None:document['backend']=state.backend_context.checkpoint_binding()
    limit = min(MAX_BYTES, state.root.policy.max_checkpoint_bytes, state.root.policy.max_working_bytes)
    count = canonical_size(document, limit)
    raw = canonical(document).encode('utf-8')
    if len(raw) != count:
        raise ValueError('checkpoint exact encoded byte admission')
    return raw


def admit_checkpoint_transport(checkpoint):
    """Admit optional transport DATA without granting graph/restore authority."""
    from .checkpoint_transport import FORMAT, CODECS, RECEIPT_FIELDS, MAX_FRAMING_BYTES
    if type(checkpoint)is not dict:raise TypeError('exact checkpoint metadata required')
    object_fields(checkpoint,('file','sha256','bytes','clock','bindings','kind','publication',*(('transport',)if 'transport'in checkpoint else ())))
    identity(checkpoint['sha256']);integer(checkpoint['bytes'],'checkpoint decoded bytes',1,MAX_BYTES)
    if 'transport'not in checkpoint:return None
    value=object_fields(checkpoint['transport'],RECEIPT_FIELDS)
    if (value['format']!=FORMAT or type(value['codec'])is not str or value['codec']not in CODECS or
            type(value['role'])is not str or value['role']!=checkpoint['kind'] or
            type(value['bindings'])is not dict or canonical(value['bindings'])!=canonical(checkpoint['bindings']) or
            value['decoded_sha256']!=checkpoint['sha256']):
        raise ValueError('checkpoint transport metadata binding/version/role')
    integer(value['decoded_bytes'],'transport decoded bytes',1,MAX_BYTES)
    integer(value['encoded_bytes'],'transport encoded bytes',1,checkpoint['bytes']+MAX_FRAMING_BYTES)
    identity(value['decoded_sha256']);identity(value['encoded_sha256'])
    if value['decoded_bytes']!=checkpoint['bytes']:raise ValueError('checkpoint transport decoded length binding')
    return value


def checkpoint_file_bytes(path, checkpoint, root, *, require_transport=False):
    """Read exact current file bytes and return the pinned canonical checkpoint.

    Scientific SHA/bytes always describe decoded bytes. The optional transport
    receipt independently pins the physical file; neither is restore authority.
    """
    from .checkpoint_transport import read_checkpoint, FORMAT
    if type(require_transport)is not bool:raise TypeError('exact checkpoint transport requirement')
    transport=admit_checkpoint_transport(checkpoint)
    if require_transport and transport is None:raise ValueError('physical store requires checkpoint transport')
    if checkpoint['bindings'].get('root_identity')!=root.identity:raise ValueError('checkpoint transport caller root')
    raw,actual=read_checkpoint(path,root,checkpoint['sha256'],checkpoint['bindings'],checkpoint['kind'])
    if (transport is None and actual['format']==FORMAT or
            transport is not None and canonical(actual)!=canonical(transport)):
        raise ValueError('checkpoint transport actual encoded receipt disagreement')
    if len(raw)!=checkpoint['bytes']:raise ValueError('checkpoint decoded exact byte length')
    return raw


def _canonical_checkpoint_bytes(raw_or_path, root, expected_sha256, expected_bindings):
    from .checkpoint_transport import read_checkpoint
    return read_checkpoint(raw_or_path,root,expected_sha256,expected_bindings)[0]


def admit_checkpoint(raw, root, expected_sha256, expected_bindings):
    """Hashes, current binding and full graph shape BEFORE any owner restore."""
    checked_bindings(root, expected_bindings)
    identity(expected_sha256)
    from .checkpoint_transport import is_transport
    if is_transport(raw):raw=_canonical_checkpoint_bytes(raw,root,expected_sha256,expected_bindings)
    limit = min(MAX_BYTES, root.policy.max_checkpoint_bytes)
    if type(raw) is not bytes or not 0 < len(raw) <= limit or sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('checkpoint external SHA/byte admission')
    document = parse_snapshot(raw)
    service=root.method==METHOD55
    solar=root.energy_attitude_policy is not None
    typed=document.get('format')in(CHECKPOINT_FORMAT64,CHECKPOINT_FORMAT65,CHECKPOINT_FORMAT_YEAR5)
    new=document.get('format')==CHECKPOINT_FORMAT65 or (document.get('format')==CHECKPOINT_FORMAT_YEAR5 and type(document.get('backend'))is dict and document['backend'].get('selection')=='B65_TYPED_EXECUTION_V2')
    backend=document.get('format')in (CHECKPOINT_FORMAT63,CHECKPOINT_FORMAT64,CHECKPOINT_FORMAT65,CHECKPOINT_FORMAT_YEAR5)
    if backend and root.environment_ageing_policy is None:raise ValueError('B63 checkpoint requires exposure model')
    compiled=document.get('format')==CHECKPOINT_FORMAT54 or (document.get('format') in (CHECKPOINT_FORMAT55,CHECKPOINT_FORMAT56,CHECKPOINT_FORMAT58,CHECKPOINT_FORMAT61,CHECKPOINT_FORMAT63,CHECKPOINT_FORMAT64,CHECKPOINT_FORMAT65,CHECKPOINT_FORMAT_YEAR5) and 'wrapper' in document)
    object_fields(document, ('format', 'version', 'bindings', 'graph',*(('wrapper',) if compiled else ()),*(('backend',) if backend else ())))
    extended=root.method in (METHOD53,METHOD55)
    if type(document['format']) is not str or document['format'] != (CHECKPOINT_FORMAT_YEAR5 if typed and is_short_circuit_policy(root.policy.quiet_solver) else CHECKPOINT_FORMAT65 if new else CHECKPOINT_FORMAT64 if typed else CHECKPOINT_FORMAT63 if backend else CHECKPOINT_FORMAT61 if root.environment_ageing_policy is not None else CHECKPOINT_FORMAT58 if root.battery_port_policy is not None else CHECKPOINT_FORMAT56 if solar else CHECKPOINT_FORMAT55 if service else CHECKPOINT_FORMAT54 if compiled and extended else CHECKPOINT_FORMAT53 if extended else CHECKPOINT_FORMAT) or type(document['version']) is not int or document['version'] != (1 if backend else 8 if root.environment_ageing_policy is not None else 7 if root.battery_port_policy is not None else 5 if solar else 4 if service else 3 if compiled else 2 if extended else 1):
        raise ValueError('checkpoint format/version')
    checked_bindings(root, document['bindings'], current=False)
    if document['bindings'] != expected_bindings:
        raise ValueError('checkpoint source/runtime/root/input/grid/clock mismatch')
    if compiled:
        from .lifecycle_admission import validate_wrapper_data
        wrapper=validate_wrapper_data(document['wrapper'])
        if wrapper['root_identity']!=root.identity or wrapper['source_identity']!=expected_bindings['source_identity']:
            raise ValueError('checkpoint wrapper root/source binding')
    if 'backend' in document:
        from .lifecycle_backend import validate_checkpoint_backend
        validate_checkpoint_backend(document['backend'])
        from .lifecycle_typed_context import CHECKPOINT_FORMAT as TYPED_BACKEND_FORMAT
        expected_typed='B65_TYPED_BACKEND_CHECKPOINT_BINDING_V2'if new else TYPED_BACKEND_FORMAT
        if typed!=(document['backend'].get('format')==expected_typed):raise ValueError('checkpoint wrapper/backend family mismatch')
    admit_graph_structure(document['graph'],record_fields=_record_fields(root))
    codec = GraphCodec(root)
    for node in document['graph']['nodes']:
        if node[0] == 'record' and RECORDS[node[1]] is J2CartesianTrajectory:
            raise ValueError('original trajectory must remain a caller-root reference')
        tokens = node[2] if node[0] == 'record' else [v for pair in node[1] for v in pair] if node[0] == 'map' else node[1]
        for token in tokens:
            if token[0] == 'root' and token[1] not in codec.roots:
                raise ValueError('checkpoint unknown immutable root reference')
    value = document['graph']['value']
    if value[0] == 'root' and value[1] not in codec.roots:
        raise ValueError('checkpoint unknown immutable root value')
    return document


def _restore_scope(model, data, role, runtime):
    object_fields(data, ('policy', 'provider', 'world'))
    if type(data['policy']) is not LifecycleOrbitPolicy:
        raise TypeError('checkpoint exact orbit policy required')
    def charge(name, count):
        runtime.charge(name, count, model.limits)
    provider = LifecycleOrbitProvider.from_data(model.environment.trajectory,
                                               data['policy'], data['provider'], charge=charge)
    if provider.role != role:
        raise ValueError('checkpoint wrong orbit authority scope')
    world = AcquiredLifecycleWorld.from_data(model.environment, provider, data['world'], charge=charge)
    return provider, world


def _read_bytes(raw_or_path, limit):
    if type(raw_or_path) is bytes:
        return raw_or_path
    if type(raw_or_path) is not str and not isinstance(raw_or_path, Path):
        raise TypeError('checkpoint bytes or explicit local path required')
    path = Path(raw_or_path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError('bounded existing checkpoint file required')
    return path.read_bytes()


class _RestoreDataSeal:
    """Bounded strong field-edge seal of one locally materialized DATA graph."""
    def __init__(self, value):
        self.edges=[];self.scalars=[];self.units=0;seen=set()
        def capture(item, depth=0):
            self.units+=1
            if self.units>9*MAX_NODES or depth>MAX_DEPTH:
                raise ValueError('B63 restore preparation bounded data seal')
            owner=type(item)
            if item is None or owner in (str,int,bool,float,bytes):return
            if owner is Fraction:
                self.scalars.append(('fraction',item,item.numerator,item.denominator));return
            if isinstance(item,Enum):
                self.scalars.append(('enum',item,owner,item.name,item.value));return
            if id(item)in seen:return
            seen.add(id(item))  # Every visited object is strongly held below.
            if owner is dict:
                entries=tuple(item.items());self.edges.append(('dict',item,entries))
                for key,child in entries:capture(key,depth+1);capture(child,depth+1)
            elif owner in (tuple,list):
                entries=tuple(item);self.edges.append(('sequence',item,owner,entries))
                for child in entries:capture(child,depth+1)
            elif is_dataclass(item):
                mapping=owner.__dataclass_fields__
                schema=tuple((name,field,field.name,field.init)for name,field in mapping.items())
                entries=tuple((field.name,getattr(item,field.name),field.init)for field in fields(owner))
                self.edges.append(('record',item,owner,mapping,schema,entries))
                for _,child,_ in entries:capture(child,depth+1)
            else:raise TypeError('B63 unsupported prepared restore DATA owner')
        capture(value)
        self.edges=tuple(self.edges);self.scalars=tuple(self.scalars)

    def guard(self):
        from .assembly_attitude import ComponentAxisBinding
        for kind,item,*saved in self.edges:
            if kind=='dict':
                entries=saved[0]
                if type(item)is not dict or len(item)!=len(entries):raise ValueError('B63 prepared restore map drift')
                for (key,value),(old_key,old_value)in zip(item.items(),entries):
                    if key is not old_key or value is not old_value:raise ValueError('B63 prepared restore map edge drift')
            elif kind=='sequence':
                owner,entries=saved
                if type(item)is not owner or len(item)!=len(entries)or any(a is not b for a,b in zip(item,entries)):
                    raise ValueError('B63 prepared restore sequence drift')
            else:
                owner,mapping,schema,entries=saved
                if type(item)is not owner or owner.__dataclass_fields__ is not mapping or len(mapping)!=len(schema):raise ValueError('B63 prepared restore owner/schema drift')
                for name,field,old_name,init in schema:
                    if mapping.get(name)is not field or field.name!=old_name or field.init is not init:raise ValueError('B63 prepared restore Field drift')
                for name,old,init in entries:
                    current=getattr(item,name)
                    if name=='_identity'and init is False:
                        if type(current)is not str or type(old)is not str or current!=old:raise ValueError('B63 prepared restore cached identity drift')
                    elif owner is ComponentAxisBinding and name=='local_axis':
                        if (type(current)is not tuple or type(old)is not tuple or len(current)!=3 or len(old)!=3 or
                            any(type(a)is not float or type(b)is not float or a.hex()!=b.hex()for a,b in zip(current,old))):
                            raise ValueError('B63 prepared restore canonical local axis drift')
                    elif current is not old:raise ValueError('B63 prepared restore record edge drift: '+name)
        for kind,item,*saved in self.scalars:
            if kind=='fraction':
                if (type(item)is not Fraction or type(item.numerator)is not int or type(item.denominator)is not int or
                    item.numerator!=saved[0]or item.denominator!=saved[1]):raise ValueError('B63 prepared restore Fraction drift')
            else:
                owner,name,value=saved
                if type(item)is not owner or item.name is not name or item.value is not value or owner.__members__.get(name)is not item:
                    raise ValueError('B63 prepared restore Enum drift')


class _PreparedCheckpointRestore:
    """Transient one-shot owner transfer, never persistent restore authority."""
    __slots__=('_root','_raw','_binding','_data','_codec','_context','_seal','_phase','_work','_receipt','_native','_static_work','_job_preparation_units')
    def __init__(self,root,raw,bindings,data,codec,context,native):
        from .lifecycle_backend import canonical as backend_canonical,runtime_binding
        self._root=root;self._raw=raw;self._data=data;self._codec=codec;self._context=context
        self._seal=_RestoreDataSeal((root,data,native))
        self._binding=(root,context,os.getpid(),backend_canonical(runtime_binding()),sha256(raw).hexdigest(),
                       canonical(bindings),context.source_binding,canonical(context.checkpoint_binding()),
                       self,data,codec,self._seal)
        self._receipt=backend_canonical(context.receipt());self._native=native;self._phase='READY'
        from .lifecycle_typed_context import TypedBackendContext
        self._job_preparation_units=context.job.receipt()['control']['control_units_reserved'] if type(context)is TypedBackendContext else 0
        self._work=dict(preparation_attempts=1,preparation_completed=1,take_attempts=0,take_completed=0,
            decoded_units=codec.units,index_visits=codec.visits,seal_capture_units=self._seal.units,
            seal_guard_reserved_units=0,hash_read_reserved_units=2*((len(raw)+63)//64))
        self._binding=(*self._binding,self._work)
        self._static_work=tuple(self._work[n]for n in('decoded_units','index_visits','seal_capture_units','hash_read_reserved_units'))
        if self._units()>CONTROL_ALLOWANCE:raise ValueError('B63 preparation exceeds existing restore control reservation')

    def _units(self):
        return self._job_preparation_units+sum(self._work[name]for name in('decoded_units','index_visits','seal_capture_units','seal_guard_reserved_units','hash_read_reserved_units'))

    def receipt(self):
        return dict(format='B63_ONE_SHOT_RESTORE_PREPARATION_V1',phase=self._phase,PID=self._binding[2],
            checkpoint_sha256=self._binding[4],source_binding=self._binding[6],work=dict(self._work),
            logical_control_units=self._units(),control_reserved_units=CONTROL_ALLOWANCE,
            scope='PAID_STATIC_ADMISSION_AND_KNOWN_OWNER_DATA_NOT_PREFIX_PHYSICS_OR_PERSISTENT_CACHE',
            native_preparation_entry_monitor=self._native)

    def begin(self,root,expected_sha256,expected_bindings):
        from .lifecycle_backend import canonical as backend_canonical,runtime_binding
        if self._phase!='READY':raise ValueError('B63 prepared restore is single-use')
        self._phase='ENTERED';self._work['take_attempts']+=1
        self._work['seal_guard_reserved_units']+=self._seal.units
        names={'preparation_attempts','preparation_completed','take_attempts','take_completed',
            'decoded_units','index_visits','seal_capture_units','seal_guard_reserved_units','hash_read_reserved_units'}
        if type(self._work)is not dict or set(self._work)!=names or any(type(n)is not int or not 0<=n<=CONTROL_ALLOWANCE for n in self._work.values()):
            raise ValueError('B63 prepared restore exact admission accounting')
        if self._units()>CONTROL_ALLOWANCE:raise ValueError('B63 prepared restore combined control allowance')
        old_root,old_context,pid,runtime,cp_sha,bindings,source,backend,owner,data,codec,seal,work=self._binding
        if (owner is not self or self._data is not data or self._codec is not codec or self._seal is not seal or self._work is not work or
            root is not old_root or self._root is not old_root or self._context is not old_context or os.getpid()!=pid or
            backend_canonical(runtime_binding())!=runtime or expected_sha256!=cp_sha or canonical(expected_bindings)!=bindings or
            self._context.source_binding!=source or canonical(self._context.checkpoint_binding())!=backend):
            raise ValueError('B63 prepared restore root/PID/runtime/source/checkpoint binding')
        if backend_canonical(self._context.receipt())!=self._receipt:
            raise ValueError('B63 prepared restore context was already used or changed')
        if (tuple(self._work[n]for n in('decoded_units','index_visits','seal_capture_units','hash_read_reserved_units'))!=self._static_work or
            self._work['preparation_attempts']!=1 or self._work['preparation_completed']!=1 or
            self._work['take_attempts']!=1 or self._work['take_completed']!=0 or
            self._work['seal_guard_reserved_units']!=self._seal.units):
            raise ValueError('B63 prepared restore admission accounting drift')
        self._seal.guard()

    def take(self,raw,document):
        if self._phase!='ENTERED'or raw!=self._raw or canonical(document['backend'])!=self._binding[7]:
            raise ValueError('B63 prepared restore current raw/backend authority')
        self._work['take_completed']+=1;self._phase='CONSUMED'
        return self._data,self._codec,self._context

    def release_transferred_data(self):
        # Successful restoration owns the graph now. Keep bounded receipts and
        # static pins, not a second retained dynamic graph or a self-cycle.
        if self._phase!='CONSUMED':raise ValueError('B63 unconsumed restore transfer')
        self._binding=self._binding[:8]
        self._data=self._codec=self._seal=None;self._raw=b''


def prepare_checkpoint_restore(raw_or_path,root,expected_sha256,expected_bindings,*,job_admission=None):
    """Explicit paid ADMISSION before the watched direct-restore entry.

    Retains the full original input/backend validation, including any original
    anchor gravity validation. No propagation, physical state start, numerical
    step, history replay or dynamic coefficient realization is performed.
    """
    raw=_canonical_checkpoint_bytes(raw_or_path,root,expected_sha256,expected_bindings)
    document=admit_checkpoint(raw,root,expected_sha256,expected_bindings)
    if 'backend'not in document:raise ValueError('B63 explicit backend checkpoint required for prepared restore')
    codec=GraphCodec(root);data=codec.decode(document['graph'])
    object_fields(data,('context','model','physical','actual','forecast','forecast_runtime','state','work','report'))
    from .lifecycle_backend import BackendContext,admit_native_build,native_restore_proof
    b=document['backend'];module=None;before=None
    if b['selection']=='PREPARED_NATIVE':
        module=admit_native_build(b['build']);before=module.native_entry_counts()
    from .lifecycle_backend import TYPED_SELECTIONS
    if b['selection']in TYPED_SELECTIONS:
        from .lifecycle_job_prepared import prepare_job_runtime
        from .lifecycle_typed_context import TypedBackendContext
        from .lifecycle_typed_backend import admit_typed_build,native_restore_proof as typed_zero
        if b['selection']=='B65_TYPED_EXECUTION_V2':
            from .lifecycle_typed_platform import admit_typed_build,native_restore_proof as typed_zero
        module=admit_typed_build(b['build'],require_quiet=b['selection']in(TYPED_SELECTIONS[0],'B65_TYPED_EXECUTION_V2'),execution_domain=b['selection'])
        before=module.native_entry_counts()
        job=prepare_job_runtime(job_admission,root,restored_model=data['model'])
        try:
            context=TypedBackendContext(job,b['selection'],b['source_binding'],b['build'])
            native=typed_zero(before,module.native_entry_counts(),b['build'],b['source_binding'])
            native['format']='B65_TYPED_STATIC_PREPARATION_ZERO_V2'if b['selection']=='B65_TYPED_EXECUTION_V2'else'B64_TYPED_STATIC_PREPARATION_ZERO_V1'
            return _PreparedCheckpointRestore(root,raw,expected_bindings,data,codec,context,native)
        except BaseException as primary:
            try:job.close()
            except BaseException as secondary:job._secondary(primary,secondary)
            raise
    if job_admission is not None:raise ValueError('foreign typed admission on B63 restore')
    context=BackendContext(root,data['model'],b['selection'],b['source_binding'],b['build'])
    native=None
    if module is not None:
        native=native_restore_proof(before,module.native_entry_counts(),b['build'],b['source_binding'])
        native['format']='B63_NATIVE_STATIC_PREPARATION_ZERO_V1'
    return _PreparedCheckpointRestore(root,raw,expected_bindings,data,codec,context,native)


def restore_checkpoint(raw_or_path,root,expected_sha256,expected_bindings,*,prepared=None):
    if prepared is None:
        return _restore_checkpoint(raw_or_path,root,expected_sha256,expected_bindings)
    if type(prepared)is not _PreparedCheckpointRestore:
        raise TypeError('B63 exact local prepared restore owner required')
    try:
        prepared.begin(root,expected_sha256,expected_bindings)
        from .lifecycle_typed_context import TypedBackendContext
        if type(prepared._context)is TypedBackendContext:
            with prepared._context.transaction():
                result=_restore_checkpoint(raw_or_path,root,expected_sha256,expected_bindings,prepared=prepared)
        else:result=_restore_checkpoint(raw_or_path,root,expected_sha256,expected_bindings,prepared=prepared)
        prepared.release_transferred_data()
        return result
    except BaseException:
        prepared._phase='FAILED'
        raise


def _restore_checkpoint(raw_or_path, root, expected_sha256, expected_bindings,*,prepared=None):
    raw = _canonical_checkpoint_bytes(raw_or_path,root,expected_sha256,expected_bindings)
    document = admit_checkpoint(raw, root, expected_sha256, expected_bindings)
    native_before=None;native_module=None
    if document.get('backend',{}).get('selection')=='PREPARED_NATIVE':
        from .lifecycle_backend import admit_native_build,admit_native_counts
        native_module=admit_native_build(document['backend']['build'])
        native_before=admit_native_counts(native_module.native_entry_counts(),document['backend']['build'])
    from .lifecycle_backend import TYPED_SELECTIONS
    if document.get('backend',{}).get('selection')in TYPED_SELECTIONS:
        if prepared is None:raise ValueError('B64 direct restore requires fresh paid current-job preparation')
        from .lifecycle_typed_backend import admit_typed_build,admit_native_counts as typed_counts
        b=document['backend']
        if b['selection']=='B65_TYPED_EXECUTION_V2':
            from .lifecycle_typed_platform import admit_typed_build,admit_native_counts as typed_counts
        native_module=admit_typed_build(b['build'],require_quiet=b['selection']in(TYPED_SELECTIONS[0],'B65_TYPED_EXECUTION_V2'),execution_domain=b['selection'])
        native_before=typed_counts(native_module.native_entry_counts(),b['build'])
    prepared_context=None
    if prepared is None:
        codec=GraphCodec(root);data=codec.decode(document['graph'])
    else:
        data,codec,prepared_context=prepared.take(raw,document)
    object_fields(data, ('context', 'model', 'physical', 'actual', 'forecast',
                         'forecast_runtime', 'state', 'work', 'report'))
    object_fields(data['physical'], _physical_fields(root))
    object_fields(data['state'], _state_fields(root))
    build_model, orbit_policy_for, _ = _builders()
    from .lifecycle_typed_context import TypedBackendContext
    expected_model = prepared_context.job.external_model if type(prepared_context)is TypedBackendContext else build_model(root)
    from .rolling_physics import digest
    if type(data['model']) is not LifecyclePhysicalModel or digest(data['model']) != digest(expected_model):
        raise ValueError('checkpoint static physical/world model binding')
    model = data['model']
    physical = data['physical']
    if type(physical['inputs']) is not LifecyclePhysicalInputs or digest(physical['inputs'].model) != digest(model):
        raise ValueError('checkpoint active physical input/model binding')
    expected_policy = orbit_policy_for(root)
    if data['actual']['policy'] != expected_policy or data['forecast']['policy'] != expected_policy:
        raise ValueError('checkpoint original orbit grid/policy binding')
    context = CheckpointState.from_dict(data['context']).restore(model.simulation_inputs)
    if context.simulation_time_seconds != expected_bindings['clock']:
        raise ValueError('checkpoint restored clock mismatch')
    rt, forecast_rt = physical['runtime_work'], data['forecast_runtime']
    if type(rt) is not RuntimeWork or type(forecast_rt) is not RuntimeWork:
        raise TypeError('checkpoint actual/forecast runtime ledgers required')
    rt.validate(model.limits)
    forecast_rt.validate(model.limits)
    actual_provider, actual_world = _restore_scope(model, data['actual'], 'ACTUAL', rt)
    forecast_provider, forecast_world = _restore_scope(model, data['forecast'], 'FORECAST', forecast_rt)
    work = data['work']
    if type(work) is not LifecycleWork:
        raise TypeError('checkpoint cumulative lifecycle work required')
    work.validate(root.policy)
    from .lifecycle_report import LifecycleReport
    report = LifecycleReport(root, context, state=data['report'],prepared_runtime=prepared_context.actual if type(prepared_context)is TypedBackendContext else None)
    p = LifecyclePhysicalState(context=context, nominal_provider=actual_provider,
        source_authority=actual_world, **physical)
    state = LifecycleState(root=root, root_identity=root.identity, model=model, physical=p,
        actual_provider=actual_provider, forecast_provider=forecast_provider,
        actual_world=actual_world, forecast_world=forecast_world,
        forecast_runtime=forecast_rt, report=report, work=work, **data['state'])
    if 'wrapper' in document:
        from .lifecycle_admission import CompiledLifecycleContext
        state.compiled_context=CompiledLifecycleContext(root,model,
            source_identity=expected_bindings['source_identity'],prior=document['wrapper'])
        state.physical.static_admission=state.compiled_context.actual
    if 'backend' in document:
        from .lifecycle_backend import attach_backend
        b=document['backend'];attach_backend(state,b['selection'],b['source_binding'],b['build'],prepared=prepared_context)
    guard_lifecycle(state)
    proof = dict(format='B52_DIRECT_RESTORE_PROOF_V1', restored_clock=state.clock,
        retained_prior_static_admission_wrapper=deepcopy(document.get('wrapper')),
        materializer='EXPLICIT_KNOWN_OWNER_DATA_ONLY_NO_START_OR_PREFIX_REPLAY',
        backend=None if state.backend_context is None else state.backend_context.receipt(),
        prefix_evaluations='EXTERNAL_INSTRUMENTATION_REQUIRED',
        validation_control_units=codec.units+codec.visits,
        validation_control_reserved_units=CONTROL_ALLOWANCE,
        validation_bytes=len(raw), retained_graph_nodes=len(document['graph']['nodes']),
        retained_prior_work=asdict(work), retained_actual_runtime_work=asdict(rt),
        retained_forecast_runtime_work=asdict(forecast_rt),
        retained_actual_orbit_work=asdict(actual_provider.work),
        retained_forecast_orbit_work=asdict(forecast_provider.work),
        pending=None if p.pending is None else p.pending.kind,
        queued_ordinals=[x.ordinal for x in state.queued],
        partial_bits=[x.transmitted_equivalent_bits for x in context.ground_data_delivery_state.partial_transfers],
        original_anchor_seconds=actual_provider.anchor.instant.elapsed_seconds,
        RNG='NONE_USED_BY_SUPPORTED_OWNERS',
        reachability='TRUSTED_GENERATED_OWNER_NOT_INDEPENDENT_PROOF')
    if prepared is not None:
        proof['preparation']=prepared.receipt()
        proof['validation_control_units']=prepared._units()
    if root.environment_ageing_policy is not None:
        # Explicit bounded derived validation; no elapsed-prefix reconstruction.
        proof['environment_derived_validation']=dict(control_units=256+64*(len(root.environment_ageing_policy.emissivity)+len(root.environment_ageing_policy.conductance)),
            work_scope='STATIC_RESTORE_VALIDATION_NOT_SELECTED_OR_FORECAST_PHYSICS',prefix_evaluations=0)
    if native_module is not None:
        from .lifecycle_backend import native_restore_proof
        if type(prepared_context)is TypedBackendContext:
            from .lifecycle_typed_backend import native_restore_proof
            if prepared_context.selection=='B65_TYPED_EXECUTION_V2':
                from .lifecycle_typed_platform import native_restore_proof
        proof['native_entry_monitor']=native_restore_proof(native_before,native_module.native_entry_counts(),
            document['backend']['build'],document['backend']['source_binding'])
    return state, proof


def _publish_new(path, raw):
    """Atomic NEW name plus fsync. Never replace a reader-held authority file.

    A hard-link publication is an atomic exclusive name claim on the same local
    filesystem. A failed manifest publication leaves an orphan immutable data
    file; it cannot replace an older complete manifest/checkpoint pair.
    """
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError('immutable checkpoint publication already exists: '+str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            _io_fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_checkpoint(path, state, bindings, maximum_output_bytes=None):
    raw = checkpoint_bytes(state, bindings)
    manifest = dict(format=MANIFEST_FORMAT, version=1, sha256=sha256(raw).hexdigest(),
        clock=state.clock, bytes=len(raw), bindings=bindings,
        encoding_control_reserved_units=CONTROL_ALLOWANCE, storage_bytes=len(raw),
        encoding_scope='EXTERNAL_PUBLICATION_LEDGER_NOT_SCIENTIFIC_MODEL_WORK')
    manifest_raw = canonical(manifest).encode('utf-8')
    limit = state.root.policy.max_task_output_bytes if maximum_output_bytes is None else maximum_output_bytes
    integer(limit, 'checkpoint publication remaining bytes', 0, 2**40)
    if len(raw)+len(manifest_raw) > limit or len(manifest_raw) > 16384:
        raise ValueError('checkpoint prospective publication disk quota')
    path = Path(path)
    manifest_path = path.with_name(path.name+'.manifest.json')
    if path.exists() or manifest_path.exists() or path.is_symlink() or manifest_path.is_symlink():
        raise FileExistsError('immutable checkpoint/manifest already exists')
    _publish_new(path, raw)
    _publish_new(manifest_path, manifest_raw)
    return {**manifest, 'path': str(path.absolute()), 'manifest_path': str(manifest_path.absolute()),
            'total_published_bytes': len(raw)+len(manifest_raw)}
