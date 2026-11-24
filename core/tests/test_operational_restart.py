"""JSON-only restart, content identity, outcome/physical consistency and history."""

from copy import deepcopy
from dataclasses import replace
import json
import os
import subprocess
import sys

import pytest

from examples import v5_operational_protection_demo as demo
from ops_sim.v5.continuation import ContinuationMemory
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, canonical_copy, check_schema_coverage
from ops_sim.v5.ids import AcquisitionDataRecordId
from ops_sim.v5.operational_continuation import OperationalMemory, OperationalState, advance_operational_continuation
from ops_sim.v5.operational_protection import ActionKind, ProtectionReason, StandbyAction, ProtectedRequest
from ops_sim.v5.state import FDIRState, OperationalMode
import ops_sim.v5.operational_continuation as operational


@pytest.fixture(scope="module")
def trajectory():
    states=[demo.build_demo_state()]
    for _ in states[0].program.requests:
        states.append(advance_operational_continuation(states[-1]))
    return states


@pytest.mark.parametrize("boundary",[0,1,2,3,4,5,6,7,8])
def test_json_fresh_process_restart_at_denial_protection_recovery_acquisition_partial(tmp_path,trajectory,boundary):
    saved,output=tmp_path/"saved.json",tmp_path/"resumed.json"
    saved.write_text(create_bundle(trajectory[boundary],repository_root=demo.ROOT).to_json(),encoding="utf-8")
    code="\n".join([
        "import sys",
        "from examples import v5_operational_protection_demo as demo",
        "def forbidden(): raise AssertionError('origin fixture called during restart')",
        "demo.build_demo_state=forbidden",
        "demo.physical.build_demo_state=forbidden",
        "demo.physical.legacy.build_demo_state=forbidden",
        "demo.main(['--resume',sys.argv[1],'--output',sys.argv[2]])",
    ])
    result=subprocess.run([sys.executable,"-B","-c",code,str(saved),str(output)],cwd=demo.ROOT,
        env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONIOENCODING":"utf-8","GIT_OPTIONAL_LOCKS":"0"},
        capture_output=True,text=True,encoding="utf-8")
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))==demo.summarize(trajectory[-1])


def test_expected_transition_trace_and_previous_success_memory(trajectory):
    outcomes=trajectory[-1].memory.outcomes
    assert [x.actual_kind for x in outcomes]==[
        ActionKind.STANDBY,ActionKind.STANDBY,ActionKind.IMAGING,ActionKind.DOWNLINK,
        ActionKind.STANDBY,ActionKind.STANDBY,ActionKind.STANDBY,ActionKind.DOWNLINK]
    assert [x.recovered for x in outcomes]==[False,False,True,False,False,False,True,False]
    assert trajectory[1].memory.previous_execution==trajectory[0].memory.previous_execution
    assert trajectory[2].memory.previous_execution==trajectory[0].memory.previous_execution
    assert trajectory[3].memory.previous_execution.scheduled_start_seconds==146
    for s in trajectory[3:]:
        assert s.memory.previous_execution==trajectory[3].memory.previous_execution
    assert trajectory[4].context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits==9000.0
    assert trajectory[5].context.ground_data_delivery_state==trajectory[4].context.ground_data_delivery_state
    assert trajectory[5].context.spacecraft_state.data_storage==trajectory[4].context.spacecraft_state.data_storage
    assert ProtectionReason.DATA_UNAVAILABLE in outcomes[1].availability.reasons
    assert ProtectionReason.DATA_UNAVAILABLE in outcomes[5].availability.reasons
    assert demo.summarize(trajectory[-1])["metrics"]=={"requests":8,"denials":4,"delivered_bits":12000.0}
    assert trajectory[-1].context.simulation_time_seconds==284
    assert trajectory[-1].context.diagnostics.completed_steps==8
    assert all(s.context.ground_knowledge_state==trajectory[0].context.ground_knowledge_state for s in trajectory)
    assert len({experiment_input_digest(s.context.inputs,s.program) for s in trajectory})==1


