"""Independent axis, Euler and constructive actuator checks (radians/SI)."""
from dataclasses import replace
from fractions import Fraction as Q
from math import pi
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.harness_hardware import compile_effective_hardware
from ops_sim.v5.assembly_attitude_3d import BodyAttitude3D
from ops_sim.v5.assembly_slew_3d import bounded_direction,cross,dot
from ops_sim.v5.solar_attitude import EnergyAttitudePolicy,plan_axis_slew,panel_axis

def setup(variant='compact'):
    m=make_inputs(variant).model
    h=compile_effective_hardware(m.assembly,m.capabilities,m.actuator,m.configuration,m.augmentation)
    p=BodyAttitude3D(m.assembly.body_frame_id,m.environment.trajectory.initial_state.position.frame,Q(128),(1.,0.,0.,0.),Q(128))
    return h,p

@pytest.mark.parametrize('axis',[(1.,0.,0.),(0.,0.,1.),(.3,-.4,.5)])
@pytest.mark.parametrize('direction',[(1.,0.,0.),(-1.,0.,0.),(0.,0.,1.),(.2,.4,-.8)])
def test_explicit_axis_rotation_and_independent_euler_bounds(axis,direction):
    h,p=setup();camera=h.camera_body_axis;axis=bounded_direction(axis)
    s=plan_axis_slew(h,p,axis,direction)
    q=replace(p,quaternion=s.quaternion_at(Q(s.duration_seconds)))
    # Unit quaternion rotation independently compared with the geometric goal.
    assert q.direction(axis)==pytest.approx(bounded_direction(direction),abs=3e-14)
    assert h.camera_body_axis==camera and s.hardware is h
    assert s.commanded_body_axis==axis
    assert s.kinetic_j(Q(0))==s.kinetic_j(Q(s.duration_seconds))==0
    for j in range(21):
        e=s.euler_at(s.motion_seconds*Q(j,20))
        inertia=h.mass_properties.inertia_com_body_kg_m2
        momentum=tuple(sum(I*w for I,w in zip(row,e.omega_body_rad_s)) for row in inertia)
        assert e.momentum_body_nms==momentum
        assert e.gyro_torque_nm==cross(e.omega_body_rad_s,momentum)
        assert dot(e.net_torque_nm,e.omega_body_rad_s)==pytest.approx(float(e.mechanical_power_w),abs=5e-15)
    assert all(x<=Q(l) for x,l in zip(s.whole_torque_abs_upper_nm,h.actuator.torque_limits_nm))
    assert all(x<=Q(l) for x,l in zip(s.whole_rate_abs_upper_rad_s,h.actuator.rate_limits_rad_s))
    assert all(x<=Q(l) for x,l in zip(s.whole_body_momentum_abs_upper_nms,h.actuator.body_momentum_limits_nms))

def test_zero_antiparallel_tie_and_actual_panel_camera_separation():
    h,p=setup();axis=panel_axis(h)
    z=plan_axis_slew(h,p,axis,axis)
    assert z.theta_rad==0 and z.motion_seconds==0
    a=plan_axis_slew(h,p,axis,tuple(-v for v in axis))
    assert a==plan_axis_slew(h,p,axis,tuple(-v for v in axis))
    assert float(a.theta_rad)==pi
    end=replace(p,quaternion=a.quaternion_at(Q(a.duration_seconds)))
    assert end.direction(h.camera_body_axis)!=end.direction(axis)

def test_real_placement_full_tensor_changes_paid_motion():
    h,p=setup();wide,_=setup('outboard')
    a=plan_axis_slew(h,p,panel_axis(h),(-1.,0.,0.))
    b=plan_axis_slew(wide,p,panel_axis(wide),(-1.,0.,0.))
    assert h.tensor_exact!=wide.tensor_exact
    assert a.effective_inertia_kg_m2!=b.effective_inertia_kg_m2
    assert a.duration_seconds!=b.duration_seconds

@pytest.mark.parametrize('changes',[{'entry_usable_fraction':True},{'exit_usable_fraction':.4},{'repoint_interval_seconds':0},{'target_assumption':'flight sensor'},{'minimum_hold_reserve_seconds':0}])
def test_policy_strict_domains(changes):
    with pytest.raises((TypeError,ValueError)):replace(EnergyAttitudePolicy(),**changes)
