"""Independent thermal/power counterexamples and atomic protected execution."""

from copy import deepcopy
from dataclasses import replace
from math import nextafter, inf

import pytest

from examples import v5_operational_protection_demo as demo
from ops_sim.v5.continuation import CoupledDownlinkAction
from ops_sim.v5.ids import ThermalNodeId, AcquisitionDataRecordId
from ops_sim.v5.operational_protection import (
    ActionKind, ProtectionReason as R, StandbyAction, ProtectedRequest,
    execute_protected_request, evaluate_action_availability)
from ops_sim.v5.state import FDIRState, OperationalMode
import ops_sim.v5.operational_protection as protection


def downlink_case():
    c = demo.physical.reference_context()
    previous = demo.physical.storage._previous_execution()
    request = ProtectedRequest(CoupledDownlinkAction("downlink", demo.physical.contact(c),
        demo.physical.record().record_id, demo.physical.physical_inputs(c)), demo.standby(c))
    return c, previous, request, demo.policy(c)


def temperature(c, name):
    return next(n for n in c.spacecraft_state.thermal.node_states if n.node_id.value == name)


def set_power(c, request, *, energy, generation, maximum):
    cfg = c.inputs.spacecraft_configuration
    eps = cfg.eps
    battery = replace(eps.battery, max_discharge_output_power_w=demo.physical.parameter_value(
        eps.battery.max_discharge_output_power_w, maximum))
    solar = replace(eps.solar_array, nominal_generation_w=demo.physical.parameter_value(
        eps.solar_array.nominal_generation_w, (generation or 20.0) / 0.8))
    c.inputs = replace(c.inputs, spacecraft_configuration=replace(cfg, eps=replace(eps, battery=battery, solar_array=solar)))
    c.spacecraft_state.battery.energy_wh = energy
    return replace(request, action=replace(request.action,
        physical_inputs=replace(request.action.physical_inputs, sunlit=generation > 0)),
        standby=replace(request.standby, sunlit=generation > 0))


def execute(c, previous, request, policy):
    return execute_protected_request(c, previous, request, policy=policy)


def test_original_400k_defect_denied_and_passively_cooled_with_separate_survival():
    state = demo.build_demo_state()
    c = state.context
    ground = deepcopy(c.ground_knowledge_state)
    result = execute(c, state.memory.previous_execution, state.program.requests[0], state.program.policy)
    assert result.outcome.actual_kind is ActionKind.STANDBY
    assert R.OPERATING_START in result.outcome.availability.reasons
    assert result.outcome.survival_start_node_ids == (ThermalNodeId("payload"),)
    assert result.outcome.survival_end_node_ids == ()
    assert temperature(c, "payload").temperature_k == 300.0  # C=G*dt, no payload heat
    assert not c.spacecraft_state.data_storage.stored_records
    assert (c.simulation_time_seconds, c.diagnostics.completed_steps) == (123, 1)
    assert c.spacecraft_state.onboard.operational_mode is OperationalMode.STANDBY
    assert c.spacecraft_state.onboard.fdir_state is FDIRState.BACKUP
    assert c.ground_knowledge_state == ground


@pytest.mark.parametrize("value,admitted", [(270.0,True),(320.0,True),
    (nextafter(270.0,-inf),False),(nextafter(320.0,inf),False)])
def test_inclusive_operating_boundaries_no_epsilon(value, admitted):
    old = demo.physical.build_demo_state()
    c, action = old.context, old.program.actions[0]
    # No payload heat or links: start == end, so this tests equality itself.
    routing = replace(action.routing_config, routes=tuple(replace(r,
        retained_heat_fraction=replace(r.retained_heat_fraction,value=0.0)) for r in action.routing_config.routes))
    heat = replace(action.external_heat_sources,node_sources=tuple(replace(s,
        absorbed_solar_w=0.0,absorbed_albedo_w=0.0,absorbed_earth_ir_w=0.0) for s in action.external_heat_sources.node_sources))
    action = replace(action,routing_config=routing,external_heat_sources=heat)
    temperature(c,"payload").temperature_k=value
    availability=evaluate_action_availability(c,old.memory.previous_execution,
        ProtectedRequest(action,demo.standby(c)),policy=demo.policy(c))
    assert availability.available is admitted
    assert (R.OPERATING_START in availability.reasons) is (not admitted)


