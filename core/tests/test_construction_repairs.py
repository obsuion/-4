from dataclasses import replace,asdict
from fractions import Fraction as Q
import pytest
from examples.m4_construction_mission_demo import make_inputs
from ops_sim.v5.long_mission import LongMissionAction
from ops_sim.v5.construction_mission import start_construction_mission,advance_construction_mission,continue_construction_mission
from ops_sim.v5.construction_document import save_construction_continuation,restore_construction_continuation
from ops_sim.v5.long_mission_continuation import scientific_bytes
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.reconstruction_planning import plan_reconstruction


def partial_inputs():
    value=make_inputs();actions=value.mission.actions
    actions=(*actions[:3],replace(actions[3],action_id='partial-first',duration_seconds=1),
        replace(actions[3],action_id='partial-second'),actions[4])
    return replace(value,mission=replace(value.mission,actions=actions))


def prefix(inputs,count):
    state=start_construction_mission(inputs)
    for _ in range(count):state=advance_construction_mission(state)
    return state


def test_actual_partial_then_complete_one_receipt_and_credit(tmp_path):
    state=prefix(partial_inputs(),4)
    progress=state.context.ground_data_delivery_state.partial_transfers
    assert state.context.simulation_time_seconds==169 and len(progress)==1
    assert progress[0].transmitted_equivalent_bits==1000 and not state.context.ground_data_delivery_state.completed_deliveries
    assert not state.assessment()[0].credited_record_ids
    packet=tmp_path/'partial.json';h=save_construction_continuation(packet,state)
    resumed,paid=restore_construction_continuation(packet,expected_packet_sha256=h,expected_input_digest=state.construction.input_digest)
    assert scientific_bytes(state,reserve=False)==scientific_bytes(resumed,reserve=False)
    state=continue_construction_mission(state);resumed=continue_construction_mission(resumed)
    assert scientific_bytes(state,reserve=False)==scientific_bytes(resumed,reserve=False)
    assert len(state.context.ground_data_delivery_state.completed_deliveries)==1
    assert not state.context.ground_data_delivery_state.partial_transfers and not state.context.spacecraft_state.data_storage.stored_records
    assert len(state.assessment()[0].credited_record_ids)==1 and paid['construction_delta']['line_calls_reserved']>0
    with pytest.raises(ValueError):advance_construction_mission(resumed,expected_action_id='partial-second')


def test_internal_forcing_split_carries_partial_progress():
    value=make_inputs();profile=value.mission.environment.profile;entry=profile[-1]
    altered=(*profile[:-1],replace(entry,end_seconds=Q(169)),replace(entry,start_seconds=Q(169),loads=replace(entry.loads,base_bus_w=3.)))
    value=replace(value,mission=replace(value.mission,environment=replace(value.mission.environment,profile=altered)))
    state=continue_construction_mission(start_construction_mission(value))
    contact=state.outcomes[3]
    assert contact.status=='completed' and len(contact.contact_outcomes)>=2
    assert contact.contact_outcomes[0].services[0].transmitted_bits==1000
    assert not contact.contact_outcomes[0].services[0].completed
    assert len(state.context.ground_data_delivery_state.completed_deliveries)==1


@pytest.mark.parametrize('kind',['wire','aggregate'])
def test_known_contact_electrical_refusal_is_atomic_and_future_hold_runs(kind):
    value=make_inputs();cfg=value.configuration
    if kind=='wire':
        lines=tuple(replace(l,wire=replace(l.wire,cross_section_m2=1e-10)) if l.line_id=='communications-line' else l for l in cfg.lines)
        cfg=replace(cfg,lines=lines)
    else:
        # Historical capture is22W while tx is12W: one constant current cap
        # cannot admit that capture and deny the lighter original tx. Declare
        # a separate30W transmitter test input; leave battery/protection alone.
        cfg=replace(cfg,bus_current_limit_a=1.)
        tx=value.mission.transmitter
        tx=replace(tx,electrical_power_w=replace(tx.electrical_power_w,value=30.,
            provenance=replace(tx.electrical_power_w.provenance,rationale='ASSUMED R3 aggregate-current regression:30W transmitter,1A ideal28V bus cap; unchanged acquisition/battery/protection.')))
        value=replace(value,mission=replace(value.mission,transmitter=tx))
    state=prefix(replace(value,configuration=cfg),3)
    assert len(state.acquisitions)==1
    before=CheckpointState.from_context(state.context).to_dict();spent=state.runtime_work.physical_completed_calls
    result=advance_construction_mission(state)
    assert result.outcomes[-1].status=='refused' and result.outcomes[-1].reason.startswith('CONSTRUCTION_CONTACT_ELECTRICAL_REFUSED:')
    assert CheckpointState.from_context(state.context).to_dict()==before
    assert result.consumed_contacts==state.consumed_contacts and not result.context.ground_data_delivery_state.completed_deliveries
    assert result.runtime_work.physical_completed_calls>spent and result.runtime_work.contact_work_unknown_events==0
    if kind=='wire':assert result.construction.work.line_calls_refused>0
    else:
        # Aggregate check fails AFTER every line returned successfully; it is
        # not a failed line call and must not fabricate line-refused accounting.
        assert result.construction.work.line_calls_refused==0
        assert result.construction.work.line_calls_returned==result.construction.work.line_calls_reserved
        assert 'aggregate regulated bus current' in result.outcomes[-1].reason
    end=advance_construction_mission(result)
    assert end.context.simulation_time_seconds==728 and len(end.context.spacecraft_state.data_storage.stored_records)==1


