"""Received-only B47 observations, deterministic latency and issued memory."""
from dataclasses import dataclass, replace
from .rolling_contract import integer, typed
from .campaign_contract import ResourceObservation
from .checkpoint import ThermalNodeStateSnapshot
from .assembly_attitude_3d import BodyAttitude3D
from .data_delivery import CompletedAcquisitionDelivery, DownlinkTransferProgress
from .storage import OnboardAcquisitionDataRecord
from .communications import ServiceableGroundContact

OBSERVED_FIELDS = ('battery_energy_wh', 'battery_retention', 'solar_retention', 'throughput_wh',
                   'all_declared_node_temperatures_k', 'operational_mode', 'fdir_state',
                   'critical_energy_since_seconds', 'body_to_model_inertial_quaternion',
                   'rest_since_seconds', 'onboard_records', 'partial_bits', 'delivery_ack',
                   'consumed_contacts', 'command_status_and_reason')


@dataclass(frozen=True, slots=True)
class KnowledgeMode:
    mode: str = 'IDEAL_BOUNDARY_OBSERVATION'
    latency_seconds: int = 0
    max_queue: int = 128
    fields: tuple[str, ...] = OBSERVED_FIELDS
    method: str = 'B47_ORDERED_BOUNDARY_PACKETS_V1'

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in ('IDEAL_BOUNDARY_OBSERVATION', 'DELAYED_BOUNDARY_OBSERVATION'):
            raise ValueError('explicit observation mode required')
        integer(self.latency_seconds, 'latency', 0, 120); integer(self.max_queue, 'queue', 1, 128)
        if (self.mode == 'IDEAL_BOUNDARY_OBSERVATION') != (self.latency_seconds == 0):
            raise ValueError('ideal mode zero delay; delayed mode positive finite delay')
        if type(self.fields) is not tuple or self.fields != OBSERVED_FIELDS or self.method != 'B47_ORDERED_BOUNDARY_PACKETS_V1':
            raise ValueError('exact explicit observation field contract required')


@dataclass(frozen=True, slots=True)
class ReceivedObservation:
    packet_id: str
    observed_at_seconds: int
    received_at_seconds: int
    resources: ResourceObservation
    attitude: BodyAttitude3D
    onboard_records: tuple[OnboardAcquisitionDataRecord, ...] = ()
    partial_transfers: tuple[DownlinkTransferProgress, ...] = ()
    delivery_acks: tuple[CompletedAcquisitionDelivery, ...] = ()
    consumed_contacts: tuple[ServiceableGroundContact, ...] = ()
    command_id: str = ''
    command_status: str = 'initial'
    command_reason: str | None = None
    origin: str = 'OBSERVED_BOUNDARY'

    def __post_init__(self):
        from .assembly import _identity
        _identity(self.packet_id, 'packet')
        integer(self.observed_at_seconds, 'sample time'); integer(self.received_at_seconds, 'receipt time')
        if not self.observed_at_seconds <= self.received_at_seconds <= self.observed_at_seconds+120:
            raise ValueError('bounded causal receipt')
        typed(self.resources, ResourceObservation); typed(self.attitude, BodyAttitude3D)
        if self.attitude.at_seconds != self.observed_at_seconds:
            raise ValueError('pose/observation time mismatch')
        for values, cls in ((self.onboard_records, OnboardAcquisitionDataRecord),
                            (self.partial_transfers, DownlinkTransferProgress),
                            (self.delivery_acks, CompletedAcquisitionDelivery),
                            (self.consumed_contacts, ServiceableGroundContact)):
            if type(values) is not tuple or len(values) > 128:
                raise ValueError('bounded immutable observed custody')
            for v in values:
                typed(v, cls)
        if self.origin not in ('DECLARED_ESTIMATE', 'OBSERVED_BOUNDARY') or self.command_status not in ('initial', 'completed', 'refused'):
            raise ValueError('explicit observation provenance/status required')
        if type(self.command_id) is not str or type(self.command_reason) not in (str, type(None)):
            raise ValueError('strict command feedback')


