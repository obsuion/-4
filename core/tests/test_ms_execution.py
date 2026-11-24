"""Integer acquisition is admitted before storage, with unchanged protection."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

import pytest

from examples.v5_ms_mission_demo import build_demo_state, parameter
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.ms_acquisition import InitialAttitudeEvidence, execute_ms_request
from ops_sim.v5.ms_continuation import advance_ms_mission, start_ms_mission
from ops_sim.v5.ms_product import REQUIRED_MS_CHANNELS
from ops_sim.v5.payload import compute_optical_acquisition


def advance(state, n):
    for _ in range(n): state = advance_ms_mission(state)
    return state


def test_non_grid_image_storage_partial_and_completed_product():
    s = build_demo_state()
    assert s.context.spacecraft_state.data_storage.stored_records == ()
    assert type(s.memory.previous_execution) is InitialAttitudeEvidence
    acq = s.program.actions[0]
    continuous = compute_optical_acquisition(s.context.inputs.spacecraft_configuration.payload.optical_acquisition,
                                            acq.timed.request.action.execution.candidate.acquisition_input)
    assert continuous.uncompressed_equivalent_bits == 113609467.4556213
    s = advance(s,1)
    assert s.memory.acquisitions[0].record.stored_equivalent_bits == 113689008.
    assert not s.memory.assessment.credited_products
    assert type(s.memory.previous_execution) is not InitialAttitudeEvidence
    previous = s.memory.previous_execution
    s = advance(s,2)
    assert s.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits == 40000000.
    assert not s.memory.assessment.credited_products and len(s.memory.consumed_contacts.contacts)==1
    s = advance(s,2)
    assert s.memory.assessment.credited_products == 1
    assert s.memory.assessment.completion_time_seconds == Fraction(155)+Fraction(73689008,1000000)
    assert s.context.simulation_time_seconds == 300 and s.context.diagnostics.completed_steps == 5
    assert s.memory.previous_execution == previous
    assert len(s.memory.consumed_contacts.contacts)==2
    assert not s.context.spacecraft_state.data_storage.stored_records


def test_fifth_acquired_band_is_charged_and_earns_one_product_only():
    s = advance(build_demo_state(channels=(*REQUIRED_MS_CHANNELS,"RE"),deadline=260),5)
    assert s.memory.acquisitions[0].record.stored_equivalent_bits == 142111260.
    assert sum(o.transmitted_bits for o in s.memory.outcomes if hasattr(o,"transmitted_bits")) == 142111260
    assert s.memory.assessment.credited_products == 1


def test_exact_grid_acquisition_and_first_contact_completion():
    s=advance(build_demo_state(width_m=13.,length_m=19.5),3)
    assert s.memory.acquisitions[0].record.stored_equivalent_bits==288.
    assert s.memory.assessment.credited_products==1
    assert s.memory.assessment.completion_time_seconds==Fraction(112)+Fraction(288,1000000)


def test_thermal_denial_has_real_standby_no_image_no_credit_and_no_fake_previous():
    initial = build_demo_state(hot=True)
    s = advance(initial,1)
    o = s.memory.outcomes[0]
    assert "required-node-outside-operating-at-start" in [r.value for r in o.availability.reasons]
    assert o.actual_kind.value == "standby" and o.accounting.served_load_wh > 0
    assert s.context.simulation_time_seconds == 110
    assert s.context.spacecraft_state.battery.energy_wh < initial.context.spacecraft_state.battery.energy_wh
    assert not s.memory.acquisitions and not s.memory.assessment.credited_products
    assert s.memory.previous_execution == initial.memory.previous_execution


def test_integer_volume_is_used_for_storage_admission_not_patched_afterward():
    s=build_demo_state();cfg=s.context.inputs.spacecraft_configuration
    # Capacity between the old continuous volume and the integer-grid volume.
    cfg=replace(cfg,storage=replace(cfg.storage,usable_capacity_gb=parameter(cfg.storage.usable_capacity_gb,113650000/8e9)))
    inputs=replace(s.context.inputs,spacecraft_configuration=cfg)
    result=advance(start_ms_mission(inputs,s.program),1)
    assert not result.memory.acquisitions
    assert result.memory.outcomes[0].actual_kind.value == "standby"


@pytest.mark.parametrize("which", ["band-count","spacing","bits","simultaneous","request","bad-version"])
def test_unsupported_ms_binding_rejects_atomically(which):
    s=build_demo_state();c=s.context;a=s.program.actions[0];cfg=c.inputs.spacecraft_configuration;opt=cfg.payload.optical_acquisition
    if which=="band-count":opt=replace(opt,multispectral_band_count=parameter(opt.multispectral_band_count,5.))
    if which=="spacing":opt=replace(opt,multispectral_reference_sample_spacing_m=parameter(opt.multispectral_reference_sample_spacing_m,6.))
    if which=="bits":opt=replace(opt,acquisition_bits_per_sample=parameter(opt.acquisition_bits_per_sample,13.))
    if which=="simultaneous":opt=replace(opt,simultaneous_pan_and_multispectral=True)
    if which=="request":
        from ops_sim.v5.ids import ImagingRequestId
        a=replace(a,acquisition=replace(a.acquisition,request=replace(a.acquisition.request,request_id=ImagingRequestId("wrong"))))
    if which=="bad-version":
        a=deepcopy(a);object.__setattr__(a.acquisition.sizing,"version",2)
    c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,payload=replace(cfg.payload,optical_acquisition=opt)))
    before=canonical_content(CheckpointState.from_context(c));refs=(c.spacecraft_state,c.ground_data_delivery_state,c.diagnostics)
    with pytest.raises((ValueError,TypeError)):
        execute_ms_request(c,s.memory.previous_execution,a.timed,acquisition=a.acquisition,policy=s.program.policy,integration=s.program.integration)
    assert canonical_content(CheckpointState.from_context(c))==before
    assert all(x is y for x,y in zip(refs,(c.spacecraft_state,c.ground_data_delivery_state,c.diagnostics)))


def test_late_shared_owner_failure_rolls_back(monkeypatch):
    from ops_sim.v5.engine import SimulationEngine
    s=build_demo_state();c=s.context;a=s.program.actions[0];before=deepcopy(c)
    def fail(*args):raise RuntimeError("commit failure")
    monkeypatch.setattr(SimulationEngine,"_commit",fail)
    with pytest.raises(RuntimeError,match="commit failure"):
        execute_ms_request(c,s.memory.previous_execution,a.timed,acquisition=a.acquisition,policy=s.program.policy,integration=s.program.integration)
    assert c==before


@pytest.mark.parametrize("case", ["slew-not-ready","view-limit","wrong-frame"])
def test_initial_attitude_uses_existing_adcs_envelope_without_fake_observation(case):
    from math import sin, cos, radians
    from ops_sim.v5.adcs import CommonFrameBoresightDirection
    from ops_sim.v5.ids import ADCSBoresightFrameId
    s=build_demo_state();a=s.program.actions[0];prior=s.memory.previous_execution;timed=a.timed
    if case=='slew-not-ready':
        prior=replace(prior,common_frame_boresight=CommonFrameBoresightDirection(
            prior.common_frame_boresight.frame_id,sin(radians(5)),0.,cos(radians(5))))
    if case=='wrong-frame':
        prior=replace(prior,common_frame_boresight=replace(prior.common_frame_boresight,frame_id=ADCSBoresightFrameId('unrelated-frame')))
    if case=='view-limit':
        action=timed.request.action;candidate=action.execution.candidate;m=candidate.maneuver_candidate
        opportunity=replace(m.opportunity,pointing=replace(m.opportunity.pointing,
            view_angle_from_nadir_deg=s.context.inputs.spacecraft_configuration.adcs.agile_pointing.maximum_view_angle_from_nadir_deg.value+1))
        action=replace(action,execution=replace(action.execution,candidate=replace(candidate,maneuver_candidate=replace(m,opportunity=opportunity))))
        timed=replace(timed,request=replace(timed.request,action=action))
    before=deepcopy(s.context)
    if case=='wrong-frame':
        with pytest.raises(ValueError,match='frame'):
            execute_ms_request(s.context,prior,timed,acquisition=a.acquisition,policy=s.program.policy,integration=s.program.integration)
        assert s.context==before
    else:
        result=execute_ms_request(s.context,prior,timed,acquisition=a.acquisition,policy=s.program.policy,integration=s.program.integration)
        assert result.created_record is None and result.outcome.actual_kind.value=='standby'
        assert result.previous_execution==prior and s.context.simulation_time_seconds==110


def test_legacy_public_executor_does_not_silently_accept_new_initial_attitude():
    from ops_sim.v5.substepped_execution import execute_substepped_request
    s=build_demo_state();before=deepcopy(s.context)
    with pytest.raises(TypeError,match='previous execution'):
        execute_substepped_request(s.context,s.memory.previous_execution,s.program.actions[0].timed,
                                  policy=s.program.policy,integration=s.program.integration)
    assert s.context==before