def test_genuinely_unreturned_contact_error_is_not_physical_refusal(monkeypatch):
    import ops_sim.v5.construction_contact as owner
    state=prefix(make_inputs(),3);before=CheckpointState.from_context(state.context).to_dict()
    def fail(*a,**k):raise TypeError('injected arbitrary bug')
    monkeypatch.setattr(owner,'construction_physical_substep',fail)
    with pytest.raises(TypeError,match='arbitrary bug'):advance_construction_mission(state)
    assert state.cursor==3 and CheckpointState.from_context(state.context).to_dict()==before
    assert state.runtime_work.contact_work_unknown_events==1


def repeated_capture_inputs(cap=30000):
    value=make_inputs();old=value.mission.actions
    actions=(old[0],*(replace(old[1],action_id='capture-'+str(i),duration_seconds=1) for i in range(7)),old[2],
        replace(old[3],duration_seconds=120),old[4])
    mission=replace(value.mission,actions=actions,limits=replace(value.mission.limits,contact_integration_level=6))
    return replace(value,mission=mission,limits=replace(value.limits,max_line_calls=cap))


def test_shared_planner_counts_repeated_captures_and_predictions():
    value=repeated_capture_inputs();plan=plan_reconstruction(value.mission,10)
    row=plan.action_bounds[-1]
    assert row['possible_records']==7 and row['integration_substeps']==64
    assert plan.construction['line_calls_reserved']>6848
    assert plan.runtime['physical_reserved_calls']>=row['physical_reservations']


def test_duplicate_contact_identity_rejects_before_physical_work(monkeypatch):
    import ops_sim.v5.construction_contact as owner
    from ops_sim.v5.contact_execution import ContactPlan
    from ops_sim.v5.communications import ServiceableGroundContact
    state=prefix(partial_inputs(),4);old=state.outcomes[-1].contact_outcomes[0].contact
    forcing=state.outcomes[-1].contact_forcing[0].legacy_forcing
    duplicate=ServiceableGroundContact(old.contact_id,old.ground_station_id,169,170)
    records=tuple(r.record_id for r in state.context.spacecraft_state.data_storage.stored_records)
    monkeypatch.setattr(owner,'construction_physical_substep',lambda *a,**k:pytest.fail('duplicate must reject before physics'))
    with pytest.raises(ValueError):owner.execute_construction_contact_plan(state.context,ContactPlan(duplicate,records,forcing.transmitter_inputs,forcing.idle_inputs),
        consumed_contacts=state.consumed_contacts,policy=state.inputs.protection,integration=__import__('ops_sim.v5.integration_time',fromlist=['IntegrationPolicy']).IntegrationPolicy(2),
        compilation=state.construction.compilation,work=state.construction.work,limits=state.construction.inputs.limits)


def test_inadequate_quota_rejects_before_start_and_adequate_replay_is_paid(tmp_path,monkeypatch):
    import ops_sim.v5.construction_document as owner
    value=repeated_capture_inputs(20000);state=prefix(value,10)
    assert state.cursor==10 and all(o.status=='completed' for o in state.outcomes)
    assert state.construction.work.line_calls_reserved==11376
    path=tmp_path/'tight.json';h=save_construction_continuation(path,state)
    original=owner.start_construction_mission
    monkeypatch.setattr(owner,'start_construction_mission',lambda *a,**k:pytest.fail('must refuse before any provider/physical work'))
    with pytest.raises(ValueError,match='CONSTRUCTION_RECONSTRUCTION_ADMISSION:line_calls_reserved'):
        restore_construction_continuation(path,expected_packet_sha256=h,expected_input_digest=state.construction.input_digest)
    monkeypatch.setattr(owner,'start_construction_mission',original)
    # A distinct admitted immutable input has adequate finite quota. No saved
    # packet or original ledger is edited or reset to manufacture acceptance.
    adequate=repeated_capture_inputs(30000);other=prefix(adequate,10)
    path2=tmp_path/'adequate.json';h2=save_construction_continuation(path2,other)
    replay,paid=restore_construction_continuation(path2,expected_packet_sha256=h2,expected_input_digest=other.construction.input_digest)
    assert scientific_bytes(other,reserve=False)==scientific_bytes(replay,reserve=False)
    assert replay.construction.work.line_calls_reserved==22752
    assert paid['construction_delta']['line_calls_reserved']==11376
    assert len(replay.context.ground_data_delivery_state.completed_deliveries)==7
