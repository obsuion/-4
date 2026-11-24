"""Independent private-step cases for the explicitly versioned V5 owner."""
from copy import deepcopy
from dataclasses import fields, replace
from fractions import Fraction as Q

import pytest

from ops_sim.v5.lifecycle_quiet import (
    QuietIntegrationPolicy, BatteryQuietIntegrationPolicy, EnvironmentQuietIntegrationPolicy,
    QuietControllerState, QuietSample, QuietTrial, QuietTrialRefusal, QuietWork,
    ShortCircuitQuietWork, integrate_quiet_hold, quiet_work_for, short_circuit_policy,
    quiet_reason_counts_v5,
)


def policy(short, **changes):
    p=replace(QuietIntegrationPolicy(),minimum_macro_seconds=4,maximum_macro_seconds=4,**changes)
    return short_circuit_policy(p) if short else p


def execute(p, *, behavior='linear', fail=None, role='REFERENCE', end=4, initial=None):
    trace=[];work=quiet_work_for(p)
    def step(context,left,right):
        dt=right-left;trace.append((left,right))
        if fail is not None:fail(context,left,right,len(trace))
        value=context['value']+float(dt)*(context['value'] if behavior=='norm' else 1.)
        context['value']=value
        near=(behavior=='full_near' and dt==4) or (behavior=='first_near' and dt==2 and left==0)
        regime=('B',)if behavior=='regime'and dt==2 and left==0 else('A',)
        sample=QuietSample((('energy_wh',value),),(('generation_wh',float(dt)),),regime,near)
        return QuietTrial(context,(left,right,value),sample)
    origin={'value':1. if behavior=='norm'else 0.}
    if initial is not None:origin=initial
    try:
        result=integrate_quiet_hold(origin,Q(0),Q(end),policy=p,
            controller=QuietControllerState(Q(0),4,method=p.method),work=work,
            clone_context=deepcopy,state_values=lambda c:(('energy_wh',c['value']),),
            step=step,reason_role=role)
    except BaseException as error:
        error.test_work=work;error.test_trace=trace;raise
    assert origin==({'value':1. if behavior=='norm'else 0.}if initial is None else initial)
    return result,work,trace


@pytest.mark.parametrize('owner',[QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy])
def test_explicit_method_opt_in_preserves_all_other_fields(owner):
    old=owner();new=short_circuit_policy(old)
    assert type(new)is type(old) and new.method!=old.method
    assert {f.name:getattr(old,f.name)for f in fields(old)if f.name!='method'}=={
        f.name:getattr(new,f.name)for f in fields(new)if f.name!='method'}
    assert type(quiet_work_for(old))is QuietWork
    assert type(quiet_work_for(new))is ShortCircuitQuietWork
    assert short_circuit_policy(new)==new


@pytest.mark.parametrize('behavior,skipped,fulls,halves',[('full_near',2,1,0),('first_near',1,1,1),('regime',1,1,1)])
def test_proved_rejection_avoids_exact_unperformed_calls(behavior,skipped,fulls,halves):
    old,old_work,old_trace=execute(policy(False),behavior=behavior)
    new,work,trace=execute(policy(True),behavior=behavior)
    assert new.context==old.context and new.cuts==old.cuts
    assert new.controller.clock_seconds==old.controller.clock_seconds==4
    assert work.skipped_half_trial_calls==skipped
    assert len(old_trace)-len(trace)==skipped
    assert work.full_trial_calls==fulls and work.half_trial_calls==halves
    assert work.reserved_leaf_calls==work.returned_leaf_calls==len(trace)
    assert work.reserved_leaf_calls+skipped==old_work.reserved_leaf_calls
    assert work.norm_evaluations==0 and work.norm_not_evaluated_early==1
    assert work.detailed_fallback_calls==2
    work.validate(policy(True))


def test_ordinary_acceptance_selects_two_halves_not_full():
    old,old_work,old_trace=execute(policy(False))
    new,work,trace=execute(policy(True))
    assert new.context==old.context and new.cuts==old.cuts
    assert trace==old_trace==[(Q(0),Q(4)),(Q(0),Q(2)),(Q(2),Q(4))]
    assert [right-left for left,right,value in new.cuts]==[2,2]
    assert work.accepted_macros==1 and work.skipped_half_trial_calls==0
    assert work.first_half_calls==work.second_half_calls==1
    assert work.norm_evaluations==1 and work.norm_rejections==0
    assert new.controller.last_error_norm==old.controller.last_error_norm==0.


