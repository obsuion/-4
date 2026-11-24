"""One-action data ownership, sampled protection, compatibility and rollback."""

from copy import deepcopy
from dataclasses import replace

import pytest

from examples import v5_substepped_execution_demo as demo
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.ids import AcquisitionDataRecordId, ThermalLinkId
from ops_sim.v5.integration_time import IntegrationPolicy
from ops_sim.v5.operational_protection import ActionKind, ProtectedRequest, StandbyAction
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.state import FDIRState, OperationalMode
from ops_sim.v5.substepped_execution import (TimedRequest, SampledReason as R,
    execute_substepped_request, evaluate_substepped_availability)
from ops_sim.v5.thermal_config import ThermalLinkConfig
from ops_sim.v5.thermal_routing import ElectricalLoadComponent as C
import ops_sim.v5.substepped_execution as execution


def run(state, index=0):
    return execute_substepped_request(state.context,state.memory.previous_execution,state.program.requests[index],
                                     policy=state.program.policy,integration=state.program.integration)


@pytest.mark.parametrize("level",[0,1,2,4])
def test_same_23_second_acquisition_full_metadata_bits_and_one_commit_under_refinement(level,monkeypatch):
    s=demo.build_demo_state(level)
    inputs=s.context.inputs
    before=deepcopy(s.context)
    counts={"commit":0,"adcs":0,"eps":0}
    original_commit=SimulationEngine._commit
    original_adcs=execution.evaluate_observation_acquisition
    original_eps=execution.compute_eps_substep_transition
    def commit(a,b):
        counts["commit"]+=1
        original_commit(a,b)
    def adcs(*a,**kw):
        counts["adcs"]+=1
        return original_adcs(*a,**kw)
    def eps(*a,**kw):
        counts["eps"]+=1
        assert s.context==before  # no intermediate public clock or physical commit
        return original_eps(*a,**kw)
    def forbidden(*a,**kw):
        raise AssertionError("substeps must not call repeated public engine actions")
    monkeypatch.setattr(SimulationEngine,"_commit",staticmethod(commit))
    monkeypatch.setattr(execution,"evaluate_observation_acquisition",adcs)
    monkeypatch.setattr(execution,"compute_eps_substep_transition",eps)
    for name in ("step","step_imaging","step_imaging_to_storage","step_downlink","step_coupled_downlink"):
        monkeypatch.setattr(SimulationEngine,name,forbidden)
    result=run(s)
    assert counts=={"commit":1,"adcs":1,"eps":2*(2**level)}
    assert s.context.inputs is inputs
    assert s.context.simulation_time_seconds==123 and s.context.diagnostics.completed_steps==1
    records=s.context.spacecraft_state.data_storage.stored_records
    assert len(records)==1 and records[0] is result.created_record
    assert records[0].acquisition_duration_seconds==23 and records[0].scheduled_start_seconds==100
    assert records[0].stored_equivalent_bits==12000.
    assert result.outcome.actual_kind is ActionKind.IMAGING
    assert result.outcome.accounting.numerical_substeps==2**level
    assert result.outcome.actual_trace.samples[-1].offset_numerator_seconds==23*(2**level)
    assert result.previous_execution.scheduled_start_seconds==100
    assert s.context.ground_knowledge_state==before.ground_knowledge_state


@pytest.mark.parametrize("level",[0,1,2])
def test_selected_record_partial_and_completion_once_tx_remains_on_whole_interval(level):
    s=demo.build_demo_state(level)
    previous=s.memory.previous_execution
    results=[]
    for timed in s.program.requests:
        result=execute_substepped_request(s.context,previous,timed,policy=s.program.policy,integration=s.program.integration)
        results.append(result);previous=result.previous_execution
        if timed.start_time_seconds==123:
            assert len(s.context.spacecraft_state.data_storage.stored_records)==1
            assert s.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits==9200.
            assert not s.context.ground_data_delivery_state.completed_deliveries
    assert [r.outcome.actual_kind for r in results]==[ActionKind.IMAGING,ActionKind.DOWNLINK,ActionKind.STANDBY,
                                                   ActionKind.STANDBY,ActionKind.DOWNLINK]
    assert results[-1].transmission_result.transmitted_equivalent_bits_this_service==2800.
    assert results[-1].transmission_result.storage_freed_equivalent_bits==12000.
    assert all(p.eps_result.loads.communications_w==36. for p in results[-1].substeps)
    assert results[-1].outcome.accounting.requested_load_wh==60*23/3600
    delivered=s.context.ground_data_delivery_state.completed_deliveries
    assert len(delivered)==1 and delivered[0].completing_contact.end_time_seconds==215
    assert not s.context.ground_data_delivery_state.partial_transfers
    assert not s.context.spacecraft_state.data_storage.stored_records
    assert s.context.diagnostics.completed_steps==5


