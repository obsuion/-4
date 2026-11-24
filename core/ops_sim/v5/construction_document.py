"""Fixed input-only codec and externally bound private-replay B45 continuation."""
from dataclasses import fields, asdict
from hashlib import sha256
import json
from pathlib import Path
from .construction_coupling import ConstructionConfiguration, ReceivingBranch
from .construction_mission import (ConstructionMissionInputs, ConstructionLimits, ConstructionWork,
    start_construction_mission, advance_construction_mission, guard_construction_state)
from .assembly_interfaces import ElectricalPort, WireProperties, OperatingPoint, HarnessMassDeclaration, LineConnection, ThermalBinding
from .assembly import MassCoverage
from .thermal import ThermalIntervalInputs, ThermalNodeBoundaryInput
from .long_mission_document import (mission_inputs_to_json, mission_inputs_from_json, canonical_json,
    _encode as old_encode, _predecode as old_admit, _decode as old_decode)
from .long_mission_continuation import _bounded_tree, _scientific, _hash, admit_reconstruction
from .long_mission import RuntimeWork, scientific_projection, validate_context_inputs, reserve_output
from .checkpoint import CheckpointState
from .experiment_codec import parse_json, object_fields

FORMAT='B45_CONSTRUCTION_MISSION_INPUT_V1'
PACKET='B45_CONSTRUCTION_ACTION_BOUNDARY_V1'
OWNERS=(ConstructionConfiguration,ConstructionLimits,ReceivingBranch,ElectricalPort,WireProperties,
    OperatingPoint,HarnessMassDeclaration,LineConnection,ThermalBinding,MassCoverage,ThermalIntervalInputs,ThermalNodeBoundaryInput)
MAP={c.__name__:c for c in OWNERS}
MAX_INPUT=16*2**20
MAX_PACKET=512*2**20


def encode(v):
    if type(v) in OWNERS:return dict(construction_type=type(v).__name__,fields={f.name:encode(getattr(v,f.name)) for f in fields(v)})
    if type(v) is tuple:return dict(construction_tuple=[encode(x) for x in v])
    return dict(legacy_input=old_encode(v))


def admit(v):
    if type(v) is not dict:raise ValueError('strict construction input object')
    if set(v)=={'construction_type','fields'}:
        name=v['construction_type']
        if type(name) is not str or name not in MAP:raise ValueError('unsafe construction type')
        d=object_fields(v['fields'],tuple(f.name for f in fields(MAP[name])))
        # Admit cardinalities before constructing nested typed hardware records.
        if name=='ConstructionConfiguration':
            for field,cap in (('ports',64),('lines',64),('receiving',7),('thermal_bindings',32)):
                sequence=object_fields(d[field],('construction_tuple',))['construction_tuple']
                if type(sequence) is not list or len(sequence)>cap:raise ValueError('predecode construction cap:'+field)
            network=object_fields(d['thermal_network'],('legacy_input',))['legacy_input']
            network=object_fields(network,('typed',))['typed']
            network=object_fields(network,('kind','type','fields'))
            if network['kind']!='record' or network['type']!='ops_sim.v5.thermal_config.ThermalNetworkConfig':raise ValueError('fixed thermal network input required')
            for field,cap in (('nodes',64),('links',256)):
                sequence=object_fields(network['fields'][field],('kind','items'))
                if sequence['kind']!='tuple' or type(sequence['items']) is not list or len(sequence['items'])>cap:raise ValueError('predecode thermal graph cap:'+field)
        elif name=='LineConnection':
            waypoints=object_fields(d['waypoints_body_m'],('construction_tuple',))['construction_tuple']
            if type(waypoints) is not list or len(waypoints)>64:raise ValueError('predecode route waypoint cap')
        for x in d.values():admit(x)
    elif set(v)=={'construction_tuple'}:
        if type(v['construction_tuple']) is not list or len(v['construction_tuple'])>256:raise ValueError('bounded construction tuple')
        for x in v['construction_tuple']:admit(x)
    elif set(v)=={'legacy_input'}:old_admit(v['legacy_input'])
    else:raise ValueError('unknown executable construction input')


def decode(v):
    if 'construction_type' in v:return MAP[v['construction_type']](**{n:decode(x) for n,x in v['fields'].items()})
    if 'construction_tuple' in v:return tuple(decode(x) for x in v['construction_tuple'])
    return old_decode(v['legacy_input'])


def input_data(inputs):
    if type(inputs) is not ConstructionMissionInputs:raise TypeError('exact construction mission input')
    return dict(mission=json.loads(mission_inputs_to_json(inputs.mission)),configuration=encode(inputs.configuration),limits=encode(inputs.limits),api=inputs.api)


def construction_input_digest(inputs):return sha256(canonical_json(dict(domain=FORMAT,inputs=input_data(inputs))).encode()).hexdigest()


def inputs_to_json(inputs):
    data=input_data(inputs)
    return canonical_json(dict(format=FORMAT,version=1,inputs=data,digest=construction_input_digest(inputs)))


