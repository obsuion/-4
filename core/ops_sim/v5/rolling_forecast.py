"""Paid isolated estimated-state forecasts; no private root checkpoint input."""
from dataclasses import dataclass, asdict
from fractions import Fraction as Q
from .rolling_contract import typed, integer, PublicPhysicalModel, RollingPolicy
from .rolling_knowledge import ReceivedKnowledge, KnowledgeMode
from .rolling_physics import start_physical, advance_physical, digest
from .contact_execution import ConsumedContacts
from .long_mission import LongMissionAction


@dataclass(frozen=True, slots=True)
class PlanningView:
    model: PublicPhysicalModel
    now_seconds: int
    requests: tuple
    contacts: tuple
    knowledge: ReceivedKnowledge
    knowledge_mode: KnowledgeMode
    policy: RollingPolicy

    def __post_init__(self):
        typed(self.model, PublicPhysicalModel); integer(self.now_seconds, 'planning time')
        typed(self.knowledge, ReceivedKnowledge); typed(self.knowledge_mode, KnowledgeMode); typed(self.policy, RollingPolicy)
        if not self.model.environment.start_seconds <= self.now_seconds <= self.model.environment.end_seconds:
            raise ValueError('planning boundary outside original domain')
        if type(self.requests) is not tuple or len(self.requests)>16 or type(self.contacts) is not tuple or len(self.contacts)>64:
            raise ValueError('bounded planning opportunities')
        from .rolling_contract import ReleasedRequest, DeclaredContact
        for r in self.requests:
            typed(r, ReleasedRequest)
            if r.release_seconds>self.now_seconds:
                raise ValueError('unreleased request in public view')
        for c in self.contacts: typed(c, DeclaredContact)
        observations=(self.knowledge.observation,*self.knowledge.received)
        if any(p.received_at_seconds>self.now_seconds for p in observations):
            raise ValueError('future receipt in public knowledge')
        age=self.now_seconds-self.knowledge.observation.observed_at_seconds
        if not 0<=age<=self.policy.maximum_observation_age_seconds:
            raise ValueError('unsupported/missing/stale resource knowledge')
        ids={n.node_id for n in self.model.simulation_inputs.spacecraft_configuration.thermal.network.nodes}
        if {n.node_id for n in self.knowledge.observation.resources.observed_temperatures} != ids:
            raise ValueError('every planning temperature needs explicit observation/estimate')
        pose=self.knowledge.observation.attitude
        if pose.body_frame_id!=self.model.assembly.body_frame_id or pose.inertial_frame!=self.model.environment.trajectory.initial_state.position.frame:
            raise ValueError('foreign estimated/observed pose frame')

    @property
    def identity(self):
        # No hidden full root/release schedule/queued future packet digest.
        return digest(self)


@dataclass(frozen=True, slots=True)
class ForecastResult:
    view_identity: str
    suffix: tuple[LongMissionAction, ...]
    status: str
    reason: str | None
    predicted_end_seconds: int
    predicted_energy_wh: float
    predicted_temperatures: tuple
    predicted_records: tuple
    predicted_partial_bits: tuple
    predicted_delivery_acks: tuple
    predicted_outcomes: tuple
    runtime_work: object
    construction_work: object
    harness_work: object
    catchup_outcome: object = None


