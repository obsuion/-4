from dataclasses import replace
from fractions import Fraction as Q
import pytest
from tests.test_assembly_attitude_3d import pose
from ops_sim.v5.mission_camera_3d import exact_held_camera
from ops_sim.v5.mission_continuous_geometry import ContinuousGeometryPolicy

@pytest.mark.parametrize('q',[(1.,0.,0.,0.),(.1,.2,.3,.4),(0.,1.,0.,0.),(0.,0.,1.,0.)])
def test_exact_norm_and_nominal_direction(q):
    p=pose(q);body=(.8,.6,0.);charges={}
    def pay(n,c):charges[n]=charges.get(n,0)+c
    result=exact_held_camera(p,body,ContinuousGeometryPolicy(),charge=pay)
    assert sum(x*x for x in result)==sum(Q(x)**2 for x in body)
    assert tuple(float(x) for x in result)==pytest.approx(p.direction(body),abs=3e-14)
    assert charges['geometry_operations']>0 and charges['geometry_control_units']>0
    assert result==exact_held_camera(replace(p,quaternion=tuple(-x for x in p.quaternion)),body,ContinuousGeometryPolicy(),charge=lambda n,c:None)


def test_transform_quota_refuses_before_operation():
    def refuse(n,c):raise ValueError('quota')
    with pytest.raises(ValueError,match='quota'):exact_held_camera(pose(),(.8,.6,0.),ContinuousGeometryPolicy(),charge=refuse)
