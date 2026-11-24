from dataclasses import replace,asdict
from fractions import Fraction as Q
from math import fsum
import json
import pytest
from examples.m3_spatial_constructor_mission_demo import make_inputs
import ops_sim.v5.environment_mission_3d as m
from ops_sim.v5.environment_mission_3d_document import mission_input_digest,mission_inputs_to_json,mission_inputs_from_json
from ops_sim.v5.environment_mission_3d_continuation import save_continuation
from ops_sim.v5.mission_continuous_geometry import _bind_acquired_source
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.state import OperationalMode,FDIRState

@pytest.fixture(scope='module')
def initial():return m.start_environment_mission(make_inputs())

def fresh(initial,inputs=None):
    d=initial.inputs if inputs is None else inputs
    return replace(initial,inputs=d,context=d.initial_checkpoint.restore(d.simulation_inputs),
        attitude=replace(initial.attitude),cursor=0,outcomes=(),acquisitions=(),runtime_work=m.RuntimeWork(**asdict(initial.runtime_work)),
        input_digest=mission_input_digest(d),source_authority=_bind_acquired_source(initial.source_result,d.environment))

def run(s,n=5):
    for _ in range(n):s=m.advance_environment_mission(s)
    return s

def test_real_spatial_capture_contact_and_end_rays(initial):
    s=run(fresh(initial));point,capture,_,contact,_=s.outcomes
    assert all(o.status=='completed' for o in s.outcomes)
    assert point.end_seconds==138 and capture.end_seconds==142
    assert s.assessment().credited_products==1 and s.assessment().completion_time_seconds==Q(22536,125)
    assert s.acquisitions[0].record.stored_equivalent_bits==12288.
    assert len(s.context.ground_data_delivery_state.completed_deliveries)==1 and not s.context.spacecraft_state.data_storage.stored_records
    assert s.context.spacecraft_state.onboard.operational_mode is OperationalMode.STANDBY
    assert capture.continuous_geometry.status==contact.continuous_geometry.status=='VISIBLE'
    assert capture.continuous_geometry.start_ray.at_seconds==Q(138) and capture.continuous_geometry.end_ray.at_seconds==Q(142)
    assert capture.continuous_geometry.end_ray.origin_position_bounds_m!=capture.continuous_geometry.start_ray.origin_position_bounds_m
    assert any(c.euler_midpoint is not None and any(abs(x)>1e-6 for x in c.euler_midpoint.gyro_torque_nm) for c in point.cuts)
    assert s.attitude.quaternion==point.attitude.quaternion and s.attitude.at_seconds==192
    assert point.slew.hardware.camera_body_axis==(.8,.6,0.)
    assert capture.continuous_geometry.start_ray.held_inertial_direction==capture.continuous_geometry.end_ray.held_inertial_direction
    assert s.runtime_work.geometry_queries==2 and s.runtime_work.spatial_reserved_units>0


def test_mechanical_heat_electrical_and_direction_generation(initial):
    s=m.advance_environment_mission(fresh(initial));o=s.outcomes[0];T=o.slew.acceleration_seconds
    assert any(c.end_seconds==128+T for c in o.cuts) and any(c.end_seconds==128+Q(1,3) for c in o.cuts)
    assert sum((c.end_seconds-c.start_seconds for c in o.cuts),Q(0))==o.slew.duration_seconds
    stored=sum((max(Q(0),c.kinetic_end_exact_j-c.kinetic_start_exact_j) for c in o.cuts),Q(0))
    heat_adjustment=fsum(c.heat_adjustment_w*float(c.end_seconds-c.start_seconds) for c in o.cuts)
    assert heat_adjustment==pytest.approx(0.,abs=2e-14)
    electric=fsum(c.actuator_draw_w*float(c.end_seconds-c.start_seconds) for c in o.cuts)
    assert electric==pytest.approx(o.slew.duration_seconds*2+float(stored)/.8,abs=3e-13)
    assert all(c.actuator_draw_w>=2 for c in o.cuts)
    assert any(c.incidence_angle_deg>90 for c in o.cuts) and any(c.incidence_angle_deg<45 for c in o.cuts)
    assert o.cuts[0].part.eps_result.solar.generation_w!=o.cuts[-1].part.eps_result.solar.generation_w
    assert all(c.part.eps_result.loads.adcs_w>=2 for c in o.cuts)
    assert o.cuts[0].kinetic_start_exact_j==o.cuts[-1].kinetic_end_exact_j==0