def test_hot_payload_does_not_block_downlink_with_explicit_bus_transmitter_binding():
    c,previous,request,policy=downlink_case()
    temperature(c,"payload").temperature_k=400.0
    result=execute(c,previous,request,policy)
    assert result.outcome.actual_kind is ActionKind.DOWNLINK
    assert result.outcome.survival_start_node_ids == (ThermalNodeId("payload"),)
    assert result.outcome.survival_end_node_ids == (ThermalNodeId("payload"),)
    assert result.requested_attempt.transmission_result.transmitted_equivalent_bits_this_service == 9000.0


@pytest.mark.parametrize("field,value", [("imaging_node_ids",()),("standby_node_ids",()),
    ("downlink_node_ids",()),("imaging_node_ids",(ThermalNodeId("bus"),)),
    ("downlink_node_ids",(ThermalNodeId("battery"),)),
    ("communications_node_id",ThermalNodeId("unknown")),
    ("standby_node_ids",(ThermalNodeId("bus"),ThermalNodeId("unknown"))),
    ("communications_binding_rationale",""),("essential_rule","implicit-default"),
    ("recovery_rule","latch"),("standby_service_order",())])
def test_invalid_or_absent_bindings_cannot_disable_protection(field,value):
    c,previous,request,policy=downlink_case()
    before=deepcopy(c)
    with pytest.raises((ValueError,TypeError)):
        execute(c,previous,request,replace(policy,**{field:value}))
    assert c==before


def test_predictive_rejection_does_not_experience_discarded_survival_excursion():
    s=demo.build_demo_state()
    for _ in range(4):
        s=demo.advance_operational_continuation(s)
    before=deepcopy(s.context)
    result=execute(s.context,s.memory.previous_execution,s.program.requests[4],s.program.policy)
    o=result.outcome
    assert o.availability.operating_start_node_ids==()
    assert o.availability.predicted_operating_end_node_ids==(ThermalNodeId("payload"),)
    assert o.survival_start_node_ids==o.survival_end_node_ids==()
    assert o.actual_kind is ActionKind.STANDBY
    assert s.context.spacecraft_state.data_storage==before.spacecraft_state.data_storage
    assert s.context.ground_data_delivery_state==before.ground_data_delivery_state
    assert s.context.simulation_time_seconds==before.simulation_time_seconds+23
    assert result.requested_attempt is None


@pytest.mark.parametrize("energy,generation,maximum,actual,essential", [
    (0.0,0.0,200.0,ActionKind.STANDBY,20.0),
    (0.0,200.0,200.0,ActionKind.DOWNLINK,0.0),
    (80.0,0.0,5.0,ActionKind.STANDBY,15.0),
    (80.0,0.0,30.0,ActionKind.STANDBY,0.0),
    (0.0,20.0,200.0,ActionKind.STANDBY,0.0),
    (80.0,20.0,200.0,ActionKind.DOWNLINK,0.0),
])
def test_action_power_is_distinct_from_essential_power(energy,generation,maximum,actual,essential):
    c,previous,request,policy=downlink_case()
    request=set_power(c,request,energy=energy,generation=generation,maximum=maximum)
    before=deepcopy(c)
    result=execute(c,previous,request,policy)
    assert result.outcome.actual_kind is actual
    assert result.outcome.availability.essential_unmet_w==essential
    assert (result.outcome.operational_mode is OperationalMode.SAFE) is (essential>0)
    assert result.outcome.critical_energy_since_seconds==(100 if essential>0 else None)
    assert c.simulation_time_seconds==136 and c.diagnostics.completed_steps==1
    if actual is ActionKind.STANDBY:
        assert c.spacecraft_state.data_storage==before.spacecraft_state.data_storage
        assert c.ground_data_delivery_state==before.ground_data_delivery_state
        assert result.step_result.eps_result.loads.payload_w==result.step_result.eps_result.loads.communications_w==0
        assert result.step_result.eps_result.loads.total_load_w==20.0
    else:
        assert result.step_result.eps_result.loads.total_load_w==60.0