def test_norm_only_rejection_still_executes_all_trials():
    old,_,old_trace=execute(policy(False),behavior='norm')
    new,work,trace=execute(policy(True),behavior='norm')
    assert trace==old_trace and new.context==old.context and new.cuts==old.cuts
    assert work.skipped_half_trial_calls==0 and work.norm_evaluations==work.norm_rejections==1
    assert work.rejected_macros==1 and work.detailed_fallback_calls==2


def test_quota_difference_is_truthful_not_fake_complete_or_refund():
    p=policy(True,max_total_leaf_calls=3)
    result,work,trace=execute(p,behavior='full_near')
    assert result.context['value']==4 and work.reserved_leaf_calls==3
    assert work.skipped_half_trial_calls==2 and len(trace)==3
    with pytest.raises(ValueError,match='QUIET_CUMULATIVE_LEAF_QUOTA')as caught:
        execute(policy(False,max_total_leaf_calls=3),behavior='full_near')
    assert caught.value.test_work.reserved_leaf_calls==3
    assert caught.value.test_work.selected_parts==0


def test_known_refusal_uses_original_rejection_then_fallback():
    class PhysicalFailure(ValueError):reason='KNOWN_TEST_DOMAIN'
    def failure(context,left,right,count):
        if right-left==4:raise QuietTrialRefusal(PhysicalFailure('known'))
    old,ow,ot=execute(policy(False),fail=failure)
    new,w,t=execute(policy(True),fail=failure)
    assert new.context==old.context and new.cuts==old.cuts and t==ot
    assert w.refused_leaf_calls==1 and w.skipped_half_trial_calls==0
    assert w.returned_leaf_calls==2 and w.reserved_leaf_calls==3


def test_unexpected_leaf_error_is_not_fallback():
    original=RuntimeError('original implementation failure')
    def failure(*args):raise original
    with pytest.raises(RuntimeError)as caught:execute(policy(True),fail=failure)
    assert caught.value is original
    assert original.test_work.reserved_leaf_calls==original.test_work.unknown_leaf_calls==1
    assert original.test_work.detailed_fallback_calls==0


def test_invalid_initial_metrics_refused_before_any_performed_leaf():
    with pytest.raises(ValueError,match='initial quiet metric')as caught:
        execute(policy(True),behavior='full_near',initial={'value':float('nan')})
    assert caught.value.test_trace==[] and caught.value.test_work.reserved_leaf_calls==0


def test_full_near_does_not_mask_wrong_authority_vector():
    p=policy(True);work=quiet_work_for(p);calls=[]
    def malformed(context,left,right):
        calls.append((left,right))
        return QuietTrial(context,None,QuietSample((('another_metric',0.),),(('generation_wh',0.),),(),True))
    with pytest.raises(ValueError,match='authority/order'):
        integrate_quiet_hold({},Q(0),Q(4),policy=p,controller=QuietControllerState(Q(0),4,method=p.method),
            work=work,clone_context=deepcopy,state_values=lambda c:(('energy_wh',0.),),step=malformed)
    assert len(calls)==1 and work.skipped_half_trial_calls==0 and work.norm_evaluations==0


@pytest.mark.parametrize('work',[QuietWork(),object()])
def test_policy_cannot_silently_reuse_legacy_or_foreign_work(work):
    p=policy(True)
    with pytest.raises(TypeError,match='matching quiet'):
        integrate_quiet_hold({},0,4,policy=p,controller=QuietControllerState(Q(0),4,method=p.method),work=work,
            clone_context=deepcopy,state_values=lambda c:(('energy_wh',0.),),step=lambda *a:None)


