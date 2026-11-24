from copy import deepcopy
from dataclasses import replace
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.rolling_execution import start_rolling,step_rolling,planning_view,guard_rolling
from ops_sim.v5.rolling_controller import build_candidates
from ops_sim.v5.rolling_document import save_continuation


@pytest.fixture(scope='module')
def capture_state():
    state=step_rolling(start_rolling(make_inputs()))
    state=step_rolling(state)
    assert state.physical.outcomes[-1].kind=='CAPTURE'
    return state


def test_actual_consumer_captures_with_unreceived_point_ack(capture_state):
    s=capture_state
    assert s.physical.context.simulation_time_seconds==140 and len(s.physical.acquisitions)==1
    assert not s.knowledge.observation.onboard_records and not s.knowledge.observation.delivery_acks
    assert {c.kind for c in s.knowledge.pending()}=={'POINT','CAPTURE'}
    assert s.decisions[-1].estimate_identity and s.decisions[-1].forecasts[0][1].estimate.command_ids
    guard_rolling(s)


def test_pending_capture_does_not_become_known_record_or_duplicate_request(capture_state):
    v=planning_view(capture_state);candidates,rejected=build_candidates(v)
    assert not any(a.product_id=='b47-medium' for _,s in candidates for a in s)
    assert not any('backlog' in tag for tag,_ in candidates)
    assert v.knowledge.acquired_ids()==frozenset()


@pytest.mark.parametrize('field',['estimate','intent','diagnosis','reconciliation'])
def test_new_history_mutations_reject_before_save(capture_state,field,tmp_path):
    s=deepcopy(capture_state)
    if field=='estimate':
        tag,f=s.decisions[-1].forecasts[0];f.estimate.runtime_work['physical_completed_calls']+=1
    if field=='intent':s.intents=(replace(s.intents[0],profile_identity='0'*64),*s.intents[1:])
    if field=='diagnosis':s.diagnosis=replace(s.diagnosis,controller_method='caller-winner')
    if field=='reconciliation':s.reconciliations=('forged-ack',)
    with pytest.raises(ValueError,match='MUTATED'):save_continuation(tmp_path/'bad.json',s)
    assert not (tmp_path/'bad.json').exists()


def test_same_new_policy_and_mission_two_assemblies():
    a,b=make_inputs(),make_inputs('outboard')
    assert a.estimation==b.estimation and a.controller_method==b.controller_method
    assert a.requests==b.requests and a.contacts==b.contacts and a.knowledge_mode==b.knowledge_mode
    assert a.model.environment==b.model.environment and a.model.actuator==b.model.actuator
