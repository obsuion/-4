from dataclasses import replace
from fractions import Fraction as Q
import pytest
from tests.test_long_environment import fresh,genuine
from ops_sim.v5.long_general_geometry import evaluate_long_geometry
from ops_sim.v5.environment_mission_3d import compile_assembly_hardware
from ops_sim.v5.mission_general_geometry import admit_general_geometry_domain,GeneralGeometryPolicy

def test_long_source_short_owner_still_refuses():
    i,_=genuine()
    with pytest.raises(ValueError,match='120'):admit_general_geometry_domain(i.environment.forcing_request(),i.catalog[0],GeneralGeometryPolicy())

def test_real_long_whole_tube_visible_station():
    s=fresh();ledger={}
    def pay(n,c):ledger[n]=ledger.get(n,0)+c
    result=evaluate_long_geometry(s.source_authority,s.inputs.environment,s.inputs.catalog[-1],Q(168),Q(188),s.inputs.geometry_policy,charge=pay)
    assert result.status=='VISIBLE' and result.original_anchor_seconds==128 and result.closed_support
    assert result.mode=='CONTINUOUS_ACQUIRED_LONG' and ledger['geometry_queries']==1
    for c in result.cells:
        tube=s.source_authority.steps[c.source_step_id].tube
        assert c.source_closed_support==(tube.source_start_seconds,tube.source_end_seconds)
        assert c.position_bounds_m==tuple(tuple(Q(v) for v in pair) for pair in tube.position_bounds_m)

def test_local_duration_and_full_frame_admission_before_charges():
    s=fresh();calls=[]
    with pytest.raises(ValueError,match='120'):evaluate_long_geometry(s.source_authority,s.inputs.environment,s.inputs.catalog[0],Q(128),Q(300),s.inputs.geometry_policy,charge=lambda *a:calls.append(a))
    assert not calls
    earth=replace(s.inputs.catalog[0].point.ellipsoid,name='foreign-equal-shape')
    e=replace(s.inputs.catalog[0],point=replace(s.inputs.catalog[0].point,ellipsoid=earth))
    with pytest.raises(ValueError,match='foreign'):evaluate_long_geometry(s.source_authority,s.inputs.environment,e,Q(168),Q(188),s.inputs.geometry_policy,charge=lambda *a:calls.append(a))
