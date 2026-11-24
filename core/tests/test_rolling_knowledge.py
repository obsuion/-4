"""Information boundaries, receipt times and strict contracts (no hidden truth)."""
from dataclasses import replace, fields
import pytest
from examples.m5_rolling_mission_demo import make_inputs
from ops_sim.v5.rolling_knowledge import (KnowledgeMode,ReceivedKnowledge,IssuedCommand,receive_boundary)
from ops_sim.v5.rolling_forecast import PlanningView
from ops_sim.v5.rolling_contract import RollingPolicy,RollingQuotas


@pytest.mark.parametrize('latency',[True,-1,121,1.5,float('nan')])
def test_invalid_latency(latency):
    with pytest.raises((TypeError,ValueError)): KnowledgeMode('DELAYED_BOUNDARY_OBSERVATION',latency)


@pytest.mark.parametrize('mode,delay',[('IDEAL_BOUNDARY_OBSERVATION',1),('DELAYED_BOUNDARY_OBSERVATION',0),('implicit',0)])
def test_explicit_mode(mode,delay):
    with pytest.raises(ValueError): KnowledgeMode(mode,delay)


def test_delayed_receipt_and_future_ack_are_not_knowledge():
    root=make_inputs(scenario='C');estimate=root.initial_estimate
    future=replace(estimate,packet_id='later',observed_at_seconds=128,received_at_seconds=168,
        command_id='issued',command_status='completed',origin='OBSERVED_BOUNDARY')
    knowledge=ReceivedKnowledge(estimate,issued=(IssuedCommand('issued','CAPTURE','target','b47-medium',128,168),))
    before,queue=receive_boundary(knowledge,(future,),167)
    assert before==knowledge and len(before.pending())==1 and queue==(future,)
    after,queue=receive_boundary(before,queue,168)
    assert not queue and not after.pending() and after.observation.packet_id=='later'


def test_public_view_contains_neither_checkpoint_nor_release_schedule():
    root=make_inputs()
    view=PlanningView(root.model,128,root.requests,root.contacts,ReceivedKnowledge(root.initial_estimate),root.knowledge_mode,root.policy)
    assert 'initial_checkpoint' not in {f.name for f in fields(type(view.model))}
    assert not hasattr(view,'queued') and not hasattr(view,'context')
    future=replace(root.requests[0],release_seconds=129)
    with pytest.raises(ValueError,match='unreleased'): replace(view,requests=(future,))
    packet=replace(root.initial_estimate,received_at_seconds=129)
    with pytest.raises(ValueError,match='future'): replace(view,knowledge=ReceivedKnowledge(packet))


@pytest.mark.parametrize('name,value',[('max_decisions',65),('max_candidates',33),('max_forecasts',513),('suffix_actions',1),('lookahead_seconds',601)])
def test_policy_finite_caps(name,value):
    with pytest.raises(ValueError): replace(RollingPolicy(),**{name:value})


def test_ambiguous_temperature_knowledge_rejects():
    root=make_inputs();obs=root.initial_estimate
    resource=replace(obs.resources,observed_temperatures=obs.resources.observed_temperatures[:1])
    knowledge=ReceivedKnowledge(replace(obs,resources=resource))
    with pytest.raises(ValueError,match='every planning temperature'):
        PlanningView(root.model,128,root.requests,root.contacts,knowledge,root.knowledge_mode,root.policy)
