"""Task 04A: one physical action, sampled protection, dyadic internal physics.

Constant forcing is declared for the whole action. Geometry/ADCS are action
inputs, not recomputed controller decisions at the numerical sample times.
Solar retention_loss denotes the whole action's uniform additive loss.
All numerical proposals are private; only a completed action can commit.
"""

from dataclasses import dataclass, fields, replace
from enum import Enum
from math import fsum, isfinite, ldexp

from .continuation import ImagingAction, CoupledDownlinkAction, _exact, _label, checked_checkpoint
from .degradation import SolarDegradationForcingInput
from .engine import (SimulationEngine, StepInterval, CoupledPhysicalSubstepResult,
                     complete_coupled_physical_substep, _validate_completed_context)
from .eps_capability import compute_eps_capability
from .eps_system import EPSIntervalInputs, compute_eps_substep_transition
from .ids import ThermalNodeId
from .imaging_feasibility import evaluate_observation_acquisition
from .imaging_resources import _checked_sum as _acquisition_sum
from .integration_time import IntegrationPolicy, MAX_ACTION_SECONDS
from .ms_acquisition import InitialAttitudeEvidence
from .observation_feasibility import ScheduledObservationExecution
from .onboard_data import OnboardAcquisitionDataRecord, compute_onboard_acquisition_data_volume_proposal
from .operational_protection import (ActionKind, ProtectedRequest, StandbyAction, action_kind,
    validate_policy, validate_request_bindings, _violations, _standby_service_ledger)
from .state import FDIRState, OperationalMode
from .storage import evaluate_storage_admission, StorageAdmissionStatus
from .thermal import _checked_product, _checked_quotient
from .thermal_coupling import compute_eps_thermal_substep_transition
from .thermal_routing import (ElectricalLoadComponent, ServedComponentPower, ServedPowerLedger,
    compute_substep_routed_internal_heat, compose_routed_internal_heat_sources)


def _nonnegative(value, name):
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative built-in number")


def _nodes(values):
    _exact(values, tuple, "node IDs")
    for node in values:
        _exact(node, ThermalNodeId, "node ID")
    if len(set(values)) != len(values):
        raise ValueError("node IDs must be unique")


@dataclass(frozen=True, slots=True)
class TimedRequest:
    start_time_seconds: int
    end_time_seconds: int
    request: ProtectedRequest
    forcing_contract: str = "constant-over-action-uniform-solar-loss-v1"
    forcing_change_times_seconds: tuple[int, ...] = ()

    def __post_init__(self):
        StepInterval(self.start_time_seconds, self.end_time_seconds)
        if self.end_time_seconds - self.start_time_seconds > MAX_ACTION_SECONDS:
            raise ValueError("physical duration exceeds representability limit")
        _exact(self.request, ProtectedRequest, "request")
        self.request.__post_init__()
        if (type(self.forcing_contract) is not str
                or self.forcing_contract != "constant-over-action-uniform-solar-loss-v1"):
            raise ValueError("unsupported forcing contract")
        _exact(self.forcing_change_times_seconds, tuple, "forcing changes")
        if self.forcing_change_times_seconds:
            raise ValueError("within-action forcing changes are unsupported; use physical boundaries")
        action = self.request.action
        if type(action) is ImagingAction:
            action.execution.__post_init__()
            if (action.execution.scheduled_start_seconds != self.start_time_seconds
                    or action.execution.candidate.acquisition_input.imaging_duration_seconds
                    != self.duration_seconds):
                raise ValueError("one exposure must equal the full physical interval")
        elif type(action) is CoupledDownlinkAction:
            action.contact.__post_init__()
            if (action.contact.start_time_seconds, action.contact.end_time_seconds) != (
                    self.start_time_seconds, self.end_time_seconds):
                raise ValueError("contact must equal the full physical interval")

    @property
    def duration_seconds(self):
        return self.end_time_seconds - self.start_time_seconds


class SampledReason(str, Enum):
    OPERATING_START = "required-node-outside-operating-at-start"
    OPERATING_TRAJECTORY = "predicted-required-node-outside-operating-at-internal-endpoint"
    ACTION_POWER = "mission-full-service-unavailable-on-subinterval"
    IMAGING_AUTHORIZATION = "imaging-sequence-or-storage-unavailable"
    DATA_UNAVAILABLE = "requested-record-not-onboard"
    ESSENTIAL_POWER = "essential-standby-service-unavailable-on-subinterval"
    STANDBY_THERMAL = "standby-required-node-outside-operating-at-sample"


