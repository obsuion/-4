"""Explicit derived epsilon/G network; immutable baseline remains authority."""
from dataclasses import dataclass,replace
from .environment_ageing import guard,saturate,digest

@dataclass(frozen=True,slots=True)
class EffectiveEnvironmentNetwork:
    baseline_identity: str
    policy_identity: str
    state_identity: str
    network: object
    def validate(self,baseline,policy,state):
        guard(policy,state,baseline)
        expected=_derive(policy,state,baseline)
        if self.baseline_identity!=state.baseline_network_identity or self.policy_identity!=policy.identity or self.state_identity!=digest(state) or self.network!=expected:raise ValueError('B61 effective thermal provenance')
        return self.network

def _derive(p,s,baseline):
    nodes={x.node_id:x for x in p.emissivity};links={x.link_id:x for x in p.conductance}
    ns=[];ls=[]
    for n in baseline.nodes:
        x=nodes.get(n.node_id.value)
        value=n.emissivity.value if x is None else saturate(n.emissivity.value,x.asymptote,s.calendar_seconds,s.thermal_exposure_seconds*x.exposure_factor,x.calendar_rate_per_second,x.exposure_rate_per_second)
        ns.append(replace(n,emissivity=replace(n.emissivity,value=value)))
    for l in baseline.links:
        x=links.get(l.link_id.value)
        value=l.conductance_w_per_k.value if x is None else saturate(l.conductance_w_per_k.value,x.asymptote_w_per_k,s.calendar_seconds,s.thermal_exposure_seconds*x.exposure_factor,x.calendar_rate_per_second,x.exposure_rate_per_second)
        ls.append(replace(l,conductance_w_per_k=replace(l.conductance_w_per_k,value=value)))
    return replace(baseline,nodes=tuple(ns),links=tuple(ls))

def effective_network(p,s,baseline):
    guard(p,s,baseline)
    return EffectiveEnvironmentNetwork(s.baseline_network_identity,p.identity,digest(s),_derive(p,s,baseline))

def thermal_network(binding,baseline,prepared_runtime=None):
    if prepared_runtime is not None:return prepared_runtime.validate_environment_binding(binding,baseline)
    if binding is None:return baseline
    # Source-owned tuple includes exact policy/state; never a bare replacement.
    if type(binding)is not tuple or len(binding)!=3:raise TypeError('B61 explicit effective binding')
    effective,policy,state=binding
    if type(effective)is not EffectiveEnvironmentNetwork:raise TypeError('B61 exact effective network owner')
    return effective.validate(baseline,policy,state)

from math import fsum,isfinite
from .construction_physics import (compute_eps_capability,evaluate_construction_eps,ServedPowerLedger,ServedComponentPower,ElectricalLoadComponent,compute_routed_internal_heat,compose_routed_internal_heat_sources,compute_eps_thermal_substep_transition,complete_coupled_physical_substep,ConstructionPhysicalResult)

def construction_environment_substep(candidate,duration,forcing,eps_inputs,policy,solar,*,compilation,work=None,limits=None,
                                  standby=False,internal_heat_adjustments_w=None,environment_binding=None):
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
    thermal=compute_eps_thermal_substep_transition(state.thermal,thermal_network(environment_binding,cfg.thermal.network),forcing.thermal_inputs,
        sources,carrier,duration=duration)
    physical=complete_coupled_physical_substep(candidate,duration,eps_result=carrier,
        thermal_coupling_result=thermal,eps_capability_result=capability,solar_degradation_forcing=solar)
    return ConstructionPhysicalResult(physical,electrical,tuple(received.items()),tuple(wire.items()),tuple(adjustments.items())),carrier
