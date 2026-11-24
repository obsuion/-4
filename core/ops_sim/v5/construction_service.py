"""Additive B55 receiving-side power allocation; not a lifecycle policy.

ASSUMED reduction: an ideal regulated star, no voltage/brownout dynamics.
BASE_BUS plus OBC is the positive authored essential demand.  An authored
zero OBC load means that housekeeping already includes its electrical draw.
SAFE/OFF/RECOVERY shed the other five branches; they do not reduce that
essential demand.  Partial receiving watts never grant essential functions.

Every private electrical proposal is charged, without advancing state.  Only
the selected feasible proposal reaches the existing thermal/ageing completion
owner.  This owner neither changes attitude nor grants mission completion.
"""
from .lifecycle_fast import admit_policy

from dataclasses import dataclass, fields, replace
from fractions import Fraction
from math import fsum, isfinite

from .construction_coupling import ConstructionCompilation
from .construction_physics import (ConstructionEPSResult,
    ConstructionPhysicalResult, BranchOperatingResult, evaluate_construction_eps)
from .design_trade_physics import ElectricalLimitError, ElectricalLineResult
from .eps import BatterySubstepTransition
from .solar import SolarGenerationResult
from .engine import complete_coupled_physical_substep
from .eps_capability import compute_eps_capability
from .integration_time import RationalSeconds, checked_duration
from .power_loads import PowerLoadBreakdown
from .thermal_coupling import compute_eps_thermal_substep_transition
from .thermal_routing import (ElectricalLoadComponent, ServedComponentPower,
    ServedPowerLedger, compose_routed_internal_heat_sources,
    compute_routed_internal_heat)


SERVICE_METHOD = 'B55_PRIORITY_RECEIVING_POWER_V1'
_MODES = ('NORMAL', 'SAFE', 'POWER_OFF', 'RECOVERY')
_FIELDS = tuple(f.name for f in fields(PowerLoadBreakdown))
_ESSENTIAL = ('base_bus_w', 'obc_w')
_PRIORITY = ('base_bus_w', 'obc_w', 'thermal_control_w', 'adcs_w',
             'communications_w', 'payload_w', 'propulsion_w')
_MAX_TRIALS = 2 + 7 * 33
_MAX_CUMULATIVE_TRIALS = 2**40


@dataclass(frozen=True, slots=True)
class ConstructionServicePolicy:
    """Finite deterministic receiving-W bisection; not an accuracy claim."""
    method: str = SERVICE_METHOD
    max_bisections: int = 32

    def __post_init__(self):
        if type(self.method) is not str or self.method != SERVICE_METHOD:
            raise ValueError('unsupported construction service method')
        if type(self.max_bisections) is not int or self.max_bisections != 32:
            raise ValueError('fixed 32-bisection policy required')


