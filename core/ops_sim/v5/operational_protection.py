"""Sampled onboard protection composed around the unchanged physical kernels.

Only this boundary enforces Task 03B policy. Private completed proposals may
be discarded; exactly one selected proposal is committed to the caller. No
continuous thermal safety, permanent damage or ground-controller model.
"""

from dataclasses import dataclass, replace
from enum import Enum
from fractions import Fraction
from math import nextafter
from struct import pack, unpack

from .continuation import ImagingAction, CoupledDownlinkAction, checked_checkpoint, _exact, _label
from .coupled_downlink import CoupledDownlinkAttempt, validate_coupled_downlink_inputs
from .degradation import SolarDegradationForcingInput
from .engine import (SimulationEngine, StepResult, ImagingStorageEngineAttempt, _complete_coupled_physical_integration,
                     _validate_completed_context)
from .eps_capability import compute_eps_capability
from .eps_system import EPSIntervalInputs, compute_eps_interval_transition
from .ids import ThermalNodeId
from .observation_feasibility import ScheduledObservationExecution, evaluate_observation_sequence_feasibility
from .power_loads import PowerLoadBreakdown
from .state import FDIRState, OperationalMode
from .thermal import ThermalIntervalInputs
from .thermal_coupling import ThermalHeatSourceInputs, compute_eps_thermal_interval_transition
from .thermal_routing import (ComponentHeatRoutingConfig, ElectricalLoadComponent,
    ServedComponentPower, ServedPowerLedger, compose_routed_internal_heat_sources,
    compute_routed_internal_heat, RoutedInternalHeatResult, _checked_sum,
    _normalized_nonnegative_real)


class ActionKind(str, Enum):
    IMAGING = "imaging"
    DOWNLINK = "coupled-downlink"
    STANDBY = "standby"


class ProtectionReason(str, Enum):
    OPERATING_START = "required-node-outside-operating-at-start"
    OPERATING_END = "predicted-required-node-outside-operating-at-end"
    ACTION_POWER = "mission-action-full-electrical-service-unavailable"
    IMAGING_AUTHORIZATION = "imaging-sequence-or-storage-unavailable"
    DATA_UNAVAILABLE = "requested-record-not-onboard"
    ESSENTIAL_POWER = "essential-standby-power-unmet"
    STANDBY_THERMAL = "standby-required-node-outside-operating"


@dataclass(frozen=True, slots=True)
class ProtectionPolicy:
    """Explicit role/dependency and power-allocation assumptions, no thresholds.

    All declared standby loads are essential. The order is a load-shedding
    assumption used only for deficient standby heat, never a second demand.
    NORMAL/BACKUP are owned as sampled normal/reduced-operation regimes; BACKUP
    does not assert hardware switching. EMERGENCY_BEACON is outside this policy.
    """
    imaging_node_ids: tuple[ThermalNodeId, ...]
    downlink_node_ids: tuple[ThermalNodeId, ...]
    standby_node_ids: tuple[ThermalNodeId, ...]
    communications_node_id: ThermalNodeId
    standby_service_order: tuple[ElectricalLoadComponent, ...]
    essential_rule: str
    recovery_rule: str
    rationale: str
    communications_binding_rationale: str

    def __post_init__(self):
        for name in ("imaging_node_ids", "downlink_node_ids", "standby_node_ids"):
            values = getattr(self, name)
            _exact(values, tuple, name)
            if not values or len(set(values)) != len(values):
                raise ValueError("thermal dependencies must be nonempty and unique")
            for node in values:
                _exact(node, ThermalNodeId, name)
        _exact(self.communications_node_id, ThermalNodeId, "communications node")
        _exact(self.standby_service_order, tuple, "standby service order")
        for component in self.standby_service_order:
            _exact(component, ElectricalLoadComponent, "component")
        if (len(self.standby_service_order) != len(ElectricalLoadComponent)
                or set(self.standby_service_order) != set(ElectricalLoadComponent)):
            raise ValueError("service order requires every component exactly once")
        for name in ("essential_rule", "recovery_rule", "rationale", "communications_binding_rationale"):
            _label(getattr(self, name), name)
        if self.essential_rule != "all-declared-standby-loads":
            raise ValueError("unsupported essential rule")
        if self.recovery_rule != "next-admissible-sampled-boundary":
            raise ValueError("unsupported recovery rule")


