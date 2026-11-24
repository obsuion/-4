from dataclasses import replace,asdict
from math import isclose,ulp,fsum
import pytest
from examples.m4_construction_mission_demo import make_inputs,actual_parts
from ops_sim.v5.construction_mission import start_construction_mission,advance_construction_mission,continue_construction_mission
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.construction_physics import cut_balance


def test_actual_connected_600s_with_nonzero_losses_and_credit():
    s=continue_construction_mission(start_construction_mission(make_inputs()))
    assert s.context.simulation_time_seconds==728 and len(s.acquisitions)==1
    assert len(s.context.ground_data_delivery_state.completed_deliveries)==1 and len(s.assessment()[0].credited_record_ids)==1
    assert all(o.status=='completed' for o in s.outcomes)
    parts=list(actual_parts(s));assert parts and any(p.electrical.receiving_wire_loss_w>0 for _,p in parts)
    assert any(identity['kind']=='CONTACT_TX' for identity,_ in parts)
    for _,p in parts:
        e=p.electrical;b=e.battery;seconds=b.dt_seconds
        assert e.fully_served and b.unmet_load_w==0
        assert abs(e.source_generation_w-e.delivered_generation_w-e.pv_wire_loss_w)<=4*ulp(max(e.source_generation_w,1.))
        assert abs(e.source_load_w-e.receiving_load_w-e.receiving_wire_loss_w)<=8*ulp(max(e.source_load_w,1.))
        expected=(b.charge_input_w-b.discharge_output_w)*seconds/3600-b.conversion_loss_wh
        assert abs((b.end_energy_wh-b.start_energy_wh)-expected)<=8*ulp(max(b.start_energy_wh,1.))
        assert abs(fsum(v for _,v in p.wire_heat_w)-e.pv_wire_loss_w-e.receiving_wire_loss_w)<=8*ulp(max(e.source_load_w,e.source_generation_w,1.))
        for ledger in p.thermal_coupling_result.node_heat_ledgers:
            expected=dict(p.receiving_retained_heat_w)[ledger.node_id]+dict(p.wire_heat_w)[ledger.node_id]+dict(p.mechanical_heat_adjustments_w).get(ledger.node_id,0.)
            assert abs(ledger.internal_dissipation_w-expected)<=4*ulp(max(expected,1.))
    assert s.construction.work.line_calls_returned==s.construction.work.line_calls_reserved


def test_electrical_weakness_refuses_capture_and_repair_keeps_demands():
    weak=make_inputs('weakness');fixed=make_inputs('repair')
    assert weak.mission==fixed.mission
    s=start_construction_mission(weak);s=advance_construction_mission(s)
    before=CheckpointState.from_context(s.context).to_dict();paid=s.construction.work.line_calls_reserved
    result=advance_construction_mission(s)
    assert result.outcomes[-1].status=='refused' and 'CONSTRUCTION_ELECTRICAL' in result.outcomes[-1].reason
    assert CheckpointState.from_context(s.context).to_dict()==before and not result.acquisitions
    assert result.construction.work.line_calls_refused>0 and result.construction.work.line_calls_reserved>paid
    complete=continue_construction_mission(start_construction_mission(fixed))
    assert len(complete.context.ground_data_delivery_state.completed_deliveries)==1


def test_late_actual_thermal_refusal_is_atomic_paid(monkeypatch):
    import ops_sim.v5.long_mission as owner
    s=start_construction_mission(make_inputs());before=CheckpointState.from_context(s.context).to_dict()
    original=owner._violations;calls=[]
    def later(context,required):
        calls.append(context)
        if len(calls)==2:return (context.inputs.spacecraft_configuration.thermal.network.bus_node_id,)
        return original(context,required)
    monkeypatch.setattr(owner,'_violations',later)
    result=advance_construction_mission(s)
    assert result.outcomes[-1].reason=='OPERATING_TEMPERATURE_AT_ENDPOINT'
    assert CheckpointState.from_context(s.context).to_dict()==before and not result.acquisitions
    assert s.runtime_work.physical_completed_calls>0 and s.construction.work.line_calls_returned>0


def test_mutated_context_config_rejects_before_work():
    s=start_construction_mission(make_inputs());cfg=s.context.inputs.spacecraft_configuration
    s.context.inputs=replace(s.context.inputs,spacecraft_configuration=replace(cfg,eps=replace(cfg.eps,battery=replace(cfg.eps.battery,
        max_discharge_output_power_w=replace(cfg.eps.battery.max_discharge_output_power_w,value=1.)))))
    before=asdict(s.runtime_work)
    with pytest.raises(ValueError,match='MUTATED_CONTEXT'):advance_construction_mission(s)
    assert asdict(s.runtime_work)==before


def test_stale_compilation_and_replayed_action():
    s=start_construction_mission(make_inputs())
    with pytest.raises(ValueError,match='duplicate/foreign'):advance_construction_mission(s,expected_action_id='foreign')
    s.construction=replace(s.construction,compilation=replace(s.construction.compilation,conductor_mass_kg=0.))
    with pytest.raises(ValueError,match='stale cached'):advance_construction_mission(s)


def test_real_operating_limit_refuses_private_physical_endpoint():
    inputs=make_inputs();mission=inputs.mission;cfg=mission.simulation_inputs.spacecraft_configuration
    network=cfg.thermal.network
    nodes=tuple(replace(n,operating_max_temperature_k=replace(n.operating_max_temperature_k,value=300.0001))
        if n.node_id==network.bus_node_id else n for n in network.nodes)
    network=replace(network,nodes=nodes)
    cfg=replace(cfg,thermal=replace(cfg.thermal,network=network))
    mission=replace(mission,simulation_inputs=replace(mission.simulation_inputs,spacecraft_configuration=cfg))
    inputs=replace(inputs,mission=mission,configuration=replace(inputs.configuration,thermal_network=network))
    state=start_construction_mission(inputs);before=CheckpointState.from_context(state.context).to_dict()
    result=advance_construction_mission(state)
    assert result.outcomes[-1].reason=='OPERATING_TEMPERATURE_AT_ENDPOINT'
    assert result.outcomes[-1].failure_diagnostic[0]=='PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED'
    assert CheckpointState.from_context(state.context).to_dict()==before
    assert not result.acquisitions and state.runtime_work.physical_completed_calls>0


def test_unserved_demand_never_publishes_wire_or_receiving_heat():
    from ops_sim.v5.construction_physics import construction_physical_substep
    from ops_sim.v5.long_mission import _forcing
    from ops_sim.v5.assembly_attitude_3d import compile_assembly_hardware_3d
    from ops_sim.v5.integration_time import RationalSeconds
    from fractions import Fraction as Q
    state=start_construction_mission(make_inputs())
    state.context.spacecraft_state.battery.energy_wh=0.
    hardware=compile_assembly_hardware_3d(state.inputs.assembly,state.inputs.capabilities,state.inputs.actuator)
    # Remain within one authored profile cell; 128..129 crosses its known cut.
    forcing,eps,*_=_forcing(state,hardware,Q(130),Q(131),state.attitude.quaternion)
    eps=replace(eps,sunlit=False)
    before=CheckpointState.from_context(state.context).to_dict()
    part,carrier=construction_physical_substep(state.context,RationalSeconds.from_fraction(Q(1)),forcing,eps,
        state.inputs.protection,None,compilation=state.construction.compilation,
        work=state.construction.work,limits=state.construction.inputs.limits)
    assert part is None and carrier.battery.unmet_load_w>0
    assert CheckpointState.from_context(state.context).to_dict()==before
