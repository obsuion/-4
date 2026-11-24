"""Exact prepared history reporting; reference owners remain independent."""
from copy import deepcopy
from dataclasses import asdict,replace
from fractions import Fraction as Q

import pytest

from lifetime_support import root_for
from ops_sim.v5.environment_ageing import initial_state
from ops_sim.v5.environment_lifecycle import projection,validate_projection
from ops_sim.v5 import environment_reporting,lifetime_reporting
from ops_sim.v5.lifecycle_contract import canonical
from ops_sim.v5.lifecycle_execution import build_model
from ops_sim.v5.lifecycle_prepared import MAX_CACHE_ENTRIES,MAX_OPERATIONAL_UNITS,prepare_runtime
from ops_sim.v5.lifecycle_report import LifecycleReport
from ops_sim.v5.long_mission_continuation import _scientific

SOURCE='6'*64

@pytest.fixture
def prepared():
    root=deepcopy(root_for(600));model=build_model(root)
    return prepare_runtime(root,model,'ACTUAL',SOURCE)

def sample(prepared,elapsed=0,pv=0.,thermal=0.,cuts=0):
    state=initial_state(prepared.environment_policy,prepared.root.start_seconds,prepared.baseline,1.)
    return replace(state,clock_seconds=Q(prepared.root.start_seconds)+Q(elapsed),
        calendar_seconds=Q(prepared.environment_policy.initial_calendar_seconds)+Q(elapsed),
        pv_exposure_seconds=pv,thermal_exposure_seconds=thermal,selected_cuts=cuts)

def arguments(prepared):return prepared._external_policy,prepared._external_baseline
def encoded(value):return canonical(_scientific(value)).encode('utf8')

@pytest.mark.parametrize('elapsed,pv,thermal,cuts',[(0,0.,0.,0),(Q(1,3),.125,.25,1),
    (120,67.25,120.,3),(600,300.,600.,20)])
def test_full_canonical_projection_matches_unchanged_reference(prepared,elapsed,pv,thermal,cuts):
    policy,baseline=arguments(prepared);history=sample(prepared,elapsed,pv,thermal,cuts)
    before=asdict(history)
    expected=projection(policy,history,baseline)
    actual=projection(policy,history,baseline,prepared_runtime=prepared)
    assert encoded(actual)==encoded(expected)
    assert asdict(history)==before
    assert prepared.snapshot()['cache_entries']==1
    assert prepared.snapshot()['coefficient_realizations']==1

def test_history_and_complete_network_digest_once_per_miss(prepared,monkeypatch):
    import ops_sim.v5.lifecycle_prepared as owner
    original=owner.digest;calls=[]
    def recorded(value):
        calls.append(type(value).__name__);return original(value)
    monkeypatch.setattr(owner,'digest',recorded)
    policy,baseline=arguments(prepared);history=sample(prepared,60,20.,60.,3)
    first=prepared.environment_projection(policy,history,baseline)
    second=prepared.environment_projection(policy,deepcopy(history),baseline)
    prepared.environment_metrics(policy,history,baseline)
    assert first==second
    assert calls.count('EnvironmentAgeingState')==1
    assert calls.count('ThermalNetworkConfig')==1
    assert prepared.snapshot()['cache_hits']==2
    assert prepared.snapshot()['state_digests']==1

def test_returned_maps_are_fresh_and_cannot_poison_cached_history(prepared):
    policy,baseline=arguments(prepared);history=sample(prepared,60,20.,60.,3)
    original=prepared.environment_projection(policy,history,baseline);expected=encoded(original)
    original['emissivity'][next(iter(original['emissivity']))]=-1.
    original['conductance_w_per_k'].clear();original['state_identity']='0'*64
    later=prepared.environment_projection(policy,history,baseline)
    assert encoded(later)==expected
    assert later is not original and later['emissivity']is not original['emissivity']

