from dataclasses import replace
from fractions import Fraction as Q
import pytest
from tests.test_long_environment import fresh,genuine
from ops_sim.v5.long_mission import advance_long_mission
from ops_sim.v5.checkpoint import CheckpointState

def finish(state):
    while state.cursor<len(state.inputs.actions):state=advance_long_mission(state)
    return state


def test_same_ids_altered_context_input_rejects_before_work():
    state=fresh();before=state.runtime_work.physical_reserved_calls
    cfg=state.context.inputs.spacecraft_configuration
    state.context.inputs=replace(state.context.inputs,spacecraft_configuration=replace(cfg,
        eps=replace(cfg.eps,battery=replace(cfg.eps.battery,max_discharge_output_power_w=
            replace(cfg.eps.battery.max_discharge_output_power_w,value=1.)))))
    with pytest.raises(ValueError,match='MUTATED_CONTEXT'):advance_long_mission(state)
    assert state.runtime_work.physical_reserved_calls==before

def test_genuine_600_second_paid_chain_and_no_idle_reset():
    state=finish(fresh())
    assert state.context.simulation_time_seconds==728 and len(state.acquisitions)==1
    assert len(state.context.ground_data_delivery_state.completed_deliveries)==1
    assert len(state.assessment()[0].credited_record_ids)==1
    assert state.outcomes[0].slew.duration_seconds>0 and state.outcomes[0].cuts
    assert all(c.kinetic_start_exact_j>=0 and c.kinetic_end_exact_j>=0 for c in state.outcomes[0].cuts)
    hold=state.outcomes[-1]
    assert hold.end_seconds-hold.start_seconds>=500 and len(hold.cuts)>100
    assert hold.cuts[0].start_seconds==hold.start_seconds and hold.cuts[-1].end_seconds==728
    assert all(a.end_seconds==b.start_seconds for a,b in zip(hold.cuts,hold.cuts[1:]))
    assert state.runtime_work.physical_completed_calls>0
    assert state.nominal_provider.work.full_steps<=60 and state.runtime_work.upstream_entries==1

def test_actual_denial_is_atomic_and_returned_work_paid(monkeypatch):
    import ops_sim.v5.long_mission as owner
    state=fresh();before=CheckpointState.from_context(state.context).to_dict();cursor=state.cursor
    original=owner._physical_substep;calls=[]
    def late(candidate,*a,**k):
        result=original(candidate,*a,**k);calls.append(result)
        return None,result[1]
    monkeypatch.setattr(owner,'_physical_substep',late)
    result=advance_long_mission(state)
    assert result.outcomes[-1].status=='refused' and result.cursor==cursor+1
    assert CheckpointState.from_context(state.context).to_dict()==before
    assert calls and state.runtime_work.physical_completed_calls==1
    assert state.runtime_work.physical_reserved_calls>=1

def test_unreturned_failure_remains_unknown(monkeypatch):
    import ops_sim.v5.long_mission as owner
    state=fresh();before=CheckpointState.from_context(state.context).to_dict()
    def late(*a,**k):raise RuntimeError('injected unreturned primitive')
    monkeypatch.setattr(owner,'_physical_substep',late)
    with pytest.raises(RuntimeError):advance_long_mission(state)
    assert state.cursor==0 and not state.outcomes and CheckpointState.from_context(state.context).to_dict()==before
    assert state.runtime_work.physical_work_unknown_events==1 and state.runtime_work.physical_completed_calls==0

def test_unsupported_regime_rejected_before_work():
    from ops_sim.v5.state import FDIRState
    state=fresh();state.context.spacecraft_state.onboard.fdir_state=FDIRState.BACKUP
    before=state.runtime_work.physical_reserved_calls
    with pytest.raises(ValueError,match='UNSUPPORTED'):advance_long_mission(state)
    assert before==state.runtime_work.physical_reserved_calls

def test_duplicate_actions_products_and_product_binding():
    inputs,_=genuine()
    with pytest.raises(ValueError,match='duplicate'):replace(inputs,actions=(inputs.actions[0],inputs.actions[0]))
    with pytest.raises(ValueError,match='ambiguous'):replace(inputs,products=(inputs.products[0],inputs.products[0]))
    with pytest.raises(ValueError,match='foreign'):replace(inputs,actions=(replace(inputs.actions[1],product_id='unknown'),))

def test_duplicate_action_and_stale_alias():
    state=fresh();next_state=advance_long_mission(state)
    with pytest.raises(ValueError,match='STALE'):advance_long_mission(state)
    with pytest.raises(ValueError,match='foreign'):advance_long_mission(next_state,expected_action_id='point-0')

def test_unresolved_continuous_geometry_cannot_publish(monkeypatch):
    import ops_sim.v5.long_mission as owner
    state=advance_long_mission(fresh());before=CheckpointState.from_context(state.context).to_dict()
    original=owner.evaluate_long_geometry
    def unresolved(*a,**k):return replace(original(*a,**k),status='UNRESOLVED')
    monkeypatch.setattr(owner,'evaluate_long_geometry',unresolved)
    result=advance_long_mission(state)
    assert result.outcomes[-1].reason=='CONTINUOUS_CAPTURE_UNRESOLVED'
    assert not result.acquisitions and CheckpointState.from_context(result.context).to_dict()==before

def test_unresolved_illumination_refuses_before_primitive(monkeypatch):
    import ops_sim.v5.long_mission as owner
    from ops_sim.v5.long_environment import LongSchedule
    state=fresh();before=CheckpointState.from_context(state.context).to_dict();original=state.source_authority.schedule
    def unresolved(a,b):
        return LongSchedule(tuple(replace(c,assessment='UNRESOLVED') for c in original(a,b).cells))
    monkeypatch.setattr(state.source_authority,'schedule',unresolved)
    monkeypatch.setattr(owner,'_physical_substep',lambda *a,**k:pytest.fail('unresolved illumination cannot feed physics'))
    result=advance_long_mission(state)
    assert result.outcomes[-1].reason=='UNRESOLVED_ILLUMINATION'
    assert CheckpointState.from_context(result.context).to_dict()==before and not result.acquisitions

def test_returned_contact_work_counted_before_outer_refusal(monkeypatch):
    import ops_sim.v5.long_mission as owner
    state=fresh()
    for _ in range(3):state=advance_long_mission(state)
    before=CheckpointState.from_context(state.context).to_dict();spent=state.runtime_work.physical_completed_calls
    original=owner.execute_contact_plan;returned=[]
    def late(candidate,*a,**k):
        result=original(candidate,*a,**k);returned.append(result.outcome.evaluated_eps_substeps)
        candidate.spacecraft_state.onboard.operational_mode=owner.OperationalMode.SAFE
        return result
    monkeypatch.setattr(owner,'execute_contact_plan',late)
    result=advance_long_mission(state)
    assert result.outcomes[-1].reason=='CONTACT_EXISTING_PROTECTION_REFUSED'
    assert state.runtime_work.physical_completed_calls-spent==sum(returned)>0
    assert CheckpointState.from_context(result.context).to_dict()==before and not result.context.ground_data_delivery_state.completed_deliveries