@dataclass(frozen=True, slots=True)
class PhysicalSample:
    """Offset numerator / 2**trace.level seconds, not an absolute float time.

    unmet_load_w is the EPS average on the preceding subinterval (zero at
    origin), not an instantaneous threshold crossing or a separate failure.
    """
    offset_numerator_seconds: int
    battery_energy_wh: float
    battery_retention: float
    solar_retention: float
    cumulative_throughput_wh: float
    temperatures_k: tuple[tuple[ThermalNodeId, float], ...]
    operating_node_ids: tuple[ThermalNodeId, ...]
    survival_node_ids: tuple[ThermalNodeId, ...]
    unmet_load_w: float

    def __post_init__(self):
        _exact(self.offset_numerator_seconds, int, "offset numerator")
        if not 0 <= self.offset_numerator_seconds <= MAX_ACTION_SECONDS * 4096:
            raise ValueError("sample offset out of range")
        for name in ("battery_energy_wh", "cumulative_throughput_wh", "unmet_load_w"):
            _nonnegative(getattr(self, name), name)
        for name in ("battery_retention", "solar_retention"):
            _nonnegative(getattr(self, name), name)
            if not 0 < getattr(self, name) <= 1:
                raise ValueError("sample retention out of range")
        _exact(self.temperatures_k, tuple, "temperatures")
        ids = []
        for item in self.temperatures_k:
            _exact(item, tuple, "temperature item")
            if len(item) != 2:
                raise ValueError("temperature item requires node and K")
            node, temperature = item
            _exact(node, ThermalNodeId, "node")
            _nonnegative(temperature, "temperature K")
            if temperature <= 0:
                raise ValueError("temperature must be positive")
            ids.append(node)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("sample requires unique thermal nodes")
        for nodes in (self.operating_node_ids, self.survival_node_ids):
            _nodes(nodes)
            if not set(nodes) <= set(ids):
                raise ValueError("observations reference unknown nodes")


@dataclass(frozen=True, slots=True)
class TrajectoryTrace:
    start_time_seconds: int
    end_time_seconds: int
    subdivision_level: int
    samples: tuple[PhysicalSample, ...]

    def __post_init__(self):
        interval = StepInterval(self.start_time_seconds, self.end_time_seconds)
        policy = IntegrationPolicy(self.subdivision_level)
        policy.duration(interval.dt_seconds)
        _exact(self.samples, tuple, "samples")
        if not 1 <= len(self.samples) <= policy.substeps + 1:
            raise ValueError("trace must be a bounded prefix of the partition")
        for i, sample in enumerate(self.samples):
            _exact(sample, PhysicalSample, "sample")
            sample.__post_init__()
            if sample.offset_numerator_seconds != i * interval.dt_seconds:
                raise ValueError("sample offsets must cover consecutive exact subintervals")
            if tuple(n for n, _ in sample.temperatures_k) != tuple(n for n, _ in self.samples[0].temperatures_k):
                raise ValueError("trace thermal node ordering changed")
        if self.samples[0].unmet_load_w != 0:
            raise ValueError("origin sample has no preceding EPS subinterval")

    @property
    def complete(self):
        return len(self.samples) == (1 << self.subdivision_level) + 1


@dataclass(frozen=True, slots=True)
class ActionAccounting:
    """Selected trajectory energies in Wh; damage/retention dimensionless.

    Reconciliation's unavailable energy is a separate ledger, never heat.
    Summation uses fsum; per-subinterval service retains exact owner checks.
    """
    generation_wh: float
    requested_load_wh: float
    served_load_wh: float
    unmet_load_wh: float
    charge_input_wh: float
    discharge_output_wh: float
    curtailed_generation_wh: float
    conversion_loss_wh: float
    throughput_wh: float
    unavailable_energy_wh: float
    calendar_damage: float
    cycling_damage: float
    solar_retention_loss: float
    routed_internal_heat_wh: float
    external_heat_wh: float
    numerical_substeps: int

    def __post_init__(self):
        for field in fields(self):
            _nonnegative(getattr(self, field.name), field.name)
        _exact(self.numerical_substeps, int, "numerical substeps")
        if not 1 <= self.numerical_substeps <= 4096:
            raise ValueError("numerical work exceeds bounded action limit")


