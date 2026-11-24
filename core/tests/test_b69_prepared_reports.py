"""Actual prepared consumers at initial frontier; no hidden mission advances."""
from copy import deepcopy
import sys
from math import nextafter,inf
import pytest
from test_lifecycle_b65 import started_pair
from ops_sim.v5.lifecycle_state import guard_lifecycle
from ops_sim.v5 import environment_ageing,environment_reporting,lifetime_reporting
from ops_sim.v5.lifecycle_report import LifecycleReport
from ops_sim.v5.lifecycle_document import canonical

def test_real_guard_report_and_received_history_callers_use_distinct_roles():
    state,_=started_pair();ctx=state.backend_context;seen=[];old=sys.getprofile()
    codes={environment_ageing.guard.__code__:'history',
           environment_reporting.validate.__code__:'selected-report',
           lifetime_reporting.validate.__code__:'lifetime-report'}
    def trace(frame,event,arg):
        if event=='call'and frame.f_code in codes:
            role=frame.f_locals.get('prepared_runtime')
            seen.append((codes[frame.f_code],None if role is None else role.role))
    before=ctx.native.native_entry_counts()
    sys.setprofile(trace)
    try:
        with ctx.transaction():
            guard_lifecycle(state)
            actual=state.report.summary(prepared_runtime=ctx.actual)
    finally:sys.setprofile(old)
    assert ('history','FORECAST')in seen
    assert ('selected-report','ACTUAL')in seen and ('lifetime-report','ACTUAL')in seen
    assert before==ctx.native.native_entry_counts()
    # Public fallback remains a full independent validator.
    expected=state.report.summary()
    assert canonical(actual)==canonical(expected)
    assert ctx.job.actual._cache is not ctx.job.forecast._cache

@pytest.mark.parametrize('target',('emissivity','state_identity','clock_seconds','selected_cuts'))
def test_warmed_projection_never_accepts_mutated_report_dictionary(target):
    state,_=started_pair();ctx=state.backend_context;data=state.report.state
    with ctx.transaction():
        state.report.validate(prepared_runtime=ctx.actual)
        value=data['environment_ageing']['end'];saved=deepcopy(value)
        try:
            if target=='emissivity':
                key=next(iter(value[target]));value[target][key]=nextafter(value[target][key],inf)
            elif target=='state_identity':value[target]='f'*64
            elif target=='clock_seconds':value[target]=str(int(value[target])+1)
            else:value[target]+=1
            with pytest.raises(ValueError):state.report.validate(prepared_runtime=ctx.actual)
        finally:value.clear();value.update(saved)
        state.report.validate(prepared_runtime=ctx.actual)
    assert len(ctx.actual._cache)<=8 and len(ctx.forecast._cache)<=8

def test_offer_and_seal_forward_current_private_report_runtime():
    state,_=started_pair();ctx=state.backend_context;report=state.report;seen=[];old=sys.getprofile()
    def trace(frame,event,arg):
        if event=='call'and frame.f_code is LifecycleReport._validate.__code__:
            seen.append(frame.f_locals.get('prepared_runtime'))
    before=ctx.native.native_entry_counts();sys.setprofile(trace)
    try:
        with ctx.transaction():
            report.offer(0,float(report._expected_weight),prepared_runtime=ctx.actual)
            row=report.seal(state.physical.context,terminal=True,prepared_runtime=ctx.actual)
    finally:sys.setprofile(old)
    assert len(seen)>=4 and all(x is ctx.actual for x in seen)
    assert row['offered']==1 and row['credits']==0
    assert before==ctx.native.native_entry_counts()

def test_private_report_runtime_outside_transaction_and_forecast_refused():
    state,_=started_pair();ctx=state.backend_context
    with pytest.raises(ValueError):state.report.validate(prepared_runtime=ctx.actual)
    with ctx.transaction():
        with pytest.raises(TypeError):state.report.validate(prepared_runtime=ctx.forecast)
    state.report.validate()

def test_callback_report_helper_mutation_keeps_primary_and_no_publication():
    state,_=started_pair();ctx=state.backend_context;original=LifecycleReport._validate
    old_code=original.__code__;primary=RuntimeError('original external callback');published=[]
    def replacement(self,data,*,prepared_runtime=None):return data
    def external():
        original.__code__=replacement.__code__
        raise primary
    try:
        with pytest.raises(RuntimeError)as caught:
            with ctx.transaction():
                ctx.job.require_transaction().callback(external)
            published.append(True)
        assert caught.value is primary and not published and getattr(primary,'__notes__',[])
        assert ctx.job._active is None
    finally:original.__code__=old_code