@dataclass(frozen=True, slots=True)
class StandbyInputs:
    loads: PowerLoadBreakdown
    sunlit: bool
    incidence_angle_deg: float
    routing_config: ComponentHeatRoutingConfig
    thermal_inputs: ThermalIntervalInputs
    external_heat_sources: ThermalHeatSourceInputs
    solar_degradation_forcing: SolarDegradationForcingInput | None
    rationale: str

    def __post_init__(self):
        for name, owner in (("loads", PowerLoadBreakdown), ("routing_config", ComponentHeatRoutingConfig),
                            ("thermal_inputs", ThermalIntervalInputs), ("external_heat_sources", ThermalHeatSourceInputs)):
            _exact(getattr(self, name), owner, name)
        self.loads.__post_init__()
        EPSIntervalInputs(self.sunlit, self.incidence_angle_deg, self.loads)
        if self.loads.payload_w != 0 or self.loads.communications_w != 0 or self.loads.propulsion_w != 0:
            raise ValueError("standby requires payload, transmitter and propulsion off")
        if self.loads.total_load_w <= 0:
            raise ValueError("standby requires explicit positive essential demand")
        if self.solar_degradation_forcing is not None:
            _exact(self.solar_degradation_forcing, SolarDegradationForcingInput, "solar forcing")
        if any(s.internal_dissipation_w != 0 for s in self.external_heat_sources.node_sources):
            raise ValueError("standby internal heat is owned by served-power routing")
        _label(self.rationale, "standby rationale")


@dataclass(frozen=True, slots=True)
class StandbyAction:
    action_id: str

    def __post_init__(self):
        _label(self.action_id, "action_id")


@dataclass(frozen=True, slots=True)
class ProtectedRequest:
    action: ImagingAction | CoupledDownlinkAction | StandbyAction
    standby: StandbyInputs

    def __post_init__(self):
        if type(self.action) not in (ImagingAction, CoupledDownlinkAction, StandbyAction):
            raise TypeError("protected requests require imaging, coupled downlink or standby")
        self.action.__post_init__()
        _exact(self.standby, StandbyInputs, "standby")
        self.standby.__post_init__()


def action_kind(action):
    return {ImagingAction: ActionKind.IMAGING, CoupledDownlinkAction: ActionKind.DOWNLINK,
            StandbyAction: ActionKind.STANDBY}[type(action)]


def validate_policy(policy, context):
    from .experiment_codec import canonical_copy
    _exact(policy, ProtectionPolicy, "policy")
    policy = canonical_copy(policy)
    network = context.inputs.spacecraft_configuration.thermal.network
    known = {n.node_id for n in network.nodes}
    core = {network.bus_node_id, network.battery_node_id}
    required = ((policy.imaging_node_ids, core | {network.payload_node_id}),
                (policy.downlink_node_ids, core | {policy.communications_node_id}),
                (policy.standby_node_ids, core))
    for declared, minimum in required:
        if not minimum <= set(declared) <= known:
            raise ValueError("missing required role binding or unknown thermal node")
    return policy


def _violations(context, node_ids, *, survival=False):
    nodes = {n.node_id: n for n in context.inputs.spacecraft_configuration.thermal.network.nodes}
    temperatures = {n.node_id: n.temperature_k for n in context.spacecraft_state.thermal.node_states}
    prefix = "survival" if survival else "operating"
    return tuple(n for n in node_ids if not (
        getattr(nodes[n], prefix + "_min_temperature_k").value <= temperatures[n]
        <= getattr(nodes[n], prefix + "_max_temperature_k").value))