def test_priority_allocation_conserves_served_power_and_only_served_heat():
    c,previous,request,policy=downlink_case()
    request=set_power(c,request,energy=80.0,generation=0.0,maximum=14.0)
    result=execute(c,previous,request,policy)
    ledger=result.standby_routed_heat.component_ledgers
    assert [x.served_power_w for x in ledger]==[12.0,2.0,0.0,0.0,0.0,0.0,0.0]
    assert sum(x.served_power_w for x in ledger)==result.step_result.eps_result.battery.served_load_w==14.0
    assert sum(x.retained_heat_w for x in ledger)==7.0
    assert result.outcome.availability.essential_unmet_w==6.0


def test_electrical_recovery_clears_sampled_timestamp_without_latch():
    c,previous,request,policy=downlink_case()
    request=set_power(c,request,energy=0.0,generation=25.0,maximum=200.0)
    off=replace(request.standby,sunlit=False)
    for _ in range(2):
        result=execute(c,previous,ProtectedRequest(StandbyAction("off"),off),policy)
        assert result.outcome.critical_energy_since_seconds==100
        assert c.spacecraft_state.onboard.fdir_state is FDIRState.BACKUP
    result=execute(c,previous,ProtectedRequest(StandbyAction("recovered"),request.standby),policy)
    assert result.outcome.recovered
    assert result.outcome.critical_energy_since_seconds is None
    assert result.outcome.operational_mode is OperationalMode.STANDBY
    assert result.outcome.fdir_state is FDIRState.NORMAL


def test_repeat_evaluation_is_read_only_and_diagnostics_are_noncausal():
    c,previous,request,policy=downlink_case()
    request=set_power(c,request,energy=0.0,generation=0.0,maximum=200.0)
    before=deepcopy(c)
    results=[evaluate_action_availability(c,previous,request,policy=policy) for _ in range(3)]
    assert results[0]==results[1]==results[2]
    assert c==before and c.spacecraft_state.onboard.critical_energy_since_seconds is None
    c.diagnostics.completed_steps=10000
    assert evaluate_action_availability(c,previous,request,policy=policy)==results[0]


@pytest.mark.parametrize("telemetry",["stale","absent"])
def test_onboard_truth_does_not_refresh_ground_knowledge(telemetry):
    c,previous,request,policy=downlink_case()
    if telemetry=="absent": c.ground_knowledge_state.latest_telemetry=None
    ground=deepcopy(c.ground_knowledge_state)
    request=set_power(c,request,energy=0.0,generation=0.0,maximum=200.0)
    result=execute(c,previous,request,policy)
    assert result.outcome.operational_mode is OperationalMode.SAFE
    assert c.ground_knowledge_state==ground


@pytest.mark.parametrize("phase",["data","physical","onboard","result","checkpoint"])
def test_late_failures_preserve_values_and_external_object_identities(monkeypatch,phase):
    c,previous,request,policy=downlink_case()
    before=deepcopy(c)
    refs=(c.inputs,c.spacecraft_state,c.spacecraft_state.battery,c.spacecraft_state.onboard,
          c.ground_data_delivery_state,c.ground_knowledge_state,c.diagnostics)
    def fail(*args,**kwargs): raise RuntimeError("injected late failure")
    if phase=="data":
        original=protection.SimulationEngine._prepare_downlink_physical_integration_handler
        def prepare(*args,**kwargs):
            handler=original(*args,**kwargs)
            def run(*a,**k):
                handler(*a,**k)
                assert a[0].ground_data_delivery_state.partial_transfers
                fail()
            return run
        monkeypatch.setattr(protection.SimulationEngine,"_prepare_downlink_physical_integration_handler",prepare)
    elif phase=="physical":
        original=protection._complete_coupled_physical_integration
        def integrate(*a,**k): original(*a,**k); fail()
        monkeypatch.setattr(protection,"_complete_coupled_physical_integration",integrate)
    elif phase=="onboard":
        original=protection._apply_protection
        def apply(*a,**k): original(*a,**k); fail()
        monkeypatch.setattr(protection,"_apply_protection",apply)
    elif phase=="result": monkeypatch.setattr(protection.ProtectedStepResult,"__post_init__",fail)
    else:
        original=protection.checked_checkpoint
        def check(candidate):
            if candidate.simulation_time_seconds==136: fail()
            return original(candidate)
        monkeypatch.setattr(protection,"checked_checkpoint",check)
    with pytest.raises(RuntimeError,match="injected late"):
        execute(c,previous,request,policy)
    assert c==before
    assert all(a is b for a,b in zip(refs,(c.inputs,c.spacecraft_state,c.spacecraft_state.battery,
        c.spacecraft_state.onboard,c.ground_data_delivery_state,c.ground_knowledge_state,c.diagnostics)))


