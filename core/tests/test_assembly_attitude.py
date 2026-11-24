from dataclasses import replace
from fractions import Fraction as Q
from math import pi,sqrt,isclose,fsum
import pytest
from examples.m3_constructor_mission_demo import make_inputs
from ops_sim.v5.assembly_attitude import compile_assembly_hardware,BodyAttitude,plan_target_slew


def hardware(name='compact'):
    d=make_inputs(name);return d,compile_assembly_hardware(d.assembly,d.capabilities,d.actuator)


def attitude(d,angle=0.):
    return BodyAttitude(d.assembly.body_frame_id,d.environment.source_request.segment.trajectory.initial_state.position.frame,Q(128),angle,Q(128))


def test_mount_then_body_to_inertial_independent_axes():
    d,h=hardware()
    assert h.camera_body_axis==(1.,0.,0.) and h.panel_body_normal==(-1.,0.,0.)
    a=attitude(d,pi/2)
    assert a.direction(h.camera_body_axis)==pytest.approx((0.,0.,-1.),abs=2**-48)
    assert a.direction(h.panel_body_normal)==pytest.approx((0.,0.,1.),abs=2**-48)


def test_inertia_independent_parallel_axis_and_actual_layout_effect():
    d,h=hardware();_,wide=hardware('outboard')
    # y inertia independent of y offsets/COM: sum m*(x^2+z^2+(dx^2+dz^2)/12).
    expected=4*(.2**2+.2**2)/12+.2*(.1**2+.1**2)/12+.4*(.1**2+.05**2)/12+2*(.25**2+(.1**2+.1**2)/12)
    assert h.inertia_y_kg_m2==pytest.approx(expected,abs=2**-49)
    assert wide.inertia_y_kg_m2-h.inertia_y_kg_m2==pytest.approx(2*(.7**2-.25**2),abs=2**-49)
    p=plan_target_slew(h,attitude(d),(-1.,0.,0.));w=plan_target_slew(wide,attitude(d),(-1.,0.,0.))
    assert w.duration_seconds>p.duration_seconds
    assert w.profile.duration_s==pytest.approx(2*sqrt(wide.inertia_y_kg_m2*pi/.02),rel=2**-45)
    assert p.profile.peak_rate_rad_s<=.6 and w.profile.peak_rate_rad_s<=.6
    assert h.inertia_y_kg_m2*p.profile.peak_rate_rad_s<=d.actuator.momentum_nms
    assert p.profile.alpha_rad_s2*h.inertia_y_kg_m2==pytest.approx(.02,rel=2**-48)


def test_zero_turn_still_has_declared_settling():
    d,h=hardware();p=plan_target_slew(h,attitude(d),(1.,0.,0.))
    assert p.profile.duration_s==0 and p.duration_seconds==1
    assert p.kinetic_j(Q(0))==0


def test_nonprincipal_tensor_is_rejected_instead_of_scalarized():
    d,h=hardware('outboard');choices=[]
    for c in d.assembly.choices:
        if c.choice_id=='mount-battery-right':
            pose=replace(c.pose,origin_body_m=(.7,.2,0.))
            box=replace(c.envelope,lower_m=(.64,.14,-.06),upper_m=(.76,.26,.06))
            c=replace(c,pose=pose,envelope=box)
        choices.append(c)
    design=replace(d.assembly,choices=tuple(choices))
    with pytest.raises(ValueError,match='NON_PRINCIPAL'):compile_assembly_hardware(design,d.capabilities,d.actuator)


def test_foreign_capability_and_unsupported_target():
    d,h=hardware()
    with pytest.raises(ValueError,match='foreign capability'):compile_assembly_hardware(d.assembly,
        (replace(d.capabilities[0],component_id='missing'),d.capabilities[1]),d.actuator)
    with pytest.raises(ValueError,match='OUTSIDE_PRINCIPAL'):plan_target_slew(h,attitude(d),(0.,1.,0.))
