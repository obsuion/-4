"""B47 immutable public model and finite adaptive ownership contracts.

No context, checkpoint, release schedule or evaluation ledger is a planner model.
Existing B44/B45/B46 input families and their fixed-program guards are unchanged.
"""
from dataclasses import dataclass, fields
from fractions import Fraction as Q
from math import isfinite
from .long_mission import LongMissionInputs, LongMissionLimits, LongSamplingPolicy
from .long_environment import NOMINAL, LongEnvironment
from .long_nominal_provider import LongNominalPolicy
from .long_general_geometry import LongGeometryPolicy, admit_long_geometry_domain
from .context import SimulationInputs
from .assembly_choices import AssemblyDesign
from .assembly_attitude import ComponentAxisBinding
from .assembly_attitude_3d import NetTorqueActuatorPolicy, canonical_quaternion
from .mission_environment import CatalogPoint
from .operational_protection import ProtectionPolicy
from .thermal_routing import ComponentHeatRoutingConfig
from .coupled_downlink import DownlinkTransmitterConfig
from .construction_coupling import ConstructionConfiguration, compile_construction
from .construction_mission import ConstructionLimits
from .harness_mass import HarnessAugmentationInputs
from .ms_product import MSProductSpec
from .checkpoint import CheckpointState

API = 'M5_ROLLING_MASS_CONSTRUCTION_V1'


def integer(v, name, lo=0, hi=2**40):
    if type(v) is not int or not lo <= v <= hi:
        raise ValueError('strict bounded integer: '+name)


def finite(v, name, lo=0., hi=1e12):
    if type(v) not in (int, float) or not isfinite(v) or not lo <= v <= hi:
        raise ValueError('strict finite value: '+name)


def typed(v, cls):
    if type(v) is not cls:
        raise TypeError('exact '+cls.__name__+' required')
    v.__post_init__()


@dataclass(frozen=True, slots=True)
class PublicPhysicalModel:
    simulation_inputs: SimulationInputs
    environment: LongEnvironment
    assembly: AssemblyDesign
    capabilities: tuple[ComponentAxisBinding, ...]
    actuator: NetTorqueActuatorPolicy
    catalog: tuple[CatalogPoint, ...]
    sampling: LongSamplingPolicy
    protection: ProtectionPolicy
    routing: ComponentHeatRoutingConfig
    transmitter: DownlinkTransmitterConfig
    camera_half_fov_rad: float
    solar_retention_loss_per_second: float
    nominal_policy: LongNominalPolicy
    limits: LongMissionLimits
    geometry_policy: LongGeometryPolicy
    configuration: ConstructionConfiguration
    construction_limits: ConstructionLimits
    augmentation: HarnessAugmentationInputs
    api: str = API

    def __post_init__(self):
        pairs = ((self.simulation_inputs, SimulationInputs), (self.environment, LongEnvironment),
                 (self.assembly, AssemblyDesign), (self.actuator, NetTorqueActuatorPolicy),
                 (self.sampling, LongSamplingPolicy), (self.protection, ProtectionPolicy),
                 (self.routing, ComponentHeatRoutingConfig), (self.transmitter, DownlinkTransmitterConfig),
                 (self.nominal_policy, LongNominalPolicy), (self.limits, LongMissionLimits),
                 (self.geometry_policy, LongGeometryPolicy), (self.configuration, ConstructionConfiguration),
                 (self.construction_limits, ConstructionLimits), (self.augmentation, HarnessAugmentationInputs))
        for v, cls in pairs:
            typed(v, cls)
        if self.api != API or type(self.api) is not str or self.environment.mode != NOMINAL:
            raise ValueError('B47 v1 explicitly supports NOMINAL_LONG only')
        if type(self.catalog) is not tuple or not 1 <= len(self.catalog) <= 16:
            raise ValueError('bounded public catalog')
        for entry in self.catalog:
            typed(entry, CatalogPoint)
            admit_long_geometry_domain(self.environment, entry, self.geometry_policy)
        if len({e.point.point_id.value for e in self.catalog}) != len(self.catalog):
            raise ValueError('duplicate public point')
        if type(self.capabilities) is not tuple or not self.capabilities:
            raise ValueError('exact component axes required')
        for axis in self.capabilities:
            typed(axis, ComponentAxisBinding)
        finite(self.camera_half_fov_rad, 'FOV', 1e-12, 1.5707963267948965)
        finite(self.solar_retention_loss_per_second, 'solar loss', 0, .008)
        if self.simulation_inputs.coast_orbit is not None or self.simulation_inputs.common_world.event_ids:
            raise ValueError('public original long orbit alone owns event-free world')
        if self.configuration.thermal_network != self.simulation_inputs.spacecraft_configuration.thermal.network:
            raise ValueError('configuration/network mismatch')
        from .environment_forcing import _case
        if any(_case(p, False).thermal_inputs != self.configuration.thermal_boundaries for p in self.environment.profile):
            raise ValueError('configuration/forcing boundary mismatch')
        if any(p.loads.payload_w or p.loads.communications_w or p.loads.propulsion_w or
               any(n.internal_dissipation_w for n in p.nodes) for p in self.environment.profile):
            raise ValueError('routed baseline excludes acquisition/transmitter and duplicate heat')
        # Structural input admission only. Derived compilation is performed by
        # the separately paid owner, not repeatedly inside planner validation.
        from .assembly_document import assembly_document_digest
        if self.configuration.assembly_digest != assembly_document_digest(self.assembly):
            raise ValueError('stale configuration assembly binding')

    @property
    def geometry_mode(self):
        return self.environment.mode


