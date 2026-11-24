"""Strict B47 input-only codec and paid complete causal prefix reconstruction."""
from dataclasses import fields, asdict
from hashlib import sha256
from pathlib import Path
import json
from .rolling_contract import (PublicPhysicalModel, RollingRoot, ReleasedRequest, DeclaredContact,
    RollingPolicy, RollingQuotas, integer)
from .rolling_knowledge import KnowledgeMode, ReceivedObservation
from .campaign_contract import ResourceObservation
from .checkpoint import CheckpointState, ThermalNodeStateSnapshot
from .assembly_attitude_3d import BodyAttitude3D
from .assembly_choices import AssemblyDesign
from .assembly_document import dumps_assembly_document, loads_assembly_document
from .state import OperationalMode, FDIRState
from .harness_mass import HarnessAugmentationInputs
from .harness_document import encode as mass_encode, admit as mass_admit, decode as mass_decode
from .construction_document import OWNERS, encode as construction_encode, admit as construction_admit, decode as construction_decode
from .long_mission_document import _encode as old_encode, _predecode as old_admit, _decode as old_decode, canonical_json
from .experiment_codec import parse_json, object_fields
from .long_mission_continuation import _bounded_tree, _scientific

FORMAT='M5_ROLLING_INPUT_V1'
PACKET='M5_ROLLING_PAID_CAUSAL_CONTINUATION_V1'
NEW=(PublicPhysicalModel,RollingRoot,ReleasedRequest,DeclaredContact,RollingPolicy,RollingQuotas,
     KnowledgeMode,ReceivedObservation,ResourceObservation,ThermalNodeStateSnapshot,BodyAttitude3D)
MAP={c.__name__:c for c in NEW}
ENUMS={c.__name__:c for c in (OperationalMode,FDIRState)}
MAX_INPUT=16*2**20
MAX_PACKET=512*2**20


def encode(v, *, input_codec=None):
    if input_codec is not None:
        from .prepared_input_codec import require_scope
        require_scope(input_codec)
    if type(v) in NEW:
        if input_codec is not None:input_codec.owner(type(v))
        result=dict(rolling_type=type(v).__name__,fields={f.name:encode(getattr(v,f.name),input_codec=input_codec) for f in fields(v)})
        if input_codec is not None:input_codec.owner(type(v))
        return result
    if type(v) in ENUMS.values():
        if input_codec is not None:input_codec.owner(type(v))
        return dict(observed_enum=type(v).__name__,member=v.name)
    if type(v) is CheckpointState:
        if input_codec is not None:input_codec.owner(CheckpointState)
        result=dict(private_root_checkpoint=v.to_dict())
        if input_codec is not None:input_codec.owner(CheckpointState)
        return result
    if type(v) is AssemblyDesign:
        if input_codec is not None:input_codec.owner(AssemblyDesign)
        result=dict(assembly=json.loads(dumps_assembly_document(v)))
        if input_codec is not None:input_codec.owner(AssemblyDesign)
        return result
    if type(v) is HarnessAugmentationInputs: return dict(mass=mass_encode(v)if input_codec is None else input_codec.mass_encode(v))
    if type(v) in OWNERS: return dict(construction=construction_encode(v)if input_codec is None else input_codec.construction_encode(v))
    if type(v) is tuple: return dict(rolling_tuple=[encode(x,input_codec=input_codec) for x in v])
    return dict(immutable_input=old_encode(v)if input_codec is None else input_codec.long_encode(v))


