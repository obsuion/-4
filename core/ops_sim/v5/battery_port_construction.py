"""B58 separate Rint transaction. No fabricated legacy fixed-eta carrier.
All proposals pay work; only selected private cuts publish physical history.
"""
from .lifecycle_fast import admit_policy

from dataclasses import dataclass, fields, replace
from fractions import Fraction
from math import fsum, isfinite
from .construction_coupling import ConstructionCompilation
from .construction_physics import BranchOperatingResult, ConstructionPhysicalResult
from .construction_service import (ConstructionServicePolicy, ConstructionServiceWork,
    ConstructionServiceDomainRefusal, ConstructionServiceElectricalRefusal,
    _FIELDS, _ESSENTIAL, _PRIORITY, _MODES, _MAX_TRIALS, _loads, _nonnegative, _service_interval)
from .design_trade_physics import (ElectricalLimitError, ElectricalLineResult, constant_power_load, generated_power_line)
from .solar import SolarGenerationResult, compute_solar_generation
from .eps_capability import compute_eps_capability, compute_battery_capacity_reconciliation
from .integration_time import RationalSeconds, checked_duration
from .power_loads import PowerLoadBreakdown
from .thermal_routing import (ElectricalLoadComponent, ServedComponentPower,
    ServedPowerLedger, compose_routed_internal_heat_sources, compute_routed_internal_heat)
from .thermal_coupling import ThermalNodeHeatLedger, EPSThermalSubstepResult
from .thermal import (ThermalAppliedHeatInputs, ThermalNodeAppliedHeatInput, compute_thermal_substep_transition)
from .degradation import (BatteryThroughputIncrement, BatteryDegradationSubstepInput,
    compute_battery_degradation_substep, compute_explicit_solar_degradation_transition)
from .state import BatteryState, ThermalNodeState, BatteryDegradationState, SolarDegradationState
from .battery_port import (BatteryPortPolicy, BatteryPortState, BatteryPortWork,
    BatteryPortTransition, battery_port_transition, advance_port_state)

@dataclass(frozen=True, slots=True)
class PortEPSResult:
    solar: object
    loads: object
    battery: BatteryPortTransition

@dataclass(frozen=True, slots=True)
class PortConstructionEPSResult:
    compilation_digest: str
    source_solar: object
    receiving_loads: object
    branches: tuple
    source_generation_w: float
    delivered_generation_w: float
    receiving_load_w: float
    source_load_w: float
    pv_wire_loss_w: float
    receiving_wire_loss_w: float
    battery: BatteryPortTransition
    fully_served: bool
    regulator_conversion_loss_w: float = 0.
    def integration_carrier(self):return PortEPSResult(self.source_solar,self.receiving_loads,self.battery)

@dataclass(frozen=True, slots=True)
class PortCoupledResult:
    eps_result: PortEPSResult
    thermal_coupling_result: object
    battery_degradation_result: object
    solar_degradation_result: object
    eps_capability_result: object
    battery_capacity_reconciliation_result: object

@dataclass(frozen=True, slots=True)
class PortConstructionPhysicalResult(ConstructionPhysicalResult):
    service: object
    port_state_after: BatteryPortState

@dataclass(frozen=True, slots=True)
class PortServiceDiagnostic:
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
    full_demand_trial: PortConstructionEPSResult | None
    selected_electrical: PortConstructionEPSResult
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
class PortServiceFailureDiagnostic:
    service_mode: str
    start_seconds: Fraction
    end_seconds: Fraction
    desired_loads: PowerLoadBreakdown
    commanded_loads: PowerLoadBreakdown
    returned_full_demand_trial: PortConstructionEPSResult | None
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


