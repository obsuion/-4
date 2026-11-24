"""Strict public policy/progress and source membership; no worker launch."""
from copy import deepcopy
from dataclasses import replace
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_application import requested_lifecycle_root,LifecycleStore
from ops_sim.v5.lifecycle_execution import start_lifecycle,progress_projection
from ops_sim.v5.solar_attitude import METHOD,EnergyAttitudePolicy
from ops_sim.v5.solar_lifecycle import validate_solar_progress

def root():
    return requested_lifecycle_root(make_inputs(),600,{}, {},'REDUCED_ASSUMED_ANNUAL_V1',service_policy='B55_CONSTRUCTION_RECOVERY_POLICY_V1',energy_attitude_policy=METHOD)

def test_input_selector_is_explicit_and_requires_service():
    from ops_sim.v5.lifecycle_service import POWER_SERVICE_METHOD
    b=make_inputs();r=requested_lifecycle_root(b,600,{}, {},'REDUCED_ASSUMED_ANNUAL_V1',service_policy=POWER_SERVICE_METHOD,energy_attitude_policy=METHOD)
    assert r.energy_attitude_policy==EnergyAttitudePolicy()
    assert requested_lifecycle_root(b,600,{}, {},'REDUCED_ASSUMED_ANNUAL_V1').energy_attitude_policy is None
    with pytest.raises((TypeError,ValueError)):requested_lifecycle_root(b,600,{}, {},'REDUCED_ASSUMED_ANNUAL_V1',energy_attitude_policy=METHOD)
    with pytest.raises((TypeError,ValueError)):requested_lifecycle_root(b,600,{}, {},'REDUCED_ASSUMED_ANNUAL_V1',service_policy=POWER_SERVICE_METHOD,energy_attitude_policy='invented')

@pytest.mark.parametrize('change',['policy','extra','clock','frame','scope'])
def test_progress_never_grants_hidden_actual_authority(change):
    from ops_sim.v5.lifecycle_service import POWER_SERVICE_METHOD
    r=requested_lifecycle_root(make_inputs(),600,{}, {},'REDUCED_ASSUMED_ANNUAL_V1',service_policy=POWER_SERVICE_METHOD,energy_attitude_policy=METHOD)
    s=start_lifecycle(r);v=progress_projection(s)['solar_attitude'];validate_solar_progress(v,r,128)
    bad=deepcopy(v)
    if change=='policy':bad['policy_identity']='f'*64
    elif change=='extra':bad['extra']=None
    elif change=='clock':bad['actual']['clock_seconds']=['129','1']
    elif change=='frame':bad['actual']['last_support']=[['128','1'],['129','1']]
    else:bad['knowledge_scope']='CURRENT_ACTUAL_IS_GROUND'
    with pytest.raises((TypeError,ValueError)):validate_solar_progress(bad,r,128)

def test_new_controller_exact_source_membership_and_finite_plan(tmp_path):
    from ops_sim.v5.lifecycle_service import POWER_SERVICE_METHOD
    from m8_solar_chain_cli import trusted_worker_binding,EXPECTED_WORKER_MEMBERS,create_for_store
    r=requested_lifecycle_root(make_inputs(),600,{}, {},'REDUCED_ASSUMED_ANNUAL_V1',service_policy=POWER_SERVICE_METHOD,energy_attitude_policy=METHOD)
    b=trusted_worker_binding();assert set(b['source_sha256'])==set(EXPECTED_WORKER_MEMBERS)
    assert len(b['source_sha256'])==668
    store=LifecycleStore(tmp_path/'solar-store',r,create=True)
    with pytest.raises((TypeError,ValueError)):create_for_store(store,chain_id='a'*32,execution_budget=__import__('ops_sim.v5.lifecycle_execution_budget',fromlist=['ExecutionBudget']).ExecutionBudget(180,150,30),maximum_primary_segments=6)
    assert not list((store.directory/'resource-chains').glob('*'))
