"""B64 explicit indexed-state boundary and exact selected materialization.

No extension is imported by saved DATA readers. The private typed static
owner is prepared once from already paid construction output. Calls only copy
current dynamic data; failed proposals never publish spacecraft state.
"""
from dataclasses import fields, replace
from fractions import Fraction
from math import isfinite
import importlib

from .construction_coupling import ConstructionCompilation
from .construction_service import (ConstructionServicePolicy, ConstructionServiceWork,
    ConstructionServiceElectricalRefusal, ConstructionServiceDomainRefusal,
    _FIELDS, _ESSENTIAL, _PRIORITY, _loads)
from .battery_port import BatteryPortPolicy, BatteryPortState, BatteryPortWork, BatteryPortTransition
from .power_loads import PowerLoadBreakdown
from .thermal_routing import ElectricalLoadComponent
from .lifecycle_prepared import _Seal, _copy_frozen, _exact_tree

METHOD='B64_TYPED_EXECUTION_V1'
_PORT_FIELDS=('ocv_temperature_v_per_k','reference_temperature_k','resistance_reference_ohm',
    'resistance_temperature_per_k','resistance_low_soc_factor','initial_resistance_damage',
    'maximum_resistance_damage')


def _number(value,name):
    if type(value)is float and isfinite(value):return value
    if type(value)is int and -2**53<=value<=2**53:return value
    raise ValueError('B64_TYPED_UNSUPPORTED_NUMERIC_DOMAIN:'+name)


def _validate_detached(value):
    """Retain constructor admission without normalizing an owned input edge.

    Several frozen input validators replace equal tuples while normalizing
    their own fields. They must run on a detached copy, not the job's sealed
    authority. The validated copy must retain every exact scalar/type/value;
    it is discarded after admission and never becomes a dynamic-state cache.
    """
    original=_exact_tree(value)
    seal=_Seal(value)
    detached=_copy_frozen(value)
    detached.__post_init__()
    if _exact_tree(detached)!=original:
        raise ValueError('B64 changed exact static data during admission')
    seal.guard()


def indexed_static_data(configuration,compilation,service_policy,port_policy,protection,routing,limits):
    """One-time strict topology conversion. No physical evaluation occurs."""
    if type(compilation)is not ConstructionCompilation or type(service_policy)is not ConstructionServicePolicy:
        raise TypeError('B64 exact paid construction/service policy')
    if type(port_policy)is not BatteryPortPolicy:raise TypeError('B64 explicit battery port domain')
    _validate_detached(service_policy);_validate_detached(port_policy)
    _validate_detached(configuration);_validate_detached(routing)
    network=configuration.thermal_network
    _validate_detached(network)
    if compilation.configuration != configuration:raise ValueError('B64 changed paid construction authority')
    if not 1<=len(network.nodes)<=64 or len(network.links)>256 or len(compilation.branches)!=8:
        raise ValueError('B64 indexed topology bounds')
    ids=tuple(n.node_id for n in network.nodes);index={n:i for i,n in enumerate(ids)}
    boundaries={x.node_id:x for x in configuration.thermal_boundaries.node_boundaries}
    if set(boundaries)!=set(ids):raise ValueError('B64 thermal boundary membership')
    byid={b.line_id:b for b in compilation.branches}
    ordered=(byid[configuration.pv_line_id],*(byid[x.line_id] for x in configuration.receiving))
    if len(ordered)!=8 or len({b.line_id for b in ordered})!=8:raise ValueError('B64 exact star branch ownership')
    component_fields={c:c.value.replace('-','_')+'_w' for c in ElectricalLoadComponent}
    if set(component_fields.values())!=set(_FIELDS):raise ValueError('B64 fixed load owner schema')
    receiving_order=tuple(_FIELDS.index(component_fields[x.component]) for x in configuration.receiving)
    route_by={x.component:x for x in routing.routes}
    routes=tuple(route_by[c] for c in ElectricalLoadComponent)
    # ElectricalLoadComponent order and PowerLoadBreakdown field order must be
    # represented explicitly; never assume their enum declaration order.
    route_by_field={component_fields[c]:route_by[c] for c in ElectricalLoadComponent}
    nodes=tuple((n.heat_capacity_j_per_k.value,n.radiating_area_m2.value,n.emissivity.value,
        boundaries[n.node_id].radiative_sink_temperature_k) for n in network.nodes)
    links=tuple((index[x.node_a_id],index[x.node_b_id],x.conductance_w_per_k.value) for x in network.links)
    branches=tuple((b.wire.resistance_ohm,b.wire.current_limit_a,b.wire.max_drop_v,
        b.wire.harness_mass_kg,index[next(n for n in ids if n.value==b.heat_node_id)]) for b in ordered)
    port=tuple(getattr(port_policy,n) for n in _PORT_FIELDS)+(0.,
        port_policy.calendar_damage_per_second,port_policy.cycling_damage_per_chemical_wh,
        port_policy.ageing_temperature_per_k,port_policy.minimum_temperature_k,
        port_policy.maximum_temperature_k,port_policy.minimum_terminal_voltage_v,
        port_policy.maximum_terminal_voltage_v,port_policy.maximum_discharge_current_a,
        port_policy.maximum_charge_current_a,port_policy.maximum_discharge_bus_w,
        port_policy.maximum_charge_bus_w,port_policy.converter_discharge_efficiency,
        port_policy.converter_charge_efficiency,0.,0.)
    # Battery/array/ageing constants are not construction geometry. The wrapper
    # supplies the exact spacecraft configuration while preserving paid wires.
    return dict(nodes=nodes,links=links,branches=branches,receiving_order=receiving_order,
        priority=tuple(_FIELDS.index(n) for n in _PRIORITY),
        routes=tuple((index[route_by_field[n].thermal_node_id],route_by_field[n].retained_heat_fraction.value) for n in _FIELDS),
        ocv=port_policy.ocv_curve,port=port,bus_voltage=configuration.bus_voltage_v,
        pv_voltage=configuration.pv_source_voltage_v,bus_limit=configuration.bus_current_limit_a,
        nominal_energy=1.,nominal_solar=1.,charge_limit=1.,discharge_limit=1.,
        reference_temperature=1.,calendar_rate=0.,cycle_rate=0.,calendar_activation=0.,cycle_activation=0.,
        bisections=service_policy.max_bisections,battery_index=index[network.battery_node_id],
        bus_index=index[network.bus_node_id],metadata=(ids,tuple(x.link_id for x in network.links),ordered),
        static_pins=(configuration,compilation,service_policy,port_policy,protection,routing,limits),port_policy=port_policy)