def _validate_eps_carrier(value, loads, interval):
    """Returned-data algebra only: no solar, wire, EPS or thermal evaluation.

    The two existing line multiplication orders are intentionally distinct:
    published wire heat is I*(I*R); source/load arithmetic used (I*I)*R.
    Recompute each recorded identity in its original order, without tolerance
    or pretending those binary64 expressions are exactly associative.
    """
    if type(value) is not PortConstructionEPSResult or type(value.source_solar) is not SolarGenerationResult:
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
    if type(value.battery) is not BatteryPortTransition:
        raise TypeError('exact returned battery substep carrier required')
    value.battery.__post_init__()
    duration = value.battery.duration
    exact_duration = (duration.fraction if type(duration) is RationalSeconds else
        Fraction(duration.numerator_seconds, 1 << duration.subdivision_level))
    if (exact_duration != interval or value.battery.generation_w != value.delivered_generation_w or
            value.battery.load_w != value.source_load_w or type(value.fully_served) is not bool or
            value.fully_served != (value.battery.unmet_load_w == 0)):
        raise ValueError('returned EPS/battery duration and source-power identity mismatch')


def evaluate_port_eps(state,config,inputs,duration,compilation,capability,*,port_policy,port_state,port_work,work=None,limits=None):
    if type(compilation) is not ConstructionCompilation:raise TypeError('compiled construction required')
    c=compilation.configuration;loads=inputs.load_breakdown
    if work is not None:work.reserve_lines(8,limits)
    def line_call(function,*args):
        try:value=function(*args)
        except ElectricalLimitError:
            if work is not None:work.line_calls_refused+=1
            raise
        except BaseException:
            if work is not None:work.line_work_unknown+=1
            raise
        if work is not None:work.line_calls_returned+=1
        return value
    loads.__post_init__()
    if any(type(getattr(loads,f.name)) not in (int,float) for f in fields(loads)):raise TypeError('built-in finite power fields required')
    source=compute_solar_generation(config.solar_array,sunlit=inputs.sunlit,
        incidence_angle_deg=inputs.incidence_angle_deg,nominal_generation_capability_w=capability.solar_nominal_generation_capability_w)
    byid={b.line_id:b for b in compilation.branches};results=[]
    pv=byid[c.pv_line_id]
    generated=line_call(generated_power_line,pv.wire,c.pv_source_voltage_v,source.generation_w)
    results.append(BranchOperatingResult(pv.line_id,'PV',generated,pv.heat_node_id))
    load_results=[]
    for binding in c.receiving:
        branch=byid[binding.line_id]
        demand=getattr(loads,binding.component.value.replace('-','_')+'_w')
        op=line_call(constant_power_load,branch.wire,c.bus_voltage_v,demand)
        results.append(BranchOperatingResult(branch.line_id,binding.component.value,op,branch.heat_node_id))
        load_results.append(op)
    current=fsum(r.current_a for r in load_results)
    if not isfinite(current) or current>c.bus_current_limit_a:raise ElectricalLimitError('aggregate regulated bus current limit exceeded')
    source_load=fsum(r.source_power_w for r in load_results)
    network=compilation.configuration.thermal_network
    temperature=next(n.temperature_k for n in state.thermal.node_states if n.node_id==network.battery_node_id)
    battery=battery_port_transition(port_policy,port_state,energy_wh=state.battery.energy_wh,
        usable_wh=capability.battery_usable_capacity_wh,temperature_k=temperature,
        generation_w=generated.delivered_power_w,load_w=source_load,duration=duration,
        charge_bus_limit_w=config.battery.max_charge_input_power_w.value,
        discharge_bus_limit_w=config.battery.max_discharge_output_power_w.value,work=port_work)
    return PortConstructionEPSResult(compilation.configuration_digest,source,loads,tuple(results),
        source.generation_w,generated.delivered_power_w,loads.total_load_w,source_load,
        generated.loss_w,fsum(r.loss_w for r in load_results),battery,battery.unmet_load_w==0)