def test_actual_forecast_work_and_diagnostic_roles_are_separate():
    before=quiet_reason_counts_v5()
    actual,aw,_=execute(policy(True),behavior='full_near',role='ACTUAL')
    forecast,fw,_=execute(policy(True),behavior='full_near',role='FORECAST')
    after=quiet_reason_counts_v5()
    assert aw is not fw and aw==fw and actual.context==forecast.context
    for role in('ACTUAL','FORECAST'):
        old=before['roles'][role]['counts'];new=after['roles'][role]['counts']
        assert new['skipped_half_trials']-old.get('skipped_half_trials',0)==2
        assert new['full_trial_performed']-old.get('full_trial_performed',0)==1
        assert new['detailed_fallback_performed']-old.get('detailed_fallback_performed',0)==2
    assert after['reset_available']is False and after['skipped_error_norm']=='NOT_MEASURED'


def test_work_mutation_cannot_create_unpaid_skips():
    p=policy(True);work=quiet_work_for(p);work.skipped_half_trial_calls=1
    with pytest.raises(ValueError,match='performed/skipped'):work.validate(p)


def test_shortened_boundary_keeps_exact_support_and_next_proposal():
    old,_,ot=execute(policy(False),end=3)
    new,w,t=execute(policy(True),end=3)
    assert new.context==old.context and new.cuts==old.cuts and t==ot
    assert w.below_minimum_fallbacks==2 and w.selected_seconds==3
    assert new.controller.next_step_seconds==old.controller.next_step_seconds==4


@pytest.mark.parametrize('name', ['_reason_sample_v5','_reason_regime_v5','_quiet_complete_sample_v5','is_short_circuit_policy','quiet_work_for'])
def test_changed_quiet_owner_function_refused_without_invocation(monkeypatch,name):
    from ops_sim.v5 import lifecycle_job_prepared as prepared,lifecycle_quiet as quiet
    seal=prepared._SchemaSeal();called=[]
    def hostile(*args,**kwargs):called.append(True);raise AssertionError('mutated owner must never run')
    original=getattr(quiet,name)
    try:
        monkeypatch.setattr(quiet,name,hostile)
        with pytest.raises(ValueError,match='prepared function drift'):seal.guard()
        assert called==[]
    finally:
        monkeypatch.setattr(quiet,name,original)
        seal.codec.__exit__(None,None,None)


@pytest.mark.parametrize('owner,name',[(QuietWork,'reserve'),(ShortCircuitQuietWork,'early'),(ShortCircuitQuietWork,'performed')])
def test_changed_paid_work_method_refused_without_invocation(monkeypatch,owner,name):
    from ops_sim.v5 import lifecycle_job_prepared as prepared
    seal=prepared._SchemaSeal();called=[]
    def hostile(*args,**kwargs):called.append(True);raise AssertionError('mutated work method must never run')
    original=getattr(owner,name)
    try:
        monkeypatch.setattr(owner,name,hostile)
        with pytest.raises(ValueError,match='prepared function drift'):seal.guard()
        assert called==[]
    finally:
        monkeypatch.setattr(owner,name,original)
        seal.codec.__exit__(None,None,None)


def test_changed_quiet_function_code_refused_without_invocation():
    from ops_sim.v5 import lifecycle_job_prepared as prepared,lifecycle_quiet as quiet
    seal=prepared._SchemaSeal();fn=quiet._reason_sample_v5;original=fn.__code__
    def alternative(*args,**kwargs):return None
    try:
        fn.__code__=alternative.__code__
        with pytest.raises(ValueError,match='prepared function drift'):seal.guard()
    finally:
        fn.__code__=original
        seal.codec.__exit__(None,None,None)


@pytest.mark.parametrize('name,value',[
    ('SHORT_QUIET_METHODS',('B61_UNIT_AWARE_ENVIRONMENT_QUIET_V1',)),
    ('SHORT_ENVIRONMENT_QUIET_METHOD','unversioned'),('_REASON_LIMIT_V5',0),
    ('_REASONS_V5',{}),
])
def test_method_selector_or_counter_authority_cannot_be_switched_as_live_flag(monkeypatch,name,value):
    from ops_sim.v5 import lifecycle_job_prepared as prepared,lifecycle_quiet as quiet
    seal=prepared._SchemaSeal();original=getattr(quiet,name)
    try:
        monkeypatch.setattr(quiet,name,value)
        with pytest.raises(ValueError,match='prepared function drift'):seal.guard()
    finally:
        monkeypatch.setattr(quiet,name,original)
        seal.codec.__exit__(None,None,None)