class TypedStatic:
    """Explicit private authority; construct through prepare_typed_static only."""
    __slots__=('compiled','module','configuration','compilation','service_policy','port_policy',
        'protection','routing','limits','spacecraft','ids','links','ordered','_kernel','_quiet_kernels','_pins','_seal')

    def _check_identity(self):
        pins=(self.compiled,self.module,self.configuration,self.compilation,self.service_policy,
            self.port_policy,self.protection,self.routing,self.limits,self.spacecraft,self.ids,self.links,self.ordered,self._kernel,self._quiet_kernels,self)
        if len(pins)!=len(self._pins) or any(a is not b for a,b in zip(pins,self._pins)):
            raise ValueError('B64 foreign/stale typed static authority')
        if self.module.coupled_cut is not self._kernel:
            raise ValueError('B64 changed compiled numerical callable')
        for name,function in self._quiet_kernels:
            if getattr(self.module,name,None)is not function:
                raise ValueError('B64 changed compiled quiet/materialization callable')

    def guard(self, *, compiled=None):
        self._check_identity()
        self._seal.guard(compiled=compiled)

    def __reduce_ex__(self,protocol):
        raise TypeError('B64 private typed static authority is not serialized DATA')


def prepare_typed_static(spacecraft,compilation,service_policy,port_policy,protection,routing,limits,*,module=None):
    """Prepare independently owned, already paid immutable inputs once per job.

    The job owner supplies owned spacecraft/configuration/compilation records;
    this owner never recompiles wires or resets scientific construction work.
    """
    if module is None:module=importlib.import_module(__package__+'._lifecycle_typed')
    _validate_detached(spacecraft)
    configuration=compilation.configuration
    data=indexed_static_data(configuration,compilation,service_policy,port_policy,protection,routing,limits)
    b=spacecraft.eps.battery;a=spacecraft.degradation.battery_ageing_model
    data.update(nominal_energy=b.nominal_energy_wh.value,
        nominal_solar=spacecraft.eps.solar_array.nominal_generation_w.value,
        charge_limit=b.max_charge_input_power_w.value,discharge_limit=b.max_discharge_output_power_w.value,
        reference_temperature=a.reference_temperature_k.value,
        calendar_rate=a.calendar_damage_rate_per_second_at_reference.value,
        cycle_rate=a.cycling_damage_per_normalized_energy_throughput_at_reference.value,
        calendar_activation=a.calendar_activation_energy_j_per_mol.value,
        cycle_activation=a.cycling_activation_energy_j_per_mol.value)
    for row in data['nodes']:
        for v in row:_number(v,'thermal static scalar')
    for k in ('nominal_energy','nominal_solar','charge_limit','discharge_limit','reference_temperature',
              'calendar_rate','cycle_rate','calendar_activation','cycle_activation'):_number(data[k],k)
    obj=object.__new__(TypedStatic)
    obj.compiled=module.IndexedStatic(data);obj.module=module;obj.spacecraft=spacecraft
    obj.configuration=configuration;obj.compilation=compilation;obj.service_policy=service_policy
    obj.port_policy=port_policy;obj.protection=protection;obj.routing=routing;obj.limits=limits
    obj.ids,obj.links,obj.ordered=data['metadata']
    obj._kernel=module.coupled_cut
    obj._quiet_kernels=tuple((name,getattr(module,name,None)) for name in
        ('integrate_quiet_hold','materialize_world_forcing','materialize_world_forcings'))
    obj._seal=_Seal((spacecraft,configuration,compilation,service_policy,port_policy,protection,routing,limits))
    obj._pins=(obj.compiled,module,configuration,compilation,service_policy,port_policy,protection,routing,limits,spacecraft,obj.ids,obj.links,obj.ordered,obj._kernel,obj._quiet_kernels,obj)
    return obj