@dataclass(frozen=True, slots=True)
class ReleasedRequest:
    release_seconds: int
    product: MSProductSpec
    acquisition_duration_seconds: int = 4

    def __post_init__(self):
        integer(self.release_seconds, 'release')
        typed(self.product, MSProductSpec)
        integer(self.acquisition_duration_seconds, 'acquisition duration', 1, 120)
        if self.release_seconds > self.product.acquisition_end_seconds:
            raise ValueError('release after acquisition window')


@dataclass(frozen=True, slots=True)
class DeclaredContact:
    contact_id: str
    station_id: str
    start_seconds: int
    end_seconds: int

    def __post_init__(self):
        from .assembly import _identity
        _identity(self.contact_id, 'declared contact'); _identity(self.station_id, 'station')
        integer(self.start_seconds, 'contact start'); integer(self.end_seconds, 'contact end')
        if not 0 < self.end_seconds-self.start_seconds <= 120:
            raise ValueError('bounded positive declared service interval')


@dataclass(frozen=True, slots=True)
class RollingPolicy:
    max_decisions: int = 64
    max_candidates: int = 32
    max_forecasts: int = 512
    suffix_actions: int = 4
    lookahead_seconds: int = 600
    recovery_seconds: int = 30
    maximum_observation_age_seconds: int = 600
    method: str = 'B47_PAID_SUFFIX_FIRST_ACTION_V1'

    def __post_init__(self):
        for name, lo, hi in (('max_decisions', 1, 64), ('max_candidates', 1, 32), ('max_forecasts', 1, 512),
                            ('suffix_actions', 2, 4), ('lookahead_seconds', 1, 600),
                            ('recovery_seconds', 1, 600), ('maximum_observation_age_seconds', 1, 600)):
            integer(getattr(self, name), name, lo, hi)
        if self.method != 'B47_PAID_SUFFIX_FIRST_ACTION_V1':
            raise ValueError('unsupported rolling policy')


@dataclass(frozen=True, slots=True)
class RollingQuotas:
    """New aggregate family; each distinct invocation also retains old leaf caps.

    Reservations are prospective control allowances, never measured CPU/leaves.
    A forecast reserves the entire old 65536 physical-call invocation ceiling.
    Replays add to these totals; no old invocation's spent work is erased.
    """
    max_forecast_invocations: int = 512
    max_forecast_physical_reserved: int = 2**25
    max_actual_physical_reserved: int = 2**18
    max_harness_compiles: int = 4096
    max_construction_line_reserved: int = 2**28
    max_nominal_force_reserved: int = 2**20
    max_control_reserved: int = 2**44
    max_output_bytes: int = 256*2**20
    max_reconstructions: int = 2
    method: str = 'B47_CUMULATIVE_INVOCATION_WORK_V1'

    def __post_init__(self):
        caps = dict(max_forecast_invocations=512, max_forecast_physical_reserved=2**25,
                    max_actual_physical_reserved=2**18, max_harness_compiles=4096,
                    max_construction_line_reserved=2**28, max_nominal_force_reserved=2**20,
                    max_control_reserved=2**44, max_output_bytes=512*2**20, max_reconstructions=2)
        for n, hi in caps.items():
            integer(getattr(self, n), n, 1, hi)
        if self.method != 'B47_CUMULATIVE_INVOCATION_WORK_V1':
            raise ValueError('unsupported aggregate accounting')


