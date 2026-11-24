"""Fixed version1 mass-input schema and complete causal partial-boundary replay."""
from dataclasses import fields,asdict
from hashlib import sha256
from pathlib import Path
import json
from .harness_mass import SpatialMassPoint,RouteMassDistribution,HarnessMassPolicy,HarnessAugmentationInputs
from .harness_mission import HarnessMissionInputs,HarnessWork,start_harness_mission,advance_harness_mission
from .construction_document import (inputs_to_json as coupled_to_json,inputs_from_json as coupled_from_json,
    encode as primitive_encode,admit as primitive_admit,decode as primitive_decode)
from .construction_mission import ConstructionWork,guard_construction_state
from .long_mission import RuntimeWork,scientific_projection,validate_context_inputs,reserve_output
from .long_mission_document import canonical_json
from .long_mission_continuation import _scientific,_bounded_tree,_hash
from .experiment_codec import parse_json,object_fields
from .checkpoint import CheckpointState
from .reconstruction_planning import plan_reconstruction,admit_runtime,admit_construction

FORMAT='B46_HARNESS_MISSION_INPUT_V1'
PACKET='B46_HARNESS_ACTION_BOUNDARY_CONTINUATION_V1'
MAX_INPUT=16*2**20;MAX_PACKET=512*2**20
MAP={c.__name__:c for c in (SpatialMassPoint,RouteMassDistribution,HarnessMassPolicy,HarnessAugmentationInputs)}


def encode(v):
    if type(v) in MAP.values():return dict(mass_type=type(v).__name__,fields={f.name:encode(getattr(v,f.name)) for f in fields(v)})
    if type(v) is tuple:return dict(mass_tuple=[encode(x) for x in v])
    return dict(primitive_input=primitive_encode(v))


def admit(v):
    if type(v) is not dict:raise ValueError('strict mass input object required')
    if set(v)=={'mass_type','fields'}:
        name=v['mass_type']
        if type(name) is not str or name not in MAP:raise ValueError('unsafe/non-input mass type')
        d=object_fields(v['fields'],tuple(f.name for f in fields(MAP[name])))
        if name=='HarnessAugmentationInputs':
            values=object_fields(d['routes'],('mass_tuple',))['mass_tuple']
            if type(values) is not list or len(values)!=8:raise ValueError('predecode exact eight mass routes')
        elif name=='RouteMassDistribution':
            values=object_fields(d['connector_points'],('mass_tuple',))['mass_tuple']
            if type(values) is not list or len(values)>2048:raise ValueError('predecode connector cap')
        for x in d.values():admit(x)
    elif set(v)=={'mass_tuple'}:
        if type(v['mass_tuple']) is not list or len(v['mass_tuple'])>2048:raise ValueError('bounded mass tuple')
        for x in v['mass_tuple']:admit(x)
    elif set(v)=={'primitive_input'}:primitive_admit(v['primitive_input'])
    else:raise ValueError('unknown executable mass fields')


def decode(v):
    if 'mass_type' in v:return MAP[v['mass_type']](**{n:decode(x) for n,x in v['fields'].items()})
    if 'mass_tuple' in v:return tuple(decode(x) for x in v['mass_tuple'])
    return primitive_decode(v['primitive_input'])


def input_data(inputs):
    if type(inputs) is not HarnessMissionInputs:raise TypeError('exact harness mission input required')
    return dict(coupled=json.loads(coupled_to_json(inputs.coupled)),augmentation=encode(inputs.augmentation),mass_mode=inputs.mass_mode,api=inputs.api)


def harness_input_digest(inputs):return sha256(canonical_json(dict(domain=FORMAT,inputs=input_data(inputs))).encode()).hexdigest()


def inputs_to_json(inputs):return canonical_json(dict(format=FORMAT,version=1,inputs=input_data(inputs),digest=harness_input_digest(inputs)))


def inputs_from_json(text,*,expected_digest=None):
    if type(text) is not str or len(text.encode())>MAX_INPUT:raise ValueError('bounded harness input document')
    p=object_fields(parse_json(text),('format','version','inputs','digest'));_bounded_tree(p)
    if p['format']!=FORMAT or type(p['version']) is not int or p['version']!=1:raise ValueError('unsupported harness format; no migration')
    d=object_fields(p['inputs'],('coupled','augmentation','mass_mode','api'));admit(d['augmentation'])
    # Global contribution admission before mass points/route objects allocation.
    if d['augmentation'].get('mass_type')!='HarnessAugmentationInputs':raise ValueError('exact augmentation root input required')
    routes=d['augmentation']['fields']['routes']['mass_tuple']
    if any(r.get('mass_type')!='RouteMassDistribution' for r in routes):raise ValueError('exact route distribution input required')
    connector_total=sum(len(r['fields']['connector_points']['mass_tuple']) for r in routes)
    coupled=object_fields(d['coupled'],('format','version','inputs','digest'))
    coupled_inputs=object_fields(coupled['inputs'],('mission','configuration','limits','api'))
    configuration=coupled_inputs['configuration'];primitive_admit(configuration)
    if configuration.get('construction_type')!='ConstructionConfiguration':raise ValueError('exact construction configuration input required')
    line_fields=configuration['fields']['lines']['construction_tuple']
    if len(line_fields)!=8 or any(l.get('construction_type')!='LineConnection' for l in line_fields):raise ValueError('exact eight line inputs required')
    upper=connector_total+sum(2*(len(l['fields']['waypoints_body_m']['construction_tuple'])+1)+2 for l in line_fields)
    if upper>2048:raise ValueError('predecode total contribution cap')
    calculated=sha256(canonical_json(dict(domain=FORMAT,inputs=d)).encode()).hexdigest()
    if p['digest']!=calculated or expected_digest is not None and expected_digest!=calculated:raise ValueError('harness input binding mismatch')
    result=HarnessMissionInputs(coupled_from_json(canonical_json(d['coupled'])),decode(d['augmentation']),d['mass_mode'],d['api'])
    if inputs_to_json(result)!=canonical_json(p):raise ValueError('noncanonical mass input')
    return result