def _dynamic(static,candidate,port_state):
    s=candidate.spacecraft_state
    byid={n.node_id:n.temperature_k for n in s.thermal.node_states}
    if set(byid)!=set(static.ids):raise ValueError('B64 exact dynamic node membership')
    if type(port_state)is not BatteryPortState:raise TypeError('B64 exact current port state')
    port_state.__post_init__()
    return static.module.TypedDynamic(static.compiled,dict(energy=s.battery.energy_wh,
        temperatures=tuple(byid[n] for n in static.ids),retention=s.degradation.battery.usable_capacity_retention,
        throughput=s.degradation.battery.cumulative_energy_throughput_wh,solar=s.degradation.solar.generation_retention,
        damage=port_state.resistance_damage,weighted=port_state.temperature_weighted_seconds,
        chemical=port_state.chemical_throughput_wh,ohmic=port_state.ohmic_heat_wh,
        converter=port_state.converter_loss_wh,exact=(port_state.clock_seconds,port_state.selected_steps)))


def _electrical(static,value,duration,solar,loads=None):
    from .design_trade_physics import ElectricalLineResult
    from .construction_physics import BranchOperatingResult
    from .battery_port_construction import PortConstructionEPSResult
    if value is None:return None
    if loads is None:loads=PowerLoadBreakdown(*value['loads'])
    branches=tuple(BranchOperatingResult(b.line_id,'PV' if i==0 else static.configuration.receiving[i-1].component.value,
        ElectricalLineResult(*value['lines'][i]),b.heat_node_id) for i,b in enumerate(static.ordered))
    battery=BatteryPortTransition(duration,*value['port'],value['reason'],value['near'])
    return PortConstructionEPSResult(static.compilation.configuration_digest,solar,loads,branches,
        value['source_generation_w'],value['delivered_generation_w'],loads.total_load_w,value['source_load_w'],
        value['pv_wire_loss_w'],value['receiving_wire_loss_w'],battery,value['fully_served'])


def _service_diagnostic(static,data,duration,source,desired,start,end):
    from .battery_port_construction import PortServiceDiagnostic
    commanded=desired if data['mode']=='NORMAL' else replace(desired,**{n:0. for n in _FIELDS if n not in _ESSENTIAL})
    served=PowerLoadBreakdown(*data['served'])
    # Unchanged served fields retain their original exact type where the old
    # allocation uses replace rather than coercing all fields to binary64.
    served=replace(served,**{n:getattr(commanded,n) for i,n in enumerate(_FIELDS)
                            if data['served_reuse'][i]})
    selected=_electrical(static,data['selected'],duration,source,served)
    full=_electrical(static,data['full'],duration,source,commanded)
    reason=('FULL_COMMANDED_SERVICE' if data['full_service'] else 'ESSENTIAL_SERVICE_UNAVAILABLE'
            if not data['essential_full'] else 'NONESSENTIAL_SERVICE_UNAVAILABLE')
    return PortServiceDiagnostic(data['mode'],start,end,desired,commanded,served,
        desired.total_load_w,commanded.total_load_w,served.total_load_w,data['shed'],data['essential_unserved'],
        data['essential_full'],data['essential_full'],data['radio'],data['full_service'],full,selected,
        data['trials'],data['initial_refusal'],reason)


