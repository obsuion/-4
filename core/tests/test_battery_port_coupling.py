"""Actual construction transaction checks independent of the kernel formula."""
from copy import deepcopy
from dataclasses import asdict,replace
from fractions import Fraction as Q
from math import ulp
import pytest
from examples.m4_construction_mission_demo import make_inputs
from ops_sim.v5.construction_mission import start_construction_mission
from ops_sim.v5.assembly_attitude_3d import compile_assembly_hardware_3d
from ops_sim.v5.long_mission import _forcing
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.construction_service import ConstructionServicePolicy,ConstructionServiceWork,service_physical_substep,ConstructionServiceDomainRefusal
from ops_sim.v5.battery_port import BatteryPortPolicy,BatteryPortState,BatteryPortWork,BatteryPortDomainError
from ops_sim.v5.battery_port_construction import PortEPSResult,PortConstructionPhysicalResult
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.lifecycle_service import PowerServicePolicy,PowerServiceWork,initial_service_state

def leaf(policy=BatteryPortPolicy(),*,energy=80.,sunlit=False,mode='NORMAL'):
    s=start_construction_mission(make_inputs());s.context.spacecraft_state.battery.energy_wh=energy
    h=compile_assembly_hardware_3d(s.inputs.assembly,s.inputs.capabilities,s.inputs.actuator)
    f,e,*_=_forcing(s,h,Q(130),Q(131),s.attitude.quaternion)
    e=replace(e,sunlit=sunlit,incidence_angle_deg=0.)
    state=BatteryPortState(Q(130),resistance_damage=policy.initial_resistance_damage);work=BatteryPortWork();allocation=ConstructionServiceWork()
    kwargs=dict(compilation=s.construction.compilation,service_policy=ConstructionServicePolicy(),service_mode=mode,
        service_work=allocation,work=s.construction.work,limits=s.construction.inputs.limits,
        start_seconds=Q(130),end_seconds=Q(131),battery_port_policy=policy,battery_port_state=state,battery_port_work=work)
    return s,f,e,state,work,allocation,kwargs

@pytest.mark.parametrize('sunlit',[False,True])
def test_separate_port_carrier_real_node_heat_and_energy_balance(sunlit):
    s,f,e,origin,w,allocation,kwargs=leaf(sunlit=sunlit)
    part,carrier=service_physical_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kwargs)
    assert type(part)is PortConstructionPhysicalResult and type(carrier)is PortEPSResult
    b=carrier.battery;net=s.context.inputs.spacecraft_configuration.thermal.network
    ledgers={n.node_id:n for n in part.thermal_coupling_result.node_heat_ledgers}
    assert ledgers[net.battery_node_id].battery_conversion_heat_w==b.ohmic_heat_wh*3600
    assert ledgers[net.bus_node_id].battery_conversion_heat_w==b.converter_loss_wh*3600
    assert b.ohmic_heat_wh>0 and b.converter_loss_wh>0
    assert abs((b.end_energy_wh-b.start_energy_wh)-((b.charge_input_w-b.discharge_output_w)/3600-b.conversion_loss_wh))<=8*ulp(80.)
    assert origin.selected_steps==0 and part.port_state_after.selected_steps==1
    assert w.returned==allocation.eps_calls_returned and w.ageing_returned==1
    assert part.port_state_after.ohmic_heat_wh==b.ohmic_heat_wh
    assert s.context.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh==b.chemical_throughput_wh

def test_positive_r_changes_actual_energy_and_temperature():
    outputs=[]
    for resistance in (0.,2.):
        s,f,e,_,_,_,kw=leaf(replace(BatteryPortPolicy(),resistance_reference_ohm=resistance))
        part,_=service_physical_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kw)
        outputs.append((s,part))
    a,b=outputs
    assert b[0].context.spacecraft_state.battery.energy_wh<a[0].context.spacecraft_state.battery.energy_wh
    node=a[0].context.inputs.spacecraft_configuration.thermal.network.battery_node_id
    temperature=lambda s:next(n.temperature_k for n in s.context.spacecraft_state.thermal.node_states if n.node_id==node)
    assert temperature(b[0])>temperature(a[0])

@pytest.mark.parametrize('mode',['NORMAL','SAFE','POWER_OFF','RECOVERY'])
def test_current_cutoff_denies_actual_essential_function_with_wh_remaining(mode):
    s,f,e,origin,w,allocation,kw=leaf(replace(BatteryPortPolicy(),maximum_discharge_current_a=.001),mode=mode)
    part,_=service_physical_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kw)
    assert s.context.spacecraft_state.battery.energy_wh>79
    assert not part.service.obc_serviceable and not part.service.communications_serviceable
    assert part.service.essential_unserved_w>0 and allocation.bisection_trials>0
    assert part.port_state_after.selected_steps==1 and w.returned>1
    assert origin.selected_steps==0 and origin.resistance_damage==0