@dataclass(frozen=True, slots=True)
class SubstepAvailability:
    requested_kind: ActionKind
    reasons: tuple[SampledReason, ...]
    operating_start_node_ids: tuple[ThermalNodeId, ...]
    predicted_operating_node_ids: tuple[ThermalNodeId, ...]
    standby_operating_node_ids: tuple[ThermalNodeId, ...]
    action_unmet_w: float
    essential_unmet_wh: float

    def __post_init__(self):
        _exact(self.requested_kind, ActionKind, "requested kind")
        _exact(self.reasons, tuple, "reasons")
        for reason in self.reasons:
            _exact(reason, SampledReason, "reason")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("availability reasons must be unique")
        for name in ("operating_start_node_ids", "predicted_operating_node_ids", "standby_operating_node_ids"):
            _nodes(getattr(self, name))
        for name in ("action_unmet_w", "essential_unmet_wh"):
            _nonnegative(getattr(self, name), name)
        for evidence, reason in ((self.operating_start_node_ids, SampledReason.OPERATING_START),
                (self.predicted_operating_node_ids, SampledReason.OPERATING_TRAJECTORY),
                (self.standby_operating_node_ids, SampledReason.STANDBY_THERMAL),
                (self.action_unmet_w, SampledReason.ACTION_POWER),
                (self.essential_unmet_wh, SampledReason.ESSENTIAL_POWER)):
            if bool(evidence) != (reason in self.reasons):
                raise ValueError("sampled evidence disagrees with reasons")

    @property
    def available(self):
        return not self.reasons


@dataclass(frozen=True, slots=True)
class SubsteppedOutcome:
    request_id: str
    availability: SubstepAvailability
    actual_kind: ActionKind
    actual_trace: TrajectoryTrace
    predicted_trace: TrajectoryTrace | None
    accounting: ActionAccounting
    evaluated_eps_substeps: int
    operational_mode: OperationalMode
    fdir_state: FDIRState
    critical_energy_since_seconds: int | None
    recovered: bool

    def __post_init__(self):
        _label(self.request_id, "request ID")
        for value, owner in ((self.availability, SubstepAvailability), (self.actual_kind, ActionKind),
                (self.actual_trace, TrajectoryTrace), (self.accounting, ActionAccounting),
                (self.operational_mode, OperationalMode), (self.fdir_state, FDIRState), (self.recovered, bool)):
            _exact(value, owner, owner.__name__)
        self.availability.__post_init__()
        self.actual_trace.__post_init__()
        self.accounting.__post_init__()
        count = 1 << self.actual_trace.subdivision_level
        if not self.actual_trace.complete or self.accounting.numerical_substeps != count:
            raise ValueError("actual outcome requires exactly one complete physical interval")
        _exact(self.evaluated_eps_substeps, int, "EPS evaluations")
        if not count <= self.evaluated_eps_substeps <= 2 * count:
            raise ValueError("invalid proposal numerical work")
        if self.predicted_trace is not None:
            _exact(self.predicted_trace, TrajectoryTrace, "prediction")
            self.predicted_trace.__post_init__()
            if (self.predicted_trace.start_time_seconds, self.predicted_trace.end_time_seconds,
                    self.predicted_trace.subdivision_level) != (self.actual_trace.start_time_seconds,
                    self.actual_trace.end_time_seconds, self.actual_trace.subdivision_level):
                raise ValueError("prediction and actual path must use the same partition")
        expected = self.availability.requested_kind if self.availability.available else ActionKind.STANDBY
        if self.actual_kind is not expected:
            raise ValueError("actual action disagrees with admission")
        safe = bool(self.availability.essential_unmet_wh or self.availability.standby_operating_node_ids)
        mode = OperationalMode.SAFE if safe else {ActionKind.IMAGING: OperationalMode.IMAGING,
            ActionKind.DOWNLINK: OperationalMode.DOWNLINK, ActionKind.STANDBY: OperationalMode.STANDBY}[expected]
        if self.operational_mode is not mode:
            raise ValueError("mode disagrees with selected action")
        if self.fdir_state is not (FDIRState.NORMAL if self.availability.available else FDIRState.BACKUP):
            raise ValueError("FDIR disagrees with sampled admission")
        stamp = self.critical_energy_since_seconds
        if stamp is not None and (type(stamp) is not int or not 0 <= stamp <= self.actual_trace.start_time_seconds):
            raise ValueError("critical timestamp denotes an integer decision boundary, not a crossing")
        if (stamp is not None) != bool(self.availability.essential_unmet_wh):
            raise ValueError("critical timestamp disagrees with essential service")
        if self.recovered and self.fdir_state is not FDIRState.NORMAL:
            raise ValueError("recovery requires a normal boundary decision")

    @property
    def evaluated_thermal_substeps(self):
        """Actual standby proposal plus any computed mission thermal prefix."""
        return self.accounting.numerical_substeps + (0 if self.predicted_trace is None
                                                     else len(self.predicted_trace.samples) - 1)