def service_port_substep(candidate, duration, forcing, eps_inputs, policy,
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
            result = evaluate_port_eps(state, cfg.eps,
                replace(eps_inputs, load_breakdown=loads), duration,
                compilation, capability, port_policy=battery_port_policy, port_state=battery_port_state, port_work=battery_port_work, work=work, limits=limits)
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
            failure = PortServiceFailureDiagnostic(service_mode, start, end,
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
    diagnostic = PortServiceDiagnostic(service_mode, start, end,
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
    thermal, physical, next_port = complete_port_cut(candidate, duration, forcing,
        sources, carrier, capability, solar, battery_port_policy, battery_port_state,
        battery_port_work, start, end,environment_binding=environment_binding,prepared_runtime=prepared_runtime)
    service_work.selected_coupled_calls += 1
    received = tuple((n.node_id, n.applied_heat_into_w) for n in routed.node_internal_heat_w)
    return PortConstructionPhysicalResult(physical, selected, received,
        tuple(wire.items()), tuple(adjustments.items()), diagnostic, next_port), carrier

def complete_port_cut(candidate,duration,forcing,sources,carrier,capability,solar,port_policy,port_state,port_work,start,end,*,environment_binding=None,prepared_runtime=None):
    """Pure accepted thermal/capacity leaves, then atomic private publication.
    Per-node battery_conversion_heat_w denotes explicit irreversible port
    heat: Ohmic at BATTERY, residual converter at BUS, each exactly once.
    """
    cfg=candidate.inputs.spacecraft_configuration;state=candidate.spacecraft_state
    network=cfg.thermal.network;b=carrier.battery;dt=checked_duration(duration)
    if type(port_policy)is not BatteryPortPolicy or type(port_state)is not BatteryPortState:raise TypeError('bound port policy/history')
    ledgers=[]
    for node in sources.node_sources:
        irreversible=b.ohmic_heat_wh*3600/dt if node.node_id==network.battery_node_id else 0.
        if node.node_id==network.bus_node_id:irreversible+=b.converter_loss_wh*3600/dt
        values=(node.internal_dissipation_w,node.absorbed_solar_w,node.absorbed_albedo_w,node.absorbed_earth_ir_w,irreversible)
        total=0
        for value in values:total+=value
        ledgers.append(ThermalNodeHeatLedger(node.node_id,*values,total))
    from .environment_thermal import thermal_network
    effective=thermal_network(environment_binding,network,prepared_runtime)
    result=compute_thermal_substep_transition(state.thermal,effective,forcing.thermal_inputs,
        ThermalAppliedHeatInputs(tuple(ThermalNodeAppliedHeatInput(n.node_id,n.total_applied_heat_w) for n in ledgers)),duration=duration)
    thermal=EPSThermalSubstepResult(tuple(ledgers),result);byid={n.node_id:n for n in result.node_transitions}
    initial=next(n.temperature_k for n in state.thermal.node_states if n.node_id==network.battery_node_id)
    representative=initial+(byid[network.battery_node_id].end_temperature_k-initial)/2
    charge=b.chemical_charge_w*dt/3600;discharge=b.chemical_discharge_w*dt/3600
    throughput=BatteryThroughputIncrement(charge,discharge,charge+discharge)
    degradation=compute_battery_degradation_substep(state.degradation.battery,cfg.eps.battery,
        cfg.degradation.battery_ageing_model,BatteryDegradationSubstepInput(representative,throughput,dt,duration))
    solar_result=None if solar is None else compute_explicit_solar_degradation_transition(state.degradation.solar,solar)
    reconciliation=compute_battery_capacity_reconciliation(b.end_energy_wh,cfg.eps.battery,degradation.end_usable_capacity_retention)
    next_port=advance_port_state(port_policy,port_state,b,start=start,end=end,representative_temperature_k=representative,work=port_work)
    BatteryState(reconciliation.authoritative_end_energy_wh)
    for n in state.thermal.node_states:ThermalNodeState(n.node_id,byid[n.node_id].end_temperature_k)
    BatteryDegradationState(degradation.end_usable_capacity_retention,degradation.end_cumulative_energy_throughput_wh)
    if solar_result is not None:SolarDegradationState(solar_result.end_generation_retention)
    physical=PortCoupledResult(carrier,thermal,degradation,solar_result,capability,reconciliation)
    state.battery.energy_wh=reconciliation.authoritative_end_energy_wh
    for n in state.thermal.node_states:n.temperature_k=byid[n.node_id].end_temperature_k
    state.degradation.battery.usable_capacity_retention=degradation.end_usable_capacity_retention
    state.degradation.battery.cumulative_energy_throughput_wh=degradation.end_cumulative_energy_throughput_wh
    if solar_result is not None:state.degradation.solar.generation_retention=solar_result.end_generation_retention
    return thermal,physical,next_port