def inputs_from_json(text,*,expected_digest=None):
    if type(text) is not str or len(text.encode())>MAX_INPUT:raise ValueError('construction input byte bound')
    p=object_fields(parse_json(text),('format','version','inputs','digest'));_bounded_tree(p)
    if p['format']!=FORMAT or type(p['version']) is not int or p['version']!=1:raise ValueError('unsupported construction format')
    d=object_fields(p['inputs'],('mission','configuration','limits','api'))
    admit(d['configuration']);admit(d['limits'])
    calculated=sha256(canonical_json(dict(domain=FORMAT,inputs=d)).encode()).hexdigest()
    if p['digest']!=calculated or expected_digest is not None and expected_digest!=calculated:raise ValueError('construction input digest mismatch')
    result=ConstructionMissionInputs(mission_inputs_from_json(canonical_json(d['mission'])),decode(d['configuration']),decode(d['limits']),d['api'])
    if inputs_to_json(result)!=canonical_json(p):raise ValueError('noncanonical construction input')
    return result


def save_construction_continuation(path,state):
    if state.harness is not None:raise ValueError('B46 requires explicit harness continuation; no implicit migration')
    validate_context_inputs(state);guard_construction_state(state)
    if type(state.cursor) is not int or not 0<=state.cursor<=len(state.inputs.actions) or state.cursor!=len(state.outcomes):raise ValueError('completed construction boundary required')
    if tuple(o.action_id for o in state.outcomes)!=tuple(a.action_id for a in state.inputs.actions[:state.cursor]):raise ValueError('foreign causal action history')
    now=state.inputs.environment.start_seconds if state.cursor==0 else state.outcomes[-1].end_seconds
    steps=state.inputs.initial_checkpoint.restore(state.inputs.simulation_inputs).diagnostics.completed_steps+sum(o.status=='completed' for o in state.outcomes)
    if state.context.simulation_time_seconds!=now or state.attitude.at_seconds!=now or state.context.diagnostics.completed_steps!=steps:raise ValueError('stale construction boundary')
    reserve_output(state);state.source_authority.guard()
    p=dict(format=PACKET,version=1,input_digest=state.construction.input_digest,
        inputs=json.loads(inputs_to_json(state.construction.inputs)),cursor=state.cursor,
        context=CheckpointState.from_context(state.context).to_dict(),science=_scientific(scientific_projection(state)),
        runtime_work=asdict(state.runtime_work),construction_work=asdict(state.construction.work))
    _bounded_tree(p);raw=(canonical_json(p)+'\n').encode()
    if len(raw)>min(MAX_PACKET,state.inputs.limits.max_document_bytes):raise ValueError('construction packet byte bound')
    with Path(path).open('xb') as f:f.write(raw)
    return sha256(raw).hexdigest()


def restore_construction_continuation(path,*,expected_packet_sha256,expected_input_digest):
    _hash(expected_packet_sha256);_hash(expected_input_digest);path=Path(path)
    if path.stat().st_size>MAX_PACKET:raise ValueError('construction packet byte bound')
    raw=path.read_bytes()
    if sha256(raw).hexdigest()!=expected_packet_sha256:raise ValueError('edited/reset construction packet')
    p=object_fields(parse_json(raw.decode()),('format','version','input_digest','inputs','cursor','context','science','runtime_work','construction_work'));_bounded_tree(p)
    if p['format']!=PACKET or type(p['version']) is not int or p['version']!=1:raise ValueError('unsupported construction continuation; no migration')
    if p['input_digest']!=expected_input_digest:raise ValueError('foreign construction identity')
    inputs=inputs_from_json(canonical_json(p['inputs']),expected_digest=expected_input_digest)
    if len(raw)>inputs.mission.limits.max_document_bytes:raise ValueError('bound packet quota')
    cursor=p['cursor']
    if type(cursor) is not int or not 0<=cursor<=len(inputs.mission.actions):raise ValueError('bounded causal cursor')
    work=RuntimeWork(**object_fields(p['runtime_work'],tuple(RuntimeWork.__dataclass_fields__)));work.validate(inputs.mission.limits)
    coupled=ConstructionWork(**object_fields(p['construction_work'],tuple(ConstructionWork.__dataclass_fields__)));coupled.validate(inputs.limits)
    before=asdict(work);cbefore=asdict(coupled)
    from .reconstruction_planning import plan_reconstruction,admit_runtime,admit_construction
    plan=plan_reconstruction(inputs.mission,cursor)
    admit_runtime(plan,inputs.mission,work);admit_construction(plan,inputs,coupled)
    state=start_construction_mission(inputs,runtime_work=work,construction_work=coupled)
    while state.cursor<cursor:state=advance_construction_mission(state)
    if _scientific(scientific_projection(state))!=p['science'] or CheckpointState.from_context(state.context).to_dict()!=p['context']:raise ValueError('full causal construction replay mismatch')
    prefix={n:asdict(work)[n]-before[n] for n in before}
    cprefix={n:asdict(coupled)[n]-cbefore[n] for n in cbefore}
    if any(before[n]<prefix[n] for n in before if n!='reconstruction_count') or any(cbefore[n]<cprefix[n] for n in cbefore if n!='reconstruction_count'):raise ValueError('cumulative construction work reset')
    reserve_output(state,2);work.reconstruction_count+=1;coupled.reconstruction_count+=1
    work.validate(inputs.mission.limits);coupled.validate(inputs.limits)
    return state,dict(prior=before,construction_prior=cbefore,reconstruction_delta={n:asdict(work)[n]-before[n] for n in before},
        construction_delta={n:asdict(coupled)[n]-cbefore[n] for n in cbefore},original_anchor_seconds=inputs.mission.environment.start_seconds.numerator)