def _sample(context, numerator, required, unmet=0.0):
    s = context.spacecraft_state
    nodes = tuple(n.node_id for n in s.thermal.node_states)
    return PhysicalSample(numerator, s.battery.energy_wh, s.degradation.battery.usable_capacity_retention,
        s.degradation.solar.generation_retention, s.degradation.battery.cumulative_energy_throughput_wh,
        tuple((n.node_id, n.temperature_k) for n in s.thermal.node_states),
        _violations(context, required), _violations(context, nodes, survival=True), unmet)


def _energy_wh(power, seconds):
    # A positive subinterval quantity must not vanish through underflow. Such
    # an integration-specific representability failure is NOT R1 allocation
    # rejection and must not become a false zero essential-power deficit.
    return _checked_quotient("action energy Wh", _checked_product("action energy J", power, seconds), 3600)


def _aggregate(parts):
    def energy(attribute):
        return fsum(_energy_wh(getattr(p.eps_result.battery, attribute), p.eps_result.battery.dt_seconds)
                    for p in parts)
    return ActionAccounting(energy("generation_w"), energy("load_w"), energy("served_load_w"),
        energy("unmet_load_w"), energy("charge_input_w"), energy("discharge_output_w"),
        energy("curtailed_generation_w"), fsum(p.eps_result.battery.conversion_loss_wh for p in parts),
        fsum(p.battery_degradation_result.throughput_increment_wh for p in parts),
        fsum(p.battery_capacity_reconciliation_result.unavailable_energy_wh for p in parts),
        fsum(p.battery_degradation_result.calendar_damage for p in parts),
        fsum(p.battery_degradation_result.cycling_damage for p in parts),
        fsum(p.solar_degradation_result.retention_loss for p in parts if p.solar_degradation_result is not None),
        fsum(_energy_wh(l.internal_dissipation_w, p.eps_result.battery.dt_seconds) for p in parts
             for l in p.thermal_coupling_result.node_heat_ledgers),
        fsum(_energy_wh(fsum((l.absorbed_solar_w, l.absorbed_albedo_w, l.absorbed_earth_ir_w)),
             p.eps_result.battery.dt_seconds) for p in parts
             for l in p.thermal_coupling_result.node_heat_ledgers), len(parts))


def _physical_substep(candidate, duration, forcing, eps_inputs, policy, solar, *, standby,
                      internal_heat_adjustments_w=None):
    """Shared EPS-to-thermal/ageing owner on private state.

    The opt-in signed heat adjustment supports explicitly accounted mechanical
    energy storage/release in the 05E maneuver executor. It changes routed
    internal dissipation only; battery conversion losses retain their existing
    owner. None follows the original arithmetic and routing without alteration.
    """
    cfg, state = candidate.inputs.spacecraft_configuration, candidate.spacecraft_state
    adjustments = None
    if internal_heat_adjustments_w is not None:
        _exact(internal_heat_adjustments_w, tuple, "internal heat adjustments")
        adjustments = {}
        known = {node.node_id for node in cfg.thermal.network.nodes}
        for item in internal_heat_adjustments_w:
            _exact(item, tuple, "internal heat adjustment")
            if len(item) != 2:
                raise ValueError("internal heat adjustment requires node and signed watts")
            node, watts = item
            _exact(node, ThermalNodeId, "internal heat adjustment node")
            _exact(node.value, str, "internal heat adjustment node value")
            node = ThermalNodeId(node.value)
            if node not in known or node in adjustments:
                raise ValueError("internal heat adjustments require unique known thermal nodes")
            if type(watts) not in (int, float):
                raise TypeError("internal heat adjustment must be a built-in number")
            try:
                watts = float(watts)
            except OverflowError as exc:
                raise ValueError("internal heat adjustment must be finite") from exc
            if not isfinite(watts):
                raise ValueError("internal heat adjustment must be finite")
            adjustments[node] = watts
    capability = compute_eps_capability(cfg.eps, state.degradation)
    eps = compute_eps_substep_transition(state.battery, cfg.eps, eps_inputs,
                                         duration=duration, capability=capability)
    if not standby and eps.battery.unmet_load_w > 0:
        # A deficient mission proposal is discarded. We do not invent a
        # mission load-shedding/partial-acquisition heat policy here.
        return None, eps
    if standby:
        served = _standby_service_ledger(eps_inputs.load_breakdown, policy.standby_service_order, eps)
    else:
        served = ServedPowerLedger(tuple(ServedComponentPower(c,
            getattr(eps_inputs.load_breakdown, c.value.replace("-", "_") + "_w"),
            getattr(eps_inputs.load_breakdown, c.value.replace("-", "_") + "_w"))
            for c in ElectricalLoadComponent))
    routed = compute_substep_routed_internal_heat(eps_inputs.load_breakdown, served,
        forcing.routing_config, cfg.thermal.network, eps_result=eps)
    sources = compose_routed_internal_heat_sources(routed, forcing.external_heat_sources)
    if adjustments is not None:
        adjusted = []
        for source in sources.node_sources:
            heat = source.internal_dissipation_w + adjustments.get(source.node_id, 0.0)
            if not isfinite(heat) or heat < 0:
                raise ValueError("adjusted internal dissipation must be finite and nonnegative")
            adjusted.append(replace(source, internal_dissipation_w=heat))
        sources = replace(sources, node_sources=tuple(adjusted))
    thermal = compute_eps_thermal_substep_transition(state.thermal, cfg.thermal.network,
        forcing.thermal_inputs, sources, eps, duration=duration)
    part = complete_coupled_physical_substep(candidate, duration, eps_result=eps,
        thermal_coupling_result=thermal, eps_capability_result=capability, solar_degradation_forcing=solar)
    _exact(part, CoupledPhysicalSubstepResult, "physical substep")
    part.__post_init__()
    return part, eps