def _materialize(static,data,candidate,duration,forcing,solar_loss,port_state,start,end,adjustments,desired):
    from .solar import SolarGenerationResult
    from .eps_capability import EPSCapabilityResult,BatteryCapacityReconciliationResult
    from .thermal import ThermalNodeTransition,ThermalLinkHeatFlow,ThermalSubstepResult
    from .thermal_coupling import ThermalNodeHeatLedger,EPSThermalSubstepResult
    from .degradation import BatteryDegradationSubstepTransition,SolarDegradationTransition
    from .battery_port_construction import PortCoupledResult,PortConstructionPhysicalResult
    from .state import BatteryState,ThermalNodeState,BatteryDegradationState,SolarDegradationState
    cfg=static.spacecraft;current=candidate.spacecraft_state
    # Preserve original int/float fields at the public record boundary.
    retention=current.degradation.battery.usable_capacity_retention
    solar_retention=current.degradation.solar.generation_retention
    capacity=EPSCapabilityResult(retention,cfg.eps.battery.nominal_energy_wh.value*retention,
        solar_retention,cfg.eps.solar_array.nominal_generation_w.value*solar_retention)
    source=SolarGenerationResult(capacity.solar_nominal_generation_capability_w,data['source_sunlit'],data['source_incidence'])
    diagnostic=_service_diagnostic(static,data,duration,source,desired,start,end)
    selected=diagnostic.selected_electrical;served=diagnostic.served_loads
    oldtemps={n.node_id:n.temperature_k for n in current.thermal.node_states}
    nodes=[]
    linked={x.node_a_id for x in static.configuration.thermal_network.links}|{x.node_b_id for x in static.configuration.thermal_network.links}
    for i,n in enumerate(static.ids):
        row=data['thermal'][i]
        nodes.append(ThermalNodeTransition(n,oldtemps[n],row[1],0 if n not in linked else row[2],*row[3:]))
    links=tuple(ThermalLinkHeatFlow(l.link_id,l.node_a_id,l.node_b_id,data['flows'][i]) for i,l in enumerate(static.configuration.thermal_network.links))
    thermal_result=ThermalSubstepResult(tuple(nodes),links,selected.battery.dt_seconds,duration)
    ledger=tuple(ThermalNodeHeatLedger(n,*data['ledgers'][i]) for i,n in enumerate(static.ids))
    thermal=EPSThermalSubstepResult(ledger,thermal_result)
    dg=list(data['degradation']);dg[0]=retention;dg[2]=current.degradation.battery.cumulative_energy_throughput_wh
    degradation=BatteryDegradationSubstepTransition(*dg,selected.battery.dt_seconds,duration)
    sr=None if solar_loss is None else SolarDegradationTransition(solar_retention,solar_loss.retention_loss,data['solar'][2])
    reconciliation=BatteryCapacityReconciliationResult(*data['reconciliation'])
    p=data['next_port'];b=selected.battery
    next_port=replace(port_state,clock_seconds=end,resistance_damage=p['damage'],temperature_weighted_seconds=p['weighted'],
        chemical_throughput_wh=p['chemical'],ohmic_heat_wh=p['ohmic'],converter_loss_wh=p['converter'],
        selected_steps=port_state.selected_steps+1,last_voltage_v=b.terminal_voltage_v,last_current_a=b.current_a,
        last_resistance_ohm=b.resistance_ohm,last_ocv_v=b.ocv_v,last_support_start_seconds=start)
    # Original constructors validate the complete selected result before any
    # caller state is changed. They perform no new physical transition.
    BatteryState(reconciliation.authoritative_end_energy_wh)
    for node in nodes:ThermalNodeState(node.node_id,node.end_temperature_k)
    BatteryDegradationState(degradation.end_usable_capacity_retention,degradation.end_cumulative_energy_throughput_wh)
    if sr is not None:SolarDegradationState(sr.end_generation_retention)
    carrier=selected.integration_carrier()
    physical=PortCoupledResult(carrier,thermal,degradation,sr,capacity,reconciliation)
    route_by_field={r.component.value.replace('-','_')+'_w':r for r in static.routing.routes}
    received=[]
    for i,n in enumerate(static.ids):
        routes=tuple((field,r) for field,r in route_by_field.items() if r.thermal_node_id==n)
        # An untouched node starts at exact int 0. When every retained product
        # is integral, valid receiving powers are <= the port's 1e12 domain,
        # so the seven-term integral sum remains exactly representable here.
        integral=all(type(getattr(served,field))is int and type(r.retained_heat_fraction.value)is int
                     for field,r in routes)
        value=int(data['routed'][i]) if integral else data['routed'][i]
        received.append((n,value))
    received=tuple(received)
    wire=tuple((n,data['wire'][i]) for i,n in enumerate(static.ids))
    part=PortConstructionPhysicalResult(physical,selected,received,wire,tuple(adjustments.items()),diagnostic,next_port)
    current.battery.energy_wh=reconciliation.authoritative_end_energy_wh
    byid={n.node_id:n.end_temperature_k for n in nodes}
    for n in current.thermal.node_states:n.temperature_k=byid[n.node_id]
    current.degradation.battery.usable_capacity_retention=degradation.end_usable_capacity_retention
    current.degradation.battery.cumulative_energy_throughput_wh=degradation.end_cumulative_energy_throughput_wh
    if sr is not None:current.degradation.solar.generation_retention=sr.end_generation_retention
    return part,carrier


