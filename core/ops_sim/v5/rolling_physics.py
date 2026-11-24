"""New typed adaptive/estimated physical owner over accepted B46 pure leaves.

The action transaction below retains B44 physical/custody semantics, but has its
own seed, model identity and explicit command lineage. It never mutates or
forges a fixed-program LongMissionState/LongMissionInputs.
"""
from dataclasses import dataclass, replace, asdict
from fractions import Fraction as Q
from hashlib import sha256
from . import long_mission as leaf
from .long_mission import (RuntimeWork, LongMissionAction, EnvironmentActionOutcome,
    _charge, _entry, _product, _observations, _physical_action, _capture_definition,
    _contact_action, _continuous_admission, _Refusal, admit_operational_regime,
    _validate_completed_context, _commit_action, canonical_copy,
    checked_checkpoint, OperationalMode, MSAcquisitionEvidence)
from .assembly_attitude_3d import BodyAttitude3D, compile_assembly_hardware_3d as compile_assembly_hardware
from .assembly_slew_3d import plan_target_slew_3d as plan_target_slew
from .harness_hardware import compile_effective_hardware
from .harness_mission import HarnessWork
from .construction_mission import ConstructionWork
from .construction_coupling import compile_construction
from .contact_execution import ConsumedContacts
from .long_mission_continuation import _scientific
from .long_mission_document import canonical_json
from .rolling_contract import PublicPhysicalModel, typed