def _validate_forcing(forcing, network):
    known = {n.node_id for n in network.nodes}
    if ({n.node_id for n in forcing.thermal_inputs.node_boundaries} != known
            or {n.node_id for n in forcing.external_heat_sources.node_sources} != known
            or not {r.thermal_node_id for r in forcing.routing_config.routes} <= known):
        raise ValueError("forcing/routing thermal node bindings do not match the network")
    if any(s.internal_dissipation_w != 0 for s in forcing.external_heat_sources.node_sources):
        raise ValueError("internal heat is owned by served-power routing")


def validate_request_bindings(request, context):
    """Validate even unused/future fallback and mission node bindings eagerly."""
    network = context.inputs.spacecraft_configuration.thermal.network
    _validate_forcing(request.standby, network)
    if type(request.action) is ImagingAction:
        _validate_forcing(request.action, network)
    elif type(request.action) is CoupledDownlinkAction:
        validate_coupled_downlink_inputs(request.action.physical_inputs, network)


def _standby_service_ledger(loads, service_order, eps):
    """Compose priority service against the unchanged routing owner's arithmetic.

    Full service preserves demands exactly. For a deficit, exact rational
    arithmetic on the admitted binary values determines the full priority
    prefix and ONE partial component. Round its exact residual to binary64;
    if necessary find the closest value whose enum-order checked sum equals
    EPS. The monotone bit search is bounded by 64 iterations, with no epsilon.
    Higher priorities stay full, lower ones zero, and the partial stays within
    its demand. If that fixed-prefix representable solution does not exist,
    reject; do not redistribute power or change EPS to manufacture equality.
    """
    requested = {c: getattr(loads, c.value.replace("-", "_") + "_w")
                 for c in ElectricalLoadComponent}
    demands = {c: _normalized_nonnegative_real("standby demand", v)
               for c, v in requested.items()}
    served = dict(demands) if eps.battery.unmet_load_w == 0 else dict.fromkeys(demands, 0)
    if eps.battery.unmet_load_w != 0:
        target = _normalized_nonnegative_real("EPS served load", eps.battery.served_load_w)
        remaining = Fraction(target)
        for component in service_order:
            demand = demands[component]
            if Fraction(demand) <= remaining:
                served[component] = demand
                remaining -= Fraction(demand)
                continue

            def aggregate(amount):
                served[component] = amount
                # builtin sum uses different floating arithmetic; reuse the
                # owner, including integer normalization and overflow checks.
                return _checked_sum("standby served load", *(
                    served[c] for c in ElectricalLoadComponent))

            upper = float(demand)
            if upper > demand:
                upper = nextafter(upper, 0.0)
            preferred = min(float(remaining), upper)
            total = aggregate(preferred)
            if total != target:
                # Nonnegative finite binary64 encodings have numeric order.
                # Search toward the target plateau, selecting its nearest edge
                # to the correctly rounded exact residual (not maximum power).
                def bits(value):
                    return unpack(">Q", pack(">d", value))[0]

                def value(index):
                    return unpack(">d", pack(">Q", index))[0]

                if total < target:
                    low, high = bits(preferred), bits(upper)
                    while low < high:
                        middle = (low + high) // 2
                        if aggregate(value(middle)) < target:
                            low = middle + 1
                        else:
                            high = middle
                else:
                    low, high = 0, bits(preferred)
                    while low < high:
                        middle = (low + high + 1) // 2
                        if aggregate(value(middle)) > target:
                            high = middle - 1
                        else:
                            low = middle
                if aggregate(value(low)) != target:
                    raise ValueError("standby priority prefix has no representable EPS-reconciled partial service")
            break
    return ServedPowerLedger(tuple(ServedComponentPower(c, requested[c], served[c])
                                   for c in ElectricalLoadComponent))