def test_physical_duration_can_differ_from_legacy_dt_without_changing_inputs():
    c=demo.old.physical.reference_context();inputs=c.inputs
    assert inputs.numerical_config.timestep_seconds==36
    r=execute_substepped_request(c,demo.old.physical.storage._previous_execution(),
        TimedRequest(100,123,ProtectedRequest(StandbyAction("23s"),demo.old.standby(c))),
        policy=demo.old.policy(c),integration=IntegrationPolicy(2))
    assert c.inputs is inputs and c.simulation_time_seconds==123
    assert all(p.eps_result.battery.dt_seconds==5.75 for p in r.substeps)
    assert c.diagnostics.completed_steps==1


def test_legacy_imaging_duration_admission_is_not_reinterpreted():
    s=demo.build_demo_state();c=s.context;a=s.program.requests[0].request.action
    c.inputs=replace(c.inputs,numerical_config=replace(c.inputs.numerical_config,timestep_seconds=36,checkpoint_interval_seconds=36))
    before=deepcopy(c)
    with pytest.raises(ValueError):
        SimulationEngine().step_imaging_to_storage(c,s.memory.previous_execution,a.execution,record_id=a.record_id,
            environment=a.environment,routing_config=a.routing_config,thermal_inputs=a.thermal_inputs,
            external_heat_sources=a.external_heat_sources,solar_degradation_forcing=a.solar_degradation_forcing)
    assert c==before
    result=run(s)
    assert result.created_record.acquisition_duration_seconds==23


@pytest.mark.parametrize("level,actual",[(0,ActionKind.IMAGING),(8,ActionKind.STANDBY)])
def test_unchanged_cooling_configuration_and_next_123_second_request_changes_decision(level,actual):
    c,wait=demo.thermal_case(cooling=True);inputs=c.inputs
    previous=demo.old.physical.storage._previous_execution()
    policy=demo.old.policy(c)
    first=execute_substepped_request(c,previous,TimedRequest(100,123,ProtectedRequest(StandbyAction("cool"),wait)),
                                     policy=policy,integration=IntegrationPolicy(level))
    template=demo.build_demo_state().program.requests[0].request.action
    action=replace(template,execution=demo.old.physical.storage._scheduled_execution(123,2,"cooling-request"),
        record_id=AcquisitionDataRecordId("cooling-image"),routing_config=template.routing_config,
        external_heat_sources=wait.external_heat_sources,thermal_inputs=wait.thermal_inputs)
    result=execute_substepped_request(c,previous,TimedRequest(123,146,ProtectedRequest(action,wait)),
                                     policy=policy,integration=IntegrationPolicy(level))
    assert c.inputs is inputs and c.simulation_time_seconds==146
    assert result.outcome.actual_kind is actual
    if level:
        assert R.OPERATING_START in result.outcome.availability.reasons
        assert result.created_record is None and result.previous_execution==previous
    else:
        assert result.created_record.acquisition_duration_seconds==23


def test_predicted_hot_samples_do_not_become_actual_survival_observations_or_data():
    s=demo.build_demo_state(2)
    previous=s.memory.previous_execution
    for timed in s.program.requests[:3]:
        r=execute_substepped_request(s.context,previous,timed,policy=s.program.policy,integration=s.program.integration)
        previous=r.previous_execution
    before=deepcopy(s.context)
    timed=s.program.requests[3]
    available=evaluate_substepped_availability(s.context,previous,timed,policy=s.program.policy,integration=s.program.integration)
    assert s.context==before
    r=execute_substepped_request(s.context,previous,timed,policy=s.program.policy,integration=s.program.integration)
    assert r.outcome.availability==available
    assert R.OPERATING_TRAJECTORY in available.reasons
    assert any(sample.operating_node_ids for sample in r.outcome.predicted_trace.samples[1:-1])
    assert any(sample.survival_node_ids for sample in r.outcome.predicted_trace.samples)
    assert all(not sample.survival_node_ids for sample in r.outcome.actual_trace.samples)
    assert s.context.spacecraft_state.data_storage==before.spacecraft_state.data_storage
    assert s.context.ground_data_delivery_state==before.ground_data_delivery_state
    assert s.context.ground_knowledge_state==before.ground_knowledge_state
    assert r.outcome.fdir_state is FDIRState.BACKUP
    # The selected result is exactly the full-duration explicit standby from origin.
    control=deepcopy(before)
    fallback=replace(timed,request=replace(timed.request,action=StandbyAction("control")))
    actual=execute_substepped_request(control,previous,fallback,policy=s.program.policy,integration=s.program.integration)
    assert r.substeps==actual.substeps


