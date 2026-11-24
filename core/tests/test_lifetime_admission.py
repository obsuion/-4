import json
from copy import deepcopy
from dataclasses import replace,asdict
import pytest
from lifetime_support import RAW,root_for
from ops_sim.v5.lifetime_admission import *
from ops_sim.v5.lifecycle_document import dumps_root,loads_root
from ops_sim.v5.environment_ageing import LAW,ACCOUNTING_LAW

def test_genuine_v7_duration_only_and_exact_owner_roundtrip():
    old=loads_root(RAW);root,raw,proof=derive_duration(b'\xef\xbb\xbf'+RAW,473364000)
    assert root.start_seconds==128 and root.end_seconds==473364128
    assert proof['full_30day_buckets']==182 and proof['terminal_bucket_seconds']==1620000
    a=json.loads(RAW);b=json.loads(raw)
    for d in(a,b):d.pop('digest');d['inputs'].pop('duration_seconds')
    assert a==b and dumps_root(loads_root(raw))==raw
    assert root.environment_ageing_policy==old.environment_ageing_policy

@pytest.mark.parametrize('duration',[True,0,-1,473364001,1.,float('nan')])
def test_duration_rejects_nonexact_or_outside_authority(duration):
    with pytest.raises((ValueError,TypeError)):derive_duration(RAW,duration)

def test_digest_and_duplicate_payload_are_not_repaired():
    for raw in (RAW.replace(b'"duration_seconds":7200',b'"duration_seconds":7201'),RAW[:-1]+b',"version":7}'):
        with pytest.raises((ValueError,TypeError)):derive_duration(raw,1800)

def test_explicit_accounting_changes_no_physics_or_accuracy():
    old=loads_root(RAW);root,raw,proof=derive_accounting(RAW)
    assert root.policy.method==ACCOUNTING and root.environment_ageing_policy.method==ACCOUNTING_LAW
    assert replace(root.environment_ageing_policy,method=LAW,maximum_proposals=old.environment_ageing_policy.maximum_proposals)==old.environment_ageing_policy
    assert replace(root.policy.quiet_solver,max_total_leaf_calls=old.policy.quiet_solver.max_total_leaf_calls)==old.policy.quiet_solver
    assert root.base==old.base and root.scenario==old.scenario
    assert dumps_root(loads_root(raw))==raw and not proof['quota_completion_proof']

def test_real_long_quotas_and_local_caps_are_finite_conditional():
    root=root_for(473364000);p=resource_plan(root)
    assert all(x['pass_']for x in p['conditional_checks'])
    assert p['physical_limits']['max_runtime_entries']>2**20
    assert p['physical_limits']['max_action_cells']==256
    assert p['orbit_limits']['step_seconds']==10.0
    assert not p['quota_completion_proof']and p['unknown_terms']
    with pytest.raises(ValueError):resource_plan(replace(root,policy=replace(root.policy,max_controller_decisions=1)))

def test_old_policy_domains_not_silently_broadened():
    from ops_sim.v5.lifecycle_contract import LifecyclePolicy
    from ops_sim.v5.environment_ageing import EnvironmentAgeingPolicy
    with pytest.raises(ValueError):LifecyclePolicy(max_forecast_transitions=2**40)
    with pytest.raises(ValueError):EnvironmentAgeingPolicy(maximum_proposals=2**40)

def test_explicit_lifetime_environment_control_bound_and_exact_ledger():
    from ops_sim.v5.environment_ageing import EnvironmentAgeingWork
    p=root_for(473364000).environment_ageing_policy
    count=2**48;units=256+64*(len(p.emissivity)+len(p.conductance))
    w=EnvironmentAgeingWork(proposed=count,returned=count,control_units=count*units)
    w.validate(p)
    assert w.control_units>2**56
    with pytest.raises(ValueError):replace(w,control_units=w.control_units+1).validate(p)
    # Old guard semantics are not expanded by the new accounting version.
    with pytest.raises(ValueError):w.validate(replace(p,method=LAW,maximum_proposals=2**36))
