"""Task 05B version-7 campaign inputs and bounded, typed boundary evidence.

No schema-5 field is repurposed. Forecasts never receive a live context or an
origin checkpoint; the continuation adapter owns that separation.
"""

from dataclasses import dataclass

from .checkpoint import CheckpointState, ThermalNodeStateSnapshot
from .communications import ServiceableGroundContact
from .contact_execution import ContactOutcome, RecordService
from .continuation import _exact, _label
from .coupled_downlink import DownlinkTransmitterConfig
from .data_delivery import DownlinkTransferProgress
from .imaging_feasibility import ObservationAcquisitionCandidate
from .integration_time import IntegrationPolicy
from .ms_acquisition import InitialAttitudeEvidence
from .ms_product import MSProductSpec, MSAcquisitionPlan, MSAcquisitionEvidence, _time, _version
from .onboard_data import OnboardAcquisitionDataRecord
from .operational_protection import ProtectionPolicy, StandbyInputs
from .state import OperationalMode, FDIRState
from .substepped_execution import SubsteppedOutcome, _nonnegative


def typed(value, owner):
    _exact(value, owner, owner.__name__)
    value.__post_init__()


def sequence(values, owner, limit):
    _exact(values, tuple, "bounded tuple")
    if len(values) > limit:
        raise ValueError("campaign sequence exceeds bounded work")
    for value in values:
        typed(value, owner)


@dataclass(frozen=True, slots=True)
class ReleasedMSRequest:
    product: MSProductSpec
    release_seconds: int

    def __post_init__(self):
        typed(self.product, MSProductSpec)
        _time(self.release_seconds)
        if self.release_seconds >= self.product.acquisition_end_seconds:
            raise ValueError("request release must precede acquisition window end")


@dataclass(frozen=True, slots=True)
class MSOpportunity:
    candidate: ObservationAcquisitionCandidate
    acquisition: MSAcquisitionPlan

    def __post_init__(self):
        typed(self.candidate, ObservationAcquisitionCandidate)
        typed(self.acquisition, MSAcquisitionPlan)
        if self.opportunity.request_id != self.acquisition.request.request_id:
            raise ValueError("opportunity/request association mismatch")

    @property
    def opportunity(self):
        return self.candidate.maneuver_candidate.opportunity


@dataclass(frozen=True, slots=True)
class CampaignForcing:
    start_seconds: int
    end_seconds: int
    standby: StandbyInputs
    transmitter: DownlinkTransmitterConfig

    def __post_init__(self):
        _time(self.start_seconds)
        _time(self.end_seconds)
        if self.end_seconds <= self.start_seconds:
            raise ValueError("forcing requires positive interval")
        typed(self.standby, StandbyInputs)
        typed(self.transmitter, DownlinkTransmitterConfig)


@dataclass(frozen=True, slots=True)
class BoundaryKnowledgeMode:
    mode: str
    observed_temperature_node_ids: tuple
    estimated_temperatures: tuple[ThermalNodeStateSnapshot, ...]
    rationale: str

    def __post_init__(self):
        from .ids import ThermalNodeId
        if type(self.mode) is not str or self.mode != "idealized-boundary-telemetry-v1":
            raise ValueError("unsupported knowledge mode")
        sequence(self.observed_temperature_node_ids, ThermalNodeId, 32)
        sequence(self.estimated_temperatures, ThermalNodeStateSnapshot, 32)
        ids = (*self.observed_temperature_node_ids, *(n.node_id for n in self.estimated_temperatures))
        if len(ids) != len(set(ids)):
            raise ValueError("observed and estimated temperatures must partition nodes")
        _label(self.rationale, "knowledge/estimate rationale")


