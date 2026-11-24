from copy import deepcopy
from dataclasses import replace
import json
import pytest
from examples.m8_environment_ageing import make_inputs
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,progress_projection
from ops_sim.v5.lifecycle_report import validate_report_summary
from ops_sim.v5.environment_lifecycle import validate_progress,validate_projection
from ops_sim.v5.lifecycle_application import requested_lifecycle_root
from ops_sim.v5.lifecycle_document import dumps_root,loads_root

def test_selected_report_projection_provenance_and_strict_types():
    s=start_lifecycle(make_inputs(duration=600));s,_,_=step_lifecycle(s)
    v=s.report.summary();assert 'environment_ageing'in v
    validate_report_summary(s.root,v,s.clock)
    assert v['environment_ageing']['end']['state_identity']==progress_projection(s)['environment_ageing']['actual']['state_identity']
    bad=deepcopy(v);bad['environment_ageing']['end']['pv_retention']=1.
    with pytest.raises(ValueError):validate_report_summary(s.root,bad,s.clock)

def test_public_shared_compiler_has_explicit_selected_law():
    r=make_inputs(duration=600)
    v=requested_lifecycle_root(r.base,600,{'quiet_solver':{}},{},r.sun_mode,service_policy='B55_CONSTRUCTION_RECOVERY_POLICY_V1',energy_attitude_policy='B56_ONBOARD_PREVENTIVE_SOLAR_ATTITUDE_V1',battery_port_policy=r.battery_port_policy.method,environment_ageing_policy='B61_ACCELERATED_ASSUMED_V1')
    assert v.environment_ageing_policy is not None and v.policy.quiet_solver.method=='B61_UNIT_AWARE_ENVIRONMENT_QUIET_V1'
    assert dumps_root(loads_root(dumps_root(v)))==dumps_root(v)

def test_progress_cannot_substitute_actual_for_old_observation():
    s=start_lifecycle(make_inputs(duration=600));s,_,_=step_lifecycle(s)
    v=progress_projection(s)['environment_ageing'];validate_progress(v,s.root,s.clock)
    v['received']=deepcopy(v['actual'])
    with pytest.raises(ValueError):validate_progress(v,s.root,s.clock)


def test_parent_quiet_validator_admits_only_exact_declared_environment_method():
    from ops_sim.v5.lifecycle_application import _quiet_accounting
    s=start_lifecycle(make_inputs(duration=600));v=progress_projection(s)['quiet']
    _quiet_accounting(v,clock=s.clock,elapsed=0,expected_method=s.root.policy.quiet_solver.method)
    with pytest.raises(ValueError,match='quiet progress method'):_quiet_accounting(v,clock=s.clock,elapsed=0)
    with pytest.raises(ValueError,match='quiet progress method'):_quiet_accounting(v,clock=s.clock,elapsed=0,expected_method='unversioned')


def test_last_paid_estimate_may_precede_a_newer_received_packet():
    from ops_sim.v5.lifecycle_execution import _estimate
    s=start_lifecycle(make_inputs(duration=600));_estimate(s)
    origin=s.environment_forecast_origin
    for _ in range(12):
        s,_,_=step_lifecycle(s)
        if s.knowledge.observed_at_seconds>origin[0].clock_seconds:break
    assert s.knowledge.observed_at_seconds>origin[0].clock_seconds
    v=progress_projection(s)['environment_ageing'];validate_progress(v,s.root,s.clock)
    assert v['estimated_source']is not None
    bad=deepcopy(v);bad['estimated_source']['received_at_seconds']=str(s.clock+1)
    with pytest.raises(ValueError):validate_progress(bad,s.root,s.clock)


def test_portable_new_policy_has_its_own_exact_work_binding(tmp_path):
    from pathlib import Path
    from ops_sim.v5.portable_job import prepare,admit_job,admit_contract
    source=Path(__file__).resolve().parents[1];r=make_inputs(duration=600);path=tmp_path/'new-law.job.zip'
    prepare(path,r,source,key='9'*32)
    j,decoded,raw=admit_job(path,source)
    assert decoded.identity==r.identity and j['contract']['physical_work']=='B61_LEGACY_LEAVES_PLUS_SEPARATE_AGEING_RESERVATIONS_V1'
    assert j['contract']['environment_native_format']=='B61_EXPOSURE_THERMAL_CHECKPOINT_V8'
    bad=deepcopy(j['contract']);bad['environment_policy_identity']='0'*64
    with pytest.raises(ValueError):admit_contract(bad,raw,source)