def digest(value):
    return sha256(canonical_json(_scientific(value)).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PhysicalInputs:
    model: PublicPhysicalModel
    products: tuple
    limits: object
    api: str = 'B47_PRIVATE_PHYSICAL_SEED_V1'
    def __getattr__(self, name):
        if name in PublicPhysicalModel.__dataclass_fields__ or name == 'geometry_mode':
            return getattr(self.model, name)
        raise AttributeError(name)


@dataclass(frozen=True, slots=True)
class ConstructionAdapterInputs:
    limits: object
    configuration: object


@dataclass(frozen=True, slots=True)
class HarnessAdapterInputs:
    augmentation: object


@dataclass(frozen=True, slots=True)
class ConstructionAdapter:
    inputs: ConstructionAdapterInputs
    compilation: object
    work: ConstructionWork


@dataclass(frozen=True, slots=True)
class HarnessAdapter:
    inputs: HarnessAdapterInputs
    hardware: object
    work: HarnessWork


@dataclass(slots=True)
class AdaptivePhysicalState:
    inputs: PhysicalInputs
    context: object
    attitude: BodyAttitude3D
    runtime_work: RuntimeWork
    nominal_provider: object
    source_authority: object
    construction: ConstructionAdapter
    harness: HarnessAdapter
    seed_identity: str
    model_identity: str
    seed_seconds: int
    seed_steps: int
    cursor: int = 0
    commands: tuple = ()
    outcomes: tuple = ()
    acquisitions: tuple = ()
    consumed_contacts: ConsumedContacts = ConsumedContacts(())
    source_result: object = None


def start_physical(model, context, attitude, products, cache, seed_identity, *, consumed=ConsumedContacts(()), forecast=False):
    typed(model, PublicPhysicalModel); typed(attitude, BodyAttitude3D)
    if cache.model != model or cache.ownership not in ('ACTUAL_PUBLIC_MODEL', 'FORECAST_PUBLIC_MODEL'):
        raise ValueError('foreign public cache bank')
    if context.inputs != model.simulation_inputs or attitude.at_seconds != context.simulation_time_seconds:
        raise ValueError('private seed/world/pose mismatch')
    if type(products) is not tuple or len(products)>16:
        raise ValueError('bounded seed product list')
    for p in products: p.__post_init__()
    rt=RuntimeWork(); rt.charge('runtime_entries',1,model.limits)
    cw=ConstructionWork();cw.reserve_compile(model.construction_limits)
    compilation=compile_construction(model.assembly,model.configuration)
    hw=HarnessWork();hw.reserve_compile(model.augmentation.policy)
    hardware=compile_effective_hardware(model.assembly,model.capabilities,model.actuator,model.configuration,model.augmentation)
    provider,source=cache.bind(rt)
    limits=replace(model.limits,max_document_bytes=min(32*2**20,model.limits.max_document_bytes),max_action_cells=min(128,model.limits.max_action_cells),
                   max_retained_cuts=min(128,model.limits.max_retained_cuts)) if forecast else model.limits
    state=AdaptivePhysicalState(PhysicalInputs(model,products,limits),context,attitude,rt,provider,source,
        ConstructionAdapter(ConstructionAdapterInputs(model.construction_limits,model.configuration),compilation,cw),
        HarnessAdapter(HarnessAdapterInputs(model.augmentation),hardware,hw),seed_identity,digest((model,products,limits)),
        context.simulation_time_seconds,context.diagnostics.completed_steps,consumed_contacts=consumed)
    checked_checkpoint(context);admit_operational_regime(context)
    return state


def guard_physical(state):
    if type(state) is not AdaptivePhysicalState or type(state.inputs) is not PhysicalInputs:
        raise TypeError('B47 private typed owner required')
    if digest((state.inputs.model,state.inputs.products,state.inputs.limits)) != state.model_identity:
        raise ValueError('mutated adaptive model/seed products')
    if state.context.inputs != state.inputs.simulation_inputs:
        raise ValueError('mutated context input authority')
    if state.cursor != len(state.outcomes) or state.cursor != len(state.commands) or state.cursor>64:
        raise ValueError('adaptive command prefix bound')
    if tuple(o.action_id for o in state.outcomes) != tuple(a.action_id for a in state.commands):
        raise ValueError('foreign command/outcome lineage')
    t=state.seed_seconds if not state.outcomes else state.outcomes[-1].end_seconds
    steps=state.seed_steps+sum(o.status=='completed' for o in state.outcomes)
    if state.context.simulation_time_seconds!=t or state.attitude.at_seconds!=t or state.context.diagnostics.completed_steps!=steps:
        raise ValueError('stale adaptive seed/prefix/time')
    state.runtime_work.validate(state.inputs.limits)
    state.construction.work.reserve_compile(state.inputs.construction_limits)
    actual=compile_construction(state.inputs.assembly,state.inputs.configuration)
    if actual != state.construction.compilation:
        raise ValueError('foreign cached construction')
    state.harness.work.reserve_compile(state.inputs.augmentation.policy)
    actual_hardware=compile_effective_hardware(state.inputs.assembly,state.inputs.capabilities,state.inputs.actuator,state.inputs.configuration,state.inputs.augmentation)
    if actual_hardware!=state.harness.hardware:
        raise ValueError('foreign cached effective tensor/mass')
    admit_operational_regime(state.context)
    state.attitude.__post_init__()


def reserve_physical_output(state):
    leaf.reserve_output(state)


def publication_admission(state):
    tree=_scientific(dict(seed=state.seed_identity,model=state.model_identity,commands=state.commands,
        checkpoint=checked_checkpoint(state.context).to_dict(),attitude=state.attitude,outcomes=state.outcomes,
        acquisitions=state.acquisitions,consumed=state.consumed_contacts))
    if len(canonical_json(tree).encode())>state.inputs.limits.max_document_bytes:
        raise ValueError('B47_PRIVATE_CAUSAL_OUTPUT_LIMIT')


def advance_physical(state, action):
    typed(action,LongMissionAction)
    guard_physical(state)
    if any(a.action_id==action.action_id for a in state.commands):
        raise ValueError('duplicate adaptive command')
    if state.cursor>=state.inputs.limits.max_actions or state.cursor>=64:
        raise ValueError('adaptive action quota')
    # Prospective immutable committed command lineage. Refusals retain it once.
    state=replace(state,commands=(*state.commands,action))
    reserve_physical_output(state)
    state.source_authority.guard()
    candidate=checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    _charge(state,'spatial_reserved_units',65536)
    hardware=(state.harness.hardware if state.harness is not None and state.harness.hardware is not None else
        compile_assembly_hardware(state.inputs.assembly,state.inputs.capabilities,state.inputs.actuator))
    a=candidate.simulation_time_seconds;b=a;geometry=();cuts=();accounting=None;record=association=None;contacts=();contact_forcing=();consumed=state.consumed_contacts;slew=None;attitude=state.attitude;continuous=None
    try:
        if action.kind=='POINT':
            geometry=_observations(state,_entry(state,action.point_id),a,a)
            if not geometry[0].visible:raise _Refusal('TARGET_POINTING_GEOMETRY_REFUSED')
            _charge(state,'spatial_reserved_units',65536+2048)
            if state.harness is not None and state.harness.hardware is not None:
                from .harness_slew import plan_effective_slew
                slew=plan_effective_slew(hardware,state.attitude,geometry[0].direction.components,work=state.harness.work,policy=state.harness.inputs.augmentation.policy)
            else:slew=plan_target_slew(hardware,state.attitude,geometry[0].direction.components)
            b=a+slew.duration_seconds
            if b>state.inputs.environment.end_seconds:raise _Refusal('SLEW_EXCEEDS_ENVIRONMENT_DOMAIN')
            if b>a:
                cuts,accounting=_physical_action(state,candidate,hardware,a,b,slew=slew,required=state.inputs.protection.imaging_node_ids)
            attitude=BodyAttitude3D(state.attitude.body_frame_id,state.attitude.inertial_frame,Q(b),
                slew.quaternion_at(Q(slew.duration_seconds)),Q(a+slew.rest_start_offset_seconds))
        elif action.kind=='HOLD_UNTIL':
            b=action.until_seconds
            if b<a:raise _Refusal('HOLD_END_ALREADY_PASSED')
            if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
            if b>a:cuts,accounting=_physical_action(state,candidate,hardware,a,b)
            attitude=replace(attitude,at_seconds=Q(b))
        elif action.kind=='CAPTURE':
            b=a+action.duration_seconds
            if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
            if not _product(state,action.product_id).acquisition_start_seconds<=a<b<=_product(state,action.product_id).acquisition_end_seconds:
                raise _Refusal('ACQUISITION_WINDOW_MISSED')
            continuous=_continuous_admission(state,_entry(state,action.point_id),a,b,hardware,capture=True)
            if continuous is not None and continuous.status!='VISIBLE':raise _Refusal('CONTINUOUS_CAPTURE_'+continuous.status)
            geometry=_observations(state,_entry(state,action.point_id),a,b)
            record,association,payload=_capture_definition(state,candidate,action,hardware,geometry)
            cuts,accounting=_physical_action(state,candidate,hardware,a,b,payload_w=payload,
                                             required=state.inputs.protection.imaging_node_ids)
            candidate.spacecraft_state.data_storage.stored_records+=(record,)
            attitude=replace(attitude,at_seconds=Q(b))
        else:
            b=a+action.duration_seconds
            if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
            continuous=_continuous_admission(state,_entry(state,action.point_id,station=True),a,b,hardware)
            if continuous is not None and continuous.status!='VISIBLE':raise _Refusal('CONTINUOUS_CONTACT_'+continuous.status)
            geometry=_observations(state,_entry(state,action.point_id,station=True),a,b)
            contacts,consumed,contact_forcing=_contact_action(state,candidate,action,hardware,geometry)
            attitude=replace(attitude,at_seconds=Q(b))
        if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
        candidate.simulation_time_seconds=b
        candidate.diagnostics.completed_steps=state.context.diagnostics.completed_steps+1
        if action.kind!='CONTACT':
            # The private reduced physical action neither owns nor performs recovery.
            admit_operational_regime(candidate)
            candidate.spacecraft_state.onboard.operational_mode={'POINT':OperationalMode.MANEUVER,'CAPTURE':OperationalMode.IMAGING,'HOLD_UNTIL':OperationalMode.STANDBY}[action.kind]
        admit_operational_regime(candidate)
        _validate_completed_context(candidate);checked_checkpoint(candidate)
    except _Refusal as refusal:
        outcome=EnvironmentActionOutcome(action.action_id,action.kind,'refused',str(refusal),a,a,geometry,(),(),None,None,state.attitude,None,slew,continuous_geometry=continuous,failure_diagnostic=refusal.diagnostic)
        result=replace(state,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome))
        publication_admission(result)
        return result
    # All late primitive errors propagate with original context/cursor intact.
    outcome=EnvironmentActionOutcome(action.action_id,action.kind,'completed',None,a,b,geometry,cuts,contacts,record,association,attitude,accounting,slew,contact_forcing,continuous)
    acquisitions=state.acquisitions if record is None else (*state.acquisitions,MSAcquisitionEvidence(record,association))
    state.source_authority.guard()
    projected=replace(state,context=candidate,attitude=attitude,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome),acquisitions=acquisitions,consumed_contacts=consumed)
    publication_admission(projected)
    _commit_action(state.context,candidate)
    return replace(state,attitude=attitude,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome),
                   acquisitions=acquisitions,consumed_contacts=consumed)