def _standby_proposal(context, inputs, policy):
    """One authoritative EPS calculation on isolated state; reuse all physics."""
    working = checked_checkpoint(context).restore(context.inputs)
    routed = None

    def integrate(candidate, interval):
        nonlocal routed
        cfg, state = candidate.inputs.spacecraft_configuration, candidate.spacecraft_state
        capability = compute_eps_capability(cfg.eps, state.degradation)
        eps = compute_eps_interval_transition(state.battery, cfg.eps,
            EPSIntervalInputs(inputs.sunlit, inputs.incidence_angle_deg, inputs.loads),
            dt_seconds=interval.dt_seconds, capability=capability)
        # Explicit priority service, bounded by the ONE EPS result. All loads
        # are essential; allocation determines heat only, not critical status.
        ledger = _standby_service_ledger(inputs.loads, policy.standby_service_order, eps)
        routed = compute_routed_internal_heat(inputs.loads, ledger, inputs.routing_config,
                                             cfg.thermal.network, eps_result=eps)
        sources = compose_routed_internal_heat_sources(routed, inputs.external_heat_sources)
        thermal = compute_eps_thermal_interval_transition(state.thermal, cfg.thermal.network,
            inputs.thermal_inputs, sources, eps, dt_seconds=interval.dt_seconds)
        return _complete_coupled_physical_integration(candidate, interval, eps_result=eps,
            thermal_coupling_result=thermal, eps_capability_result=capability,
            solar_degradation_forcing=inputs.solar_degradation_forcing)

    step = SimulationEngine()._run_transaction(working, physical_integration_handler_factory=lambda: integrate)
    return working, step, routed


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    requested_kind: ActionKind
    reasons: tuple[ProtectionReason, ...]
    operating_start_node_ids: tuple[ThermalNodeId, ...]
    predicted_operating_end_node_ids: tuple[ThermalNodeId, ...]
    standby_operating_node_ids: tuple[ThermalNodeId, ...]
    essential_unmet_w: float

    def __post_init__(self):
        _exact(self.requested_kind, ActionKind, "requested kind")
        _exact(self.reasons, tuple, "reasons")
        for reason in self.reasons:
            _exact(reason, ProtectionReason, "reason")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("reasons must be unique")
        for name in ("operating_start_node_ids", "predicted_operating_end_node_ids", "standby_operating_node_ids"):
            _exact(getattr(self, name), tuple, name)
            if len(set(getattr(self, name))) != len(getattr(self, name)):
                raise ValueError("observed node IDs must be unique")
            for node in getattr(self, name):
                _exact(node, ThermalNodeId, name)
        from math import isfinite
        if type(self.essential_unmet_w) not in (int, float) or not isfinite(self.essential_unmet_w) or self.essential_unmet_w < 0:
            raise ValueError("essential unmet power must be finite nonnegative W")
        for evidence, reason in ((self.operating_start_node_ids, ProtectionReason.OPERATING_START),
            (self.predicted_operating_end_node_ids, ProtectionReason.OPERATING_END),
            (self.standby_operating_node_ids, ProtectionReason.STANDBY_THERMAL),
            (self.essential_unmet_w, ProtectionReason.ESSENTIAL_POWER)):
            if bool(evidence) != (reason in self.reasons):
                raise ValueError("availability evidence and reasons disagree")

    @property
    def available(self):
        return not self.reasons