def test_one_external_commit_reuses_selected_mission_physics(monkeypatch):
    c,previous,request,policy=downlink_case()
    calls=[]
    original=protection.SimulationEngine._commit
    def commit(target,working):
        if target is c: calls.append(working)
        original(target,working)
    monkeypatch.setattr(protection.SimulationEngine,"_commit",staticmethod(commit))
    result=execute(c,previous,request,policy)
    assert len(calls)==1
    assert result.step_result is result.requested_attempt.step_result
    assert c.spacecraft_state is calls[0].spacecraft_state


@pytest.mark.parametrize("bad",["missing-policy","missing-forcing","wrong-node","double-heat","payload-on","tx-on","no-demand","wrong-contact","outside-owned-regime"])
def test_malformed_inputs_raise_without_standby_commit(bad):
    c,previous,request,policy=downlink_case()
    before=deepcopy(c)
    with pytest.raises((TypeError,ValueError)):
        if bad=="missing-policy": policy=None
        elif bad=="missing-forcing": request=replace(request,standby=None)
        elif bad=="wrong-node":
            first,*rest=request.standby.external_heat_sources.node_sources
            request=replace(request,standby=replace(request.standby,external_heat_sources=replace(request.standby.external_heat_sources,
                node_sources=(replace(first,node_id=ThermalNodeId("unknown")),*rest))))
        elif bad=="double-heat":
            first,*rest=request.standby.external_heat_sources.node_sources
            request=replace(request,standby=replace(request.standby,external_heat_sources=replace(request.standby.external_heat_sources,
                node_sources=(replace(first,internal_dissipation_w=1.0),*rest))))
        elif bad in ("payload-on","tx-on"):
            request=replace(request,standby=replace(request.standby,loads=replace(request.standby.loads,
                **{("payload_w" if bad=="payload-on" else "communications_w"):1.0})))
        elif bad=="no-demand": request=replace(request,standby=replace(request.standby,loads=demo.PowerLoadBreakdown(0.,0.,0.,0.,0.,0.,0.)))
        elif bad=="wrong-contact": request=replace(request,action=replace(request.action,
            contact=replace(request.action.contact,start_time_seconds=101)))
        else:
            c.spacecraft_state.onboard.fdir_state=FDIRState.EMERGENCY_BEACON
            before=deepcopy(c)
        execute(c,previous,request,policy)
    assert c==before


def test_independent_standby_reference_nonzero_ageing_and_no_data():
    result=demo.numerical_reference()
    assert result["clock_seconds"]==136 and result["completed_steps"]==1
    rows={r["quantity"]:r for r in result["rows"]}
    assert rows["calendar_damage"]["actual"]>0
    assert rows["cycling_damage"]["actual"]>0


def test_missing_record_valid_low_level_request_consumes_contact_without_fabrication():
    c,previous,request,policy=downlink_case()
    request=replace(request,action=replace(request.action,record_id=AcquisitionDataRecordId("missing")))
    before=deepcopy(c)
    result=execute(c,previous,request,policy)
    assert R.DATA_UNAVAILABLE in result.outcome.availability.reasons
    assert c.simulation_time_seconds==136
    assert c.ground_data_delivery_state==before.ground_data_delivery_state
    assert c.spacecraft_state.data_storage==before.spacecraft_state.data_storage


def test_hot_standby_core_integrates_passively_without_functionality_claim():
    c,previous,request,policy=downlink_case()
    temperature(c,"bus").temperature_k=400.0
    result=execute(c,previous,request,policy)
    assert result.outcome.operational_mode is OperationalMode.SAFE
    assert R.STANDBY_THERMAL in result.outcome.availability.reasons
    assert result.outcome.critical_energy_since_seconds is None  # thermal != power
    assert temperature(c,"bus").temperature_k>400.0  # no clamp
    assert c.simulation_time_seconds==136