def service_port_substep(candidate,duration,forcing,eps_inputs,policy,solar,*,compiled_static,
        compilation,service_policy,service_mode,service_work,work=None,limits=None,standby=False,
        internal_heat_adjustments_w=None,start_seconds=None,end_seconds=None,battery_port_policy=None,
        battery_port_state=None,battery_port_work=None,environment_binding=None,prepared_runtime=None):
    from .integration_time import RationalSeconds,checked_duration
    from .environment_thermal import thermal_network
    from .battery_port_construction import PortServiceFailureDiagnostic
    if type(compiled_static)is not TypedStatic:raise TypeError('B64 exact private typed static authority')
    st=compiled_static
    st._check_identity()
    if (compilation is not st.compilation or service_policy is not st.service_policy or
            battery_port_policy is not st.port_policy or policy is not st.protection or limits is not st.limits):
        raise ValueError('B64 foreign coupled static/work authority')
    if type(service_work)is not ConstructionServiceWork or type(battery_port_work)is not BatteryPortWork:
        raise TypeError('B64 exact scientific work owners')
    if type(duration)is not RationalSeconds:raise TypeError('B64 exact RationalSeconds cut required')
    checked_duration(duration)
    start=Fraction(candidate.simulation_time_seconds if start_seconds is None else start_seconds)
    end=start+duration.fraction if end_seconds is None else Fraction(end_seconds)
    if end-start!=duration.fraction:raise ValueError('exact inner service interval must match duration')
    if battery_port_state.clock_seconds!=start:raise ValueError('BATTERY_PORT_HISTORY_SUPPORT')
    if candidate.inputs.spacecraft_configuration is not st.spacecraft:
        # Owned job adapter may provide a shell over equivalent independently
        # admitted records, but cannot substitute a different configuration.
        if candidate.inputs.spacecraft_configuration!=st.spacecraft:raise ValueError('B64 foreign spacecraft numerical configuration')
    if forcing.routing_config!=st.routing or forcing.thermal_inputs!=st.configuration.thermal_boundaries:
        raise ValueError('B64 stale routing/thermal forcing')
    desired=_loads(eps_inputs.load_breakdown)
    if type(forcing.sunlit)is not bool:raise TypeError('B64 exact illumination')
    effective=thermal_network(environment_binding,st.configuration.thermal_network,prepared_runtime=prepared_runtime)
    if tuple(n.node_id for n in effective.nodes)!=st.ids or tuple(l.link_id for l in effective.links)!=st.links:
        raise ValueError('B64 changed effective thermal topology')
    adjustments={} if internal_heat_adjustments_w is None else dict(internal_heat_adjustments_w)
    if len(adjustments)!=(0 if internal_heat_adjustments_w is None else len(internal_heat_adjustments_w)) or not set(adjustments)<=set(st.ids):
        raise ValueError('unique known mechanical heat destination required')
    sources={n.node_id:n for n in forcing.external_heat_sources.node_sources}
    temperatures={n.node_id:n.temperature_k for n in candidate.spacecraft_state.thermal.node_states}
    if set(sources)!=set(st.ids) or set(temperatures)!=set(st.ids):raise ValueError('B64 complete source/state membership')
    sink_by={b.node_id:b.radiative_sink_temperature_k for b in st.configuration.thermal_boundaries.node_boundaries}
    boundary=dict(start=start,end=end,duration=duration,mode=service_mode,loads=tuple(getattr(desired,n) for n in _FIELDS),
        essential_indices=tuple(_FIELDS.index(n) for n in _ESSENTIAL),communications_index=_FIELDS.index('communications_w'),
        incidence=eps_inputs.incidence_angle_deg,sunlit=eps_inputs.sunlit,
        emissivity=tuple(n.emissivity.value for n in effective.nodes),conductance=tuple(l.conductance_w_per_k.value for l in effective.links),
        adjustments=tuple(adjustments.get(n,0.) for n in st.ids),
        external_heat=tuple((sources[n].absorbed_solar_w,sources[n].absorbed_albedo_w,sources[n].absorbed_earth_ir_w) for n in st.ids),
        sink_values=tuple(sink_by[n] for n in st.ids),
        start_temperature_values=tuple(temperatures[n] for n in st.ids),solar_loss=None if solar is None else solar.retention_loss)
    dynamic=_dynamic(st,candidate,battery_port_state)
    try:data=st._kernel(st.compiled,dynamic,boundary,service_work,battery_port_work,work,limits)
    except st.module.CoupledElectricalRefusal as error:
        from .solar import SolarGenerationResult
        source=SolarGenerationResult(st.spacecraft.eps.solar_array.nominal_generation_w.value*candidate.spacecraft_state.degradation.solar.generation_retention,eps_inputs.sunlit,eps_inputs.incidence_angle_deg)
        commanded=desired if service_mode=='NORMAL' else replace(desired,**{n:0. for n in _FIELDS if n not in _ESSENTIAL})
        full=_electrical(st,error.full,duration,source,commanded)
        diagnostic=PortServiceFailureDiagnostic(service_mode,start,end,desired,commanded,full,str(error),error.trials)
        raise ConstructionServiceElectricalRefusal(str(error),diagnostic) from error
    except st.module.CoupledDomainRefusal as error:
        from .solar import SolarGenerationResult
        source=SolarGenerationResult(st.spacecraft.eps.solar_array.nominal_generation_w.value*candidate.spacecraft_state.degradation.solar.generation_retention,eps_inputs.sunlit,eps_inputs.incidence_angle_deg)
        diagnostic=_service_diagnostic(st,error.data,duration,source,desired,start,end)
        raise ConstructionServiceDomainRefusal(str(error),diagnostic) from error
    data['mode']=service_mode
    result=_materialize(st,data,candidate,duration,forcing,solar,battery_port_state,start,end,adjustments,desired)
    service_work.selected_coupled_calls+=1
    return result