@dataclass(frozen=True, slots=True)
class OperationalOutcome:
    """Typed sampled history, validated by bounded deterministic replay on restore."""
    request_id: str
    start_time_seconds: int
    end_time_seconds: int
    availability: ActionAvailability
    actual_kind: ActionKind
    survival_start_node_ids: tuple[ThermalNodeId, ...]
    survival_end_node_ids: tuple[ThermalNodeId, ...]
    operational_mode: OperationalMode
    fdir_state: FDIRState
    critical_energy_since_seconds: int | None
    recovered: bool

    def __post_init__(self):
        _label(self.request_id, "request ID")
        for name in ("start_time_seconds", "end_time_seconds"):
            _exact(getattr(self, name), int, name)
        if not 0 <= self.start_time_seconds < self.end_time_seconds:
            raise ValueError("outcome must consume a positive interval")
        _exact(self.availability, ActionAvailability, "availability")
        self.availability.__post_init__()
        _exact(self.actual_kind, ActionKind, "actual kind")
        _exact(self.operational_mode, OperationalMode, "mode")
        _exact(self.fdir_state, FDIRState, "FDIR")
        _exact(self.recovered, bool, "recovered")
        for nodes in (self.survival_start_node_ids, self.survival_end_node_ids):
            _exact(nodes, tuple, "survival nodes")
            if len(set(nodes)) != len(nodes):
                raise ValueError("survival nodes must be unique")
            for node in nodes:
                _exact(node, ThermalNodeId, "survival node")
        expected = self.availability.requested_kind if self.availability.available else ActionKind.STANDBY
        if self.actual_kind is not expected:
            raise ValueError("actual action disagrees with availability")
        safe = self.availability.essential_unmet_w > 0 or bool(self.availability.standby_operating_node_ids)
        expected_mode = OperationalMode.SAFE if safe else {
            ActionKind.IMAGING: OperationalMode.IMAGING, ActionKind.DOWNLINK: OperationalMode.DOWNLINK,
            ActionKind.STANDBY: OperationalMode.STANDBY}[self.actual_kind]
        if self.operational_mode is not expected_mode:
            raise ValueError("mode disagrees with the selected physical operation")
        if self.fdir_state is not (FDIRState.NORMAL if self.availability.available else FDIRState.BACKUP):
            raise ValueError("FDIR disagrees with the sampled outcome")
        timestamp = self.critical_energy_since_seconds
        if timestamp is not None and (type(timestamp) is not int or not 0 <= timestamp <= self.start_time_seconds):
            raise ValueError("critical-power timestamp must be an observed prior/start boundary")
        if (timestamp is not None) != (self.availability.essential_unmet_w > 0):
            raise ValueError("critical-power timestamp inconsistent with essential service")
        if self.recovered and self.fdir_state is not FDIRState.NORMAL:
            raise ValueError("recovery requires normal outcome")


@dataclass(frozen=True, slots=True)
class ProtectedStepResult:
    outcome: OperationalOutcome
    step_result: StepResult
    requested_attempt: ImagingStorageEngineAttempt | CoupledDownlinkAttempt | None
    standby_routed_heat: RoutedInternalHeatResult | None

    def __post_init__(self):
        _exact(self.outcome, OperationalOutcome, "outcome")
        self.outcome.__post_init__()
        _exact(self.step_result, StepResult, "step")
        self.step_result.__post_init__()
        if (self.step_result.start_time_seconds, self.step_result.end_time_seconds) != (
                self.outcome.start_time_seconds, self.outcome.end_time_seconds):
            raise ValueError("selected physics and outcome intervals disagree")
        if any(x is None for x in (self.step_result.eps_result, self.step_result.thermal_coupling_result,
                                  self.step_result.battery_degradation_result,
                                  self.step_result.battery_capacity_reconciliation_result)):
            raise ValueError("protected execution requires complete physical evolution")
        if self.outcome.actual_kind is ActionKind.STANDBY and self.requested_attempt is not None:
            raise ValueError("discarded mission proposal must not be reported as executed")
        if self.outcome.actual_kind is ActionKind.STANDBY:
            _exact(self.standby_routed_heat, RoutedInternalHeatResult, "standby heat")
            self.standby_routed_heat.__post_init__()
            if self.step_result.eps_result.battery.unmet_load_w != self.outcome.availability.essential_unmet_w:
                raise ValueError("actual standby service and essential-power evidence disagree")
        else:
            expected = ImagingStorageEngineAttempt if self.outcome.actual_kind is ActionKind.IMAGING else CoupledDownlinkAttempt
            _exact(self.requested_attempt, expected, "selected mission attempt")
            self.requested_attempt.__post_init__()
            if self.requested_attempt.step_result is not self.step_result or self.standby_routed_heat is not None:
                raise ValueError("selected mission must reuse its validated physical proposal")


