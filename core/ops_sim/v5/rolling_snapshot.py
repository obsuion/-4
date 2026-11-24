"""Direct restoration of trusted, bounded short nominal B48 owner state.

This is advanced-state authority. Hashes establish local bindings, not an
independent reachability proof. Historical causal replay remains separate.
"""
from dataclasses import asdict, fields
from hashlib import sha256
import math
from .rolling_snapshot_document import GraphCodec, canonical, parse_snapshot, MAX_BYTES,admit_graph_structure,CONTROL_ALLOWANCE
from .experiment_codec import object_fields
from .rolling_execution import RollingState, guard_rolling
from .rolling_physics import AdaptivePhysicalState, digest
from .checkpoint import CheckpointState
from .rolling_cache import PublicCacheBank
from .long_nominal_provider import LongNominalProvider, NominalWork, METHOD as ORBIT_METHOD, _digest
from .long_environment import AcquiredLongEnvironment, NOMINAL
from .orbit_j2 import _authorities

METHOD='B51_DIRECT_NOMINAL_SHORT_STATE_V1'
FORMAT='B51_TRUSTED_ADVANCED_SNAPSHOT_V1'
BINDINGS=('root_identity','revision','source_identity','runtime','project_input_sha256','method','clock')
PHYSICAL=('inputs','attitude','runtime_work','construction','harness','seed_identity','model_identity',
    'seed_seconds','seed_steps','cursor','commands','outcomes','acquisitions','consumed_contacts','source_result')
ROLLING=('knowledge','queued','decisions','command_lineage','status','boundary_identity',
    'retained_bytes_upper','intents','reconciliations','diagnosis')

def checked_bindings(value):
    object_fields(value,BINDINGS)
    for n in ('root_identity','revision','source_identity','project_input_sha256'):
        s=value[n]
        if type(s) is not str or len(s)!=64 or any(c not in '0123456789abcdef' for c in s):raise ValueError('snapshot binding hash: '+n)
    if value['method']!=METHOD or type(value['clock']) is not int or not 128<=value['clock']<=728:raise ValueError('snapshot method/clock')
    object_fields(value['runtime'],('python','platform','executable','interpreter_sha256'))
    if any(type(x) is not str or not x for x in value['runtime'].values()):raise ValueError('snapshot runtime')
    return value

def _cache_data(bank):
    p=bank.provider;e=bank.environment;p.validate()
    if bank.model.environment.mode!=NOMINAL or p.failed or e.source is not None:raise ValueError('snapshot V1 only nominal nonfailure cache')
    return dict(ownership=bank.ownership,provider_identity=p.identity,environment_identity=e.identity,
        prefix=p._prefix,tails=p._tails,work=p.work,lighting=e._lighting,
        controls=e.controls,lookups=e.lookups,guards=e.guards)

def capture_snapshot(state,bindings,*,report_state=None):
    guard_rolling(state);checked_bindings(bindings)
    if bindings['root_identity']!=state.root_identity or bindings['clock']!=state.physical.context.simulation_time_seconds:
        raise ValueError('committed snapshot boundary binding')
    if state.root.model.environment.mode!=NOMINAL or state.root.model.environment.end_seconds>728:raise ValueError('unsupported snapshot domain')
    p=state.physical
    if p.nominal_provider.bank is not state.actual_cache or p.source_authority.bank is not state.actual_cache:
        raise ValueError('snapshot actual owner binding')
    graph=GraphCodec(state.root)
    payload=dict(checkpoint=CheckpointState.from_context(p.context).to_dict(),
        physical={n:getattr(p,n) for n in PHYSICAL},rolling={n:getattr(state,n) for n in ROLLING},
        work=state.work,actual=_cache_data(state.actual_cache),forecast=_cache_data(state.forecast_cache),
        report=report_state)
    encoded=graph.encode(payload)
    document=dict(format=FORMAT,version=1,bindings=bindings,graph=encoded)
    from .rolling_cache import canonical_size
    count=canonical_size(document,MAX_BYTES)
    raw=canonical(document).encode()
    if count!=len(raw):raise ValueError('snapshot exact byte admission')
    paid=dict(method=METHOD,encoding_nodes=len(encoded['nodes']),encoding_control_units=graph.units+graph.visits,
        encoding_control_reserved_units=CONTROL_ALLOWANCE,
        encoding_bytes=len(raw),storage_bytes=len(raw),retained_prior_work=asdict(state.work),
        retained_history='FULL_BOUNDED_SHORT_PREFIX_NOT_LONG_CONSTANT_SIZE')
    return raw,paid