@dataclass(frozen=True, slots=True)
class IssuedCommand:
    command_id: str
    kind: str
    point_id: str
    product_id: str
    issued_at_seconds: int
    feedback_due_seconds: int

    def __post_init__(self):
        integer(self.issued_at_seconds, 'issued'); integer(self.feedback_due_seconds, 'known feedback bound')
        if self.kind not in ('POINT', 'CAPTURE', 'CONTACT', 'HOLD_UNTIL') or self.feedback_due_seconds < self.issued_at_seconds:
            raise ValueError('issued command memory')


@dataclass(frozen=True, slots=True)
class ReceivedKnowledge:
    observation: ReceivedObservation
    received: tuple[ReceivedObservation, ...] = ()
    issued: tuple[IssuedCommand, ...] = ()

    def __post_init__(self):
        typed(self.observation, ReceivedObservation)
        if type(self.received) is not tuple or len(self.received) > 128 or type(self.issued) is not tuple or len(self.issued) > 64:
            raise ValueError('bounded received history/memory')
        for p in self.received:
            typed(p, ReceivedObservation)
        for c in self.issued:
            typed(c, IssuedCommand)
        if tuple(sorted(self.received, key=lambda p: (p.received_at_seconds, p.observed_at_seconds, p.packet_id))) != self.received or len({p.packet_id for p in self.received}) != len(self.received):
            raise ValueError('strict received ordering/identities')

    def acknowledged_ids(self):
        return frozenset(p.command_id for p in self.received if p.command_id)

    def pending(self):
        ack = self.acknowledged_ids()
        return tuple(c for c in self.issued if c.command_id not in ack and c.kind != 'HOLD_UNTIL')

    def acquired_ids(self):
        return frozenset(r.imaging_request_id.value for p in (self.observation, *self.received)
                         for r in (*p.onboard_records, *(d.record for d in p.delivery_acks)))


def observe_boundary(physical, mode, ordinal, command=None):
    """Trusted adapter alone reads truth. The resulting finite packet is data.

    Ideal mode is an explicit engineering information assumption; delayed mode
    is deterministic boundary latency, not sensor or communication calibration.
    """
    typed(mode, KnowledgeMode)
    s = physical.context.spacecraft_state
    resources = ResourceObservation(s.battery.energy_wh, s.degradation.battery.usable_capacity_retention,
        s.degradation.solar.generation_retention, s.degradation.battery.cumulative_energy_throughput_wh,
        tuple(ThermalNodeStateSnapshot.from_state(n) for n in s.thermal.node_states),
        s.onboard.operational_mode, s.onboard.fdir_state, s.onboard.critical_energy_since_seconds)
    t = physical.context.simulation_time_seconds
    outcome = None if command is None else physical.outcomes[-1]
    return ReceivedObservation('b47-packet-'+str(ordinal), t, t+mode.latency_seconds,
        resources, physical.attitude, s.data_storage.stored_records,
        physical.context.ground_data_delivery_state.partial_transfers,
        physical.context.ground_data_delivery_state.completed_deliveries,
        physical.consumed_contacts.contacts, '' if command is None else command.action_id,
        'initial' if outcome is None else outcome.status, None if outcome is None else outcome.reason)


def receive_boundary(knowledge, queue, now):
    typed(knowledge, ReceivedKnowledge); integer(now, 'boundary')
    if type(queue) is not tuple or len(queue) > 128:
        raise ValueError('bounded private queue')
    ordered = tuple(sorted(queue, key=lambda p: (p.received_at_seconds, p.observed_at_seconds, p.packet_id)))
    for p in ordered:
        typed(p, ReceivedObservation)
    ready = tuple(p for p in ordered if p.received_at_seconds <= now)
    remaining = tuple(p for p in ordered if p.received_at_seconds > now)
    received = tuple(sorted((*knowledge.received, *ready), key=lambda p: (p.received_at_seconds, p.observed_at_seconds, p.packet_id)))
    latest = max((knowledge.observation, *ready), key=lambda p: (p.observed_at_seconds, p.received_at_seconds, p.packet_id))
    return ReceivedKnowledge(latest, received, knowledge.issued), remaining