def admit(v, depth=0, *, input_codec=None):
    if input_codec is not None:
        from .prepared_input_codec import require_scope
        require_scope(input_codec)
    if depth>64 or type(v) is not dict: raise ValueError('bounded exact input object')
    if set(v)=={'rolling_type','fields'}:
        name=v['rolling_type']
        if type(name) is not str or name not in MAP: raise ValueError('unsafe/non-input rolling type')
        if input_codec is not None:input_codec.owner(MAP[name])
        d=object_fields(v['fields'],tuple(f.name for f in fields(MAP[name])))
        caps={'RollingRoot':{'requests':16,'contacts':64},'PublicPhysicalModel':{'catalog':16,'capabilities':32},
              'ResourceObservation':{'observed_temperatures':32},'ReceivedObservation':{'onboard_records':16,'partial_transfers':16,'delivery_acks':16,'consumed_contacts':128}}
        for name,cap in caps.get(v['rolling_type'],{}).items():
            arr=object_fields(d[name],('rolling_tuple',))['rolling_tuple']
            if type(arr) is not list or len(arr)>cap: raise ValueError('preallocation input cardinality:'+name)
        for x in d.values(): admit(x,depth+1,input_codec=input_codec)
        if input_codec is not None:input_codec.owner(MAP[v['rolling_type']])
    elif set(v)=={'rolling_tuple'}:
        if type(v['rolling_tuple']) is not list or len(v['rolling_tuple'])>256: raise ValueError('bounded tuple')
        for x in v['rolling_tuple']: admit(x,depth+1,input_codec=input_codec)
    elif set(v)=={'observed_enum','member'}:
        if type(v['observed_enum']) is not str or v['observed_enum'] not in ENUMS or type(v['member']) is not str or v['member'] not in ENUMS[v['observed_enum']].__members__:
            raise ValueError('exact observed enum')
    elif set(v)=={'private_root_checkpoint'}:
        if type(v['private_root_checkpoint']) is not dict: raise ValueError('exact private root checkpoint')
        if input_codec is not None:input_codec.owner(CheckpointState)
        CheckpointState.from_dict(v['private_root_checkpoint'])
        if input_codec is not None:input_codec.owner(CheckpointState)
    elif set(v)=={'assembly'}:
        if input_codec is not None:input_codec.owner(AssemblyDesign)
        loads_assembly_document(canonical_json(v['assembly']))
        if input_codec is not None:input_codec.owner(AssemblyDesign)
    elif set(v)=={'mass'}:
        if input_codec is None:mass_admit(v['mass'])
        else:input_codec.mass_admit(v['mass'],depth+1)
    elif set(v)=={'construction'}:
        if input_codec is None:construction_admit(v['construction'])
        else:input_codec.construction_admit(v['construction'],depth+1)
    elif set(v)=={'immutable_input'}:
        if input_codec is None:old_admit(v['immutable_input'])
        else:input_codec.long_admit(v['immutable_input'],depth+1)
    else: raise ValueError('unknown/executable input fields')


def decode(v, *, input_codec=None):
    if input_codec is not None:
        from .prepared_input_codec import require_scope
        require_scope(input_codec)
    if 'rolling_type' in v:
        owner=MAP[v['rolling_type']]
        if input_codec is not None:input_codec.owner(owner)
        result=owner(**{n:decode(x,input_codec=input_codec) for n,x in v['fields'].items()})
        if input_codec is not None:input_codec.owner(owner)
        return result
    if 'rolling_tuple' in v: return tuple(decode(x,input_codec=input_codec) for x in v['rolling_tuple'])
    if 'observed_enum' in v:
        owner=ENUMS[v['observed_enum']]
        if input_codec is not None:input_codec.owner(owner)
        return owner[v['member']]
    if 'private_root_checkpoint' in v:
        if input_codec is not None:input_codec.owner(CheckpointState)
        result=CheckpointState.from_dict(v['private_root_checkpoint'])
        if input_codec is not None:input_codec.owner(CheckpointState)
        return result
    if 'assembly' in v:
        if input_codec is not None:input_codec.owner(AssemblyDesign)
        result=loads_assembly_document(canonical_json(v['assembly']))
        if input_codec is not None:input_codec.owner(AssemblyDesign)
        return result
    if 'mass' in v: return mass_decode(v['mass'])if input_codec is None else input_codec.mass_decode(v['mass'])
    if 'construction' in v: return construction_decode(v['construction'])if input_codec is None else input_codec.construction_decode(v['construction'])
    return old_decode(v['immutable_input'])if input_codec is None else input_codec.long_decode(v['immutable_input'])


def inputs_to_json(root, *, input_codec=None):
    if type(root) is not RollingRoot: raise TypeError('typed rolling root required')
    root.__post_init__(); data=encode(root,input_codec=input_codec)
    digest=sha256(canonical_json(dict(domain=FORMAT,inputs=data)).encode()).hexdigest()
    text=canonical_json(dict(format=FORMAT,version=1,inputs=data,digest=digest))
    if len(text.encode())>MAX_INPUT: raise ValueError('input bytes exceeded')
    return text