def _prepare(context, previous, request, policy):
    from .experiment_codec import canonical_copy
    _validate_completed_context(context)
    canonical_copy(context.inputs)
    _exact(previous, ScheduledObservationExecution, "previous execution")
    previous = canonical_copy(previous)
    if (previous.scheduled_start_seconds + previous.candidate.opportunity.imaging_duration_seconds
            > context.simulation_time_seconds):
        raise ValueError("previous acquisition must end by the current boundary")
    _exact(request, ProtectedRequest, "request")
    request = canonical_copy(request)
    policy = validate_policy(policy, context)
    onboard = context.spacecraft_state.onboard
    if (onboard.fdir_state not in (FDIRState.NORMAL, FDIRState.BACKUP)
            or onboard.operational_mode not in (OperationalMode.SAFE, OperationalMode.STANDBY,
                                               OperationalMode.IMAGING, OperationalMode.DOWNLINK)):
        raise ValueError("onboard regime is outside this policy's ownership")
    validate_request_bindings(request, context)
    action, kind = request.action, action_kind(request.action)
    ids = {ActionKind.IMAGING: policy.imaging_node_ids, ActionKind.DOWNLINK: policy.downlink_node_ids,
           ActionKind.STANDBY: policy.standby_node_ids}[kind]
    start_bad = _violations(context, ids)
    reasons = [ProtectionReason.OPERATING_START] if start_bad else []
    standby, standby_step, routed = _standby_proposal(context, request.standby, policy)
    standby_bad = tuple(dict.fromkeys((*_violations(context, policy.standby_node_ids),
                                      *_violations(standby, policy.standby_node_ids))))
    essential_unmet = standby_step.eps_result.battery.unmet_load_w
    candidate, step, attempt = standby, standby_step, None
    end_bad = ()
    if kind is ActionKind.IMAGING:
        if (action.execution.scheduled_start_seconds != context.simulation_time_seconds
                or action.execution.candidate.acquisition_input.imaging_duration_seconds
                != context.inputs.numerical_config.timestep_seconds):
            raise ValueError("protected imaging must equal the current full step")
        if (any(r.record_id == action.record_id for r in context.spacecraft_state.data_storage.stored_records)
                or any(d.record.record_id == action.record_id for d in context.ground_data_delivery_state.completed_deliveries)):
            raise ValueError("imaging record ID already has an acquisition")
        sequence = evaluate_observation_sequence_feasibility(
            context.inputs.spacecraft_configuration.adcs.agile_pointing, previous,
            action.execution.candidate.maneuver_candidate)
        if not sequence.feasible or sequence.candidate_next_start_seconds > action.execution.scheduled_start_seconds:
            reasons.append(ProtectionReason.IMAGING_AUTHORIZATION)
            step = None
        else:
            candidate = checked_checkpoint(context).restore(context.inputs)
            attempt = SimulationEngine().step_imaging_to_storage(candidate, previous, action.execution,
                record_id=action.record_id, environment=action.environment, routing_config=action.routing_config,
                thermal_inputs=action.thermal_inputs, external_heat_sources=action.external_heat_sources,
                solar_degradation_forcing=action.solar_degradation_forcing)
            step = attempt.step_result
            if step is None:
                auth = attempt.authorization_result.imaging_authorization_result
                reasons.append(ProtectionReason.ACTION_POWER if auth.status.value ==
                    "electrical-full-service-not-established" else ProtectionReason.IMAGING_AUTHORIZATION)
    elif kind is ActionKind.DOWNLINK:
        start = context.simulation_time_seconds
        if (action.contact.start_time_seconds != start
                or action.contact.end_time_seconds != start + context.inputs.numerical_config.timestep_seconds):
            raise ValueError("protected contact must equal the current full step")
        if not any(r.record_id == action.record_id for r in context.spacecraft_state.data_storage.stored_records):
            reasons.append(ProtectionReason.DATA_UNAVAILABLE)
            step = None
        else:
            candidate = checked_checkpoint(context).restore(context.inputs)
            attempt = SimulationEngine().step_coupled_downlink(candidate, action.contact,
                record_id=action.record_id, physical_inputs=action.physical_inputs)
            step = attempt.step_result
            if step is None:
                reasons.append(ProtectionReason.ACTION_POWER)
    if step is not None:
        end_bad = _violations(candidate, ids)
        if end_bad:
            reasons.append(ProtectionReason.OPERATING_END)
    if essential_unmet > 0:
        reasons.append(ProtectionReason.ESSENTIAL_POWER)
    if standby_bad:
        reasons.append(ProtectionReason.STANDBY_THERMAL)
    availability = ActionAvailability(kind, tuple(reasons), start_bad, end_bad, standby_bad, essential_unmet)
    if not availability.available or kind is ActionKind.STANDBY:
        candidate, step, attempt = standby, standby_step, None
    return candidate, step, attempt, routed, availability, request