def _materialize_quiet_parts(static,physical,candidate,world_plan,selected):
    """One retained/failure publication boundary over saved numeric proposals."""
    from .integration_time import RationalSeconds
    from .degradation import SolarDegradationForcingInput
    from .long_mission import MissionPhysicalCut
    from .environment_ageing import EnvironmentAgeingState,digest
    from .environment_lifecycle import EnvironmentSolarTransition,EnvironmentCoupledResult
    if type(static)is not TypedStatic:raise TypeError('B64 exact selected static materializer')
    static._check_identity()
    port=physical.battery_port_state;cuts=[];last=physical.last_service_diagnostic
    environment=physical.environment_ageing_state
    forcings=static.module.materialize_world_forcings(world_plan,tuple(item[2]for item in selected))
    for item,(forcing,eps) in zip(selected,forcings):
        left,right,world_data,data,step_service,step_work,port_steps=item
        duration=RationalSeconds.from_fraction(right-left)
        legacy_solar=(None if physical.inputs.environment_ageing_policy is not None or data['solar'][1]is None
                      else SolarDegradationForcingInput(data['solar'][1]))
        part,carrier=_materialize(static,data,candidate,duration,forcing,legacy_solar,port,left,right,{},eps.load_breakdown)
        if physical.inputs.environment_ageing_policy is not None:
            before=EnvironmentAgeingState(**data['environment_before'])
            after=EnvironmentAgeingState(**data['environment_after'])
            transition=EnvironmentSolarTransition(*data['solar'],physical.inputs.environment_ageing_policy.identity,
                digest(before),digest(after))
            base=part.physical
            replacement=EnvironmentCoupledResult(base.eps_result,base.thermal_coupling_result,
                base.battery_degradation_result,transition,base.eps_capability_result,base.battery_capacity_reconciliation_result)
            part=replace(part,physical=replacement)
            candidate.spacecraft_state.degradation.solar.generation_retention=data['solar'][2]
            environment=after
        port=part.port_state_after
        if port.selected_steps!=port_steps:raise ValueError('B64 selected native port frontier differs')
        last=part.service
        cuts.append(MissionPhysicalCut(left,right,world_data['supports'],world_data['incidence'],
            world_data['camera'],world_data['panel'],0.,0.,0.,0.,part,physical.attitude.quaternion,None,Fraction(0),Fraction(0)))
    return tuple(cuts),port,environment,last