def test_two_design_placement_only_causes_missed_window(initial):
    d=replace(initial.inputs,assembly=make_inputs('outboard').assembly);s=m.advance_environment_mission(fresh(initial,d))
    assert s.context.simulation_time_seconds==145 and s.outcomes[0].slew.duration_seconds==17
    before=CheckpointState.from_context(s.context).to_dict();work=s.runtime_work.geometry_queries
    denied=m.advance_environment_mission(s)
    assert denied.outcomes[-1].reason=='ACQUISITION_WINDOW_MISSED' and denied.runtime_work.geometry_queries==work
    assert CheckpointState.from_context(denied.context).to_dict()==before and denied.acquisitions==()
    assert initial.inputs.environment==d.environment and initial.inputs.actions==d.actions and initial.inputs.actuator==d.actuator


def test_actual_power_refusal_atomic_with_work(initial):
    d=initial.inputs;cfg=d.simulation_inputs.spacecraft_configuration;b=cfg.eps.battery
    cfg=replace(cfg,eps=replace(cfg.eps,battery=replace(b,max_discharge_output_power_w=replace(b.max_discharge_output_power_w,value=1.))))
    s=fresh(initial,replace(d,simulation_inputs=replace(d.simulation_inputs,spacecraft_configuration=cfg)))
    before=CheckpointState.from_context(s.context).to_dict();r=m.advance_environment_mission(s)
    assert r.outcomes[-1].reason=='FULL_ELECTRICAL_SERVICE_UNAVAILABLE' and r.runtime_work.physical_completed_calls==1
    assert r.runtime_work.physical_reserved_calls>1 and r.runtime_work.spatial_reserved_units>65536
    assert CheckpointState.from_context(r.context).to_dict()==before and r.attitude==s.attitude and not r.acquisitions


def test_late_failure_has_unknown_event_and_no_custody(initial,monkeypatch):
    s=fresh(initial);before=CheckpointState.from_context(s.context).to_dict();real=m._physical_substep;calls=[]
    def fail(*a,**k):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('injected late failure')
        return real(*a,**k)
    monkeypatch.setattr(m,'_physical_substep',fail)
    with pytest.raises(RuntimeError,match='injected'):m.advance_environment_mission(s)
    assert s.cursor==0 and s.outcomes==() and s.runtime_work.physical_completed_calls==1 and s.runtime_work.physical_work_unknown_events==1
    assert CheckpointState.from_context(s.context).to_dict()==before


def test_contact_denied_returned_work_before_refusal(initial):
    d=replace(initial.inputs,transmitter=replace(initial.inputs.transmitter,electrical_power_w=replace(initial.inputs.transmitter.electrical_power_w,value=1e6)))
    s=run(fresh(initial,d),3);before=CheckpointState.from_context(s.context).to_dict();paid=s.runtime_work.physical_completed_calls
    r=m.advance_environment_mission(s)
    assert r.outcomes[-1].reason=='CONTACT_EXISTING_PROTECTION_REFUSED' and r.runtime_work.physical_completed_calls-paid==9
    assert CheckpointState.from_context(r.context).to_dict()==before and not r.context.ground_data_delivery_state.completed_deliveries