def test_exact_old_history_survives_newer_queries_and_eight_entry_eviction(prepared):
    assert MAX_CACHE_ENTRIES==8
    policy,baseline=arguments(prepared);old=sample(prepared)
    first=prepared.environment_projection(policy,old,baseline)
    for i in range(1,MAX_CACHE_ENTRIES+2):
        prepared.environment_projection(policy,sample(prepared,i*30,float(i*10),float(i*30),i),baseline)
    assert prepared.snapshot()['cache_entries']==8
    assert prepared.snapshot()['cache_evictions']==2
    again=prepared.environment_projection(policy,old,baseline)
    assert encoded(first)==encoded(again)
    assert prepared.snapshot()['coefficient_realizations']==11

def test_caller_history_mutation_uses_new_key_without_mutating_retained_projection(prepared):
    policy,baseline=arguments(prepared);history=sample(prepared,60,20.,60.,3)
    before=prepared.environment_projection(policy,history,baseline);raw=encoded(before)
    object.__setattr__(history,'selected_cuts',4)
    after=prepared.environment_projection(policy,history,baseline)
    assert encoded(before)==raw
    assert before['state_identity']!=after['state_identity']and after['selected_cuts']==4

@pytest.mark.parametrize('field',['policy_identity','baseline_network_identity'])
def test_history_provenance_refused_even_when_valid_history_is_cached(prepared,field):
    policy,baseline=arguments(prepared);history=sample(prepared)
    prepared.environment_projection(policy,history,baseline)
    with pytest.raises(ValueError,match='stale/foreign'):
        prepared.environment_projection(policy,replace(history,**{field:'f'*64}),baseline)
    assert prepared.snapshot()['cache_entries']==1

@pytest.mark.parametrize('part',['policy','coefficient','provenance'])
def test_caller_static_and_provenance_mutation_refused_on_hit(prepared,part):
    policy,baseline=arguments(prepared);history=sample(prepared)
    prepared.environment_projection(policy,history,baseline)
    if part=='policy':target,name=policy,'pv_floor_fraction'
    elif part=='coefficient':target,name=baseline.nodes[0].emissivity,'value'
    else:target,name=baseline.nodes[0].emissivity.provenance,'rationale'
    old=getattr(target,name)
    try:
        object.__setattr__(target,name,'hostile change'if part=='provenance'else old*.9)
        with pytest.raises(ValueError,match='drift'):
            prepared.environment_projection(policy,history,baseline)
    finally:object.__setattr__(target,name,old)

def test_evolving_coefficients_and_signed_zero_are_not_initial_state_cache(prepared):
    policy,baseline=arguments(prepared);initial=sample(prepared)
    zero=prepared.environment_projection(policy,initial,baseline)
    negative_zero=prepared.environment_projection(policy,replace(initial,pv_exposure_seconds=-0.),baseline)
    evolved=prepared.environment_projection(policy,sample(prepared,600,300.,600.,20),baseline)
    assert encoded(zero)!=encoded(negative_zero)
    assert zero['state_identity']!=negative_zero['state_identity']
    assert zero['effective_network_identity']!=evolved['effective_network_identity']
    assert zero['pv_retention']!=evolved['pv_retention']

def test_rejected_forecast_sample_never_enters_actual_report_history(prepared):
    forecast=prepare_runtime(prepared._external_root,prepared._external_model,'FORECAST',SOURCE)
    root=prepared._external_root;policy,baseline=arguments(prepared);history=sample(prepared)
    actual=environment_reporting.initial(root,history,prepared_runtime=prepared);before=encoded(actual)
    forecast.environment_projection(policy,sample(prepared,120,90.,120.,10),baseline)
    assert encoded(actual)==before
    assert prepared.snapshot()['cache_entries']==1 and forecast.snapshot()['cache_entries']==1
    with pytest.raises(TypeError,match='ACTUAL'):
        environment_reporting.initial(root,history,prepared_runtime=forecast)

