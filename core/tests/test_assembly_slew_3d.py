from dataclasses import replace
from fractions import Fraction as Q
from math import pi
import pytest
from examples.m3_spatial_constructor_mission_demo import make_inputs
from examples.m3_constructor_mission_demo import make_inputs as old_inputs
from ops_sim.v5.assembly_attitude_3d import BodyAttitude3D,compile_assembly_hardware_3d
from ops_sim.v5.assembly_slew_3d import plan_target_slew_3d, cross, dot

def setup(name='compact',principal=False):
    i=make_inputs(name)
    if principal:
        old=old_inputs(name);i=replace(i,assembly=old.assembly,capabilities=old.capabilities)
    h=compile_assembly_hardware_3d(i.assembly,i.capabilities,i.actuator)
    pose=BodyAttitude3D(i.assembly.body_frame_id,i.environment.source_request.segment.trajectory.initial_state.position.frame,Q(128),(1.,0.,0.,0.),Q(128))
    return i,h,pose

@pytest.mark.parametrize('goal',[(1.,0.,0.),(-1.,0.,0.),(0.,1.,0.),(0.,0.,1.),(.2,-.3,.5)])
def test_shortest_steering_and_whole_bounds(goal):
    i,h,p=setup();s=plan_target_slew_3d(h,p,goal)
    final=replace(p,quaternion=s.quaternion_at(Q(s.duration_seconds)))
    from ops_sim.v5.assembly_slew_3d import bounded_direction
    assert final.direction(h.camera_body_axis)==pytest.approx(bounded_direction(goal),abs=3e-14)
    assert s.kinetic_j(Q(0))==s.kinetic_j(Q(s.duration_seconds))==0
    assert s.duration_seconds<=120 and s.scalar_state(s.motion_seconds)[1]==0
    assert all(x<=Q(l) for x,l in zip(s.whole_torque_abs_upper_nm,i.actuator.torque_limits_nm))
    assert all(x<=Q(l) for x,l in zip(s.whole_rate_abs_upper_rad_s,i.actuator.rate_limits_rad_s))
    for j in range(21):
        t=s.motion_seconds*Q(j,20);v=s.euler_at(t)
        assert all(abs(x)<=float(b)+3e-15 for x,b in zip(v.net_torque_nm,s.whole_torque_abs_upper_nm))
        assert dot(v.net_torque_nm,v.omega_body_rad_s)==pytest.approx(float(v.mechanical_power_w),abs=3e-15)


def test_principal_hand_reference_and_zero_antiparallel():
    i,h,p=setup(principal=True);s=plan_target_slew_3d(h,p,(0.,0.,1.))
    assert s.axis_body==(0.,-1.,0.) and s.effective_inertia_kg_m2==Q(h.mass_properties.inertia_com_body_kg_m2[1][1])
    v=s.euler_at(s.acceleration_seconds/2)
    assert v.gyro_torque_nm==(0.,0.,0.)
    assert v.net_torque_nm[1]==pytest.approx(-float(s.acceleration_rad_s2)*float(s.effective_inertia_kg_m2),abs=1e-16)
    z=plan_target_slew_3d(h,p,h.camera_body_axis);assert z.theta_rad==0 and z.motion_seconds==0
    a=plan_target_slew_3d(h,p,tuple(-x for x in h.camera_body_axis))
    b=plan_target_slew_3d(h,p,tuple(-x for x in h.camera_body_axis));assert a==b and float(a.theta_rad)==pi


def test_full_euler_cross_and_mass_placement_causality():
    i,h,p=setup();s=plan_target_slew_3d(h,p,(-1.,0.,0.));v=s.euler_at(s.acceleration_seconds)
    # Boundary belongs to braking; full I omega is not parallel to omega.
    H=tuple(sum(I*w for I,w in zip(row,v.omega_body_rad_s)) for row in h.mass_properties.inertia_com_body_kg_m2)
    assert v.momentum_body_nms==H and v.gyro_torque_nm==cross(v.omega_body_rad_s,H)
    assert any(abs(x)>1e-6 for x in v.gyro_torque_nm)
    _,wide,_=setup('outboard');other=plan_target_slew_3d(wide,p,(-1.,0.,0.))
    assert other.duration_seconds>s.duration_seconds
    with pytest.raises(ValueError):plan_target_slew_3d(replace(h,tensor_exact=((Q(1),Q(0),Q(0)),)*3),p,(-1.,0.,0.))
    bad=replace(i.actuator,torque_limits_nm=(2**-30,)*3)
    with pytest.raises(ValueError,match='short action'):plan_target_slew_3d(compile_assembly_hardware_3d(i.assembly,i.capabilities,bad),p,(-1.,0.,0.))
