from dataclasses import replace
from fractions import Fraction as Q
from decimal import Decimal,localcontext
import pytest
from examples.m3_continuous_mission_demo import make_continuous_inputs
from ops_sim.v5.environment_mission import start_environment_mission,RuntimeWork
from ops_sim.v5.mission_continuous_geometry import (_Arithmetic,_trig_bounds,_predicates,
    evaluate_continuous_geometry,ContinuousGeometryPolicy,_AcquiredSource)


@pytest.fixture(scope='module')
def acquired():return start_environment_mission(make_continuous_inputs())


def ar(policy=None):
    counts={}
    def pay(n,c):counts[n]=counts.get(n,0)+c
    return _Arithmetic(policy or ContinuousGeometryPolicy(),pay),counts


def evaluate(s,a,b,entry=None,**kwargs):
    p=s.inputs.geometry_policy
    def pay(n,c):s.runtime_work.charge(n,c,s.inputs.limits)
    return evaluate_continuous_geometry(s.source_authority,s.inputs.environment,entry or s.inputs.catalog[0],Q(a),Q(b),p,charge=pay,**kwargs)


@pytest.mark.parametrize('angle',[Q(0),Q(1,2),Q(-1,2),Q(19)])
def test_trig_against_independent_high_precision_order_400_reference(angle):
    a,counts=ar();s,c=_trig_bounds(a,angle,angle)
    with localcontext() as ctx:
        ctx.prec=100
        x=Decimal(angle.numerator)/Decimal(angle.denominator)
        # Independently recompute high order analytic series, round-error reserve
        # 1e-85 >400*1e-100*exp(19); omitted tail <1e-650 for |x|<=19.
        sv=x;cv=Decimal(1);st=x;ct=Decimal(1)
        for k in range(1,200):
            st=-st*x*x/((2*k)*(2*k+1));ct=-ct*x*x/((2*k-1)*(2*k));sv+=st;cv+=ct
        error=Q(Decimal('1e-85'))
        for box,ref in ((s,Q(sv)),(c,Q(cv))):assert box[0]-error<=ref<=box[1]+error
    assert counts['geometry_operations']>0


def test_closed_clip_retains_full_original_box_and_partition(acquired):
    r=evaluate(acquired,Q(139,1)+Q(1,3),Q(142)+Q(1,7))
    assert r.status=='VISIBLE' and r.original_anchor_seconds==128 and r.closed_support and r.positive_duration
    assert r.cells[0].start_seconds==Q(139)+Q(1,3) and r.cells[-1].end_seconds==Q(142)+Q(1,7)
    assert all(x.end_seconds==y.start_seconds for x,y in zip(r.cells,r.cells[1:]))
    for cell in r.cells:
        t=acquired.source_result.steps[cell.source_step_id].tube
        assert cell.position_bounds_m==tuple(tuple(Q(x) for x in pair) for pair in t.position_bounds_m)
        assert cell.source_closed_support==(t.source_start_seconds,t.source_end_seconds)
        assert cell.parent_boundary_id==acquired.source_result.steps[cell.source_step_id].parent_boundary_id


def test_zero_duration_is_closed_support_not_positive_coverage(acquired):
    r=evaluate(acquired,138,138)
    assert not r.positive_duration and len(r.cells)==1 and r.cells[0].start_seconds==r.cells[0].end_seconds==138


def test_horizon_foreign_frame_and_result_file_never_authority(acquired):
    with pytest.raises(ValueError,match='in-domain'):evaluate(acquired,127,129)
    with pytest.raises(ValueError,match='acquired'):
        evaluate_continuous_geometry({},acquired.inputs.environment,acquired.inputs.catalog[0],Q(139),Q(143),acquired.inputs.geometry_policy,charge=lambda *x:None)
    entry=acquired.inputs.catalog[0]
    ellipsoid=replace(entry.point.ellipsoid,name='foreign')
    with pytest.raises(ValueError,match='frame'):evaluate(acquired,139,143,replace(entry,point=replace(entry.point,ellipsoid=ellipsoid)))


def test_analytic_sphere_overhead_and_opposite_visibility():
    a,_=ar();r=((Q(7000000),)*2,(Q(0),)*2,(Q(0),)*2);n=((Q(1),)*2,(Q(0),)*2,(Q(0),)*2)
    out=_predicates(a,r,n,Q(6400000),Q(0),(-Q(1),Q(0),Q(0)),(Q(1,2),Q(1,2)))
    assert out[2]==(Q(600000),Q(600000)) and out[3]==(Q(600000),Q(600000)) and out[-1]=='VISIBLE'
    a,_=ar();out=_predicates(a,r,((-Q(1),)*2,(Q(0),)*2,(Q(0),)*2),Q(6400000),Q(0),None,None)
    assert out[-1]=='BLOCKED'


def test_control_quota_failure_retains_spent_work_and_no_partial_certificate(acquired):
    s=replace(acquired,runtime_work=RuntimeWork(upstream_entries=1));p=s.inputs.geometry_policy
    s.runtime_work.geometry_operations=s.inputs.limits.max_geometry_operations-5
    with pytest.raises(ValueError,match='QUOTA'):evaluate(s,139,143)
    assert s.runtime_work.geometry_operations==s.inputs.limits.max_geometry_operations
    assert s.runtime_work.geometry_control_units>0


def test_cell_and_phase_domains_rejected_explicitly(acquired):
    p=ContinuousGeometryPolicy(maximum_cells=1)
    with pytest.raises(ValueError,match='CELL_LIMIT'):
        evaluate_continuous_geometry(acquired.source_authority,acquired.inputs.environment,acquired.inputs.catalog[0],Q(139),Q(143),p,charge=lambda *x:None)
    a,_=ar()
    with pytest.raises(ValueError,match='PHASE'):_trig_bounds(a,Q(33),Q(34))