def _physical_proposal(context, timed, integration, forcing, eps_inputs, required, policy, *, standby):
    """One EPS per internal interval; no repeated engine actions or input clones."""
    candidate = checked_checkpoint(context).restore(context.inputs)
    duration = integration.duration(timed.duration_seconds)
    solar = forcing.solar_degradation_forcing
    if solar is not None:
        loss = ldexp(float(solar.retention_loss), -integration.subdivision_level)
        if solar.retention_loss > 0 and loss == 0:
            raise ValueError("nonzero solar loss cannot be represented on the requested partition")
        solar = SolarDegradationForcingInput(loss)
    samples = [_sample(candidate, 0, required)]
    parts = []
    unmet = 0.0
    evaluated = 0
    for i in range(integration.substeps):
        part, eps = _physical_substep(candidate, duration, forcing, eps_inputs, policy, solar, standby=standby)
        evaluated += 1
        if part is None:
            unmet = eps.battery.unmet_load_w
            break
        parts.append(part)
        samples.append(_sample(candidate, (i + 1) * timed.duration_seconds, required, eps.battery.unmet_load_w))
    trace = TrajectoryTrace(timed.start_time_seconds, timed.end_time_seconds, integration.subdivision_level, tuple(samples))
    return candidate, tuple(parts), trace, unmet, evaluated


def _imaging_request(context, previous, action, ms_acquisition=None):
    from .ms_acquisition import initial_acquisition_result, validate_ms_acquisition
    cfg = context.inputs.spacecraft_configuration
    if (any(r.record_id == action.record_id for r in context.spacecraft_state.data_storage.stored_records)
            or any(d.record.record_id == action.record_id for d in context.ground_data_delivery_state.completed_deliveries)):
        raise ValueError("imaging record ID already has an acquisition")
    if ms_acquisition is not None:
        validate_ms_acquisition(action, cfg.payload.optical_acquisition, ms_acquisition)
    if type(previous) is InitialAttitudeEvidence:
        optical = initial_acquisition_result(cfg, previous, action)
        if optical is None:
            return None, None
    else:
        evaluation = evaluate_observation_acquisition(cfg.adcs.agile_pointing, cfg.payload.optical_acquisition,
                                                    previous, action.execution.candidate)
        if (not evaluation.feasible or evaluation.sequence_result.candidate_next_start_seconds
                > action.execution.scheduled_start_seconds):
            return None, None
        optical = evaluation.acquisition_result
    if ms_acquisition is None:
        volume = compute_onboard_acquisition_data_volume_proposal(optical)
        bits = volume.stored_equivalent_bits
    else:
        bits = float(ms_acquisition.sizing.stored_bits)  # <=2**40, lossless schema-5 representation
    acquisition = action.execution.candidate.acquisition_input
    opportunity = action.execution.candidate.maneuver_candidate.opportunity
    record = OnboardAcquisitionDataRecord(action.record_id, opportunity.request_id, opportunity.opportunity_id,
        action.execution.scheduled_start_seconds, acquisition.imaging_duration_seconds, acquisition.channel_selection,
        bits, bits)
    admission = evaluate_storage_admission(cfg.storage, context.spacecraft_state.data_storage.stored_records, record)
    if admission.status is not StorageAdmissionStatus.ADMISSIBLE:
        return None, None
    environment = action.environment
    loads = replace(environment.non_acquisition_loads, payload_w=_acquisition_sum("combined payload request",
        environment.non_acquisition_loads.payload_w, optical.requested_acquisition_power_w))
    return record, EPSIntervalInputs(environment.sunlit, environment.incidence_angle_deg, loads)