@dataclass(frozen=True, slots=True)
class RollingRoot:
    model: PublicPhysicalModel
    initial_checkpoint: CheckpointState
    initial_quaternion: tuple[float, float, float, float]
    requests: tuple[ReleasedRequest, ...]
    contacts: tuple[DeclaredContact, ...]
    knowledge_mode: object
    initial_estimate: object
    policy: RollingPolicy = RollingPolicy()
    quotas: RollingQuotas = RollingQuotas()
    api: str = API

    def __post_init__(self):
        typed(self.model, PublicPhysicalModel); typed(self.policy, RollingPolicy); typed(self.quotas, RollingQuotas)
        from .rolling_knowledge import KnowledgeMode, ReceivedObservation
        typed(self.knowledge_mode, KnowledgeMode); typed(self.initial_estimate, ReceivedObservation)
        typed(self.initial_checkpoint, CheckpointState)
        if self.api != API or type(self.api) is not str:
            raise ValueError('unsupported adaptive root')
        q = canonical_quaternion(self.initial_quaternion)
        if q != self.initial_quaternion:
            raise ValueError('canonical declared initial pose required')
        ctx = self.initial_checkpoint.restore(self.model.simulation_inputs)
        from .long_mission import admit_operational_regime
        admit_operational_regime(ctx)
        if Q(ctx.simulation_time_seconds) != self.model.environment.start_seconds or ctx.spacecraft_state.data_storage.stored_records or ctx.ground_data_delivery_state.partial_transfers or ctx.ground_data_delivery_state.completed_deliveries:
            raise ValueError('actual root must be original empty-custody boundary')
        if self.initial_estimate.observed_at_seconds != ctx.simulation_time_seconds or self.initial_estimate.received_at_seconds != ctx.simulation_time_seconds or self.initial_estimate.origin != 'DECLARED_ESTIMATE':
            raise ValueError('explicit original estimate required, never an implicit truth copy')
        if type(self.requests) is not tuple or not 1 <= len(self.requests) <= 16 or type(self.contacts) is not tuple or len(self.contacts) > 64:
            raise ValueError('bounded requests/contacts')
        points = {p.point.point_id.value: p for p in self.model.catalog}
        for r in self.requests:
            typed(r, ReleasedRequest)
            p = r.product
            if p.request.target_id.value not in points or not self.model.environment.start_seconds <= p.acquisition_start_seconds < p.acquisition_end_seconds <= p.delivery_deadline_seconds <= self.model.environment.end_seconds:
                raise ValueError('product/world binding')
        if len({r.product.request.request_id for r in self.requests}) != len(self.requests) or len({r.product.capture_group for r in self.requests}) != len(self.requests):
            raise ValueError('duplicate request/capture group')
        for c in self.contacts:
            typed(c, DeclaredContact)
            if c.station_id not in points or not self.model.environment.start_seconds <= c.start_seconds < c.end_seconds <= self.model.environment.end_seconds:
                raise ValueError('contact/world binding')
        if tuple(sorted(self.contacts, key=lambda c: (c.start_seconds, c.contact_id))) != self.contacts or len({c.contact_id for c in self.contacts}) != len(self.contacts):
            raise ValueError('deterministic unique contact order required')
        if any(a.end_seconds > b.start_seconds for a, b in zip(self.contacts, self.contacts[1:])):
            raise ValueError('overlapping declared service intervals unsupported')


def public_model_from_harness(inputs):
    """Trusted input conversion strips fixed program/private CP/products completely."""
    from .harness_mission import HarnessMissionInputs
    typed(inputs, HarnessMissionInputs)
    m = inputs.coupled.mission
    names = {f.name for f in fields(PublicPhysicalModel)} - {'configuration', 'construction_limits', 'augmentation', 'api'}
    return PublicPhysicalModel(**{n: getattr(m, n) for n in names}, configuration=inputs.coupled.configuration,
                               construction_limits=inputs.coupled.limits, augmentation=inputs.augmentation)
