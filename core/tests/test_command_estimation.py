"""Paid estimates are isolated, typed, unconfirmed and reconstructed from intent."""
from dataclasses import replace,fields
from copy import deepcopy
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.command_estimation import (CommandPlanningView,CommandWork,EstimationPolicy,
    forecast_command_suffix,reconcile_intents)
from ops_sim.v5.rolling_execution import start_rolling,step_rolling,planning_view,scientific_bytes
from ops_sim.v5.long_mission import LongMissionAction as A
from ops_sim.v5.rolling_knowledge import receive_boundary


@pytest.fixture(scope='module')
def point_state():return step_rolling(start_rolling(make_inputs()))


def test_public_view_distinguishes_received_and_expected_pose(point_state):
    s=deepcopy(point_state);v=planning_view(s)
    assert type(v) is CommandPlanningView and v.now_seconds==136
    assert v.knowledge.observation.observed_at_seconds==128
    assert v.intents[0].expected_end_seconds==136 and v.intents[0].prediction_status=='ASSUMED_COMPLETED_NOT_ACKNOWLEDGED'
    assert v.knowledge.observation.attitude.quaternion!=v.intents[0].expected_attitude.quaternion
    forbidden={'checkpoint','context','actual','queued','assessments','root','physical'}
    assert not forbidden & {f.name for f in fields(v)}
    assert v.knowledge.observation.delivery_acks==()


def test_forecast_recomputes_paid_intent_and_cannot_publish_actual_credit(point_state):
    s=deepcopy(point_state);v=planning_view(s);before=scientific_bytes(s)
    f=forecast_command_suffix(v,(A('trial-capture','CAPTURE','target',4,product_id='b47-medium'),A('trial-hold','HOLD_UNTIL',until_seconds=160)),
        s.forecast_cache,s.work,s.root.quotas)
    assert f.status=='admissible'
    assert f.estimate.command_ids==('b47-command-0',)
    assert f.estimate.attitude.quaternion==v.intents[0].expected_attitude.quaternion
    assert f.estimate.observation_age_seconds==8 and f.estimate.status=='MODEL_ESTIMATE_UNCONFIRMED'
    assert f.estimate.runtime_work['physical_completed_calls']>0
    assert f.estimate.harness_work['compilation_calls']>=3
    assert s.work.estimator_command_propagations_completed>0
    assert f.predicted_records and not f.estimate.expected_records
    assert scientific_bytes(s)==before and not s.physical.acquisitions
    assert not s.physical.context.ground_data_delivery_state.completed_deliveries


def test_only_received_refusal_reconciles_and_removes_assumed_point(point_state):
    s=deepcopy(point_state);v=planning_view(s)
    packet=replace(v.knowledge.observation,packet_id='synthetic-refusal',received_at_seconds=168,
        command_id='b47-command-0',command_status='refused',command_reason='SYNTHETIC_REFUSAL',origin='OBSERVED_BOUNDARY')
    early,q=receive_boundary(v.knowledge,(packet,),167)
    assert reconcile_intents(early,v.intents)==() and q==(packet,)
    received,q=receive_boundary(v.knowledge,(packet,),168)
    rows=reconcile_intents(received,v.intents)
    assert rows[0].conclusion=='CONTRADICTED_REBASE_FROM_RECEIVED' and rows[0].observed_reason=='SYNTHETIC_REFUSAL'
    view=replace(v,now_seconds=168,knowledge=received,reconciliations=rows)
    assert view.propagation_intents()==() and received.pending()==()


def test_future_private_feedback_cannot_change_public_view(point_state):
    s=deepcopy(point_state);before=planning_view(s)
    s.queued=tuple(replace(p,resources=replace(p.resources,battery_energy_wh=1.)) for p in s.queued)
    assert planning_view(s)==before


def test_estimator_admission_before_physical_start(point_state,monkeypatch):
    s=deepcopy(point_state);s.work.estimator_invocations=512
    import ops_sim.v5.command_estimation as owner
    def forbidden(*a,**k):raise AssertionError('model work after estimator exhaustion')
    monkeypatch.setattr(owner,'start_physical',forbidden)
    with pytest.raises(ValueError,match='ESTIMATOR'):
        forecast_command_suffix(planning_view(s),(A('a','HOLD_UNTIL',until_seconds=160),A('b','HOLD_UNTIL',until_seconds=161)),s.forecast_cache,s.work,s.root.quotas)


@pytest.mark.parametrize('value',[True,0,9,1.5])
def test_policy_exact_bounded_pending(value):
    with pytest.raises(ValueError):EstimationPolicy(maximum_unreceived_intents=value)


def test_forecast_rejects_actual_cache(point_state):
    s=deepcopy(point_state)
    with pytest.raises(ValueError,match='independent'):
        forecast_command_suffix(planning_view(s),(A('a','HOLD_UNTIL',until_seconds=160),A('b','HOLD_UNTIL',until_seconds=161)),s.actual_cache,s.work,s.root.quotas)


def test_hostile_intent_text_and_frame_reject_before_work(point_state):
    class EqualText(str):
        def __eq__(self,other):return True
        def __ne__(self,other):return False
    i=point_state.intents[0]
    with pytest.raises(ValueError):replace(i,prediction_status=EqualText('wrong'))
    from ops_sim.v5.assembly_attitude_3d import BodyAttitude3D
    foreign=replace(i,expected_attitude=replace(i.expected_attitude,body_frame_id='foreign-body'))
    with pytest.raises(ValueError,match='foreign frame'):replace(planning_view(point_state),intents=(foreign,))