def test_internal_only_operating_excursion_is_seen_even_with_safe_initial_and_final_states():
    c,wait=demo.thermal_case();cfg=c.inputs.spacecraft_configuration;n=cfg.thermal.network
    nodes=tuple(replace(node,
        heat_capacity_j_per_k=replace(node.heat_capacity_j_per_k,value={"bus":10.,"payload":1.,"battery":3600.}[node.node_id.value]),
        operating_max_temperature_k=replace(node.operating_max_temperature_k,value=300.25 if node.node_id.value=="bus" else 320.))
        for node in n.nodes)
    link=ThermalLinkConfig(ThermalLinkId("bus-battery"),n.bus_node_id,n.battery_node_id,
        demo.old.physical.storage._parameter("thermal.link.bus-battery.conductance","W/K",2.))
    c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,thermal=replace(cfg.thermal,network=replace(n,nodes=nodes,links=(*n.links,link)))))
    for node in c.spacecraft_state.thermal.node_states:
        node.temperature_k={"bus":300.,"payload":400.,"battery":270.}[node.node_id.value]
    r=execute_substepped_request(c,demo.old.physical.storage._previous_execution(),
        TimedRequest(100,123,ProtectedRequest(StandbyAction("internal-peak"),wait)),
        policy=demo.old.policy(c),integration=IntegrationPolicy(6))
    trace=r.outcome.actual_trace
    assert not trace.samples[0].operating_node_ids and not trace.samples[-1].operating_node_ids
    assert any(sample.operating_node_ids for sample in trace.samples[1:-1])
    assert R.STANDBY_THERMAL in r.outcome.availability.reasons
    assert r.outcome.operational_mode is OperationalMode.SAFE
    assert c.diagnostics.completed_steps==1


def test_energy_exhaustion_inside_action_denies_mission_and_uses_integer_boundary_timestamp():
    s=demo.build_demo_state(2);s.context.spacecraft_state.battery.energy_wh=.04
    timed=s.program.requests[0]
    action=replace(timed.request.action,environment=replace(timed.request.action.environment,sunlit=False))
    timed=replace(timed,request=replace(timed.request,action=action))
    before=deepcopy(s.context)
    r=execute_substepped_request(s.context,s.memory.previous_execution,timed,policy=s.program.policy,integration=s.program.integration)
    assert R.ACTION_POWER in r.outcome.availability.reasons
    assert R.ESSENTIAL_POWER in r.outcome.availability.reasons
    assert r.outcome.actual_kind is ActionKind.STANDBY
    assert r.outcome.actual_trace.samples[1].unmet_load_w==0
    assert any(x.unmet_load_w>0 for x in r.outcome.actual_trace.samples[2:])
    assert r.outcome.critical_energy_since_seconds==100  # boundary owning observation, not 105.75
    assert s.context.spacecraft_state.data_storage==before.spacecraft_state.data_storage
    assert s.context.ground_knowledge_state==before.ground_knowledge_state
    assert r.created_record is None


@pytest.mark.parametrize("stage",["last-substep","result-validation","commit"])
def test_late_failure_is_atomic_for_context_and_external_memory(stage,monkeypatch):
    s=demo.build_demo_state(2);before=deepcopy(s)
    if stage=="last-substep":
        original=execution.complete_coupled_physical_substep;count=0
        def broken(*a,**kw):
            nonlocal count
            count+=1
            result=original(*a,**kw)
            if count==8:
                raise RuntimeError("last mission substep")
            return result
        monkeypatch.setattr(execution,"complete_coupled_physical_substep",broken)
    elif stage=="result-validation":
        def broken(self):
            raise RuntimeError("final validation")
        monkeypatch.setattr(execution.SubsteppedActionResult,"__post_init__",broken)
    else:
        original=SimulationEngine._commit
        def broken(a,b):
            original(a,b)
            raise RuntimeError("after commit assignments")
        monkeypatch.setattr(SimulationEngine,"_commit",staticmethod(broken))
    with pytest.raises(RuntimeError):
        run(s)
    assert s==before
    assert canonical_content(s.memory)==canonical_content(before.memory)