def estimated_context(view):
    """Only received fields; unused propulsion/authority/diagnostics are declared zero.

    Ground receipt history is allowed solely through explicit received ack fields.
    The pose belongs to the observation time, not an unobserved future command.
    """
    from .context import SimulationContext
    from .state import (SpacecraftState, BatteryState, PropulsionState, ThermalState, DegradationState,
                        BatteryDegradationState, SolarDegradationState, OnboardOperationsState, DataStorageState)
    from .knowledge import GroundKnowledgeState
    from .data_delivery import GroundDataDeliveryState
    from .mission import MissionState
    from .controller_state import ControllerState
    from .diagnostics import Diagnostics
    from .experiment_codec import canonical_copy
    p=view.knowledge.observation; r=p.resources
    inputs=canonical_copy(view.model.simulation_inputs)
    context=SimulationContext(p.observed_at_seconds,inputs,
        SpacecraftState(BatteryState(r.battery_energy_wh),PropulsionState(0.),
            ThermalState(tuple(n.restore() for n in r.observed_temperatures)),
            DegradationState(BatteryDegradationState(r.battery_retention,r.throughput_wh),SolarDegradationState(r.solar_retention)),
            OnboardOperationsState(r.operational_mode,r.fdir_state,None,None,None,r.critical_energy_since_seconds),
            DataStorageState(canonical_copy(p.onboard_records))),
        GroundKnowledgeState(None,()),GroundDataDeliveryState(canonical_copy(p.partial_transfers),canonical_copy(p.delivery_acks)),
        MissionState((),(),(),None,(),()),ControllerState(inputs.model_manifest.controller_id,None,0),Diagnostics(0))
    return context


def forecast_suffix(view, suffix, cache, work, quotas):
    if type(view) is not PlanningView or type(suffix) is not tuple or not 2<=len(suffix)<=view.policy.suffix_actions:
        raise TypeError('received-only view and bounded linked suffix required')
    view.__post_init__()
    if cache.ownership!='FORECAST_PUBLIC_MODEL' or cache.model!=view.model:
        raise ValueError('forecasts require independent public-model cache')
    if work.forecast_invocations>=min(quotas.max_forecast_invocations,view.policy.max_forecasts):
        raise ValueError('B47_FORECAST_COUNT_EXHAUSTED')
    work.reserve_forecast(view.model,quotas)
    context=estimated_context(view)
    state=start_physical(view.model,context,view.knowledge.observation.attitude,
        tuple(r.product for r in view.requests),cache,'ESTIMATED_FROM_RECEIVED:'+view.identity,
        consumed=ConsumedContacts(view.knowledge.observation.consumed_contacts),forecast=True)
    catchup=None;reason=None
    try:
        if context.simulation_time_seconds<view.now_seconds:
            state=advance_physical(state,LongMissionAction('estimate-age-'+view.identity[:20],'HOLD_UNTIL',until_seconds=view.now_seconds))
            catchup=state.outcomes[-1]
            if catchup.status!='completed':
                reason='ESTIMATE_CATCHUP:'+catchup.reason
        if reason is None:
            for a in suffix:
                if (a.kind=='HOLD_UNTIL' and a.until_seconds>min(view.now_seconds+view.policy.lookahead_seconds,view.model.environment.end_seconds)):
                    raise ValueError('suffix exceeds admitted lookahead')
                state=advance_physical(state,a)
                if state.outcomes[-1].status!='completed':
                    reason=state.outcomes[-1].reason;break
                if state.context.simulation_time_seconds>min(view.now_seconds+view.policy.lookahead_seconds,view.model.environment.end_seconds):
                    reason='FORECAST_LOOKAHEAD_EXCEEDED';break
        result=ForecastResult(view.identity,suffix,'admissible' if reason is None else 'refused',reason,
            state.context.simulation_time_seconds,state.context.spacecraft_state.battery.energy_wh,
            tuple((n.node_id.value,n.temperature_k) for n in state.context.spacecraft_state.thermal.node_states),
            state.context.spacecraft_state.data_storage.stored_records,
            tuple((p.record_id.value,p.transmitted_equivalent_bits) for p in state.context.ground_data_delivery_state.partial_transfers),
            state.context.ground_data_delivery_state.completed_deliveries,state.outcomes,
            asdict(state.runtime_work),asdict(state.construction.work),asdict(state.harness.work),catchup)
        from .rolling_cache import paid_publication
        paid_publication(result,work,quotas,32*2**20)
        return result
    finally:
        # Returned/refused/unknown work is retained even if a branch raises.
        work.record('FORECAST_FROM_RECEIVED',state)