def _bad(trace, *, endpoints_only=False):
    return tuple(dict.fromkeys(n for sample in trace.samples[1 if endpoints_only else 0:]
                              for n in sample.operating_node_ids))


def _prepare(context, previous, timed, policy, integration, *, ms_acquisition=None, allow_initial_attitude=False):
    from .experiment_codec import canonical_copy
    _validate_completed_context(context)
    canonical_copy(context.inputs)
    _exact(timed, TimedRequest, "timed request")
    _exact(integration, IntegrationPolicy, "integration policy")
    if not (allow_initial_attitude and type(previous) is InitialAttitudeEvidence):
        _exact(previous, ScheduledObservationExecution, "previous execution")
    timed, integration, previous = canonical_copy(timed), canonical_copy(integration), canonical_copy(previous)
    ms_acquisition = canonical_copy(ms_acquisition)
    integration.duration(timed.duration_seconds)
    if timed.start_time_seconds != context.simulation_time_seconds or timed.end_time_seconds > context.inputs.common_world.horizon_seconds:
        raise ValueError("physical action must start now and end within the horizon")
    if context.inputs.common_world.event_ids:
        raise ValueError("world-event execution is unsupported in constant-forcing actions")
    previous_end = (previous.at_seconds if type(previous) is InitialAttitudeEvidence else
                    previous.scheduled_start_seconds + previous.candidate.opportunity.imaging_duration_seconds)
    if previous_end > timed.start_time_seconds:
        raise ValueError("previous acquisition ends after current boundary")
    onboard = context.spacecraft_state.onboard
    if (onboard.fdir_state not in (FDIRState.NORMAL, FDIRState.BACKUP)
            or onboard.operational_mode not in (OperationalMode.SAFE, OperationalMode.STANDBY,
                                               OperationalMode.IMAGING, OperationalMode.DOWNLINK)):
        raise ValueError("onboard regime outside sampled policy ownership")
    policy = validate_policy(policy, context)
    request = timed.request
    validate_request_bindings(request, context)
    action, kind = request.action, action_kind(request.action)
    required = {ActionKind.IMAGING: policy.imaging_node_ids, ActionKind.DOWNLINK: policy.downlink_node_ids,
                ActionKind.STANDBY: policy.standby_node_ids}[kind]
    start_bad = _violations(context, required)
    wait = request.standby
    standby = _physical_proposal(context, timed, integration, wait,
        EPSIntervalInputs(wait.sunlit, wait.incidence_angle_deg, wait.loads), policy.standby_node_ids, policy, standby=True)
    standby_accounting = _aggregate(standby[1])
    standby_bad = _bad(standby[2])
    reasons = []
    if start_bad:
        reasons.append(SampledReason.OPERATING_START)
    candidate, parts, trace = standby[:3]
    predicted = None
    predicted_bad = ()
    record, eps_inputs, forcing = None, None, None
    if kind is ActionKind.IMAGING:
        record, eps_inputs = _imaging_request(context, previous, action, ms_acquisition)
        forcing = action
        if record is None:
            reasons.append(SampledReason.IMAGING_AUTHORIZATION)
    elif kind is ActionKind.DOWNLINK:
        if not any(r.record_id == action.record_id for r in context.spacecraft_state.data_storage.stored_records):
            reasons.append(SampledReason.DATA_UNAVAILABLE)
        else:
            forcing = action.physical_inputs
            eps_inputs = forcing.eps_inputs
    unmet, evaluated = 0.0, standby[4]
    if eps_inputs is not None:
        proposal = _physical_proposal(context, timed, integration, forcing, eps_inputs, required, policy, standby=False)
        candidate, parts, predicted, unmet, work = proposal
        trace = predicted
        evaluated += work
        predicted_bad = _bad(predicted, endpoints_only=True)
        if unmet:
            reasons.append(SampledReason.ACTION_POWER)
        if predicted_bad:
            reasons.append(SampledReason.OPERATING_TRAJECTORY)
    if standby_accounting.unmet_load_wh:
        reasons.append(SampledReason.ESSENTIAL_POWER)
    if standby_bad:
        reasons.append(SampledReason.STANDBY_THERMAL)
    availability = SubstepAvailability(kind, tuple(reasons), start_bad, predicted_bad, standby_bad,
                                      unmet, standby_accounting.unmet_load_wh)
    if not availability.available or kind is ActionKind.STANDBY:
        candidate, parts, trace = standby[:3]
        record = None
    return candidate, parts, trace, predicted, availability, evaluated, record, timed, previous