def test_unsafe_contact_and_unknown_exception(initial,monkeypatch):
    d=initial.inputs;c=d.initial_checkpoint.restore(d.simulation_inputs);c.spacecraft_state.thermal.node_states[0].temperature_k=319.9999
    env=replace(d.environment,profile=(replace(d.environment.profile[1],start_seconds=Q(128)),))
    d=replace(d,environment=env,initial_checkpoint=CheckpointState.from_context(c),actions=(m.MissionAction('unsafe','CONTACT','station',2),))
    s=fresh(initial,d);before=CheckpointState.from_context(s.context).to_dict();r=m.advance_environment_mission(s)
    assert r.outcomes[-1].reason=='CONTACT_EXISTING_PROTECTION_REFUSED' and r.runtime_work.physical_completed_calls==4
    assert CheckpointState.from_context(r.context).to_dict()==before
    d=replace(d,initial_checkpoint=initial.inputs.initial_checkpoint);s=fresh(initial,d)
    def error(*a,**k):raise RuntimeError('injected unreturned contact')
    monkeypatch.setattr(m,'execute_contact_plan',error)
    with pytest.raises(RuntimeError):m.advance_environment_mission(s)
    assert s.runtime_work.contact_work_unknown_events==1 and s.runtime_work.physical_completed_calls==0

@pytest.mark.parametrize('mode,fdir,marker',[(OperationalMode.SAFE,FDIRState.NORMAL,None),(OperationalMode.STANDBY,FDIRState.BACKUP,None),(OperationalMode.EMERGENCY_BEACON,FDIRState.NORMAL,None),(OperationalMode.STANDBY,FDIRState.NORMAL,128)])
def test_regime_before_paid_work(initial,mode,fdir,marker,tmp_path,monkeypatch):
    s=fresh(initial);c=s.context;c.spacecraft_state.onboard.operational_mode=mode;c.spacecraft_state.onboard.fdir_state=fdir;c.spacecraft_state.onboard.critical_energy_since_seconds=marker
    monkeypatch.setattr(m.light,'evaluate_zonotope_local_illumination_v2',lambda *a:pytest.fail('no launch'))
    with pytest.raises(ValueError,match='REGIME'):replace(s.inputs,initial_checkpoint=CheckpointState.from_context(c))
    with pytest.raises(ValueError,match='REGIME'):m.advance_environment_mission(s)
    with pytest.raises(ValueError,match='REGIME'):save_continuation(tmp_path/'p.json',s)
    assert s.runtime_work.physical_reserved_calls==0 and s.cursor==0


def test_source_frame_quota_and_alias_rejected(initial):
    s=fresh(initial);s.source_authority=None
    s=replace(s,inputs=replace(s.inputs,actions=(m.MissionAction('capture-only','CAPTURE','target',4),)));s.input_digest=mission_input_digest(s.inputs)
    with pytest.raises(ValueError,match='authority'):m.advance_environment_mission(s)
    s=fresh(initial);s.attitude=replace(s.attitude,body_frame_id='foreign')
    with pytest.raises(ValueError,match='foreign attitude'):m.advance_environment_mission(s)
    s=fresh(initial);s.runtime_work.spatial_reserved_units=s.inputs.limits.max_spatial_reserved_units
    with pytest.raises(ValueError,match='QUOTA'):m.advance_environment_mission(s)
    s=fresh(initial);m.advance_environment_mission(s)
    with pytest.raises(ValueError,match='STALE'):m.advance_environment_mission(s)


def test_strict_codec_no_unsafe_types_and_new_identity():
    i=make_inputs();text=mission_inputs_to_json(i);assert mission_inputs_to_json(mission_inputs_from_json(text))==text
    p=json.loads(text);assert p['version']==3
    p['inputs']['actuator']['input_type']='BodyAttitude3D'
    with pytest.raises(ValueError):mission_inputs_from_json(json.dumps(p))
    p=json.loads(text);p['inputs']['simulation_inputs']['typed']['type']='os.system'
    with pytest.raises(ValueError,match='unsafe'):mission_inputs_from_json(json.dumps(p))
    with pytest.raises((TypeError,ValueError)):m.MissionLimits(max_spatial_reserved_units=True)
    with pytest.raises(ValueError):replace(i,geometry_mode='NOMINAL_SAMPLED_V1')
