from dataclasses import replace
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.rolling_execution import start_rolling,step_rolling,planning_view
from ops_sim.v5.mission_diagnosis import collect_diagnosis,classify_returned_reason,MissionDiagnosis


def test_typed_actual_and_forecast_scope_no_hidden_planner_ledger():
    s=step_rolling(start_rolling(make_inputs()))
    report=collect_diagnosis(s)
    assert type(report) is MissionDiagnosis and report.root_identity==s.root_identity
    assert report.boundary_commands==1
    scopes={f.scope for f in report.findings}
    assert {'ACTUAL','FORECAST','POLICY','EVALUATION_ONLY','ESTIMATE'}<=scopes
    assert any(f.category=='ACQUISITION_WINDOW' and f.scope=='FORECAST' for f in report.findings)
    assert all(f.evidence and f.finding_id for f in report.findings)
    assert not hasattr(planning_view(s),'diagnosis')


@pytest.mark.parametrize('reason',['EXISTING_ACQUISITION_SEQUENCE_OR_STORAGE_REFUSED','STATION_GEOMETRY_OR_DECLARED_SERVICE_UNAVAILABLE','made-up thermal failure'])
def test_ambiguous_subcauses_remain_unknown(reason):assert 'UNKNOWN' in classify_returned_reason(reason)


def test_collector_rejects_untyped_marketing_trace():
    with pytest.raises(TypeError):collect_diagnosis({'reason':'battery failure'})


@pytest.mark.parametrize('kind,category',[('MODEL_EXCEPTION','COMPUTATIONAL_ERROR'),('ADMISSION_REFUSAL','WORK_OR_OUTPUT'),
    ('OWNED_PROCESS_TIMEOUT','PROCESS_TIMEOUT'),('INCOMPLETE_COORDINATOR','INCOMPLETE_BOUNDED')])
def test_termination_scope_does_not_infer_coverage(kind,category):
    from ops_sim.v5.mission_diagnosis import TerminationEvidence,diagnose_termination
    e=TerminationEvidence('0'*64,'1'*64,kind,'synthetic-owner','synthetic-evidence',None,True,'2'*64)
    d=diagnose_termination(e)
    assert category in d.category and 'UNKNOWN' in d.conclusion and d.scope=='TERMINATION'
    assert diagnose_termination(replace(e,integrity_verified=False)).category=='DIAGNOSTIC_INTEGRITY_UNESTABLISHED'
