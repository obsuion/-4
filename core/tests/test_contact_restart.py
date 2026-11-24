"""Version-5 causal identity, completed-contact replay and fresh-process JSON."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import os
import subprocess
import sys

import pytest

from examples import v5_contact_execution_demo as demo
from ops_sim.v5.contact_continuation import ContactMemory, ContactState, advance_contact_continuation
import ops_sim.v5.contact_continuation as continuation
from ops_sim.v5.contact_execution import ConsumedContacts, execute_contact_plan
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.ids import GroundContactId
from ops_sim.v5.integration_time import IntegrationPolicy


@pytest.fixture(scope='module',params=[1,2])
def trajectory(request):
    states=[demo.build_demo_state(request.param)]
    for _ in states[0].program.plans:states.append(advance_contact_continuation(states[-1]))
    return states


@pytest.mark.parametrize('boundary',[1,2,3])
def test_fresh_process_restart_complete_state_metrics_and_consumed_replay(tmp_path,trajectory,boundary):
    state=trajectory[boundary]
    saved=tmp_path/'saved.json';output=tmp_path/'resumed.json'
    saved.write_text(create_bundle(state,repository_root=demo.ROOT).to_json(),encoding='utf-8')
    code='\n'.join([
        'import sys',
        'from examples import v5_contact_execution_demo as demo',
        "def forbidden(*a,**kw): raise AssertionError('fixture regeneration during restart')",
        'demo.build_demo_state=forbidden', 'demo.contact_case=forbidden',
        "demo.main(['--resume',sys.argv[1],'--output',sys.argv[2]])",
    ])
    command=[sys.executable,'-B','-c',code,str(saved),str(output)]
    result=subprocess.run(command,cwd=demo.ROOT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1',
        'PYTHONIOENCODING':'utf-8','PYTHONHASHSEED':'403','GIT_OPTIONAL_LOCKS':'0'},capture_output=True,text=True,encoding='utf-8')
    (tmp_path/'restart-process.json').write_text(json.dumps({'command':command,'exit_code':result.returncode,
        'stdout':result.stdout,'stderr':result.stderr}),encoding='utf-8')
    assert result.returncode==0,result.stdout+result.stderr
    actual=json.loads(output.read_text(encoding='utf-8'))
    assert actual==demo.summarize(trajectory[-1])
    assert actual['metrics']['clock_seconds']==125 and actual['metrics']['outer_steps']==3
    assert actual['metrics']['completed_records']==5 and actual['metrics']['partial_records']==0
    assert actual['metrics']['transmitted_bits']==60
    assert actual['consumed_replay_rejection']=='contact identity already consumed'
    assert len(state.memory.consumed_contacts.contacts)==boundary
    assert state.memory.previous_execution==state.program.initial_previous_execution
    if boundary==2:
        assert state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits==20.


def test_same_physical_schedule_refines_only_numerical_identity_and_work():
    starts=[demo.build_demo_state(k) for k in (0,1,2,4)]
    assert len({demo.physical_scenario_digest(s) for s in starts})==1
    assert len({experiment_input_digest(s.context.inputs,s.program) for s in starts})==4
    for s in starts:
        origin=s
        for _ in s.program.plans:s=advance_contact_continuation(s)
        assert s.memory.transmitted_bits==60 and s.context.simulation_time_seconds==125
        assert s.context.diagnostics.completed_steps==3
        assert tuple(o.contact for o in s.memory.outcomes)==tuple(p.contact for p in origin.program.plans)
        assert tuple(tuple(x.transmitted_bits for x in o.services) for o in s.memory.outcomes)==((6,8,4),(15,),(20,7))
        assert s.context.ground_knowledge_state==origin.context.ground_knowledge_state


@pytest.mark.parametrize('change',['numerical-policy','order','tx-power','contact-id','assumptions'])
def test_changed_causal_content_changes_digest_and_expected_program_restore_rejects(change):
    state=demo.build_demo_state();p=state.program;first=p.plans[0]
    bundle=create_bundle(state,repository_root=demo.ROOT)
    if change=='numerical-policy':p=replace(p,integration=IntegrationPolicy(1))
    elif change=='order':p=replace(p,plans=(replace(first,record_ids=tuple(reversed(first.record_ids))),*p.plans[1:]))
    elif change=='tx-power':
        tx=first.tx_inputs;tx=replace(tx,transmitter=replace(tx.transmitter,
            electrical_power_w=demo.old.physical.parameter_value(tx.transmitter.electrical_power_w,37.)))
        p=replace(p,plans=(replace(first,tx_inputs=tx),*p.plans[1:]))
    elif change=='contact-id':p=replace(p,plans=(replace(first,contact=replace(first.contact,contact_id=GroundContactId('other'))),*p.plans[1:]))
    else:p=replace(p,assumptions=(*p.assumptions,'Changed declared assumptions.'))
    assert experiment_input_digest(state.context.inputs,p)!=bundle.input_digest
    with pytest.raises(ValueError,match='program/forcing content'):bundle.restore(repository_root=demo.ROOT,expected_program=p)


@pytest.mark.parametrize('change',['accounting','sample','consumed','prior','checkpoint','timestamp','order'])
def test_false_runtime_history_rejected_even_when_reencoded(change):
    state=advance_contact_continuation(demo.build_demo_state(0));c=deepcopy(state.context);m=deepcopy(state.memory)
    with pytest.raises((ValueError,TypeError)):
        if change=='accounting':
            o=m.outcomes[0];o=replace(o,accounting=replace(o.accounting,throughput_wh=o.accounting.throughput_wh+.01))
            m=replace(m,outcomes=(o,))
        elif change=='sample':
            o=m.outcomes[0];segments=list(o.segments);trace=segments[-1].trace
            sample=replace(trace.samples[-1],battery_energy_wh=trace.samples[-1].battery_energy_wh+.01)
            segments[-1]=replace(segments[-1],trace=replace(trace,samples=(*trace.samples[:-1],sample)))
            m=replace(m,outcomes=(replace(o,segments=tuple(segments)),))
        elif change=='consumed':m=replace(m,consumed_contacts=ConsumedContacts(()))
        elif change=='prior':m=replace(m,previous_execution=replace(m.previous_execution,scheduled_start_seconds=m.previous_execution.scheduled_start_seconds-1))
        elif change=='checkpoint':c.spacecraft_state.battery.energy_wh-=.01
        elif change=='timestamp':
            o=m.outcomes[0];s=o.services[1]
            m=replace(m,outcomes=(replace(o,services=(o.services[0],replace(s,completion_time_seconds=104),*o.services[2:])),))
        else:
            o=m.outcomes[0];m=replace(m,outcomes=(replace(o,requested_order=tuple(reversed(o.requested_order))),))
        ContactState(c,state.program,m)


def test_consumed_identity_cannot_be_reused_with_new_interval_and_contact_memory_not_diagnostics():
    s=advance_contact_continuation(demo.build_demo_state(0));before=deepcopy(s)
    p=replace(s.program.plans[1],contact=replace(s.program.plans[1].contact,contact_id=s.program.plans[0].contact.contact_id))
    with pytest.raises(ValueError,match='already consumed'):
        execute_contact_plan(s.context,p,consumed_contacts=s.memory.consumed_contacts,policy=s.program.policy,integration=s.program.integration)
    assert s==before
    assert s.memory.consumed_contacts.contacts==(s.program.plans[0].contact,)


def test_late_continuation_validation_rolls_back_caller_context_and_memory(monkeypatch):
    s=demo.build_demo_state(0);before=deepcopy(s);context=s.context;memory=s.memory
    original=continuation.execute_contact_plan
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('late memory failure')
    monkeypatch.setattr(continuation,'execute_contact_plan',fail)
    with pytest.raises(RuntimeError):advance_contact_continuation(s)
    assert s==before and s.context is context and s.memory is memory


@pytest.mark.parametrize('version',[1,2,3,4,True,5.,6])
def test_version_five_does_not_reinterpret_prior_programs(version):
    with pytest.raises((ValueError,TypeError)):replace(demo.build_demo_state(0).program,version=version)


def test_repeated_contact_in_program_and_fractional_checkpoint_rejected():
    s=demo.build_demo_state(0)
    with pytest.raises(ValueError,match='already consumed'):replace(s.program,plans=(s.program.plans[0],s.program.plans[0]))
    with pytest.raises(TypeError):replace(s.program.initial_checkpoint,simulation_time_seconds=Fraction(304,3))