@dataclass(frozen=True, slots=True)
class RollingPolicy:
    version: int = 1
    lookahead_seconds: int = 300
    standby_poll_seconds: int = 30
    plan_actions: int = 3
    max_decisions: int = 32
    max_candidate_evaluations: int = 64
    max_forecast_eps: int = 4096

    def __post_init__(self):
        _version(self.version)
        for name, maximum in (("lookahead_seconds", 2**40), ("standby_poll_seconds", 2**40),
                ("plan_actions", 8), ("max_decisions", 128), ("max_candidate_evaluations", 128),
                ("max_forecast_eps", 16384)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("rolling policy bound exceeded: " + name)
        if self.plan_actions < 2 or self.standby_poll_seconds > self.lookahead_seconds:
            raise ValueError("rolling policy requires multi-action planning and bounded standby")
        if self.max_decisions * self.max_forecast_eps > 131072:
            raise ValueError("campaign replay forecast-work bound exceeded")


@dataclass(frozen=True, slots=True)
class MSCampaignProgram:
    version: int
    initial_checkpoint: CheckpointState
    initial_attitude: InitialAttitudeEvidence
    requests: tuple[ReleasedMSRequest, ...]
    opportunities: tuple[MSOpportunity, ...]
    contacts: tuple[ServiceableGroundContact, ...]
    forcing: tuple[CampaignForcing, ...]
    protection: ProtectionPolicy
    integration: IntegrationPolicy
    policy: RollingPolicy
    knowledge: BoundaryKnowledgeMode
    assumptions: tuple[str, ...]

    def __post_init__(self):
        _version(self.version, 7)
        _exact(self.initial_checkpoint, CheckpointState, "origin checkpoint")
        for value, owner in ((self.initial_attitude, InitialAttitudeEvidence),
                (self.protection, ProtectionPolicy), (self.integration, IntegrationPolicy),
                (self.policy, RollingPolicy), (self.knowledge, BoundaryKnowledgeMode)):
            typed(value, owner)
        sequence(self.requests, ReleasedMSRequest, 16)
        sequence(self.opportunities, MSOpportunity, 64)
        sequence(self.contacts, ServiceableGroundContact, 64)
        sequence(self.forcing, CampaignForcing, 64)
        if not self.requests or not self.forcing:
            raise ValueError("campaign requires requests and complete forcing")
        for identities in ([r.product.request.request_id for r in self.requests],
                [o.opportunity.opportunity_id for o in self.opportunities],
                [c.contact_id for c in self.contacts]):
            if len(set(identities)) != len(identities):
                raise ValueError("duplicate campaign identity")
        if any(a.end_time_seconds > b.start_time_seconds for a, b in zip(self.contacts, self.contacts[1:])):
            raise ValueError("contacts must be ordered and nonoverlapping")
        if any(a.end_seconds != b.start_seconds for a, b in zip(self.forcing, self.forcing[1:])):
            raise ValueError("forcing intervals must be consecutive")
        if (len(self.requests)+1)*self.integration.substeps > 4096:
            raise ValueError("campaign contact physical-work bound exceeded")
        if self.policy.max_decisions*(2*len(self.requests)+1)*self.integration.substeps > 16384:
            raise ValueError("campaign execution-work bound exceeded")
        _exact(self.assumptions, tuple, "assumptions")
        if not 1 <= len(self.assumptions) <= 32:
            raise ValueError("explicit bounded campaign assumptions required")
        for value in self.assumptions:
            _label(value, "assumption")


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    battery_energy_wh: float
    battery_retention: float
    solar_retention: float
    throughput_wh: float
    observed_temperatures: tuple[ThermalNodeStateSnapshot, ...]
    operational_mode: OperationalMode
    fdir_state: FDIRState
    critical_energy_since_seconds: int | None

    def __post_init__(self):
        for name in ("battery_energy_wh", "battery_retention", "solar_retention", "throughput_wh"):
            _nonnegative(getattr(self, name), name)
        if not 0 < self.battery_retention <= 1 or not 0 < self.solar_retention <= 1:
            raise ValueError("invalid observed retention")
        sequence(self.observed_temperatures, ThermalNodeStateSnapshot, 32)
        _exact(self.operational_mode, OperationalMode, "observed activity")
        _exact(self.fdir_state, FDIRState, "observed protection")
        if self.critical_energy_since_seconds is not None:
            _time(self.critical_energy_since_seconds)


@dataclass(frozen=True, slots=True)
class BoundaryFeedback:
    sampled_at_seconds: int
    received_at_seconds: int
    resources: ResourceObservation
    onboard_records: tuple[OnboardAcquisitionDataRecord, ...]
    partial_transfers: tuple[DownlinkTransferProgress, ...]
    actual_kind: str
    reasons: tuple[str, ...]
    acquisition: MSAcquisitionEvidence | None
    contact: ServiceableGroundContact | None
    services: tuple[RecordService, ...]

    def __post_init__(self):
        _time(self.sampled_at_seconds)
        if type(self.received_at_seconds) is not int or self.received_at_seconds != self.sampled_at_seconds:
            raise ValueError("idealized feedback requires zero receipt latency")
        typed(self.resources, ResourceObservation)
        sequence(self.onboard_records, OnboardAcquisitionDataRecord, 16)
        sequence(self.partial_transfers, DownlinkTransferProgress, 16)
        sequence(self.services, RecordService, 16)
        if type(self.actual_kind) is not str or self.actual_kind not in ("initial", "imaging", "standby", "contact"):
            raise ValueError("unknown acknowledged action")
        _exact(self.reasons, tuple, "acknowledged reasons")
        for value in self.reasons:
            _label(value, "acknowledged reason")
        if self.acquisition is not None:
            typed(self.acquisition, MSAcquisitionEvidence)
        if self.contact is not None:
            typed(self.contact, ServiceableGroundContact)
            if self.contact.end_time_seconds != self.sampled_at_seconds:
                raise ValueError("contact acknowledgement must be at completion")
        elif self.services:
            raise ValueError("services require contact acknowledgement")


@dataclass(frozen=True, slots=True)
class PlannedAction:
    kind: str
    identity: str
    start_seconds: int
    end_seconds: int
    record_ids: tuple
    reason: str

    def __post_init__(self):
        from .ids import AcquisitionDataRecordId
        if type(self.kind) is not str or self.kind not in ("imaging", "contact", "standby"):
            raise ValueError("unknown planned action")
        _label(self.identity, "action identity")
        _time(self.start_seconds)
        _time(self.end_seconds)
        if self.end_seconds <= self.start_seconds:
            raise ValueError("planned action must advance time")
        sequence(self.record_ids, AcquisitionDataRecordId, 16)
        _label(self.reason, "selection reason")


@dataclass(frozen=True, slots=True)
class RollingPlan:
    sampled_at_seconds: int
    received_at_seconds: int
    forecast_until_seconds: int
    actions: tuple[PlannedAction, ...]
    rejected: tuple[tuple[str, str], ...]
    candidate_evaluations: int
    forecast_eps_bound: int

    def __post_init__(self):
        for value in (self.sampled_at_seconds, self.received_at_seconds, self.forecast_until_seconds):
            _time(value)
        sequence(self.actions, PlannedAction, 8)
        if not self.actions or self.sampled_at_seconds != self.received_at_seconds:
            raise ValueError("plan needs current boundary observation and action")
        if self.actions[0].start_seconds != self.received_at_seconds:
            raise ValueError("plan must start at received boundary")
        if any(a.end_seconds != b.start_seconds for a, b in zip(self.actions, self.actions[1:])):
            raise ValueError("plan has physical gaps")
        if self.actions[-1].end_seconds > self.forecast_until_seconds:
            raise ValueError("plan exceeds forecast visibility")
        _exact(self.rejected, tuple, "rejection evidence")
        if len(self.rejected) > 512:
            raise ValueError("rejection evidence exceeds bound")
        for pair in self.rejected:
            _exact(pair, tuple, "rejection pair")
            if len(pair) != 2:
                raise ValueError("rejection requires identity and reason")
            for value in pair:
                _label(value, "rejection evidence")
        for value in (self.candidate_evaluations, self.forecast_eps_bound):
            if type(value) is not int or value < 0:
                raise ValueError("invalid forecast work evidence")


@dataclass(frozen=True, slots=True)
class CampaignDecision:
    plan: RollingPlan
    outcome: SubsteppedOutcome | ContactOutcome
    feedback: BoundaryFeedback

    def __post_init__(self):
        typed(self.plan, RollingPlan)
        if type(self.outcome) not in (SubsteppedOutcome, ContactOutcome):
            raise TypeError("unsupported actual outcome")
        self.outcome.__post_init__()
        typed(self.feedback, BoundaryFeedback)
        if self.feedback.received_at_seconds != self.plan.actions[0].end_seconds:
            raise ValueError("feedback does not acknowledge the executed interval")


@dataclass(frozen=True, slots=True)
class MSCampaignMemory:
    initial_feedback: BoundaryFeedback
    decisions: tuple[CampaignDecision, ...]

    def __post_init__(self):
        typed(self.initial_feedback, BoundaryFeedback)
        if self.initial_feedback.actual_kind != "initial":
            raise ValueError("initial telemetry boundary required")
        sequence(self.decisions, CampaignDecision, 128)

    @property
    def feedback(self):
        return self.decisions[-1].feedback if self.decisions else self.initial_feedback