def test_moving_power_loss_has_no_private_commit_and_no_ageing_refund():
    s,f,e,origin,w,_,kw=leaf(replace(BatteryPortPolicy(),maximum_discharge_current_a=.001))
    before=CheckpointState.from_context(s.context).to_dict()
    bus=s.context.inputs.spacecraft_configuration.thermal.network.bus_node_id
    with pytest.raises(ConstructionServiceDomainRefusal,match='UNSUPPORTED_UNPOWERED'):
        service_physical_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,
            **kw,internal_heat_adjustments_w=((bus,-.001),))
    assert CheckpointState.from_context(s.context).to_dict()==before
    assert w.reserved>0 and origin.selected_steps==0 and w.ageing_reserved==0

def test_ageing_domain_failure_is_atomic_and_paid():
    p=replace(BatteryPortPolicy(),initial_resistance_damage=64.,calendar_damage_per_second=1.)
    s,f,e,origin,w,_,kw=leaf(p);before=CheckpointState.from_context(s.context).to_dict()
    with pytest.raises(BatteryPortDomainError,match='ACCUMULATED_DAMAGE'):
        service_physical_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kw)
    assert CheckpointState.from_context(s.context).to_dict()==before and origin.resistance_damage==64
    assert w.ageing_reserved==w.ageing_refused==1


def port_contact_case(*, limited):
    """Leaf negative fixture, not an original-root campaign or restart claim."""
    from ops_sim.v5.construction_mission import advance_construction_mission
    # Identical portable original-fixture builders from construction repairs.
    def partial_inputs():
        value = make_inputs(); actions = value.mission.actions
        actions = (*actions[:3], replace(actions[3], action_id='partial-first', duration_seconds=1),
            replace(actions[3], action_id='partial-second'), actions[4])
        return replace(value, mission=replace(value.mission, actions=actions))
    def prefix(inputs, count):
        state = start_construction_mission(inputs)
        for _ in range(count): state = advance_construction_mission(state)
        return state
    from ops_sim.v5.assembly_attitude_3d import compile_assembly_hardware_3d
    from ops_sim.v5.long_mission import _forcing
    from ops_sim.v5.coupled_downlink import CoupledDownlinkInputs
    from ops_sim.v5.operational_protection import StandbyInputs
    from ops_sim.v5.communications import ServiceableGroundContact
    from ops_sim.v5.ids import GroundContactId, GroundStationId
    from ops_sim.v5.contact_execution import ContactPlan, ConsumedContacts
    from ops_sim.v5.integration_time import IntegrationPolicy
    from ops_sim.v5.lifecycle_service_contact import execute_service_contact_plan
    state = prefix(partial_inputs(), 4)
    assert state.context.simulation_time_seconds == 169
    before_bits = state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits
    hardware = compile_assembly_hardware_3d(state.inputs.assembly, state.inputs.capabilities, state.inputs.actuator)
    forcing, *_ = _forcing(state, hardware, Q(169), Q(170), state.attitude.quaternion)
    # Explicit dark constant-forcing electrical leaf input in BOTH TX and idle.
    # The injected energy is a targeted guard test, not a migrated experiment.
    state.context.spacecraft_state.battery.energy_wh = 80.
    port_policy=replace(BatteryPortPolicy(),maximum_discharge_current_a=.001) if limited else BatteryPortPolicy()
    port_state=BatteryPortState(Q(169));port_work=BatteryPortWork()
    tx = CoupledDownlinkInputs(state.inputs.transmitter, forcing.loads, False, 0.,
        forcing.routing_config, forcing.thermal_inputs, forcing.external_heat_sources, None)
    idle = StandbyInputs(forcing.loads, False, 0., forcing.routing_config,
        forcing.thermal_inputs, forcing.external_heat_sources, None,
        'Explicit synthetic dark leaf regression; no visibility certification.')
    contact = ServiceableGroundContact(GroundContactId('b55-unit-dark'), GroundStationId('station'), 169, 170)
    ids = tuple(record.record_id for record in state.context.spacecraft_state.data_storage.stored_records)
    result = execute_service_contact_plan(state.context, ContactPlan(contact, ids, tx, idle),
        consumed_contacts=ConsumedContacts(()), policy=state.inputs.protection,
        integration=IntegrationPolicy(2), compilation=state.construction.compilation,
        work=state.construction.work, limits=state.construction.inputs.limits,
        service_policy=PowerServicePolicy(), service_state=initial_service_state(Q(169)),
        service_work=PowerServiceWork(), allocation_work=ConstructionServiceWork(),battery_port_policy=port_policy,battery_port_state=port_state,battery_port_work=port_work)
    return state,result,before_bits,port_state,port_work

@pytest.mark.parametrize('limited',[False,True])
def test_actual_contact_new_port_preserves_custody_and_only_selected_history(limited):
    state,result,before,origin,work=port_contact_case(limited=limited)
    assert state.context.spacecraft_state.battery.energy_wh>79
    assert result.outcome.transmitted_bits==(0 if limited else 1000)
    assert state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits==before+result.outcome.transmitted_bits
    assert not state.context.ground_data_delivery_state.completed_deliveries
    assert result.service_state.tx_fully_served is (not limited)
    assert origin.selected_steps==0 and result.battery_port_state.selected_steps==4
    selected=[p for e in result.evaluations if e.selected for p in e.parts]
    assert result.battery_port_state.chemical_throughput_wh==sum(p.eps_result.battery.chemical_throughput_wh for p in selected)
    assert work.ageing_returned>len(selected)