@pytest.mark.parametrize("change",["policy-rationale","comm-binding","dependencies","priority","standby-loads","standby-forcing","standby-rationale","mission-forcing","initial-truth"])
def test_every_new_policy_forcing_and_origin_input_is_content_bound(trajectory,change):
    s=trajectory[0];p=s.program;r=p.requests[0]
    if change=="policy-rationale": p=replace(p,policy=replace(p.policy,rationale="Another explicit assumption."))
    elif change=="comm-binding": p=replace(p,policy=replace(p.policy,communications_binding_rationale="Another explicit role assumption."))
    elif change=="dependencies": p=replace(p,policy=replace(p.policy,downlink_node_ids=p.policy.imaging_node_ids))
    elif change=="priority": p=replace(p,policy=replace(p.policy,standby_service_order=tuple(reversed(p.policy.standby_service_order))))
    elif change=="standby-loads": r=replace(r,standby=replace(r.standby,loads=replace(r.standby.loads,obc_w=4.0)))
    elif change=="standby-forcing": r=replace(r,standby=replace(r.standby,sunlit=False))
    elif change=="standby-rationale": r=replace(r,standby=replace(r.standby,rationale="Other explicit standby provenance."))
    elif change=="mission-forcing": r=replace(r,action=replace(r.action,environment=replace(r.action.environment,sunlit=False)))
    else: p=replace(p,initial_checkpoint=replace(p.initial_checkpoint,spacecraft=replace(p.initial_checkpoint.spacecraft,battery_energy_wh=70.0)))
    p=replace(p,requests=(r,*p.requests[1:]))
    assert experiment_input_digest(s.context.inputs,p)!=experiment_input_digest(s.context.inputs,s.program)
    bundle=create_bundle(s,repository_root=demo.ROOT)
    with pytest.raises(ValueError,match="program/forcing"):
        bundle.restore(repository_root=demo.ROOT,expected_program=p)


@pytest.mark.parametrize("damage",["outcome-missing","request-id","false-success","previous","time","steps","energy","thermal","critical-timestamp","ground-knowledge","data-progress"])
def test_rehashed_bundle_cannot_hide_outcome_or_runtime_inconsistency(trajectory,damage):
    from ops_sim.v5.experiment_bundle import _runtime_digest,_bundle_digest
    s=trajectory[5]
    payload=json.loads(create_bundle(s,repository_root=demo.ROOT).to_json())
    memory=canonical_copy(s.memory)
    checkpoint=payload["checkpoint"]["schema5"]
    if damage=="outcome-missing": memory=replace(memory,outcomes=memory.outcomes[:-1])
    elif damage=="request-id": memory=replace(memory,outcomes=(*memory.outcomes[:-1],replace(memory.outcomes[-1],request_id="different")))
    elif damage=="false-success":
        last=memory.outcomes[-1]
        good=replace(last.availability,reasons=(),predicted_operating_end_node_ids=())
        last=replace(last,availability=good,actual_kind=ActionKind.IMAGING,operational_mode=OperationalMode.IMAGING,fdir_state=FDIRState.NORMAL)
        memory=replace(memory,outcomes=(*memory.outcomes[:-1],last))
    elif damage=="previous": memory=replace(memory,previous_execution=s.program.initial_previous_execution)
    else:
        # Modify a valid typed checkpoint, then serialize it; no schema guessing.
        snapshot=demo.CheckpointState.from_dict(checkpoint)
        context=snapshot.restore(s.context.inputs)
        if damage=="time": context.simulation_time_seconds+=23
        elif damage=="steps": context.diagnostics.completed_steps+=1
        elif damage=="energy": context.spacecraft_state.battery.energy_wh-=1.0
        elif damage=="thermal": context.spacecraft_state.thermal.node_states[0].temperature_k+=1.0
        elif damage=="critical-timestamp": context.spacecraft_state.onboard.critical_energy_since_seconds=100
        elif damage=="ground-knowledge": context.ground_knowledge_state.latest_telemetry=None
        else:
            first=context.ground_data_delivery_state.partial_transfers[0]
            context.ground_data_delivery_state.partial_transfers=(replace(first,transmitted_equivalent_bits=8999.0),)
        payload["checkpoint"]["schema5"]=demo.CheckpointState.from_context(context).to_dict()
    payload["memory"]=canonical_content(memory)
    payload["runtime_digest"]=_runtime_digest(payload)
    payload["bundle_digest"]=_bundle_digest(payload)
    with pytest.raises(ValueError,match="outcome|checkpoint|previous|replay"):
        ExperimentBundle.from_json(json.dumps(payload))