def admit_snapshot(raw,*,expected_sha256,expected_bindings):
    checked_bindings(expected_bindings)
    if type(expected_sha256) is not str or sha256(raw).hexdigest()!=expected_sha256:raise ValueError('external snapshot SHA')
    document=parse_snapshot(raw)
    object_fields(document,('format','version','bindings','graph'))
    if document['format']!=FORMAT or type(document['version']) is not int or document['version']!=1:raise ValueError('snapshot version')
    checked_bindings(document['bindings'])
    if document['bindings']!=expected_bindings:raise ValueError('snapshot source/runtime/root/revision/input/method/clock mismatch')
    admit_graph_structure(document['graph'])
    return document

def _restore_cache(model,work,quotas,data,ownership):
    object_fields(data,('ownership','provider_identity','environment_identity','prefix','tails','work','lighting','controls','lookups','guards'))
    if data['ownership']!=ownership or model.environment.mode!=NOMINAL:raise ValueError('snapshot bank ownership/mode')
    bank=PublicCacheBank.__new__(PublicCacheBank)
    bank.model=model;bank.work=work;bank.quotas=quotas;bank.ownership=ownership
    def charge(name,count):
        work.charge('nominal_force_reserved' if name=='nominal_force_reserved' else 'control_reserved',count,quotas)
    trajectory=model.environment.trajectory;policy=model.nominal_policy
    state,gravity=_authorities(trajectory.initial_state,trajectory.gravity_model)
    # Dedicated fixed owner reconstruction avoids __init__'s initial gravity call.
    p=LongNominalProvider.__new__(LongNominalProvider)
    p.trajectory=trajectory;p.policy=policy;p.anchor=state.position;p.model=gravity
    p.identity=_digest((ORBIT_METHOD,trajectory,policy));p._charge=charge;p.failed=False
    if p.identity!=data['provider_identity'] or type(data['work']) is not NominalWork:raise ValueError('snapshot provider identity/work')
    p.work=data['work'];p._prefix=data['prefix'];p._tails=data['tails']
    if type(p._prefix) is not dict or set(p._prefix)!= {-1,1} or type(p._tails) is not dict:raise ValueError('snapshot signed original grid')
    initial=(state.position.components_m,state.velocity.components_m_per_s)
    for xs in p._prefix.values():
        if type(xs) is not list or not xs or len(xs)>policy.max_steps+1 or xs[0]!=initial:raise ValueError('snapshot original anchor/prefix')
    values=[x for xs in p._prefix.values() for x in xs]+list(p._tails.values())
    for x in values:
        if type(x) is not tuple or len(x)!=2 or any(type(y) is not tuple or len(y)!=3 or any(type(z) is not float or not math.isfinite(z) for z in y) for y in x):raise ValueError('snapshot Cartesian cache record')
    w=p.work
    if any(type(getattr(w,f.name)) is not int or getattr(w,f.name)<0 for f in fields(w)):raise ValueError('snapshot cache counter')
    if w.full_steps!=sum(len(x)-1 for x in p._prefix.values()) or w.tail_steps!=len(p._tails) or w.cache_records!=1+w.full_steps+w.tail_steps:
        raise ValueError('snapshot cache ledger/retained states')
    if w.force_completed!=1+4*(w.full_steps+w.tail_steps) or w.force_reserved!=w.force_completed or w.unknown_primitive_events:
        raise ValueError('snapshot cache force ledger')
    if w.cache_records>policy.max_cache_records or w.force_reserved>policy.max_force_reservations or w.control_reserved>policy.max_control_units or w.queries>policy.max_queries:raise ValueError('snapshot cache quota')
    p.validate();bank.provider=p
    e=AcquiredLongEnvironment(model.environment,p,charge=charge)
    if e.identity!=data['environment_identity']:raise ValueError('snapshot environment identity')
    if type(data['lighting']) is not dict or len(data['lighting'])>8192:raise ValueError('snapshot lighting bound')
    for k,v in data['lighting'].items():
        if type(k) is not int or not 0<=k<8192 or v not in ('ILLUMINATED','OCCULTED'):raise ValueError('snapshot lighting record')
    e._lighting=data['lighting']
    for n in ('controls','lookups','guards'):
        v=data[n]
        if type(v) is not int or not 0<=v<=model.environment.max_index_control_units:raise ValueError('snapshot environment counters')
        setattr(e,n,v)
    bank.environment=e
    return bank