@pytest.mark.parametrize("change",["forcing-change","wrong-time","wrong-duration","world-event","method","resource"])
def test_unsupported_time_forcing_or_policy_fails_before_mutation(change):
    s=demo.build_demo_state();before=deepcopy(s);timed=s.program.requests[0];integration=s.program.integration
    with pytest.raises((TypeError,ValueError)):
        if change=="forcing-change": timed=replace(timed,forcing_change_times_seconds=(111,))
        elif change=="wrong-time": timed=replace(timed,start_time_seconds=101)
        elif change=="wrong-duration": timed=replace(timed,end_time_seconds=124)
        elif change=="world-event":
            from ops_sim.v5.ids import WorldEventId
            s.context.inputs=replace(s.context.inputs,common_world=replace(s.context.inputs.common_world,event_ids=(WorldEventId("event"),)))
            before=deepcopy(s)
        elif change=="method": integration=IntegrationPolicy(2,"implicit")
        else: integration=IntegrationPolicy(13)
        execute_substepped_request(s.context,s.memory.previous_execution,timed,policy=s.program.policy,integration=integration)
    assert s==before


@pytest.mark.parametrize("unsupported",[False,True])
def test_r1_fixed_prefix_allocation_and_rejection_survive_fractional_duration(unsupported):
    c=demo.old.physical.reference_context();cfg=c.inputs.spacecraft_configuration
    demands=(.721,40.482,65.091,30.281) if unsupported else (21.977,18.199,20.138,25.591)
    maximum=113.808 if unsupported else 59.106
    c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,eps=replace(cfg.eps,battery=replace(cfg.eps.battery,
        max_discharge_output_power_w=replace(cfg.eps.battery.max_discharge_output_power_w,value=maximum)))))
    wait=demo.old.standby(c,sunlit=False,loads=PowerLoadBreakdown(*demands[:3],0.,0.,demands[3],0.))
    policy=demo.old.policy(c)
    if unsupported:
        policy=replace(policy,standby_service_order=(C.PAYLOAD,C.BASE_BUS,C.THERMAL_CONTROL,C.PROPULSION,C.COMMUNICATIONS,C.ADCS,C.OBC))
    before=deepcopy(c)
    def execute():
        return execute_substepped_request(c,demo.old.physical.storage._previous_execution(),
            TimedRequest(100,123,ProtectedRequest(StandbyAction("R1"),wait)),policy=policy,integration=IntegrationPolicy(2))
    if unsupported:
        with pytest.raises(ValueError,match="no representable EPS-reconciled"):
            execute()
        assert c==before
    else:
        r=execute()
        assert all(part.eps_result.battery.served_load_w==maximum for part in r.substeps)
        assert r.outcome.accounting.unmet_load_wh==26.799*23/3600


def test_r1_incompatible_full_service_sums_remain_explicit_rejection():
    c=demo.old.physical.reference_context();before=deepcopy(c)
    wait=demo.old.standby(c,sunlit=False,loads=PowerLoadBreakdown(.1,.2,.3,0.,0.,0.,0.))
    with pytest.raises(ValueError,match="total served component power"):
        execute_substepped_request(c,demo.old.physical.storage._previous_execution(),
            TimedRequest(100,123,ProtectedRequest(StandbyAction("incompatible-full"),wait)),
            policy=demo.old.policy(c),integration=IntegrationPolicy(2))
    assert c==before


def test_integration_specific_energy_underflow_cannot_erase_essential_deficit():
    c=demo.old.physical.reference_context();c.spacecraft_state.battery.energy_wh=0.
    wait=replace(demo.old.standby(c,sunlit=False,loads=PowerLoadBreakdown(1e-321,0.,0.,0.,0.,0.,0.)),
                 solar_degradation_forcing=None)
    before=deepcopy(c)
    # Positive W at h=.25 s has a positive real Wh integral below binary64.
    # This is a new duration/accounting rejection, NOT an R1 service-sum gap.
    with pytest.raises(ValueError,match="action energy Wh.*nonzero quotient"):
        execute_substepped_request(c,demo.old.physical.storage._previous_execution(),
            TimedRequest(100,101,ProtectedRequest(StandbyAction("underflow"),wait)),
            policy=demo.old.policy(c),integration=IntegrationPolicy(2))
    assert c==before


@pytest.mark.parametrize("level",[0,1,2,4])
def test_whole_action_solar_loss_distributed_once_and_recomputed_capability(level):
    c=demo.old.physical.reference_context();wait=demo.old.standby(c)
    r=execute_substepped_request(c,demo.old.physical.storage._previous_execution(),
        TimedRequest(100,123,ProtectedRequest(StandbyAction("solar"),wait)),
        policy=demo.old.policy(c),integration=IntegrationPolicy(level))
    assert r.outcome.accounting.solar_retention_loss==wait.solar_degradation_forcing.retention_loss
    for i,part in enumerate(r.substeps):
        assert part.solar_degradation_result.retention_loss==1e-5/(2**level)
        if i:
            assert part.eps_capability_result.solar_generation_retention==r.substeps[i-1].solar_degradation_result.end_generation_retention
    assert abs(c.spacecraft_state.degradation.solar.generation_retention-(.8-1e-5)) <= (2**level)*2e-16
