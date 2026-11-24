from dataclasses import replace,asdict
import pytest
from examples.m7_design_repair_demo import make_spec
from ops_sim.v5.design_repair import ConstructorLedger,MissionRequirements,StudyLimits
from ops_sim.v5.design_repair_study import (start_study,begin_case,StudyWork,feasibility,tradeoff_table,finalize_selection,
    publish_metadata,record_case_failure,executed_point_seconds,_plain_output)


def row(state,index,*,terminal='COMPLETE',credit=2,mass=7.,energy=.1):
    return dict(index=index,variant_identity=state.catalogue[index].manifest.variant_identity,terminal=terminal,scientific_sha256='0'*64,
        manifest=asdict(state.catalogue[index].manifest),
        metrics=dict(status=terminal,clock=728,credited_products=credit,priority_weighted_delivery_score=.5 if credit else 0.,
            unmet_load_wh=0.,actual_refusals=0,actual_full_service_shortfalls=0,returned_temperature_violations=[],mass_properties=dict(total_mass_kg=mass),
            actuator_energy_wh=energy,wire_loss_wh=0.))


def test_zero_output_and_incomplete_cases_never_win():
    s=start_study(make_spec())
    s.cases=(row(s,0,credit=0,mass=6.),row(s,1,terminal='ACTIVE',mass=6.),row(s,2,mass=8.))
    finalize_selection(s)
    assert s.selected_variant==s.cases[2]['variant_identity'] and s.status=='PARTIAL'
    assert not tradeoff_table(s)[0]['feasible'] and not tradeoff_table(s)[1]['feasible']


def test_exact_ties_use_stable_identity_and_pareto_is_bounded():
    s=start_study(make_spec());s.cases=(row(s,1),row(s,2))
    finalize_selection(s)
    assert s.selected_variant==min(r['variant_identity'] for r in s.cases)
    assert all(r['pareto_admissible_completed'] for r in tradeoff_table(s))


def test_baseline_identity_is_not_a_successful_intervention():
    s=start_study(make_spec());s.cases=(row(s,0),)
    finalize_selection(s)
    assert s.selected_variant is None and not tradeoff_table(s)[0]['feasible']


def test_no_feasible_repair_and_failed_catalogue_are_explicit():
    s=start_study(make_spec());s.cases=tuple(row(s,i,credit=0) for i in range(8));finalize_selection(s)
    assert s.status=='NO_FEASIBLE_REPAIR' and s.selected_variant is None
    s.cases=(*s.cases[:-1],row(s,7,terminal='FAILED'));finalize_selection(s)
    assert s.status=='FAILED' and s.selected_variant is None


def test_start_budget_admits_before_actual_owner(monkeypatch):
    import ops_sim.v5.design_repair_study as owner
    spec=replace(make_spec(),limits=replace(StudyLimits(),max_actual_starts=1))
    s=start_study(spec);s.work.reserve_case(spec)
    monkeypatch.setattr(owner,'start_rolling',lambda *a:pytest.fail('entered exhausted actual owner'))
    with pytest.raises(ValueError,match='ADMISSION'):begin_case(s,0)


def test_whole_case_reservations_are_cumulative_not_refunded():
    s=start_study(make_spec());s.work.reserve_case(s.spec)
    prior=dict(s.work.case_ceiling_reservations);s.work.reserve_case(s.spec)
    assert s.work.actual_starts==2 and all(s.work.case_ceiling_reservations[n]==2*v for n,v in prior.items())


def test_metadata_admits_before_file_allocation(tmp_path):
    s=start_study(make_spec());s.work.metadata_reserved_bytes=s.spec.limits.max_metadata_bytes
    with pytest.raises(ValueError,match='METADATA_BEFORE'):publish_metadata(s,tmp_path/'never.json',dict(x=1))
    assert not (tmp_path/'never.json').exists()


def test_later_failed_case_preserves_earlier_durable_evidence(tmp_path):
    s=start_study(make_spec());s.cases=(row(s,0),);s.active_index=1
    earlier=tmp_path/'cases/00/science.json';earlier.parent.mkdir(parents=True);earlier.write_bytes(b'previous-owned-evidence')
    try:raise RuntimeError('injected synthetic later failure')
    except RuntimeError as e:record_case_failure(s,tmp_path,e)
    assert earlier.read_bytes()==b'previous-owned-evidence'
    assert (tmp_path/'cases/01/case.json').exists() and s.cases[-1]['metrics'] is None
    assert s.status=='PARTIAL'


def test_actual_boundary_metrics_match_existing_returned_owner():
    from hashlib import sha256
    from ops_sim.v5.design_repair_study import step_case,metrics_from_science
    from ops_sim.v5.rolling_execution import paid_scientific_bytes
    from ops_sim.v5.engineering_experiment import actual_metrics
    s=start_study(make_spec());begin_case(s,0);step_case(s)
    raw=paid_scientific_bytes(s.active)
    m=metrics_from_science(raw,s.active.root,expected_scientific_sha256=sha256(raw).hexdigest())
    old=actual_metrics(s.active)
    for key in ('minimum_energy_wh','final_energy_wh','wire_loss_wh','unmet_load_wh','maximum_temperature_k','credited_products'):
        assert m[key]==old[key]
    assert s.active.physical.outcomes and m['clock']>128
    assert m['credited_products']==m['receipts']==m['acquired']==0
    assert s.active.knowledge.observation.observed_at_seconds==128


def test_retained_actual_refused_point_prefix_counts_nine_not_seventeen():
    import json
    from pathlib import Path
    from copy import deepcopy
    fixture=json.loads((Path(__file__).parent/'fixtures/m7_refused_point_prefix.json').read_text())
    assert fixture['source_scientific_sha256']=='97e1029e9504e383e95c12d6ee7a5cecc47dc89e69407b840f46dc59c99a3747'
    outcomes=_plain_output(fixture['outcomes']);before=deepcopy(outcomes)
    assert [(o['status'],o['start_seconds'],o['end_seconds']) for o in outcomes]==[
        ('refused',128,128),('completed',168,177)]
    assert [o['slew']['duration_seconds'] for o in outcomes]==[8,9]
    assert [executed_point_seconds(o) for o in outcomes]==[0,9]
    assert sum(executed_point_seconds(o) for o in outcomes)==9
    assert outcomes==before  # Retained plans remain diagnostic data, not executed progress.


@pytest.mark.parametrize('change',[{'end_seconds':129},{'cuts':[{'start_seconds':128,'end_seconds':128}]},
    {'status':'partially_completed'}])
def test_unsupported_point_execution_semantics_reject(change):
    o=dict(kind='POINT',status='refused',start_seconds=128,end_seconds=128,cuts=[],slew={'duration_seconds':8})
    o.update(change)
    with pytest.raises(ValueError):executed_point_seconds(o)


def test_completed_point_requires_exact_returned_cut_coverage():
    o=dict(kind='POINT',status='completed',start_seconds=10,end_seconds=19,
        cuts=[dict(start_seconds=10,end_seconds=13),dict(start_seconds=13,end_seconds=19)],slew={'duration_seconds':100})
    assert executed_point_seconds(o)==9
    o['cuts'][1]['start_seconds']=14
    with pytest.raises(ValueError,match='noncontiguous'):executed_point_seconds(o)


def test_zero_duration_completed_point_and_partial_contact_do_not_invent_slew():
    assert executed_point_seconds(dict(kind='POINT',status='completed',start_seconds=10,end_seconds=10,cuts=[],slew=None))==0
    assert executed_point_seconds(dict(kind='CONTACT',status='completed',start_seconds=10,end_seconds=30,cuts=[],slew=None))==0
