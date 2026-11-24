"""Paid forecast isolation and immutable tensor/geometry authority."""
from dataclasses import replace
from hashlib import sha256
import pytest
from examples.m5_rolling_mission_demo import make_inputs
from ops_sim.v5.rolling_execution import start_rolling,planning_view,scientific_bytes
from ops_sim.v5.rolling_forecast import forecast_suffix
from ops_sim.v5.long_mission import LongMissionAction as Action


def test_forecast_isolation_and_physical_cost():
    state=start_rolling(make_inputs());before=scientific_bytes(state)
    view=planning_view(state)
    suffix=(Action('trial-point','POINT','target'),Action('trial-image','CAPTURE','target',4,product_id='b47-medium'))
    result=forecast_suffix(view,suffix,state.forecast_cache,state.work,state.root.quotas)
    assert result.status=='admissible'
    assert result.harness_work['compilation_calls']>=4
    assert result.runtime_work['physical_completed_calls']>0
    assert result.construction_work['line_calls_reserved']>0
    assert result.predicted_outcomes[0].slew.hardware.tensor_exact==state.physical.harness.hardware.tensor_exact
    assert scientific_bytes(state)==before and state.work.forecast_invocations==1


def test_refused_forecast_keeps_paid_work():
    state=start_rolling(make_inputs());view=planning_view(state)
    result=forecast_suffix(view,(Action('point','POINT','target'),Action('short','CAPTURE','target',4,product_id='b47-urgent')),
        state.forecast_cache,state.work,state.root.quotas)
    assert result.status=='refused' and result.reason=='ACQUISITION_WINDOW_MISSED'
    assert state.work.invocation_records[-1]['runtime']['physical_completed_calls']>0
    assert not state.physical.acquisitions


def test_actual_cache_cannot_seed_forecast():
    state=start_rolling(make_inputs());view=planning_view(state)
    with pytest.raises(ValueError,match='independent'):
        forecast_suffix(view,(Action('a','HOLD_UNTIL',until_seconds=129),Action('b','HOLD_UNTIL',until_seconds=130)),
            state.actual_cache,state.work,state.root.quotas)


def test_forecast_adapter_never_increases_a_smaller_input_document_limit():
    from ops_sim.v5.rolling_physics import start_physical
    root=make_inputs();model=replace(root.model,limits=replace(root.model.limits,max_document_bytes=16*2**20))
    state=start_rolling(replace(root,model=model))
    physical=start_physical(model,root.initial_checkpoint.restore(model.simulation_inputs),state.physical.attitude,
        tuple(r.product for r in root.requests),state.forecast_cache,'LOWER_DOCUMENT_LIMIT',forecast=True)
    assert physical.inputs.limits.max_document_bytes==16*2**20
