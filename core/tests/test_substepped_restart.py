"""Version-4 identity, JSON-only restart and actual sampled-history validation."""

from copy import deepcopy
from dataclasses import replace
import json
import os
import subprocess
import sys

import pytest

from examples import v5_substepped_execution_demo as demo
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, check_schema_coverage
from ops_sim.v5.integration_time import IntegrationPolicy
from ops_sim.v5.substepped_continuation import (SubsteppedMemory, SubsteppedState, advance_substepped_continuation)
import ops_sim.v5.substepped_continuation as continuation


@pytest.fixture(scope="module",params=[1,2])
def trajectory(request):
    states=[demo.build_demo_state(request.param)]
    for _ in states[0].program.requests:
        states.append(advance_substepped_continuation(states[-1]))
    return states


@pytest.mark.parametrize("boundary",[1,2,4,5])
def test_fresh_process_exact_state_outcomes_prior_acquisition_and_metrics(tmp_path,trajectory,boundary):
    state=trajectory[boundary]
    assert state.memory.outcomes
    assert state.memory.previous_execution!=state.program.initial_previous_execution
    if boundary in (2,4):
        assert state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits==9200.
    saved,output=tmp_path/"saved.json",tmp_path/"resumed.json"
    saved.write_text(create_bundle(state,repository_root=demo.ROOT).to_json(),encoding="utf-8")
    code="\n".join([
        "import sys",
        "from examples import v5_substepped_execution_demo as demo",
        "def forbidden(*a,**kw): raise AssertionError('origin fixture used during restart')",
        "demo.build_demo_state=forbidden",
        "demo.old.physical.build_demo_state=forbidden",
        "demo.main(['--resume',sys.argv[1],'--output',sys.argv[2]])",
    ])
    command=[sys.executable,"-B","-c",code,str(saved),str(output)]
    result=subprocess.run(command,cwd=demo.ROOT,env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONIOENCODING":"utf-8",
        "PYTHONHASHSEED":"519","GIT_OPTIONAL_LOCKS":"0"},capture_output=True,text=True,encoding="utf-8")
    (tmp_path/"restart-process.json").write_text(json.dumps({"command":command,"exit_code":result.returncode,
        "stdout":result.stdout,"stderr":result.stderr}),encoding="utf-8")
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))==demo.summarize(trajectory[-1])
    assert trajectory[-1].context.simulation_time_seconds==215
    assert trajectory[-1].context.diagnostics.completed_steps==5
    assert trajectory[-1].memory.numerical_substeps==5*(2**state.program.integration.subdivision_level)
    assert all(s.context.ground_knowledge_state==trajectory[0].context.ground_knowledge_state for s in trajectory)


def test_refinement_keeps_entire_physical_scenario_but_changes_experiment_identity():
    states=[demo.build_demo_state(level) for level in (0,1,2,4)]
    assert len({demo.physical_scenario_digest(s) for s in states})==1
    assert len({experiment_input_digest(s.context.inputs,s.program) for s in states})==4
    initial=states[0]
    for state in states[1:]:
        assert canonical_content(state.context.inputs)==canonical_content(initial.context.inputs)
        assert canonical_content(state.program.requests)==canonical_content(initial.program.requests)
        assert state.program.initial_checkpoint==initial.program.initial_checkpoint
        assert state.program.policy==initial.program.policy


@pytest.mark.parametrize("change",["integration","physical-duration","mission-forcing","standby-forcing","policy"])
def test_causal_inputs_change_canonical_identity_and_restore_rejects_changed_program(change):
    s=demo.build_demo_state();p=s.program
    bundle=create_bundle(s,repository_root=demo.ROOT)
    if change=="integration":p=replace(p,integration=IntegrationPolicy(1))
    elif change=="physical-duration":
        # A standby interval can have a distinct physical duration. No implicit
        # schedule shifting: the program validator also detects the resulting gap.
        r=replace(p.requests[2],end_time_seconds=170)
        p=replace(p,requests=(*p.requests[:2],r,*p.requests[3:]))
    elif change=="mission-forcing":
        r=p.requests[0];a=r.request.action
        r=replace(r,request=replace(r.request,action=replace(a,environment=replace(a.environment,sunlit=not a.environment.sunlit))))
        p=replace(p,requests=(r,*p.requests[1:]))
    elif change=="standby-forcing":
        r=p.requests[0];r=replace(r,request=replace(r.request,standby=replace(r.request.standby,sunlit=True)))
        p=replace(p,requests=(r,*p.requests[1:]))
    else:p=replace(p,policy=replace(p.policy,rationale="Different explicitly declared policy."))
    assert experiment_input_digest(s.context.inputs,p)!=bundle.input_digest
    with pytest.raises(ValueError,match="program/forcing content"):
        bundle.restore(repository_root=demo.ROOT,expected_program=p)


@pytest.mark.parametrize("change",["outcome","trace","aggregate","work","prior","checkpoint"])
def test_replay_rejects_consistently_rehashed_but_false_runtime_history(change):
    state=advance_substepped_continuation(demo.build_demo_state())
    memory=state.memory;outcome=memory.outcomes[0];context=deepcopy(state.context)
    if change=="outcome":outcome=replace(outcome,request_id="wrong-action")
    elif change=="trace":
        t=outcome.actual_trace;sample=replace(t.samples[-1],battery_energy_wh=t.samples[-1].battery_energy_wh+.01)
        outcome=replace(outcome,actual_trace=replace(t,samples=(*t.samples[:-1],sample)))
    elif change=="aggregate":outcome=replace(outcome,accounting=replace(outcome.accounting,throughput_wh=outcome.accounting.throughput_wh+.01))
    elif change=="work":outcome=replace(outcome,evaluated_eps_substeps=4)
    elif change=="prior":memory=replace(memory,previous_execution=state.program.initial_previous_execution)
    else:context.spacecraft_state.battery.energy_wh-=.01
    if change not in ("prior","checkpoint"):
        memory=replace(memory,outcomes=(outcome,))
    with pytest.raises(ValueError,match="disagrees"):
        SubsteppedState(context,state.program,memory)


def test_advance_failure_after_execution_does_not_mutate_external_context_or_memory(monkeypatch):
    state=demo.build_demo_state();before=deepcopy(state)
    original=continuation.execute_substepped_request
    def executed_then_fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError("late continuation memory validation")
    monkeypatch.setattr(continuation,"execute_substepped_request",executed_then_fail)
    with pytest.raises(RuntimeError):
        advance_substepped_continuation(state)
    assert state==before


@pytest.mark.parametrize("version",[1,2,3,True,4.0,5])
def test_version_four_is_distinct_and_old_versions_not_reinterpreted(version):
    state=demo.build_demo_state()
    with pytest.raises((ValueError,TypeError)):
        replace(state.program,version=version)


def test_no_fractional_or_incomplete_physical_checkpoint_and_bounded_replay():
    state=demo.build_demo_state()
    with pytest.raises(ValueError,match="bounded replay work"):
        replace(state.program,integration=IntegrationPolicy(12))
    with pytest.raises(TypeError):
        replace(state.program.initial_checkpoint,simulation_time_seconds=105.75)
    check_schema_coverage()
    assert state.program.initial_checkpoint.schema_version==5
    assert state.memory==SubsteppedMemory((),state.program.initial_previous_execution)