def evaluate_action_availability(context, previous_execution, request, *, policy):
    """Read-only start/end prediction, including explicit fallback feasibility."""
    return _prepare(context, previous_execution, request, policy)[4]


def _apply_protection(candidate, original, availability):
    onboard = candidate.spacecraft_state.onboard
    old = original.spacecraft_state.onboard
    if availability.essential_unmet_w > 0:
        onboard.critical_energy_since_seconds = (old.critical_energy_since_seconds
            if old.critical_energy_since_seconds is not None else original.simulation_time_seconds)
    else:
        onboard.critical_energy_since_seconds = None
    actual = availability.requested_kind if availability.available else ActionKind.STANDBY
    safe = availability.essential_unmet_w > 0 or bool(availability.standby_operating_node_ids)
    onboard.operational_mode = OperationalMode.SAFE if safe else {
        ActionKind.IMAGING: OperationalMode.IMAGING, ActionKind.DOWNLINK: OperationalMode.DOWNLINK,
        ActionKind.STANDBY: OperationalMode.STANDBY}[actual]
    onboard.fdir_state = FDIRState.NORMAL if availability.available else FDIRState.BACKUP
    return actual


def execute_protected_request(context, previous_execution, request, *, policy):
    """Validate selected completed state/result before ONE external commit.

    Missing onboard data is a valid unavailable request here. A bounded script
    additionally validates that its record reference has a preceding producer.
    Existing low-level kernels retain their historical missing-record errors.
    """
    candidate, step, attempt, routed, availability, request = _prepare(
        context, previous_execution, request, policy)
    physical_snapshot = checked_checkpoint(candidate)
    actual = _apply_protection(candidate, context, availability)
    _validate_completed_context(candidate)
    nodes = tuple(n.node_id for n in context.inputs.spacecraft_configuration.thermal.network.nodes)
    onboard = candidate.spacecraft_state.onboard
    outcome = OperationalOutcome(request.action.action_id, context.simulation_time_seconds,
        candidate.simulation_time_seconds, availability, actual,
        _violations(context, nodes, survival=True), _violations(candidate, nodes, survival=True),
        onboard.operational_mode, onboard.fdir_state, onboard.critical_energy_since_seconds,
        context.spacecraft_state.onboard.fdir_state is FDIRState.BACKUP and onboard.fdir_state is FDIRState.NORMAL)
    result = ProtectedStepResult(outcome, step, attempt, routed if actual is ActionKind.STANDBY else None)
    # Checkpoint and engine validators remain the persistent-state owners.
    from .experiment_codec import canonical_content
    expected = replace(physical_snapshot, spacecraft=replace(physical_snapshot.spacecraft,
        operational_mode=outcome.operational_mode, fdir_state=outcome.fdir_state,
        critical_energy_since_seconds=outcome.critical_energy_since_seconds))
    if canonical_content(checked_checkpoint(candidate)) != canonical_content(expected):
        raise ValueError("protection update changed state outside its owned onboard fields")
    SimulationEngine._commit(context, candidate)
    return result


__all__ = ["ProtectionPolicy", "StandbyInputs", "StandbyAction", "ProtectedRequest", "ActionKind",
           "ProtectionReason", "ActionAvailability", "OperationalOutcome", "ProtectedStepResult",
           "evaluate_action_availability", "execute_protected_request"]