@dataclass(slots=True)
class ConstructionServiceWork:
    """Electrical-proposal entries, including refused/unreturned work.

    Each proposal invokes the unchanged construction EPS owner, which pays
    its own eight line reservations.  These counts are separate from physical
    coupled substeps and do not claim that a refused line reached the battery.
    """
    eps_calls_reserved: int = 0
    eps_calls_returned: int = 0
    eps_calls_refused: int = 0
    eps_work_unknown: int = 0
    allocation_trials: int = 0
    bisection_trials: int = 0
    selected_coupled_calls: int = 0

    def validate(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 0 <= value <= _MAX_CUMULATIVE_TRIALS:
                raise ValueError('bounded nonnegative construction service work')
        if self.eps_calls_returned + self.eps_calls_refused + self.eps_work_unknown > self.eps_calls_reserved:
            raise ValueError('service work exceeds reservations')
        if self.allocation_trials != self.eps_calls_reserved or self.bisection_trials > self.allocation_trials:
            raise ValueError('inconsistent service proposal accounting')
        if self.selected_coupled_calls > self.eps_calls_returned:
            raise ValueError('coupled service work lacks a returned proposal')

    def reserve(self, *, bisection=False):
        self.validate()
        if type(bisection) is not bool:
            raise TypeError('exact service bisection flag required')
        if self.eps_calls_reserved == _MAX_CUMULATIVE_TRIALS:
            raise ValueError('CONSTRUCTION_SERVICE_TRIAL_QUOTA')
        self.eps_calls_reserved += 1
        self.allocation_trials += 1
        self.bisection_trials += int(bisection)


@dataclass(frozen=True, slots=True)
class ConstructionServiceDiagnostic:
    """Immutable returned proposal, never by itself committed coverage."""
    service_mode: str
    start_seconds: Fraction
    end_seconds: Fraction
    desired_loads: PowerLoadBreakdown
    commanded_loads: PowerLoadBreakdown
    served_loads: PowerLoadBreakdown
    desired_load_w: float
    commanded_load_w: float
    served_load_w: float
    shed_load_w: float
    essential_unserved_w: float
    essential_fully_served: bool
    obc_serviceable: bool
    communications_serviceable: bool
    full_commanded_service: bool
    full_demand_trial: ConstructionEPSResult | None
    selected_electrical: ConstructionEPSResult
    trial_count: int
    initial_wire_refusal: str | None
    reason: str
    scope: str = 'PRIVATE_SELECTED_CANDIDATE_NOT_COMMITTED_COVERAGE'

    def __post_init__(self):
        _service_interval(self.service_mode, self.start_seconds, self.end_seconds)
        for value in (self.desired_loads, self.commanded_loads, self.served_loads): _loads(value)
        for name in _FIELDS:
            if not 0 <= getattr(self.served_loads, name) <= getattr(self.commanded_loads, name) <= getattr(self.desired_loads, name):
                raise ValueError('ordered desired/commanded/served component powers required')
            if self.service_mode != 'NORMAL' and name not in _ESSENTIAL and getattr(self.commanded_loads, name) != 0:
                raise ValueError('degraded service must shed declared nonessential branches')
        if fsum(getattr(self.commanded_loads, name) for name in _ESSENTIAL) <= 0:
            raise ValueError('positive authored essential demand required')
        for name in ('desired_load_w', 'commanded_load_w', 'served_load_w', 'shed_load_w', 'essential_unserved_w'):
            _nonnegative(getattr(self, name), name)
        expected = (self.desired_loads.total_load_w, self.commanded_loads.total_load_w,
            self.served_loads.total_load_w,
            fsum(getattr(self.desired_loads, name)-getattr(self.commanded_loads, name) for name in _FIELDS),
            fsum(getattr(self.commanded_loads, name)-getattr(self.served_loads, name) for name in _ESSENTIAL))
        if (self.desired_load_w, self.commanded_load_w, self.served_load_w,
                self.shed_load_w, self.essential_unserved_w) != expected:
            raise ValueError('service aggregate differs from its exact returned component projection')
        essential = all(getattr(self.commanded_loads, name) == getattr(self.served_loads, name) for name in _ESSENTIAL)
        full = all(getattr(self.commanded_loads, name) == getattr(self.served_loads, name) for name in _FIELDS)
        radio = self.service_mode == 'NORMAL' and essential and self.commanded_loads.communications_w == self.served_loads.communications_w
        flags = (self.essential_fully_served, self.obc_serviceable,
                 self.communications_serviceable, self.full_commanded_service)
        if any(type(value) is not bool for value in flags) or flags != (essential, essential, radio, full):
            raise ValueError('service functional flags disagree with actual component completeness')
        _validate_eps_carrier(self.selected_electrical, self.served_loads, self.end_seconds-self.start_seconds)
        if not self.selected_electrical.fully_served:
            raise ValueError('selected allocation requires fully supplied allocated source power')
        if self.full_demand_trial is not None:
            _validate_eps_carrier(self.full_demand_trial, self.commanded_loads, self.end_seconds-self.start_seconds)
            if (self.full_demand_trial.compilation_digest != self.selected_electrical.compilation_digest or
                    self.full_demand_trial.source_solar != self.selected_electrical.source_solar):
                raise ValueError('private/selected electrical proposals changed authority/forcing')
        if self.initial_wire_refusal is not None and (type(self.initial_wire_refusal) is not str or not 1 <= len(self.initial_wire_refusal) <= 512):
            raise ValueError('bounded original electrical refusal text required')
        if (self.full_demand_trial is None) != (self.initial_wire_refusal is not None):
            raise ValueError('full-demand proposal return/refusal identity mismatch')
        if type(self.trial_count) is not int or not 1 <= self.trial_count <= _MAX_TRIALS:
            raise ValueError('bounded paid service trial count required')
        reason = ('FULL_COMMANDED_SERVICE' if full else 'ESSENTIAL_SERVICE_UNAVAILABLE'
                  if not essential else 'NONESSENTIAL_SERVICE_UNAVAILABLE')
        if type(self.reason) is not str or self.reason != reason:
            raise ValueError('service reason differs from returned completeness')
        if type(self.scope) is not str or self.scope != 'PRIVATE_SELECTED_CANDIDATE_NOT_COMMITTED_COVERAGE':
            raise ValueError('explicit private selected-candidate scope required')


@dataclass(frozen=True, slots=True)
class ConstructionServicePhysicalResult(ConstructionPhysicalResult):
    service: ConstructionServiceDiagnostic


@dataclass(frozen=True, slots=True)
class ConstructionServiceFailureDiagnostic:
    service_mode: str
    start_seconds: Fraction
    end_seconds: Fraction
    desired_loads: PowerLoadBreakdown
    commanded_loads: PowerLoadBreakdown
    returned_full_demand_trial: ConstructionEPSResult | None
    reason: str
    trial_count: int
    scope: str = 'PAID_PRIVATE_REFUSAL_NO_SELECTED_PHYSICAL_TRANSITION'

    def __post_init__(self):
        _service_interval(self.service_mode, self.start_seconds, self.end_seconds)
        _loads(self.desired_loads); _loads(self.commanded_loads)
        if any(getattr(self.commanded_loads, name) > getattr(self.desired_loads, name) for name in _FIELDS):
            raise ValueError('failure commanded power exceeds authored desired demand')
        if self.service_mode != 'NORMAL' and any(getattr(self.commanded_loads, name) != 0
                for name in _FIELDS if name not in _ESSENTIAL):
            raise ValueError('failure degraded demand must preserve declared shedding')
        if fsum(getattr(self.commanded_loads, name) for name in _ESSENTIAL) <= 0:
            raise ValueError('failure requires positive authored essential demand')
        if self.returned_full_demand_trial is not None:
            _validate_eps_carrier(self.returned_full_demand_trial, self.commanded_loads,
                                  self.end_seconds-self.start_seconds)
        if type(self.reason) is not str or not 1 <= len(self.reason) <= 512:
            raise ValueError('bounded original failure reason required')
        if type(self.trial_count) is not int or not 1 <= self.trial_count <= _MAX_TRIALS:
            raise ValueError('bounded failure trial count required')
        if type(self.scope) is not str or self.scope != 'PAID_PRIVATE_REFUSAL_NO_SELECTED_PHYSICAL_TRANSITION':
            raise ValueError('explicit private refusal scope required')


class ConstructionServiceElectricalRefusal(ElectricalLimitError):
    def __init__(self, reason, diagnostic):
        super().__init__(reason)
        self.diagnostic = diagnostic


class ConstructionServiceDomainRefusal(ValueError):
    def __init__(self, reason, diagnostic):
        super().__init__(reason)
        self.diagnostic = diagnostic


def _loads(value):
    if type(value) is not PowerLoadBreakdown:
        raise TypeError('exact PowerLoadBreakdown required')
    for name in _FIELDS:
        power = getattr(value, name)
        _nonnegative(power, 'component W')
    return replace(value)


def _nonnegative(value, name):
    try: valid = type(value) in (int, float) and isfinite(value) and value >= 0
    except OverflowError: valid = False
    if not valid: raise ValueError('finite built-in nonnegative '+name+' required')


def _service_interval(mode, start, end):
    if type(mode) is not str or mode not in _MODES:
        raise ValueError('known construction service mode required')
    if (type(start) is not Fraction or type(end) is not Fraction or not 0 <= start < end or
            max(start.numerator.bit_length(), start.denominator.bit_length(),
                end.numerator.bit_length(), end.denominator.bit_length()) > 4096):
        raise ValueError('exact bounded advancing service interval required')


def _validate_eps_carrier(value, loads, interval):
    """Returned-data algebra only: no solar, wire, EPS or thermal evaluation.

    The two existing line multiplication orders are intentionally distinct:
    published wire heat is I*(I*R); source/load arithmetic used (I*I)*R.
    Recompute each recorded identity in its original order, without tolerance
    or pretending those binary64 expressions are exactly associative.
    """
    if type(value) is not ConstructionEPSResult or type(value.source_solar) is not SolarGenerationResult:
        raise TypeError('exact returned construction EPS carrier required')
    value.source_solar.__post_init__(); _loads(value.receiving_loads)
    if value.receiving_loads != loads:
        raise ValueError('electrical carrier/component load identity mismatch')
    if (type(value.compilation_digest) is not str or len(value.compilation_digest) != 64 or
            any(c not in '0123456789abcdef' for c in value.compilation_digest)):
        raise ValueError('bound construction digest required')
    for name in ('source_generation_w', 'delivered_generation_w', 'receiving_load_w',
                 'source_load_w', 'pv_wire_loss_w', 'receiving_wire_loss_w', 'regulator_conversion_loss_w'):
        _nonnegative(getattr(value, name), name)
    if type(value.branches) is not tuple or len(value.branches) != 8:
        raise ValueError('exact PV plus seven receiving branches required')
    by_component = {}; line_ids = set()
    for branch in value.branches:
        if type(branch) is not BranchOperatingResult or type(branch.electrical) is not ElectricalLineResult:
            raise TypeError('exact returned branch operating result required')
        if (type(branch.component) is not str or branch.component in by_component or
                type(branch.line_id) is not str or not branch.line_id or branch.line_id in line_ids or
                type(branch.heat_node_id) is not str or not branch.heat_node_id):
            raise ValueError('unique named returned construction branches required')
        operation = branch.electrical
        for field in fields(operation): _nonnegative(getattr(operation, field.name), field.name)
        if (operation.voltage_drop_v != operation.current_a*operation.resistance_ohm or
                operation.loss_w != operation.current_a*operation.voltage_drop_v or operation.load_voltage_v <= 0):
            raise ValueError('returned branch wire heat/drop identity mismatch')
        wire_product = operation.current_a*operation.current_a*operation.resistance_ohm
        if branch.component == 'PV':
            if operation.delivered_power_w != operation.source_power_w-wire_product:
                raise ValueError('returned PV receiving/source arithmetic mismatch')
        elif operation.source_power_w != operation.delivered_power_w+wire_product:
            raise ValueError('returned receiving/source arithmetic mismatch')
        by_component[branch.component] = branch; line_ids.add(branch.line_id)
    if set(by_component) != {'PV', *(component.value for component in ElectricalLoadComponent)}:
        raise ValueError('complete returned branch component ownership required')
    pv = by_component['PV'].electrical
    receiving = tuple(by_component[component.value].electrical for component in ElectricalLoadComponent)
    if any(by_component[component.value].electrical.delivered_power_w !=
           getattr(loads, component.value.replace('-', '_')+'_w') for component in ElectricalLoadComponent):
        raise ValueError('returned receiving branch power differs from allocated component W')
    if (value.source_generation_w != pv.source_power_w or value.delivered_generation_w != pv.delivered_power_w or
            value.pv_wire_loss_w != pv.loss_w or value.receiving_wire_loss_w != fsum(item.loss_w for item in receiving) or
            value.source_load_w != fsum(item.source_power_w for item in receiving) or
            value.receiving_load_w != loads.total_load_w or value.regulator_conversion_loss_w != 0):
        raise ValueError('returned construction aggregate/source/wire identity mismatch')
    if type(value.battery) is not BatterySubstepTransition:
        raise TypeError('exact returned battery substep carrier required')
    value.battery.__post_init__()
    duration = value.battery.duration
    exact_duration = (duration.fraction if type(duration) is RationalSeconds else
        Fraction(duration.numerator_seconds, 1 << duration.subdivision_level))
    if (exact_duration != interval or value.battery.generation_w != value.delivered_generation_w or
            value.battery.load_w != value.source_load_w or type(value.fully_served) is not bool or
            value.fully_served != (value.battery.unmet_load_w == 0)):
        raise ValueError('returned EPS/battery duration and source-power identity mismatch')


def service_physical_substep(candidate, duration, forcing, eps_inputs, policy,
        solar, *, compilation, service_policy, service_mode, service_work,
        work=None, limits=None, standby=False, internal_heat_adjustments_w=None,
        start_seconds=None, end_seconds=None, battery_port_policy=None, battery_port_state=None, battery_port_work=None,environment_binding=None,prepared_runtime=None):
    """Commit one selected private physical proposal, including OFF evolution.

    The caller owns atomic publication, operating/survival domain decisions,
    mode hysteresis, action eligibility, clock and attitude.  Full feasible
    NORMAL operation follows the unchanged electrical and coupled primitives.
    In a deficit, branch priority and bisection are applied to RECEIVING W;
    each proposal recomputes actual nonlinear line current/loss and battery
    conversion.  The greatest tested feasible lower point is retained.  Zero
    representable service is an explicit unavailable result, not a function
    grant.  No trial thermal state or trial heat is published.
    """
    if battery_port_policy is not None:
        from .battery_port_construction import service_port_substep
        return service_port_substep(candidate,duration,forcing,eps_inputs,policy,solar,
            compilation=compilation,service_policy=service_policy,service_mode=service_mode,
            service_work=service_work,work=work,limits=limits,standby=standby,
            internal_heat_adjustments_w=internal_heat_adjustments_w,start_seconds=start_seconds,
            end_seconds=end_seconds,battery_port_policy=battery_port_policy,
            battery_port_state=battery_port_state,battery_port_work=battery_port_work,environment_binding=environment_binding,prepared_runtime=prepared_runtime)
    if type(compilation) is not ConstructionCompilation:
        raise TypeError('compiled construction required')
    if type(service_policy) is not ConstructionServicePolicy:
        raise TypeError('exact ConstructionServicePolicy required')
    admit_policy(service_policy)
    if type(service_work) is not ConstructionServiceWork:
        raise TypeError('exact ConstructionServiceWork required')
    service_work.validate()
    if type(service_mode) is not str or service_mode not in _MODES:
        raise ValueError('known construction service mode required')
    seconds = checked_duration(duration)
    start = Fraction(candidate.simulation_time_seconds if start_seconds is None else start_seconds)
    exact_duration = (duration.fraction if type(duration) is RationalSeconds else
                      Fraction(duration.numerator_seconds, 1 << duration.subdivision_level))
    end = start + exact_duration if end_seconds is None else Fraction(end_seconds)
    if end <= start or end-start != exact_duration:
        raise ValueError('exact inner service interval must match duration')
    cfg = candidate.inputs.spacecraft_configuration
    state = candidate.spacecraft_state
    if (cfg.thermal.network != compilation.configuration.thermal_network or
            forcing.thermal_inputs != compilation.configuration.thermal_boundaries):
        raise ValueError('stale thermal construction binding')
    desired = _loads(eps_inputs.load_breakdown)
    if fsum(getattr(desired, name) for name in _ESSENTIAL) <= 0:
        raise ValueError('positive authored essential demand required')
    commanded = desired if service_mode == 'NORMAL' else replace(desired,
        **{name: 0. for name in _FIELDS if name not in _ESSENTIAL})
    capability = compute_eps_capability(cfg.eps, state.degradation)
    entry_trials = service_work.allocation_trials

    def trial(loads, *, bisect=False):
        if service_work.allocation_trials-entry_trials >= _MAX_TRIALS:
            raise ValueError('CONSTRUCTION_SERVICE_LOCAL_TRIAL_QUOTA')
        service_work.reserve(bisection=bisect)
        try:
            result = evaluate_construction_eps(state.battery, cfg.eps,
                replace(eps_inputs, load_breakdown=loads), duration,
                compilation, capability, work=work, limits=limits)
        except ElectricalLimitError:
            service_work.eps_calls_refused += 1
            raise
        except BaseException:
            service_work.eps_work_unknown += 1
            raise
        service_work.eps_calls_returned += 1
        return result

    initial_wire_refusal = None
    try:
        full = trial(commanded)
    except ElectricalLimitError as error:
        full = None
        initial_wire_refusal = str(error)
    if full is not None and full.fully_served:
        selected = full
        served = commanded
    else:
        # A zero load proposal still evaluates current-attitude PV, PV cable
        # heat and battery charging.  It can itself refuse an invalid PV line.
        served = PowerLoadBreakdown(*(0. for _ in _FIELDS))
        try:
            selected = trial(served)
        except ElectricalLimitError as error:
            failure = ConstructionServiceFailureDiagnostic(service_mode, start, end,
                desired, commanded, full, str(error), service_work.allocation_trials-entry_trials)
            raise ConstructionServiceElectricalRefusal(str(error), failure) from error
        if not selected.fully_served:
            raise ValueError('zero receiving load failed EPS admission')
        available = not (selected.delivered_generation_w == 0 and state.battery.energy_wh == 0)
        # Bisection probes are a FIXED 32-level receiving-W grid.  Its smallest
        # positive tested power for a positive component is requested/2**32.
        # Source W is at least receiving W on every admitted resistive branch.
        # If the returned full-demand battery proposal cannot supply even the
        # smallest such probe, all positive grid points are proved infeasible.
        # Retain the zero-allocation proposal AND its small positive energy;
        # never snap energy to zero or spend an unrouted numerical residue.
        quanta = tuple(getattr(commanded, name)/(2**service_policy.max_bisections)
                       for name in _FIELDS if getattr(commanded, name) > 0)
        below_grid = (full is not None and quanta and min(quanta) > 0 and
                      full.battery.served_load_w < min(quanta))
        if below_grid: available = False
        if available:
            for name in _PRIORITY:
                requested = getattr(commanded, name)
                if requested == 0:
                    continue
                try:
                    attempt = trial(replace(served, **{name: requested}))
                except ElectricalLimitError:
                    attempt = None
                if attempt is not None and attempt.fully_served:
                    selected = attempt
                    served = replace(served, **{name: requested})
                    continue
                low, high = 0., requested
                best = getattr(served, name)
                for _ in range(service_policy.max_bisections):
                    midpoint = low + (high-low)/2
                    if midpoint == low or midpoint == high:
                        break
                    try:
                        attempt = trial(replace(served, **{name: midpoint}), bisect=True)
                    except ElectricalLimitError:
                        attempt = None
                    if attempt is not None and attempt.fully_served:
                        low = midpoint
                        best = midpoint
                        selected = attempt
                    else:
                        high = midpoint
                served = replace(served, **{name: best})

    essential_unserved = fsum(getattr(commanded, n)-getattr(served, n) for n in _ESSENTIAL)
    essential_full = all(getattr(commanded, n) == getattr(served, n) for n in _ESSENTIAL)
    full_service = all(getattr(commanded, n) == getattr(served, n) for n in _FIELDS)
    radio = (service_mode == 'NORMAL' and essential_full and
             commanded.communications_w == served.communications_w)
    reason = ('FULL_COMMANDED_SERVICE' if full_service else
              'ESSENTIAL_SERVICE_UNAVAILABLE' if not essential_full else 'NONESSENTIAL_SERVICE_UNAVAILABLE')
    diagnostic = ConstructionServiceDiagnostic(service_mode, start, end,
        desired, commanded, served, desired.total_load_w, commanded.total_load_w,
        served.total_load_w, fsum(getattr(desired, n)-getattr(commanded, n) for n in _FIELDS),
        essential_unserved, essential_full, essential_full, radio, full_service,
        full, selected, service_work.allocation_trials-entry_trials,
        initial_wire_refusal, reason)
    ledger = ServedPowerLedger(tuple(ServedComponentPower(component,
        getattr(commanded, component.value.replace('-', '_')+'_w'),
        getattr(served, component.value.replace('-', '_')+'_w')) for component in ElectricalLoadComponent))
    routed = compute_routed_internal_heat(commanded, ledger, forcing.routing_config, cfg.thermal.network)
    sources = compose_routed_internal_heat_sources(routed, forcing.external_heat_sources)
    wire = {n.node_id: fsum(b.electrical.loss_w for b in selected.branches
        if b.heat_node_id == n.node_id.value) for n in cfg.thermal.network.nodes}
    adjustments = {} if internal_heat_adjustments_w is None else dict(internal_heat_adjustments_w)
    if (len(adjustments) != (0 if internal_heat_adjustments_w is None else len(internal_heat_adjustments_w)) or
            not set(adjustments) <= set(wire)):
        raise ValueError('unique known mechanical heat destination required')
    if any(value != 0 for value in adjustments.values()) and (
            service_mode != 'NORMAL' or not diagnostic.full_commanded_service):
        raise ConstructionServiceDomainRefusal(
            'UNSUPPORTED_UNPOWERED_MECHANICAL_TRANSITION', diagnostic)
    changed = []
    for node in sources.node_sources:
        value = node.internal_dissipation_w+wire[node.node_id]+adjustments.get(node.node_id, 0.)
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError('finite nonnegative combined heat required')
        changed.append(replace(node, internal_dissipation_w=value))
    sources = replace(sources, node_sources=tuple(changed))
    carrier = selected.integration_carrier()
    from .environment_thermal import thermal_network
    thermal = compute_eps_thermal_substep_transition(state.thermal,
        thermal_network(environment_binding,cfg.thermal.network), forcing.thermal_inputs, sources, carrier, duration=duration)
    physical = complete_coupled_physical_substep(candidate, duration,
        eps_result=carrier, thermal_coupling_result=thermal,
        eps_capability_result=capability, solar_degradation_forcing=solar)
    service_work.selected_coupled_calls += 1
    received = tuple((n.node_id, n.applied_heat_into_w) for n in routed.node_internal_heat_w)
    return ConstructionServicePhysicalResult(physical, selected, received,
        tuple(wire.items()), tuple(adjustments.items()), diagnostic), carrier