def evaluate_substepped_availability(context, previous_execution, request, *, policy, integration):
    """Read-only admission using precisely the same refined proposal as execution."""
    return _prepare(context, previous_execution, request, policy, integration)[4]


def _validate_physical_samples(parts, samples, duration):
    """Shared evidence check: selected trace must match authoritative physical parts."""
    for part, start, end in zip(parts, samples[:-1], samples[1:], strict=True):
        battery = part.eps_result.battery
        ageing = part.battery_degradation_result
        if (battery.duration != duration or battery.start_energy_wh != start.battery_energy_wh
                or part.battery_capacity_reconciliation_result.authoritative_end_energy_wh != end.battery_energy_wh
                or ageing.start_usable_capacity_retention != start.battery_retention
                or ageing.end_usable_capacity_retention != end.battery_retention
                or ageing.start_cumulative_energy_throughput_wh != start.cumulative_throughput_wh
                or ageing.end_cumulative_energy_throughput_wh != end.cumulative_throughput_wh
                or battery.unmet_load_w != end.unmet_load_w):
            raise ValueError("selected sample disagrees with its physical substep")
        before, after = dict(start.temperatures_k), dict(end.temperatures_k)
        for node in part.thermal_coupling_result.thermal_result.node_transitions:
            if (node.start_temperature_k != before[node.node_id]
                    or node.end_temperature_k != after[node.node_id]):
                raise ValueError("thermal trace disagrees with its physical substep")
        solar = part.solar_degradation_result
        if solar is None:
            if start.solar_retention != end.solar_retention:
                raise ValueError("solar retention changed without forcing")
        elif (solar.start_generation_retention, solar.end_generation_retention) != (
                start.solar_retention, end.solar_retention):
            raise ValueError("solar trace disagrees with forcing")


@dataclass(frozen=True, slots=True)
class SubsteppedActionResult:
    outcome: SubsteppedOutcome
    substeps: tuple[CoupledPhysicalSubstepResult, ...]
    final_checkpoint: object
    previous_execution: ScheduledObservationExecution | InitialAttitudeEvidence
    created_record: OnboardAcquisitionDataRecord | None
    transmission_result: object | None

    def __post_init__(self):
        from .checkpoint import CheckpointState
        from .downlink import DownlinkTransmissionResult
        _exact(self.outcome, SubsteppedOutcome, "outcome")
        self.outcome.__post_init__()
        _exact(self.substeps, tuple, "substeps")
        for part in self.substeps:
            _exact(part, CoupledPhysicalSubstepResult, "substep")
            part.__post_init__()
        if _aggregate(self.substeps) != self.outcome.accounting:
            raise ValueError("accounting differs from selected physical substeps")
        trace = self.outcome.actual_trace
        duration = IntegrationPolicy(trace.subdivision_level).duration(trace.end_time_seconds - trace.start_time_seconds)
        _validate_physical_samples(self.substeps, trace.samples, duration)
        _exact(self.final_checkpoint, CheckpointState, "checkpoint")
        if type(self.previous_execution) not in (ScheduledObservationExecution, InitialAttitudeEvidence):
            raise TypeError("expected previous execution or explicit initial attitude")
        self.previous_execution.__post_init__()
        if self.final_checkpoint.simulation_time_seconds != self.outcome.actual_trace.end_time_seconds:
            raise ValueError("result checkpoint is not the completed physical boundary")
        final = self.final_checkpoint.spacecraft
        last = trace.samples[-1]
        if (final.battery_energy_wh != last.battery_energy_wh
                or final.degradation.battery.usable_capacity_retention != last.battery_retention
                or final.degradation.battery.cumulative_energy_throughput_wh != last.cumulative_throughput_wh
                or final.degradation.solar.generation_retention != last.solar_retention
                or tuple((n.node_id, n.temperature_k) for n in final.thermal.node_states) != last.temperatures_k
                or final.operational_mode is not self.outcome.operational_mode
                or final.fdir_state is not self.outcome.fdir_state
                or final.critical_energy_since_seconds != self.outcome.critical_energy_since_seconds):
            raise ValueError("final physical/protection state disagrees with the selected outcome")
        if self.outcome.actual_kind is ActionKind.IMAGING:
            _exact(self.created_record, OnboardAcquisitionDataRecord, "created record")
        elif self.created_record is not None:
            raise ValueError("only selected imaging can create a product")
        if self.outcome.actual_kind is ActionKind.DOWNLINK:
            _exact(self.transmission_result, DownlinkTransmissionResult, "transmission")
            self.transmission_result.__post_init__()
        elif self.transmission_result is not None:
            raise ValueError("only selected downlink can deliver data")