def test_invalid_reference_is_distinct_from_prior_denied_acquisition(trajectory):
    s=trajectory[0]
    r=s.program.requests[1]
    invalid=replace(r,action=replace(r.action,record_id=AcquisitionDataRecordId("no-producer")))
    program=replace(s.program,requests=(s.program.requests[0],invalid,*s.program.requests[2:]))
    with pytest.raises(ValueError,match="structurally invalid"):
        OperationalState(s.context,program,s.memory)
    assert trajectory[2].memory.outcomes[-1].availability.reasons==(ProtectionReason.DATA_UNAVAILABLE,)


def test_memory_version_ownership_and_strict_codec(trajectory):
    s=trajectory[0]
    check_schema_coverage()
    with pytest.raises(ValueError,match="version"):
        replace(s.program,version=2)
    with pytest.raises(TypeError,match="memory"):
        OperationalState(s.context,s.program,ContinuationMemory((),s.memory.previous_execution))
    wire=canonical_content(s.program)
    del wire["fields"]["policy"]
    from ops_sim.v5.experiment_codec import decode_content
    with pytest.raises(ValueError,match="fields"):
        decode_content(wire)


def test_late_continuation_failure_does_not_advance_external_context_or_memory(monkeypatch,trajectory):
    s=trajectory[4];before=deepcopy(s)
    original=operational.validate_operational_continuation
    def validate(context,program,memory):
        if context is not s.context:
            assert len(memory.outcomes)==5
            assert memory.outcomes[-1].actual_kind is ActionKind.STANDBY
            raise RuntimeError("late operational-state validation")
        return original(context,program,memory)
    monkeypatch.setattr(operational,"validate_operational_continuation",validate)
    refs=(s.context,s.context.spacecraft_state,s.memory)
    with pytest.raises(RuntimeError,match="late operational"):
        advance_operational_continuation(s)
    assert s==before
    assert refs==(s.context,s.context.spacecraft_state,s.memory)
    assert refs[0] is s.context and refs[1] is s.context.spacecraft_state and refs[2] is s.memory


def test_electrical_protection_and_recovery_json_restart(tmp_path):
    s=demo.build_demo_state()
    context=s.context
    # Passive isolated nodes stay admissible; empty energy, eclipse then sunlight.
    for node in context.spacecraft_state.thermal.node_states: node.temperature_k=300.0
    context.spacecraft_state.battery.energy_wh=0.0
    wait=demo.standby(context)
    cfg=context.inputs.spacecraft_configuration
    solar=replace(cfg.eps.solar_array,nominal_generation_w=demo.physical.parameter_value(cfg.eps.solar_array.nominal_generation_w,50.0))
    context.inputs=replace(context.inputs,spacecraft_configuration=replace(cfg,eps=replace(cfg.eps,solar_array=solar)))
    requests=(ProtectedRequest(StandbyAction("critical"),replace(wait,sunlit=False)),
              ProtectedRequest(StandbyAction("recovered"),wait))
    program=replace(s.program,initial_checkpoint=demo.CheckpointState.from_context(context),requests=requests)
    s=OperationalState(context,program,OperationalMemory((),s.memory.previous_execution))
    protected=advance_operational_continuation(s)
    assert protected.context.spacecraft_state.onboard.critical_energy_since_seconds==100
    path=tmp_path/"protected.json";out=tmp_path/"resumed.json"
    path.write_text(create_bundle(protected,repository_root=demo.ROOT).to_json(),encoding="utf-8")
    result=subprocess.run([sys.executable,"-B","-m","examples.v5_operational_protection_demo","--resume",str(path),"--output",str(out)],
        cwd=demo.ROOT,env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","GIT_OPTIONAL_LOCKS":"0"},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    final=advance_operational_continuation(protected)
    assert final.memory.outcomes[-1].recovered
    assert final.context.spacecraft_state.onboard.critical_energy_since_seconds is None
    assert json.loads(out.read_text(encoding="utf-8"))==demo.summarize(final)


def test_future_unused_fallback_wrong_node_is_rejected_at_program_boundary(trajectory):
    from ops_sim.v5.ids import ThermalNodeId
    s=trajectory[0]
    last=s.program.requests[-1]
    first,*rest=last.standby.thermal_inputs.node_boundaries
    wait=replace(last.standby,thermal_inputs=replace(last.standby.thermal_inputs,
        node_boundaries=(replace(first,node_id=ThermalNodeId("unknown")),*rest)))
    program=replace(s.program,requests=(*s.program.requests[:-1],replace(last,standby=wait)))
    with pytest.raises(ValueError,match="bindings"):
        OperationalState(s.context,program,s.memory)
