"""Strict, replay-validated short action-boundary continuation, format 1.

A packet's externally retained SHA-256 is required: a checksum is not an
attestation of arbitrary physical state or an authenticated ownership history.
Derived results are saved as comparison DATA only; fresh owner evidence always
starts from the original anchor. Completed history is recomputed privately,
never appended again to the published mission. All replay work is charged.
"""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from .environment_mission_3d import (EnvironmentMissionState3D, RuntimeWork,
    start_environment_mission, advance_environment_mission, scientific_projection, admit_operational_regime)
from .environment_mission_general_document import (mission_input_digest, mission_inputs_to_json,
    mission_inputs_from_json, canonical_json)
from .environment_forcing_document import _bounded_tree
from .experiment_codec import object_fields, parse_json
from .checkpoint import CheckpointState

FORMAT='B43_GENERAL_EARTH_ACTION_BOUNDARY_CONTINUATION_V4'
MAX_BYTES=16*2**20


def _hash(v):
    if type(v) is not str or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
        raise ValueError('external lowercase SHA-256 binding required')
    return v


def _scientific(value):
    # Output-only fixed canonical encoding, deliberately no decoder/imports.
    from dataclasses import fields,is_dataclass
    from enum import Enum
    from fractions import Fraction
    from decimal import Decimal
    if isinstance(value,Enum):return dict(enum_type=type(value).__module__+'.'+type(value).__qualname__,member=value.name)
    if type(value) is Decimal:
        t=value.as_tuple();return dict(decimal_tuple=dict(sign=t.sign,digits=list(t.digits),exponent=t.exponent))
    if type(value) is Fraction:return dict(numerator_hex=hex(value.numerator),denominator_hex=hex(value.denominator))
    if type(value) is float:return dict(float_hex=value.hex())
    if is_dataclass(value):return dict(record_type=type(value).__module__+'.'+type(value).__qualname__,
        fields={f.name:_scientific(getattr(value,f.name)) for f in fields(value)})
    if type(value) in (tuple,list):return {'tuple' if type(value) is tuple else 'list':[_scientific(x) for x in value]}
    if type(value) is dict:return {k:_scientific(x) for k,x in value.items()}
    if value is None or type(value) in (str,int,bool):return value
    raise TypeError('unsupported scientific output')


def scientific_bytes(state):
    return (canonical_json(_scientific(scientific_projection(state)))+'\n').encode()


def save_continuation(path,state):
    if type(state) is not EnvironmentMissionState3D:raise TypeError('mission state required')
    if mission_input_digest(state.inputs)!=state.input_digest:raise ValueError('foreign mission state')
    state.runtime_work.validate(state.inputs.limits)
    admit_operational_regime(state.context)
    if type(state.cursor) is not int or state.cursor!=len(state.outcomes) or not 0<=state.cursor<=len(state.inputs.actions):
        raise ValueError('completed action boundary required')
    if tuple(o.action_id for o in state.outcomes)!=tuple(a.action_id for a in state.inputs.actions[:state.cursor]):
        raise ValueError('foreign completed-action history')
    # A stale alias of a mutable context is not a new completed boundary.
    initial=state.inputs.initial_checkpoint.restore(state.inputs.simulation_inputs)
    now=initial.simulation_time_seconds if not state.outcomes else state.outcomes[-1].end_seconds
    steps=initial.diagnostics.completed_steps+sum(o.status=='completed' for o in state.outcomes)
    if state.context.simulation_time_seconds!=now or state.attitude.at_seconds!=now or state.context.diagnostics.completed_steps!=steps:
        raise ValueError('stale action-boundary state')
    packet=dict(format=FORMAT,version=4,input_digest=state.input_digest,
        inputs=json.loads(mission_inputs_to_json(state.inputs)),cursor=state.cursor,
        context=CheckpointState.from_context(state.context).to_dict(),
        scientific=_scientific(scientific_projection(state)),runtime_work=asdict(state.runtime_work),
        trust='EXTERNAL_PACKET_BINDING_AND_PRIVATE_ORIGINAL_ANCHOR_REPLAY_V1')
    data=(canonical_json(packet)+'\n').encode()
    if len(data)>min(MAX_BYTES,state.inputs.limits.max_document_bytes):raise ValueError('continuation exceeds finite document limit')
    with Path(path).open('xb') as f:f.write(data)
    return sha256(data).hexdigest()


def _admit(path,expected_packet_sha256,expected_input_digest):
    _hash(expected_packet_sha256);_hash(expected_input_digest)
    p=Path(path)
    if p.stat().st_size>MAX_BYTES:raise ValueError('continuation document bound exceeded')
    raw=p.read_bytes()
    if sha256(raw).hexdigest()!=expected_packet_sha256:raise ValueError('foreign/edited packet or reset quota history')
    data=object_fields(parse_json(raw.decode('utf-8')),('format','version','input_digest','inputs','cursor',
        'context','scientific','runtime_work','trust'));_bounded_tree(data)
    if data['format']!=FORMAT or type(data['version']) is not int or data['version']!=4:
        raise ValueError('unsupported continuation format')
    if data['trust']!='EXTERNAL_PACKET_BINDING_AND_PRIVATE_ORIGINAL_ANCHOR_REPLAY_V1':raise ValueError('unsafe trust contract')
    if data['input_digest']!=expected_input_digest:raise ValueError('foreign input authority')
    inputs=mission_inputs_from_json(canonical_json(data['inputs']),expected_digest=expected_input_digest)
    if len(raw)>inputs.limits.max_document_bytes:raise ValueError('packet exceeds bound input quota')
    cursor=data['cursor']
    if type(cursor) is not int or not 0<=cursor<=len(inputs.actions):raise ValueError('invalid completed-action cursor')
    work_fields=tuple(RuntimeWork.__dataclass_fields__)
    fields=object_fields(data['runtime_work'],work_fields)
    work=RuntimeWork(**fields);work.validate(inputs.limits)
    if work.upstream_entries<1 or work.physical_completed_calls>work.physical_reserved_calls:
        raise ValueError('reset/invalid cumulative runtime work')
    # Existing strict checkpoint decoder/manifest checks remain in force.
    saved=CheckpointState.from_dict(data['context']);admit_operational_regime(saved.restore(inputs.simulation_inputs))
    return data,inputs,work


def restore_continuation(path,*,expected_packet_sha256,expected_input_digest):
    """One original-anchor B38 entry, then finite private history validation."""
    data,inputs,work=_admit(path,expected_packet_sha256,expected_input_digest)
    before=asdict(work)
    state=start_environment_mission(inputs,runtime_work=work)
    while state.cursor<data['cursor']:state=advance_environment_mission(state)
    if _scientific(scientific_projection(state))!=data['scientific']:
        raise ValueError('replayed scientific state/history mismatch')
    if CheckpointState.from_context(state.context).to_dict()!=data['context']:
        raise ValueError('replayed context/checkpoint mismatch')
    # Minimum costs of the same prefix are the measured replay costs. Original
    # cumulative history cannot be smaller even with externally rebound packets.
    after=asdict(work)
    delta={n:after[n]-before[n] for n in before}
    if any(before[n]<delta[n] for n in before if n!='reconstruction_count'):
        raise ValueError('cumulative quota/history reset detected')
    work.reconstruction_count+=1;work.validate(inputs.limits)
    return state,dict(prior=before,reconstruction_delta={**delta,'reconstruction_count':1},
                      after=asdict(work),original_anchor_seconds=inputs.environment.start_seconds.numerator)


def continue_mission(state):
    while state.cursor<len(state.inputs.actions):state=advance_environment_mission(state)
    return state
