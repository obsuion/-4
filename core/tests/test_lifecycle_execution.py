"""Actual new-owner transactions; no long campaign or B48 full run here."""
from dataclasses import replace
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection,progress_projection
from ops_sim.v5.lifecycle_state import guard_lifecycle

def test_short_execution_uses_bounded_owner_not_old_coordinator(monkeypatch):
    import ops_sim.v5.rolling_execution as old
    def forbidden(*a,**k):raise AssertionError('old full prefix owner called')
    monkeypatch.setattr(old,'start_rolling',forbidden);monkeypatch.setattr(old,'step_rolling',forbidden)
    root=LifecycleRoot(make_inputs(wire='nominal'),600)
    state=start_lifecycle(root);previous=state.clock;chain=state.event_chain
    for _ in range(8):
        state,event,row=step_lifecycle(state)
        assert event['start_seconds']==previous
        assert state.clock>=previous
        assert state.event_chain!=chain
        previous=state.clock;chain=state.event_chain
        guard_lifecycle(state)
    assert not hasattr(state.physical,'outcomes')
    assert not hasattr(state,'decisions')
    assert len(state.recent)<=root.policy.recent_records
    assert state.work.transitions_completed==8
    assert state.work.controller_decisions>0
    assert state.knowledge.received_at_seconds<=state.clock
    assert scientific_projection(state)['clock']==state.clock

def test_quota_refusal_preserves_context_and_spent_reservation():
    root=LifecycleRoot(make_inputs(wire='nominal'),600,policy=LifecyclePolicy(max_transitions=1))
    state=start_lifecycle(root);state,_,_=step_lifecycle(state)
    before=state.clock
    with pytest.raises(ValueError,match='QUOTA|ADMISSION'):step_lifecycle(state)
    assert state.clock==before
    assert state.work.transitions_reserved==1

def test_progress_distinguishes_simulated_horizon_and_cache():
    root=LifecycleRoot(make_inputs(wire='nominal'),86400)
    state=start_lifecycle(root);p=progress_projection(state)
    assert p['simulated_seconds']==0 and p['end_seconds']==86528
    assert p['actual_cache']['retained_grid']==1
    assert p['credits']==0


def test_refused_quiet_evolution_stops_without_repeating_zero_time(monkeypatch):
    import ops_sim.v5.lifecycle_execution as owner
    from ops_sim.v5.lifecycle_physics import _refused
    from ops_sim.v5.long_mission import _Refusal
    state=start_lifecycle(LifecycleRoot(make_inputs(wire='nominal'),600))
    monkeypatch.setattr(owner,'_select',lambda s:(None,'',None))
    calls=[]
    def refuse(physical,action,**kwargs):
        calls.append(action)
        return _refused(physical,action,_Refusal('OPERATING_TEMPERATURE_AT_ENDPOINT'))
    monkeypatch.setattr(owner,'execute_lifecycle_action',refuse)
    stopped,event,_=step_lifecycle(state)
    assert stopped.clock==128 and stopped.status=='INCOMPLETE_NO_PROGRESS_HOLD_REFUSAL'
    assert event['reason']=='OPERATING_TEMPERATURE_AT_ENDPOINT'
    assert stopped.work.transitions_completed==1 and stopped.report.summary()['totals']['refused_actions']==1
    with pytest.raises(ValueError):step_lifecycle(stopped)
    assert len(calls)==1