def save_harness_continuation(path,state):
    if state.harness is None:raise ValueError('mass-aware boundary required')
    validate_context_inputs(state);guard_construction_state(state)
    if type(state.cursor) is not int or state.cursor!=len(state.outcomes) or not 0<=state.cursor<=len(state.inputs.actions):raise ValueError('completed harness boundary required')
    if tuple(o.action_id for o in state.outcomes)!=tuple(a.action_id for a in state.inputs.actions[:state.cursor]):raise ValueError('foreign completed history')
    expected=state.inputs.environment.start_seconds if state.cursor==0 else state.outcomes[-1].end_seconds
    steps=state.inputs.initial_checkpoint.restore(state.inputs.simulation_inputs).diagnostics.completed_steps+sum(o.status=='completed' for o in state.outcomes)
    if state.context.simulation_time_seconds!=expected or state.attitude.at_seconds!=expected or state.context.diagnostics.completed_steps!=steps:raise ValueError('stale harness boundary')
    reserve_output(state);state.source_authority.guard()
    p=dict(format=PACKET,version=1,input_digest=state.harness.input_digest,inputs=json.loads(inputs_to_json(state.harness.inputs)),
        cursor=state.cursor,context=CheckpointState.from_context(state.context).to_dict(),science=_scientific(scientific_projection(state)),
        runtime_work=asdict(state.runtime_work),construction_work=asdict(state.construction.work),harness_work=asdict(state.harness.work))
    _bounded_tree(p);raw=(canonical_json(p)+'\n').encode()
    if len(raw)>min(MAX_PACKET,state.inputs.limits.max_document_bytes):raise ValueError('harness packet byte bound')
    with Path(path).open('xb') as f:f.write(raw)
    return sha256(raw).hexdigest()


def restore_harness_continuation(path,*,expected_packet_sha256,expected_input_digest):
    _hash(expected_packet_sha256);_hash(expected_input_digest);path=Path(path)
    if path.stat().st_size>MAX_PACKET:raise ValueError('harness packet byte bound')
    raw=path.read_bytes()
    if sha256(raw).hexdigest()!=expected_packet_sha256:raise ValueError('edited/reset harness packet')
    p=object_fields(parse_json(raw.decode()),('format','version','input_digest','inputs','cursor','context','science','runtime_work','construction_work','harness_work'));_bounded_tree(p)
    if p['format']!=PACKET or type(p['version']) is not int or p['version']!=1 or p['input_digest']!=expected_input_digest:raise ValueError('foreign harness format/input; no migration')
    inputs=inputs_from_json(canonical_json(p['inputs']),expected_digest=expected_input_digest)
    if len(raw)>inputs.coupled.mission.limits.max_document_bytes:raise ValueError('bound harness packet quota')
    cursor=p['cursor']
    if type(cursor) is not int or not 0<=cursor<=len(inputs.coupled.mission.actions):raise ValueError('invalid harness cursor')
    runtime=RuntimeWork(**object_fields(p['runtime_work'],tuple(RuntimeWork.__dataclass_fields__)))
    construction=ConstructionWork(**object_fields(p['construction_work'],tuple(ConstructionWork.__dataclass_fields__)))
    masswork=HarnessWork(**object_fields(p['harness_work'],tuple(HarnessWork.__dataclass_fields__)))
    runtime.validate(inputs.coupled.mission.limits);construction.validate(inputs.coupled.limits);masswork.validate(inputs.augmentation.policy)
    plan=plan_reconstruction(inputs.coupled.mission,cursor)
    admit_runtime(plan,inputs.coupled.mission,runtime);admit_construction(plan,inputs.coupled,construction)
    count=cursor+sum(a.kind=='POINT' for a in inputs.coupled.mission.actions[:cursor])+2
    policy=inputs.augmentation.policy
    if masswork.compilation_calls+count>policy.max_runtime_compiles or masswork.control_reserved_units+count*policy.control_units_per_compile>policy.max_runtime_control_units:raise ValueError('HARNESS_RECONSTRUCTION_ADMISSION')
    before=[asdict(w) for w in (runtime,construction,masswork)]
    state=start_harness_mission(inputs,runtime_work=runtime,construction_work=construction,harness_work=masswork)
    while state.cursor<cursor:state=advance_harness_mission(state)
    if _scientific(scientific_projection(state))!=p['science'] or CheckpointState.from_context(state.context).to_dict()!=p['context']:raise ValueError('full causal harness replay mismatch')
    delta=[{n:asdict(w)[n]-b[n] for n in b} for w,b in zip((runtime,construction,masswork),before)]
    if any(b[n]<d[n] for b,d in zip(before,delta) for n in b if n!='reconstruction_count'):raise ValueError('reset cumulative harness replay history')
    reserve_output(state,2)
    for w in (runtime,construction,masswork):w.reconstruction_count+=1
    runtime.validate(inputs.coupled.mission.limits);construction.validate(inputs.coupled.limits);masswork.validate(policy)
    return state,dict(prior=before,reconstruction_delta=[{n:asdict(w)[n]-b[n] for n in b} for w,b in zip((runtime,construction,masswork),before)],original_anchor_seconds=inputs.coupled.mission.environment.start_seconds.numerator)