@pytest.mark.parametrize("value,violated",[(250.0,False),(340.0,False),
    (nextafter(250.0,-inf),True),(nextafter(340.0,inf),True)])
def test_survival_start_boundary_is_separate_and_inclusive(value,violated):
    c,previous,request,policy=downlink_case()
    temperature(c,"payload").temperature_k=value
    result=execute(c,previous,request,policy)
    assert (ThermalNodeId("payload") in result.outcome.survival_start_node_ids) is violated
    assert result.outcome.actual_kind is ActionKind.DOWNLINK


@pytest.mark.parametrize("cause",["electrical","storage","readiness"])
def test_valid_imaging_unavailability_runs_standby(cause):
    old=demo.physical.build_demo_state()
    c,action,previous=old.context,old.program.actions[0],old.memory.previous_execution
    cfg=c.inputs.spacecraft_configuration
    if cause=="electrical":
        c.spacecraft_state.battery.energy_wh=0.0
        action=replace(action,environment=replace(action.environment,sunlit=False))
    elif cause=="storage":
        cfg=replace(cfg,storage=replace(cfg.storage,usable_capacity_gb=demo.physical.parameter_value(cfg.storage.usable_capacity_gb,1e-9)))
        c.inputs=replace(c.inputs,spacecraft_configuration=cfg)
    else:
        agile=cfg.adcs.agile_pointing
        agile=replace(agile,post_slew_settling_time_seconds=demo.physical.parameter_value(agile.post_slew_settling_time_seconds,500.0))
        c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,adcs=replace(cfg.adcs,agile_pointing=agile)))
        direction=previous.candidate.common_frame_boresight
        previous=replace(previous,candidate=replace(previous.candidate,
            common_frame_boresight=replace(direction,x=1.0,y=0.0,z=0.0)))
    result=execute(c,previous,ProtectedRequest(action,demo.standby(c)),demo.policy(c))
    assert result.outcome.actual_kind is ActionKind.STANDBY
    assert (R.ACTION_POWER if cause=="electrical" else R.IMAGING_AUTHORIZATION) in result.outcome.availability.reasons
    assert not c.spacecraft_state.data_storage.stored_records
    assert c.simulation_time_seconds==123


@pytest.mark.parametrize("field",["battery","ground","data"])
def test_protection_update_cannot_corrupt_other_state_even_with_valid_values(monkeypatch,field):
    c,previous,request,policy=downlink_case()
    before=deepcopy(c)
    original=protection._apply_protection
    def corrupt(candidate,*args):
        result=original(candidate,*args)
        if field=="battery": candidate.spacecraft_state.battery.energy_wh-=1.0
        elif field=="ground": candidate.ground_knowledge_state.latest_telemetry=None
        else:
            first=candidate.ground_data_delivery_state.partial_transfers[0]
            candidate.ground_data_delivery_state.partial_transfers=(replace(first,transmitted_equivalent_bits=8999.0),)
        return result
    monkeypatch.setattr(protection,"_apply_protection",corrupt)
    with pytest.raises(ValueError,match="outside its owned"):
        execute(c,previous,request,policy)
    assert c==before


def test_elapsed_denied_contact_cannot_be_reused():
    c,previous,request,policy=downlink_case()
    request=set_power(c,request,energy=0.0,generation=0.0,maximum=200.0)
    execute(c,previous,request,policy)
    before=deepcopy(c)
    with pytest.raises(ValueError,match="current full step"):
        execute(c,previous,request,policy)
    assert c==before


def test_future_previous_acquisition_is_malformed_not_unavailable():
    old=demo.physical.build_demo_state()
    action=old.program.actions[0]
    from ops_sim.v5.observation_feasibility import ScheduledObservationExecution
    future=ScheduledObservationExecution(action.execution.candidate.maneuver_candidate,100)
    before=deepcopy(old.context)
    with pytest.raises(ValueError,match="previous acquisition must end"):
        execute(old.context,future,ProtectedRequest(action,demo.standby(old.context)),demo.policy(old.context))
    assert old.context==before
