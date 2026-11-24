"""Finite input/calendar authority tests; 15-year case performs no simulation."""
from dataclasses import replace
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import (LifecycleRoot,LifecyclePolicy,LifecycleScenario,MAX_DURATION,occurrence,static_admission,horizon_inputs,initial_context)

@pytest.fixture(scope='module')
def base():return make_inputs(wire='nominal')

def test_fifteen_julian_years_is_only_static_admission(base):
    root=LifecycleRoot(base,MAX_DURATION)
    data=static_admission(root)
    assert root.month_rows==183
    assert data['status']=='ADMITTED_INPUT_ONLY_NOT_COMPUTED'
    assert data['duration_seconds']==473364000
    assert data['offered_population']==525960

@pytest.mark.parametrize('value',[True,0,-1,473364001,1.5])
def test_horizon_exact_finite(base,value):
    with pytest.raises((ValueError,TypeError)):LifecycleRoot(base,value)

@pytest.mark.parametrize('namespace',['UPPER','русский','double--dash','trailing-','space here'])
def test_namespace_must_form_actual_stable_ids(namespace):
    with pytest.raises(ValueError):LifecycleScenario(namespace=namespace)

def test_occurrence_ids_times_and_inputs_are_distinct(base):
    root=LifecycleRoot(base,86400)
    a,c=occurrence(root,0);b,d=occurrence(root,1)
    assert a.product.request.request_id!=b.product.request.request_id
    assert b.release_seconds-a.release_seconds==root.scenario.cadence_seconds
    assert c.station_id==d.station_id
    assert c.contact_id!=d.contact_id
    assert a.product.footprint==b.product.footprint
    assert root.offered_population==96

def test_initial_identity_rebinding_changes_no_dynamic_values(base):
    root=LifecycleRoot(base,86400);inputs=horizon_inputs(root)
    ctx=initial_context(root,inputs)
    assert ctx.inputs.common_world.horizon_seconds==86528
    assert ctx.inputs.common_world.world_id!=base.model.simulation_inputs.common_world.world_id
    assert ctx.spacecraft_state.battery.energy_wh==base.initial_checkpoint.spacecraft.battery_energy_wh
    assert ctx.controller_state.controller_id==inputs.model_manifest.controller_id

def test_short_table_cannot_be_silently_extended(base):
    with pytest.raises(ValueError):LifecycleRoot(base,86400,sun_mode='BOUND_SHORT_TABLE_V1')

def test_work_and_placement_policies_strict():
    with pytest.raises(ValueError):LifecyclePolicy(quiet_step_seconds=True)
    with pytest.raises(ValueError):LifecycleScenario(acquisition_window_seconds=600,deadline_offset_seconds=400)