def inputs_from_json(text, *, expected_digest=None, input_codec=None):
    if type(text) is not str or len(text.encode())>MAX_INPUT: raise ValueError('bounded exact input text')
    p=object_fields(parse_json(text),('format','version','inputs','digest'));_bounded_tree(p)
    if p['format']!=FORMAT or type(p['version']) is not int or p['version']!=1: raise ValueError('unsupported rolling schema')
    if type(p['inputs']) is not dict or p['inputs'].get('rolling_type')!='RollingRoot': raise ValueError('exact root type')
    admit(p['inputs'],input_codec=input_codec)
    digest=sha256(canonical_json(dict(domain=FORMAT,inputs=p['inputs'])).encode()).hexdigest()
    if p['digest']!=digest or expected_digest is not None and expected_digest!=digest: raise ValueError('input digest mismatch')
    result=decode(p['inputs'],input_codec=input_codec)
    if inputs_to_json(result,input_codec=input_codec)!=canonical_json(p): raise ValueError('noncanonical input document')
    return result


def save_continuation(path,state):
    from .rolling_execution import guard_rolling,scientific_projection,work_projection
    guard_rolling(state)
    state.work.charge('control_reserved',2*((MAX_PACKET+63)//64)+4*2**20,state.root.quotas)
    # Exact packet size is admitted before its final byte allocation; primitive
    # metadata and the input-bound retained causal tree remain independently capped.
    from .command_estimation import CommandRollingRoot
    command=type(state.root) is CommandRollingRoot
    from .command_document import inputs_to_json as command_to_json,PACKET as command_packet
    data=dict(format=command_packet if command else PACKET,version=1,inputs=json.loads(command_to_json(state.root) if command else inputs_to_json(state.root)),root_identity=state.root_identity,
        completed_decisions=len(state.decisions),scientific=_scientific(scientific_projection(state)),paid_work=work_projection(state))
    from .rolling_cache import canonical_size
    def size():
        return canonical_size(data,min(MAX_PACKET,state.root.model.limits.max_document_bytes))
    initial_size=size()
    state.work.admit_output_capacity(initial_size+64,state.root.quotas)
    # Finite four-step decimal-length fixed point for the persisted byte charge.
    prior=state.work.output_bytes;prior_encoded=state.work.publication_reencoded_bytes;count=initial_size
    for _ in range(4):
        data['paid_work']['aggregate']['output_bytes']=prior+count
        data['paid_work']['aggregate']['publication_reencoded_bytes']=prior_encoded+count
        data['paid_work']['aggregate']['output_capacity_peak_bytes']=state.work.output_capacity_peak_bytes
        data['paid_work']['aggregate']['output_admission_events']=state.work.output_admission_events
        updated=size()
        if updated==count: break
        count=updated
    else: raise ValueError('packet byte-accounting finalization failed')
    raw=canonical_json(data).encode()
    if len(raw)!=count: raise ValueError('packet byte finalization mismatch')
    state.work.charge('output_bytes',len(raw),state.root.quotas)
    state.work.publication_reencoded_bytes+=len(raw);state.work.validate(state.root.quotas)
    with Path(path).open('xb') as f: f.write(raw)
    return sha256(raw).hexdigest()


def admit_reconstruction(root, count, prior):
    """Static conservative admission before any source or physics reconstruction.

    Each replay is a distinct old-bounded invocation. The new global family
    retains prior and replay work; saved predictions/counters never seed physics.
    """
    integer(count,'prefix count',0,root.policy.max_decisions)
    from .rolling_cache import CumulativeWork
    p=object_fields(prior,tuple(f.name for f in fields(CumulativeWork)))
    if type(p['invocation_records']) is not list or len(p['invocation_records'])>520: raise ValueError('paid history cap')
    owned=json.loads(json.dumps(p))
    # JSON turns only this explicitly typed derived membership tuple into list.
    if type(owned['publication_reuse_seen']) is not list: raise ValueError('reuse membership array')
    owned['publication_reuse_seen']=tuple(owned['publication_reuse_seen'])
    work=CumulativeWork(**owned);work.validate(root.quotas)
    forecast_bound=count*min(root.policy.max_candidates,4*len(root.requests)+3)
    additions=dict(forecast_invocations=forecast_bound,
        forecast_physical_reserved=forecast_bound*root.model.limits.max_physical_substeps,
        construction_line_reserved=8*(forecast_bound+1)*root.model.limits.max_physical_substeps,
        harness_compiles=10*forecast_bound+2*count+1,
        actual_physical_reserved=root.model.limits.max_physical_substeps,
        nominal_force_reserved=2*root.model.nominal_policy.max_force_reservations,
        control_reserved=(forecast_bound+1)*root.model.limits.max_output_control_units+10*forecast_bound*2**20,
        reconstructions=1)
    for n,amount in additions.items():
        if getattr(work,n)+amount>getattr(root.quotas,'max_'+n): raise ValueError('RECONSTRUCTION_ADMISSION:'+n)
    # Replay computes every forecast/physical transition again. It may retain
    # only byte-identical prior canonical publications, once per hash. Inputs,
    # knowledge and time are inside those complete publications. Their saved
    # scientific values never seed physics. Any unknown/mismatching publication
    # fails atomically; prior lengths are a static maximum for exact reuse.
    byte_bound=sum(work.publication_digests.values())
    if work.publication_reencoded_bytes+byte_bound>root.quotas.max_output_bytes:
        raise ValueError('RECONSTRUCTION_ADMISSION:reencoded_bytes')
    additions['canonical_reencoded_byte_bound']=byte_bound
    # Admission bounds are not claimed as executed work and are not refunds.
    return work, additions


def restore_continuation(path, *, expected_packet_sha256, expected_root_identity):
    p=Path(path)
    if p.stat().st_size>MAX_PACKET: raise ValueError('packet bytes exceeded')
    raw=p.read_bytes()
    if type(expected_packet_sha256) is not str or sha256(raw).hexdigest()!=expected_packet_sha256: raise ValueError('external packet binding mismatch')
    d=object_fields(parse_json(raw.decode('utf-8')),('format','version','inputs','root_identity','completed_decisions','scientific','paid_work'));_bounded_tree(d)
    from .command_document import PACKET as command_packet,inputs_from_json as command_from_json,admit_command_reconstruction
    if type(d['format']) is not str or d['format'] not in (PACKET,command_packet) or type(d['version']) is not int or d['version']!=1: raise ValueError('unsupported continuation')
    command=d['format']==command_packet
    from .rolling_physics import digest
    root=(command_from_json if command else inputs_from_json)(canonical_json(d['inputs']))
    if digest(root)!=d['root_identity'] or d['root_identity']!=expected_root_identity: raise ValueError('external root binding mismatch')
    work_data=object_fields(d['paid_work'],('aggregate','actual_runtime','actual_construction','actual_harness','actual_public_cache','forecast_public_cache'))
    work,bound=(admit_command_reconstruction if command else admit_reconstruction)(root,d['completed_decisions'],work_data['aggregate'])
    # Preserve complete previous invocation ledgers, including actual/caches.
    work.invocation_records.append(dict(kind='PAID_PRIOR_RECONSTRUCTION_BUNDLE',bundle=json.loads(json.dumps(work_data))))
    work.publication_reuse_mode=True;work.publication_reuse_seen=()
    work.charge('reconstructions',1,root.quotas)
    from .rolling_execution import start_rolling,run_rolling,scientific_bytes
    state=run_rolling(start_rolling(root,work=work),stop_after=d['completed_decisions'])
    if len(state.decisions)!=d['completed_decisions'] or json.loads(scientific_bytes(state))!=d['scientific']:
        raise ValueError('FULL_CAUSAL_REPLAY_MISMATCH')
    state.work.publication_reuse_mode=False
    return state,dict(method='B48_FRESH_PAID_COMMAND_CAUSAL_REPLAY_V1' if command else 'B47_FRESH_PAID_CAUSAL_REPLAY_V1',admitted_bound=bound,prior_work=work_data,
        replay_completed_decisions=len(state.decisions),scientific_equal=True)
