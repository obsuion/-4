"""Short closed-world quiet differentials; no long-duration qualification."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction as Q
from pathlib import Path
import json
import sys

import pytest

from ops_sim.v5 import _lifecycle_typed as native
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.lifecycle_physics import (_service_quiet_physical_piece,
    _quiet_clone_context, _Refusal)
from ops_sim.v5.lifecycle_typed_state import typed_quiet_piece
from ops_sim.v5.long_mission_continuation import _scientific
from test_lifecycle_typed_world import pair, owner_data


def encoded(value):
    return json.dumps(_scientific(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def science(result):
    private,cuts,account,controller=result
    return encoded((CheckpointState.from_context(private.context),private.service_state,
        private.service_work,private.last_service_diagnostic,private.battery_port_state,
        private.environment_ageing_state,cuts,account,controller))


def fees(physical):
    return encoded((asdict(physical.quiet_work),asdict(physical.service_allocation_work),
        asdict(physical.battery_port_work),asdict(physical.construction.work),
        asdict(physical.environment_ageing_work),owner_data(physical)))


@pytest.mark.parametrize('table,end',((False,129),(False,148),(True,148),(False,188)))
def test_complete_quiet_records_state_and_all_nonrefundable_work_match(table,end):
    state,reference,pending=pair(table)
    old=reference.physical;physical=state.physical
    expected=_service_quiet_physical_piece(old,_quiet_clone_context(old.context),old.harness.hardware,Q(128),Q(end),pending)
    with state.backend_context.transaction():
        static=state.backend_context._static_for(physical)
        before=native.native_entry_counts()
        actual=typed_quiet_piece(physical,_quiet_clone_context(physical.context),physical.harness.hardware,
            Q(128),Q(end),pending,compiled_static=static)
        after=native.native_entry_counts()
        assert after['counts']['quiet_interval']==before['counts']['quiet_interval']+1
        assert after['counts']['world_forcing']>before['counts']['world_forcing']
    assert science(actual)==science(expected)
    assert fees(physical)==fees(old)


@pytest.mark.parametrize('energy_fraction',(0.,0.00000001,.1,1.))
def test_quiet_depletion_shedding_or_recovery_preserves_actual_outcome_and_fees(energy_fraction):
    state,reference,pending=pair()
    answers=[]
    for physical,is_typed in ((reference.physical,False),(state.physical,True)):
        capacity=(physical.context.inputs.spacecraft_configuration.eps.battery.nominal_energy_wh.value*
            physical.context.spacecraft_state.degradation.battery.usable_capacity_retention)
        physical.context.spacecraft_state.battery.energy_wh=capacity*energy_fraction
        context=_quiet_clone_context(physical.context)
        try:
            if is_typed:
                with state.backend_context.transaction():
                    result=typed_quiet_piece(physical,context,physical.harness.hardware,Q(128),Q(148),pending,
                        compiled_static=state.backend_context._static_for(physical))
            else:result=_service_quiet_physical_piece(physical,context,physical.harness.hardware,Q(128),Q(148),pending)
        except _Refusal as error:answers.append(('REFUSED',str(error),encoded(error.diagnostic),fees(physical)))
        else:answers.append(('COMPLETE',science(result),fees(physical)))
    assert answers[0]==answers[1]


def test_closed_quiet_does_not_call_python_model_or_generic_trial_clone():
    state,reference,pending=pair()
    physical=state.physical
    forbidden={('lifecycle_physics.py','_service_leaf'),('lifecycle_physics.py','_forcing'),
        ('lifecycle_physics.py','_clone_service_candidate'),('lifecycle_physics.py','_quiet_clone_context'),
        ('construction_service.py','service_physical_substep'),('battery_port_construction.py','service_port_substep'),
        ('thermal.py','compute_thermal_substep_transition'),('degradation.py','compute_battery_degradation_substep'),
        ('lifecycle_orbit.py','query'),('orbit_j2.py','_rk4_step'),('orbit_j2_gravity.py','_gravity'),
        ('lifecycle_world.py','schedule'),('lifecycle_world.py','orientation_inputs')}
    observed=[]
    def watch(frame,event,unused):
        if event=='call':
            identity=(Path(frame.f_code.co_filename).name,frame.f_code.co_name)
            if identity in forbidden:observed.append(identity)
    with state.backend_context.transaction():
        static=state.backend_context._static_for(physical)
        candidate=_quiet_clone_context(physical.context)
        previous=sys.getprofile()
        try:
            sys.setprofile(watch)
            typed_quiet_piece(physical,candidate,physical.harness.hardware,Q(128),Q(148),pending,compiled_static=static)
        finally:sys.setprofile(previous)
    assert observed==[]


def test_quiet_domain_rejects_moving_or_loaded_hold_before_scientific_fees():
    state,reference,pending=pair()
    physical=state.physical
    with state.backend_context.transaction():
        static=state.backend_context._static_for(physical)
        before=fees(physical)
        with pytest.raises(ValueError,match='stationary, unloaded HOLD'):
            typed_quiet_piece(physical,_quiet_clone_context(physical.context),physical.harness.hardware,
                Q(128),Q(148),replace(pending,payload_w=1.),compiled_static=static)
        assert fees(physical)==before


@pytest.mark.parametrize('foreign',('forecast','pending','candidate'))
def test_supplied_world_and_candidate_require_exact_current_physical_authority(foreign):
    state,reference,pending=pair();physical=state.physical;context=state.backend_context
    with context.transaction():
        static=context._static_for(physical)
        candidate=_quiet_clone_context(physical.context)
        owner=(replace(physical,nominal_provider=state.forecast_provider,
            source_authority=state.forecast_world,prepared_runtime=context.forecast)
            if foreign=='forecast' else physical)
        plan=native.prepare_world(owner,owner.harness.hardware,pending)
        request=replace(pending)if foreign=='pending' else pending
        if foreign=='candidate':candidate=deepcopy(physical.context)
        before=(fees(physical),owner_data(owner))
        with pytest.raises(ValueError,match='foreign quiet'):
            typed_quiet_piece(physical,candidate,physical.harness.hardware,Q(128),Q(148),request,
                compiled_static=static,world_plan=plan)
        assert (fees(physical),owner_data(owner))==before