def _commit_action(original, candidate):
    """One external commit, with assignment rollback if the commit hook fails."""
    names = ("simulation_time_seconds", "spacecraft_state", "ground_knowledge_state",
             "ground_data_delivery_state", "mission_state", "controller_state", "diagnostics")
    before = tuple(getattr(original, name) for name in names)
    try:
        SimulationEngine._commit(original, candidate)
    except BaseException:
        for name, value in zip(names, before):
            setattr(original, name, value)
        raise


def execute_substepped_request(context, previous_execution, request, *, policy, integration):
    """Complete one action atomically; no mid-action checkpoint is exposed."""
    return _execute_substepped_request(context, previous_execution, request, policy=policy, integration=integration)


def _execute_substepped_request(context, previous_execution, request, *, policy, integration,
                               ms_acquisition=None, allow_initial_attitude=False):
    """Shared execution transaction; the MS adapter only changes pre-storage sizing."""
    candidate, parts, trace, predicted, availability, evaluated, record, timed, previous = _prepare(
        context, previous_execution, request, policy, integration,
        ms_acquisition=ms_acquisition, allow_initial_attitude=allow_initial_attitude)
    actual = availability.requested_kind if availability.available else ActionKind.STANDBY
    transmission = []
    if actual is ActionKind.IMAGING:
        candidate.spacecraft_state.data_storage.stored_records += (record,)
        execution = timed.request.action.execution
        previous = ScheduledObservationExecution(execution.candidate.maneuver_candidate, execution.scheduled_start_seconds)
    elif actual is ActionKind.DOWNLINK:
        action = timed.request.action
        # Existing single-record arithmetic and mutation owner, exactly once.
        SimulationEngine()._prepare_downlink_physical_integration_handler(action.contact, action.record_id,
            transmission.append)(candidate, StepInterval(timed.start_time_seconds, timed.end_time_seconds))
    candidate.simulation_time_seconds = timed.end_time_seconds
    candidate.diagnostics.completed_steps = context.diagnostics.completed_steps + 1
    physical_snapshot = checked_checkpoint(candidate)
    onboard, old = candidate.spacecraft_state.onboard, context.spacecraft_state.onboard
    onboard.critical_energy_since_seconds = ((old.critical_energy_since_seconds
        if old.critical_energy_since_seconds is not None else timed.start_time_seconds)
        if availability.essential_unmet_wh else None)
    safe = bool(availability.essential_unmet_wh or availability.standby_operating_node_ids)
    onboard.operational_mode = OperationalMode.SAFE if safe else {ActionKind.IMAGING: OperationalMode.IMAGING,
        ActionKind.DOWNLINK: OperationalMode.DOWNLINK, ActionKind.STANDBY: OperationalMode.STANDBY}[actual]
    onboard.fdir_state = FDIRState.NORMAL if availability.available else FDIRState.BACKUP
    outcome = SubsteppedOutcome(timed.request.action.action_id, availability, actual, trace, predicted,
        _aggregate(parts), evaluated, onboard.operational_mode, onboard.fdir_state,
        onboard.critical_energy_since_seconds, old.fdir_state is FDIRState.BACKUP and onboard.fdir_state is FDIRState.NORMAL)
    _validate_completed_context(candidate)
    checkpoint = checked_checkpoint(candidate)
    from .experiment_codec import canonical_content
    expected = replace(physical_snapshot, spacecraft=replace(physical_snapshot.spacecraft,
        operational_mode=outcome.operational_mode, fdir_state=outcome.fdir_state,
        critical_energy_since_seconds=outcome.critical_energy_since_seconds))
    if canonical_content(checkpoint) != canonical_content(expected):
        raise ValueError("protection changed state outside its owned fields")
    result = SubsteppedActionResult(outcome, parts, checkpoint, previous, record,
                                    transmission[0] if transmission else None)
    _commit_action(context, candidate)
    return result


__all__ = ["TimedRequest", "SampledReason", "PhysicalSample", "TrajectoryTrace", "ActionAccounting",
           "SubstepAvailability", "SubsteppedOutcome", "SubsteppedActionResult",
           "evaluate_substepped_availability", "execute_substepped_request"]