def test_canonical_saved_projection_stays_strict_with_prepared_cache(prepared):
    root=prepared._external_root;policy,baseline=arguments(prepared);history=sample(prepared,60,20.,60.,3)
    value=projection(policy,history,baseline,prepared_runtime=prepared)
    assert validate_projection(value,root,history.clock_seconds,prepared_runtime=prepared)==history
    changed=deepcopy(value);changed['state_identity']='f'*64
    for runtime in(None,prepared):
        with pytest.raises(ValueError,match='type/provenance/clock'):
            validate_projection(changed,root,history.clock_seconds,prepared_runtime=runtime)

def test_failed_network_digest_keeps_attempts_but_no_partial_cache_entry(prepared,monkeypatch):
    import ops_sim.v5.lifecycle_prepared as owner
    original=owner.digest;policy,baseline=arguments(prepared);history=sample(prepared)
    def injected(value):
        if type(value).__name__=='ThermalNetworkConfig':raise RuntimeError('EXPECTED_INJECTED_NETWORK_DIGEST_FAILURE')
        return original(value)
    monkeypatch.setattr(owner,'digest',injected)
    with pytest.raises(RuntimeError,match='EXPECTED_INJECTED'):
        prepared.environment_projection(policy,history,baseline)
    failed=prepared.snapshot()
    assert failed['cache_entries']==0 and failed['environment_failed']==1
    assert failed['coefficient_attempts']==failed['coefficient_realizations']==1
    monkeypatch.setattr(owner,'digest',original)
    assert prepared.environment_projection(policy,history,baseline)==projection(policy,history,baseline)
    assert prepared.snapshot()['coefficient_attempts']==2

def test_output_control_refusal_does_not_refund_or_publish_state(prepared):
    policy,baseline=arguments(prepared);history=sample(prepared)
    prepared.environment_projection(policy,history,baseline)
    prepared._work['control_units_reserved']=MAX_OPERATIONAL_UNITS-1
    with pytest.raises(ValueError,match='PREPARATION_WORK_LIMIT'):
        prepared.environment_projection(policy,history,baseline)
    assert prepared._work['control_units_reserved']==MAX_OPERATIONAL_UNITS-1
    assert len(prepared._cache)==1

def test_environment_and_bucket_report_forwarding_preserves_complete_data(prepared):
    root=prepared._external_root;before=sample(prepared);after=sample(prepared,60,20.,60.,3)
    plain=environment_reporting.initial(root,before)
    bound=environment_reporting.initial(root,before,prepared_runtime=prepared)
    a=environment_reporting.advance(plain,root,before,after)
    b=environment_reporting.advance(bound,root,before,after,prepared_runtime=prepared)
    assert encoded(a)==encoded(b)
    environment_reporting.validate(b,root,root.start_seconds,root.start_seconds+60,prepared_runtime=prepared)
    x=lifetime_reporting.initial(root,before);y=lifetime_reporting.initial(root,before,prepared_runtime=prepared)
    x=lifetime_reporting.advance(x,root,before,after)
    y=lifetime_reporting.advance(y,root,before,after,prepared_runtime=prepared)
    assert encoded(x)==encoded(y)
    lifetime_reporting.validate(y,root,root.start_seconds+60,prepared_runtime=prepared)

def test_report_summary_uses_optional_runtime_without_persisting_it(prepared):
    root=prepared._external_root
    context=root.base.initial_checkpoint.restore(root.base.model.simulation_inputs)
    report=LifecycleReport(root,context,environment_ageing_state=sample(prepared))
    before=encoded(report.state)
    plain=report.summary();bound=report.summary(prepared_runtime=prepared)
    assert encoded(plain)==encoded(bound)and encoded(report.state)==before
    assert not any('prepared'in name or 'backend'in name for name in report.state)
    changed=deepcopy(report.state);changed['environment_ageing']['end']['pv_retention']=-1.
    with pytest.raises(ValueError):report._validate(changed,prepared_runtime=prepared)
    assert encoded(report.state)==before
