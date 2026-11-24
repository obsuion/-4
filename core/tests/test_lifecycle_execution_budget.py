"""Focused wrapper admission/clock checks, no long scientific evaluation."""
from copy import deepcopy
from dataclasses import asdict,FrozenInstanceError
import ast,inspect
import pytest
from ops_sim.v5.lifecycle_execution_budget import (ExecutionBudget,SoftBudgetGuard,
    admit_budget,admit_receipt,INTENT)
from ops_sim.v5.lifecycle_application import make_intent,validate_intent,_job_format,execute_worker

def policy():return ExecutionBudget(180,10,170)

@pytest.mark.parametrize('field,value',[(f,v) for f in ('hard_execution_seconds','soft_stop_seconds','finalization_reserve_seconds') for v in (True,0,-1,1801,1.,'10')])
def test_budget_rejects_hostile_exact_types_and_ranges(field,value):
    data=asdict(policy());data[field]=value
    with pytest.raises((ValueError,TypeError)):admit_budget(data,execution_seconds=180)

def test_budget_is_immutable_and_unknown_fields_are_not_defaults():
    p=policy()
    with pytest.raises(FrozenInstanceError):p.soft_stop_seconds=1
    with pytest.raises(ValueError):admit_budget(dict(asdict(p),cached_trust=True),execution_seconds=180)
    with pytest.raises(ValueError):admit_budget(asdict(p),execution_seconds=179)
    with pytest.raises(ValueError):ExecutionBudget(180,10,169)

def test_setup_inclusive_fakeclock_cuts_without_external_marker():
    now=[100.];guard=SoftBudgetGuard(policy(),95.,clock=lambda:now[0])
    assert not guard.boundary('BEFORE_TRANSITION')
    now[0]=106.
    assert guard.boundary('AFTER_COMMITTED_TRANSITION')
    assert guard.cut_elapsed==11. and guard.cut_phase=='AFTER_COMMITTED_TRANSITION'
    now[0]=108.
    r=guard.receipt();admit_receipt(r,policy())
    assert r['record_elapsed_seconds']==13. and r['stop_cause']=='BUDGET'
    assert guard.boundary('BEFORE_TRANSITION') and guard.cut_elapsed==11.
    # Integration check: both selected guards live in worker, before marker
    # and after committed transition publication; there is no model time cut.
    source=inspect.getsource(execute_worker);ast.parse(source)
    assert source.index('worker_entry=time.perf_counter()')<source.index('from .lifecycle_document')
    assert source.index("boundary('BEFORE_TRANSITION')")<source.index("marker=jobdir/'stop-request.json'")
    assert source.index("boundary('AFTER_COMMITTED_TRANSITION')")>source.index('step_lifecycle')

def test_fakeclock_initial_setup_exhaustion_and_clock_regression():
    g=SoftBudgetGuard(policy(),0.,clock=lambda:11.)
    assert g.boundary('BEFORE_TRANSITION')
    now=[2.];g=SoftBudgetGuard(policy(),0.,clock=lambda:now[0]);g.boundary('BEFORE_TRANSITION');now[0]=1.
    with pytest.raises(ValueError):g.boundary('BEFORE_TRANSITION')

def test_legacy_wire_is_exact_and_budget_is_separate_version():
    old=make_intent('0'*64,key='a'*32,execution_seconds=180)
    assert len(old)==9 and 'execution_budget' not in old
    new=make_intent('0'*64,key='a'*32,execution_seconds=180,execution_budget=policy())
    assert new['format']==INTENT and _job_format(new)!=_job_format(old)
    assert validate_intent(new)==new
    for mutation in (dict(cached_trust=True),dict(execution_budget_identity='f'*64),dict(format=old['format']),dict(execution_seconds=True)):
        bad=deepcopy(new);bad.update(mutation)
        with pytest.raises((ValueError,TypeError)):validate_intent(bad)

@pytest.mark.parametrize('mutation',[dict(cached_trust=True),dict(stop_cause='BUDGET'),dict(cut_elapsed_seconds=1.),dict(record_elapsed_seconds=float('nan')),dict(hard_deadline_guaranteed=True),dict(policy_identity='f'*64)])
def test_receipt_rejects_unbound_or_hostile_metadata(mutation):
    g=SoftBudgetGuard(policy(),0.,clock=lambda:2.);r=g.receipt();r.update(mutation)
    with pytest.raises((ValueError,TypeError)):admit_receipt(r,policy())


def test_selected_stop_request_is_visible_only_after_complete_write(tmp_path,monkeypatch):
    import json
    import ops_sim.v5.lifecycle_application as owner
    job=dict(job_id='a'*32,root_identity='0'*64,intent=make_intent('0'*64,key='b'*32,execution_seconds=180,execution_budget=policy()))
    marker=tmp_path/'stop-request.json';rename=owner.os.rename;seen=[]
    def publish(pending,target):
        assert not target.exists()
        seen.append(json.loads(pending.read_bytes()))
        return rename(pending,target)
    monkeypatch.setattr(owner.os,'rename',publish)
    owner._write_stop_request(marker,job)
    assert len(seen)==1 and json.loads(marker.read_bytes())==seen[0]
    assert seen[0]['job_id']==job['job_id'] and not marker.with_suffix('.pending').exists()
