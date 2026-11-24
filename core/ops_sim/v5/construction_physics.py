"""Actual B45 per-cut electrical/thermal composition of unchanged pure owners."""
from dataclasses import dataclass, replace, fields
from math import fsum, isfinite
from .construction_coupling import ConstructionCompilation
from .design_trade_physics import constant_power_load, generated_power_line, ElectricalLimitError
from .eps_capability import compute_eps_capability
from .solar import compute_solar_generation
from .eps import compute_battery_substep_transition
from .eps_system import EPSSubstepResult
from .engine import complete_coupled_physical_substep
from .thermal_coupling import compute_eps_thermal_substep_transition
from .thermal_routing import (ElectricalLoadComponent, ServedPowerLedger, ServedComponentPower,
    compute_routed_internal_heat, compose_routed_internal_heat_sources)
from .ids import ThermalNodeId


@dataclass(frozen=True, slots=True)
class BranchOperatingResult:
    line_id: str
    component: str
    electrical: object
    heat_node_id: str


@dataclass(frozen=True, slots=True)
class ConstructionEPSResult:
    compilation_digest: str
    source_solar: object
    receiving_loads: object
    branches: tuple[BranchOperatingResult,...]
    source_generation_w: float
    delivered_generation_w: float
    receiving_load_w: float
    source_load_w: float
    pv_wire_loss_w: float
    receiving_wire_loss_w: float
    battery: object
    fully_served: bool
    regulator_conversion_loss_w: float = 0.
    def integration_carrier(self):
        # Typed legacy thermal/ageing carrier ONLY. Raw solar geometry stays
        # intact. Battery owns actual delivered-PV/source-demand transition.
        # This is not a compute_eps_substep_transition output or bus-load grant.
        return EPSSubstepResult(self.source_solar,self.receiving_loads,self.battery)


@dataclass(frozen=True, slots=True)
class ConstructionPhysicalResult:
    physical: object
    electrical: ConstructionEPSResult
    receiving_retained_heat_w: tuple
    wire_heat_w: tuple
    mechanical_heat_adjustments_w: tuple
    @property
    def eps_result(self):return self.physical.eps_result
    @property
    def thermal_coupling_result(self):return self.physical.thermal_coupling_result
    @property
    def battery_degradation_result(self):return self.physical.battery_degradation_result
    @property
    def solar_degradation_result(self):return self.physical.solar_degradation_result
    @property
    def battery_capacity_reconciliation_result(self):return self.physical.battery_capacity_reconciliation_result
    @property
    def eps_capability_result(self):return self.physical.eps_capability_result


def evaluate_construction_eps(state,config,inputs,duration,compilation,capability,*,work=None,limits=None):
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
    battery=compute_battery_substep_transition(state,config.battery,generation_w=generated.delivered_power_w,
        load_w=source_load,duration=duration,usable_capacity_wh=capability.battery_usable_capacity_wh)
    return ConstructionEPSResult(compilation.configuration_digest,source,loads,tuple(results),
        source.generation_w,generated.delivered_power_w,loads.total_load_w,source_load,
        generated.loss_w,fsum(r.loss_w for r in load_results),battery,battery.unmet_load_w==0)


def construction_physical_substep(candidate,duration,forcing,eps_inputs,policy,solar,*,compilation,work=None,limits=None,
                                  standby=False,internal_heat_adjustments_w=None):
    """No load shedding: even idle needs full service. Failure publishes no heat.

    Received component power routes once; PV/load cable heat once; battery
    conversion is added only by accepted thermal coupling; ideal regulator zero.
    Mechanical storage adjustment is applied only to the declared ADCS bus node.
    """
    cfg=candidate.inputs.spacecraft_configuration;state=candidate.spacecraft_state
    if cfg.thermal.network!=compilation.configuration.thermal_network or forcing.thermal_inputs!=compilation.configuration.thermal_boundaries:
        raise ValueError('stale thermal construction binding')
    capability=compute_eps_capability(cfg.eps,state.degradation)
    electrical=evaluate_construction_eps(state.battery,cfg.eps,eps_inputs,duration,compilation,capability,work=work,limits=limits)
    if not electrical.fully_served:return None,electrical.integration_carrier()
    served=ServedPowerLedger(tuple(ServedComponentPower(component,
        getattr(eps_inputs.load_breakdown,component.value.replace('-','_')+'_w'),
        getattr(eps_inputs.load_breakdown,component.value.replace('-','_')+'_w')) for component in ElectricalLoadComponent))
    # Existing pure served-power route, without falsely equating receiving
    # component watts with wire-inclusive EPS source watts.
    routed=compute_routed_internal_heat(eps_inputs.load_breakdown,served,forcing.routing_config,cfg.thermal.network)
    sources=compose_routed_internal_heat_sources(routed,forcing.external_heat_sources)
    wire={n.node_id:fsum(b.electrical.loss_w for b in electrical.branches if b.heat_node_id==n.node_id.value) for n in cfg.thermal.network.nodes}
    adjustments={} if internal_heat_adjustments_w is None else dict(internal_heat_adjustments_w)
    if len(adjustments)!=(0 if internal_heat_adjustments_w is None else len(internal_heat_adjustments_w)) or not set(adjustments)<=set(wire):raise ValueError('unique known mechanical heat destination required')
    received={n.node_id:n.applied_heat_into_w for n in routed.node_internal_heat_w}
    changed=[]
    for n in sources.node_sources:
        value=n.internal_dissipation_w+wire[n.node_id]+adjustments.get(n.node_id,0.)
        if type(value) not in (int,float) or not isfinite(value) or value<0:raise ValueError('finite nonnegative combined heat required')
        changed.append(replace(n,internal_dissipation_w=value))
    sources=replace(sources,node_sources=tuple(changed))
    carrier=electrical.integration_carrier()
    thermal=compute_eps_thermal_substep_transition(state.thermal,cfg.thermal.network,forcing.thermal_inputs,
        sources,carrier,duration=duration)
    physical=complete_coupled_physical_substep(candidate,duration,eps_result=carrier,
        thermal_coupling_result=thermal,eps_capability_result=capability,solar_degradation_forcing=solar)
    return ConstructionPhysicalResult(physical,electrical,tuple(received.items()),tuple(wire.items()),tuple(adjustments.items())),carrier


def cut_balance(part):
    """Transition-derived W/Wh accounting, before capacity reconciliation."""
    e=part.electrical;b=e.battery
    return dict(source_generation_w=e.source_generation_w,delivered_generation_w=e.delivered_generation_w,
        receiving_load_w=e.receiving_load_w,source_load_w=e.source_load_w,
        pv_wire_loss_w=e.pv_wire_loss_w,receiving_wire_loss_w=e.receiving_wire_loss_w,
        actual_served_source_w=b.served_load_w,actual_served_receiving_w=e.receiving_load_w if e.fully_served else None,
        charge_input_w=b.charge_input_w,discharge_output_w=b.discharge_output_w,
        stored_delta_wh=b.end_energy_wh-b.start_energy_wh,conversion_loss_wh=b.conversion_loss_wh,
        curtailed_generation_w=b.curtailed_generation_w,unmet_load_w=b.unmet_load_w,
        regulator_conversion_loss_w=e.regulator_conversion_loss_w,
        duration_seconds=b.dt_seconds,capacity_reconciliation_loss_wh=part.battery_capacity_reconciliation_result.unavailable_energy_wh)
