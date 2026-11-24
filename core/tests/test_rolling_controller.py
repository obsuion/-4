"""Nontrivial paid priority/timing and public-input causal negatives."""
from dataclasses import replace
from examples.m5_rolling_mission_demo import make_inputs
from ops_sim.v5.rolling_execution import start_rolling,planning_view,step_rolling
from ops_sim.v5.rolling_controller import select_rolling,build_candidates
from ops_sim.v5.rolling_knowledge import ReceivedKnowledge
from ops_sim.v5.rolling_forecast import PlanningView


def test_common_policy_skips_tight_priority_by_paid_timing():
    state=start_rolling(make_inputs());view=planning_view(state)
    decision=select_rolling(view,state.forecast_cache,state.work,state.root.quotas)
    assert decision.selected_suffix[0].kind=='POINT'
    assert any('ACQUISITION_WINDOW_MISSED' in reason for _,reason in decision.rejected)
    assert 'medium' in decision.explanation
    assert 2<=len(decision.selected_suffix)<=4
    state=step_rolling(state)
    assert state.physical.cursor==1 and not state.physical.acquisitions


def test_future_schedule_and_ack_changes_leave_actual_public_input_equal():
    root=make_inputs(scenario='C');future=replace(root.requests[0],release_seconds=200,
        product=replace(root.requests[0].product,acquisition_end_seconds=250))
    one=replace(root,requests=(future,*root.requests[1:]))
    altered=replace(future,product=replace(future.product,delivery_deadline_seconds=340))
    two=replace(root,requests=(altered,*root.requests[1:]))
    def public(r):
        return PlanningView(r.model,128,tuple(x for x in r.requests if x.release_seconds<=128),r.contacts,
            ReceivedKnowledge(r.initial_estimate),r.knowledge_mode,r.policy)
    a,b=public(one),public(two)
    assert a==b and a.identity==b.identity and build_candidates(a)==build_candidates(b)
    # A future private packet never enters this API: received knowledge is held
    # exactly fixed. Changing only unreleased input cannot change kernel calls.
    s1=start_rolling(one);s2=start_rolling(two)
    s2.queued=(replace(s2.queued[0],resources=replace(s2.queued[0].resources,battery_energy_wh=10.)),)
    assert planning_view(s1)==planning_view(s2)
    d1=select_rolling(a,s1.forecast_cache,s1.work,one.quotas)
    d2=select_rolling(b,s2.forecast_cache,s2.work,two.quotas)
    assert d1==d2


def test_declared_sampling_mismatch_is_screened_without_physics():
    root=make_inputs();obs=ReceivedKnowledge(root.initial_estimate)
    requests=tuple(replace(r,product=replace(r.product,maximum_spacing_x_m=6.25,maximum_spacing_y_m=6.25)) for r in root.requests)
    view=PlanningView(root.model,128,requests,root.contacts,obs,root.knowledge_mode,root.policy)
    candidates,rejected=build_candidates(view)
    assert not any(a.kind=='CAPTURE' for _,suffix in candidates for a in suffix)
    assert sum(reason=='DECLARED_MS_SAMPLING_CAPABILITY_INSUFFICIENT' for _,reason in rejected)==3