def restore_snapshot(raw,root,*,expected_sha256,expected_bindings):
    document=admit_snapshot(raw,expected_sha256=expected_sha256,expected_bindings=expected_bindings)
    if digest(root)!=expected_bindings['root_identity']:raise ValueError('snapshot caller immutable root')
    codec=GraphCodec(root);data=codec.decode(document['graph'])
    object_fields(data,('checkpoint','physical','rolling','work','actual','forecast','report'))
    object_fields(data['physical'],PHYSICAL);object_fields(data['rolling'],ROLLING)
    context=CheckpointState.from_dict(data['checkpoint']).restore(root.model.simulation_inputs)
    if context.simulation_time_seconds!=expected_bindings['clock']:raise ValueError('snapshot checkpoint clock')
    work=data['work'];work.validate(root.quotas)
    actual=_restore_cache(root.model,work,root.quotas,data['actual'],'ACTUAL_PUBLIC_MODEL')
    forecast=_restore_cache(root.model,work,root.quotas,data['forecast'],'FORECAST_PUBLIC_MODEL')
    p=data['physical'];rt=p['runtime_work'];rt.validate(root.model.limits)
    from .rolling_physics import PhysicalInputs
    if type(p['inputs']) is not PhysicalInputs or digest(p['inputs'].model)!=digest(root.model) or p['inputs'].limits!=root.model.limits or p['inputs'].api!='B47_PRIVATE_PHYSICAL_SEED_V1':raise ValueError('snapshot physical input/model binding')
    if digest(p['inputs'].products)!=digest(tuple(r.product for r in root.requests)):raise ValueError('snapshot product authority')
    if p['seed_identity']!='ACTUAL_ROOT:'+expected_bindings['root_identity'] or p['model_identity']!=digest((root.model,p['inputs'].products,p['inputs'].limits)) or p['seed_seconds']!=root.initial_checkpoint.simulation_time_seconds or p['seed_steps']!=root.initial_checkpoint.diagnostics.completed_steps or p['source_result'] is not None:raise ValueError('snapshot original actual seed binding')
    if type(p['cursor']) is not int or not 0<=p['cursor']<=64 or type(p['commands']) is not tuple or type(p['outcomes']) is not tuple or len(p['commands'])!=p['cursor'] or len(p['outcomes'])!=p['cursor']:raise ValueError('snapshot complete physical prefix')
    if p['attitude'].at_seconds!=context.simulation_time_seconds or p['attitude'].body_frame_id!=root.model.assembly.body_frame_id or p['attitude'].inertial_frame!=root.model.environment.trajectory.initial_state.position.frame:raise ValueError('snapshot body/time/frame binding')
    provider,source=actual.bind(rt)
    physical=AdaptivePhysicalState(context=context,nominal_provider=provider,source_authority=source,**p)
    result=RollingState(root,expected_bindings['root_identity'],physical,actual,forecast,work,**data['rolling'])
    guard_rolling(result)
    proof=dict(method=METHOD,restored_clock=context.simulation_time_seconds,
        pending=[c.kind for c in result.knowledge.pending()],
        queued_packet_ids=[x.packet_id for x in result.queued],
        partial_bits=[p.transmitted_equivalent_bits for p in context.ground_data_delivery_state.partial_transfers],
        retained_prior_work=asdict(work),validation_control_units=codec.units+codec.visits,
        validation_control_reserved_units=CONTROL_ALLOWANCE,
        validation_bytes=len(raw),retained_graph_nodes=len(document['graph']['nodes']),
        original_anchor_seconds=actual.provider.anchor.instant.elapsed_seconds,
        RNG='NONE_USED_BY_SUPPORTED_OWNERS',reachability='TRUSTED_GENERATED_OWNER_NOT_INDEPENDENT_PROOF')
    return result,data['report'],proof
