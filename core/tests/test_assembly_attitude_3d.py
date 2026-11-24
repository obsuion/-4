from dataclasses import replace
from fractions import Fraction as Q
from math import sqrt, pi
import pytest
from examples.m3_spatial_constructor_mission_demo import make_inputs
from ops_sim.v5.assembly_attitude_3d import (BodyAttitude3D, canonical_quaternion,
    quaternion_product, admit_tensor, compile_assembly_hardware_3d)
from ops_sim.v5.assembly_attitude import compile_assembly_hardware
from examples.m3_constructor_mission_demo import make_inputs as old_inputs

def pose(q=(1.,0.,0.,0.)):
    i=make_inputs();return BodyAttitude3D(i.assembly.body_frame_id,
        i.environment.source_request.segment.trajectory.initial_state.position.frame,Q(128),q,Q(128))

@pytest.mark.parametrize('q',[(1.,0.,0.,0.),(.1,.2,.3,.4),(0.,-1.,0.,-0.),(1e50,2e50,-3e50,4e50)])
def test_sign_and_idempotence(q):
    a=canonical_quaternion(q);assert a==canonical_quaternion(tuple(-x for x in q))==canonical_quaternion(a)
    assert all(x.hex()!='-0x0.0p+0' for x in a)

@pytest.mark.parametrize('q',[(0.,0.,0.,0.),(float('nan'),0.,0.,0.),(float('inf'),0.,0.,0.),(1e-100,0.,0.,0.),(1,0.,0.,0.)])
def test_invalid_quaternion(q):
    with pytest.raises((ValueError,TypeError)):pose(q)

def test_active_composition_inverse_and_halfturn():
    s=sqrt(.5);x=(s,s,0.,0.);z=(s,0.,0.,s)
    p=pose(quaternion_product(z,x))
    assert p.direction((0.,1.,0.))==pytest.approx((0.,0.,1.),abs=3e-14)
    assert p.inverse_direction(p.direction((.2,.3,.4)))==pytest.approx(tuple(v/sqrt(.29) for v in (.2,.3,.4)),abs=3e-14)
    assert pose((0.,0.,0.,1.)).direction((1.,0.,0.))==(-1.,0.,0.)
    with pytest.raises(ValueError):replace(p,rest_since_seconds=Q(129))

@pytest.mark.parametrize('I',[((0.,0.,0.),)*3,((1.,1.,0.),(1.,1.,0.),(0.,0.,1.)),((1.,.1,0.),(.2,1.,0.),(0.,0.,1.)),((1.,0.,0.),(0.,1.,0.),(0.,0.,-1.))])
def test_tensor_rejections(I):
    with pytest.raises(ValueError):admit_tensor(I)

@pytest.mark.parametrize('name,d',[('compact',.25),('outboard',.7)])
def test_real_full_tensor_independent_parallel_axis_and_mounts(name,d):
    i=make_inputs(name);h=compile_assembly_hardware_3d(i.assembly,i.capabilities,i.actuator)
    assert h.camera_body_axis==(.8,.6,0.) and h.panel_body_normal==(-.8,-.6,0.)
    # Independent volume second moments of five uniform cuboids; actual COM.
    masses=[4.,.2,.4,1.,1.];centers=[(0,0,0),(0,.25,0),(0,-.5,0),(-d,-.15,.1),(d,.15,-.1)]
    dimensions=[(.2,.2,.2),(.1,.1,.1),(.05,.6,.1),(.1,.1,.1),(.1,.1,.1)]
    M=sum(masses);com=tuple(sum(m*r[k] for m,r in zip(masses,centers))/M for k in range(3))
    expected=[[0.]*3 for _ in range(3)]
    for m,c,L in zip(masses,centers,dimensions):
        shift=tuple(c[k]-com[k] for k in range(3))
        for a in range(3):
            for b in range(3):
                expected[a][b]+=m*((sum(L[k]**2 for k in range(3) if k!=a)/12+sum(shift[k]**2 for k in range(3) if k!=a)) if a==b else -shift[a]*shift[b])
    assert h.mass_properties.center_body_m==pytest.approx(com,abs=3e-15)
    for got,ref in zip(h.mass_properties.inertia_com_body_kg_m2,expected):assert got==pytest.approx(ref,abs=3e-15)
    assert all(v>0 for v in h.spd_leading_minors)
    old=old_inputs()
    with pytest.raises(ValueError,match='NON_PRINCIPAL'):compile_assembly_hardware(i.assembly,i.capabilities,old.actuator)
    with pytest.raises(ValueError):compile_assembly_hardware_3d(i.assembly,(replace(i.capabilities[0],component_id='foreign'),i.capabilities[1]),i.actuator)


def test_noncardinal_actual_mount_and_roundoff_symmetry():
    from math import sin,cos
    from ops_sim.v5.assembly_attitude import rotate,vector
    i=make_inputs();angle=.37;c=cos(angle);s=sin(angle);R=((c,-s,0.),(s,c,0.),(0.,0.,1.))
    choices=tuple(replace(choice,pose=replace(choice.pose,rotation_body_from_local=R)) if choice.choice_id=='mount-camera' else choice for choice in i.assembly.choices)
    design=replace(i.assembly,choices=choices);h=compile_assembly_hardware_3d(design,i.capabilities,i.actuator)
    assert h.camera_body_axis==vector(rotate(R,i.capabilities[0].local_axis))
    assert h.tensor_exact==tuple(tuple(Q(x) for x in row) for row in h.mass_properties.inertia_com_body_kg_m2)
    assert h.symmetry_residual_kg_m2<=h.symmetry_allowance_kg_m2
    # Numerical symmetry allowance is admission only; no averaging in output.
    raw=((2.,.3,0.),(.3+2**-45,3.,.1),(0.,.1,4.))
    exact,minors=admit_tensor(raw);assert exact[0][1]!=exact[1][0] and all(x>0 for x in minors)