def materialize_quiet_result(static,physical,candidate,hardware,pending,world_plan,selected,
        service_data,service_work_data,environment_data,controller):
    """Publish ONLY retained native cuts as the existing complete records.

    Saved forcing DATA is materialized without another world/orbit/Sun query;
    the private native full/half trial states are never generic graph decoded.
    """
    from .lifecycle_service import PowerServiceState,PowerServiceWork
    from .lifecycle_physics import _ServiceCandidate
    from .substepped_execution import _aggregate
    from .environment_ageing import EnvironmentAgeingState
    cuts,port,environment,last=_materialize_quiet_parts(static,physical,candidate,world_plan,selected)
    service=PowerServiceState(**service_data);service_work=PowerServiceWork(**service_work_data)
    if environment_data is not None:
        final_environment=EnvironmentAgeingState(**environment_data)
        if environment!=final_environment:raise ValueError('B64 selected environment frontier differs')
        environment=final_environment
    private=_ServiceCandidate(candidate,service,service_work,last,port,environment)
    return private,cuts,_aggregate(tuple(c.part for c in cuts)),controller


def materialize_quiet_failure_part(static,physical,origin,hardware,pending,world_plan,proposals):
    """Original rich endpoint refusal, with no reevaluation or caller mutation.

    Full/half ancestry is immutable compact arithmetic evidence. Rendering its
    private prefix reuses those results; it grants no fees, queries, coverage
    or continuation authority and is discarded after constructing the refusal.
    """
    from .lifecycle_physics import _quiet_clone_context
    private=_quiet_clone_context(origin)
    cuts,port,environment,last=_materialize_quiet_parts(static,physical,private,world_plan,proposals)
    if not cuts:raise ValueError('B64 missing paid endpoint refusal proposal')
    return cuts[-1].part


def materialize_quiet_service_refusal(static,world_plan,world_data,data,left,right,mode,solar_retention,*,domain):
    """Restore the original electrical/domain diagnostic from saved numbers."""
    from .integration_time import RationalSeconds
    from .solar import SolarGenerationResult
    from .battery_port_construction import PortServiceFailureDiagnostic
    static._check_identity()
    forcing,eps=static.module.materialize_world_forcing(world_plan,world_data)
    duration=RationalSeconds.from_fraction(right-left)
    desired=eps.load_breakdown
    source=SolarGenerationResult(static.spacecraft.eps.solar_array.nominal_generation_w.value*solar_retention,
        eps.sunlit,eps.incidence_angle_deg)
    if domain:return _service_diagnostic(static,data,duration,source,desired,left,right)
    commanded=desired if mode=='NORMAL' else replace(desired,**{n:0. for n in _FIELDS if n not in _ESSENTIAL})
    full=_electrical(static,data.full,duration,source,commanded)
    return PortServiceFailureDiagnostic(mode,left,right,desired,commanded,full,str(data),data.trials)


def typed_quiet_piece(physical,candidate,hardware,start,end,pending,*,compiled_static,world_plan=None):
    """Explicit closed compiled quiet entry; accepts no model callback."""
    if type(compiled_static)is not TypedStatic:raise TypeError('B64 exact typed quiet authority')
    compiled_static._check_identity()
    return compiled_static.module.integrate_quiet_hold(physical,candidate,hardware,Fraction(start),Fraction(end),pending,
        compiled_static=compiled_static,world_plan=world_plan)
