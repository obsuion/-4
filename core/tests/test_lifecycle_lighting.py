"""Selected sampled-held lighting duration accounting, independent of cache."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
from functools import lru_cache
import pytest

from examples.m3_long_mission_demo import make_inputs
from ops_sim.v5.lifecycle_world import LifecycleWorld,AcquiredLifecycleWorld,LIGHT_TALLY_METHOD
from ops_sim.v5.lifecycle_orbit import LifecycleOrbitProvider,LifecycleOrbitPolicy,_qread


@lru_cache(maxsize=1)
def original():return make_inputs(duration=600)


def source(*,duration=600,records=256):
    old=original().environment
    end=old.start_seconds+duration
    world=LifecycleWorld(old.trajectory,old.start_seconds,end,old.node_ids,
        (replace(old.profile[0],start_seconds=old.start_seconds,end_seconds=end),),
        max_lighting_records=records)
    provider=LifecycleOrbitProvider(old.trajectory,LifecycleOrbitPolicy(max_retained_grid=16))
    return AcquiredLifecycleWorld(world,provider)


def seconds(source,name):return _qread(source.lighting_accounting()[name])


def test_queries_are_not_consumption_and_selected_support_has_no_geometry_calls(monkeypatch):
    s=source();s.schedule(Q(128),Q(248))
    assert seconds(s,'covered_seconds')==0
    flags=dict(s._lighting);force=s.provider.work.force_reserved
    import ops_sim.v5.lifecycle_world as owner
    def forbidden(*a,**k):raise AssertionError('duration consumption invoked geometry')
    monkeypatch.setattr(owner,'nominal_parallel_ray',forbidden)
    monkeypatch.setattr(s.provider,'at_seconds',forbidden)
    first=s.prepare_support_delta(Q(128),Q(188))
    assert seconds(s,'covered_seconds')==0
    s.commit_support_delta(first);s.consume_support(Q(188),Q(248))
    assert s.provider.work.force_reserved==force
    assert seconds(s,'covered_seconds')==120
    for name,flag in (('illuminated_seconds','ILLUMINATED'),('occulted_seconds','OCCULTED'),('unresolved_seconds','UNRESOLVED')):
        assert seconds(s,name)==sum((Q(60) for f in flags.values() if f==flag),Q(0))


def test_partial_support_is_exact_and_duplicate_or_gap_is_rejected():
    s=source();s.schedule(Q(128),Q(249))
    for a,b in ((Q(128),Q(257,2)),(Q(257,2),Q(180)),(Q(180),Q(249))):s.consume_support(a,b)
    assert seconds(s,'covered_seconds')==121
    assert sum((seconds(s,n) for n in ('illuminated_seconds','occulted_seconds','unresolved_seconds')),Q(0))==121
    for a,b in ((Q(128),Q(188)),(Q(250),Q(260))):
        with pytest.raises(ValueError,match='GAP_OR_DUPLICATE'):s.consume_support(a,b)


def test_unconsumed_or_missing_support_is_not_invented():
    s=source();before=s.lighting_accounting()
    with pytest.raises(ValueError,match='EXISTING_SELECTED_SUPPORT'):s.consume_support(Q(128),Q(188))
    assert s.lighting_accounting()==before
    s.consume_support(Q(128),Q(128))
    assert s.lighting_accounting()==before


def test_prepared_delta_cannot_substitute_a_different_lighting_classification():
    s=source();s.schedule(Q(128),Q(188));delta=s.prepare_support_delta(Q(128),Q(188))
    flag='UNRESOLVED' if delta.spans[0][2]!='UNRESOLVED' else 'ILLUMINATED'
    flags=('ILLUMINATED','OCCULTED','UNRESOLVED')
    altered=replace(delta,spans=((Q(128),Q(188),flag),),
        durations=tuple(Q(60) if name==flag else Q(0) for name in flags))
    with pytest.raises(ValueError,match='differs from retained'):s.commit_support_delta(altered)
    assert seconds(s,'covered_seconds')==0
    s.commit_support_delta(delta)
    assert seconds(s,'covered_seconds')==60


def test_eviction_and_restart_preserve_cumulative_durations_without_re_evaluation(monkeypatch):
    s=source(duration=1200,records=2)
    for i in range(8):
        a=Q(128+i*60);s.schedule(a,a+60);s.consume_support(a,a+60);s.retain_from(a+60)
    assert seconds(s,'covered_seconds')==480 and len(s._lighting)<=2
    orbit_data=s.provider.to_data();world_data=s.to_data()
    import ops_sim.v5.lifecycle_world as owner
    def forbidden(*a,**k):raise AssertionError('restore performed numerical query')
    monkeypatch.setattr(owner,'nominal_parallel_ray',forbidden)
    p=LifecycleOrbitProvider.from_data(s.provider.trajectory,s.provider.policy,orbit_data)
    restored=AcquiredLifecycleWorld.from_data(s.environment,p,world_data)
    assert restored.to_data()==world_data
    assert restored.lighting_accounting()['method']==LIGHT_TALLY_METHOD


def test_forecast_inherits_history_but_cannot_claim_forecast_duration():
    s=source();s.schedule(Q(128),Q(188));s.consume_support(Q(128),Q(188))
    p=s.provider.fork('FORECAST');f=s.fork(p)
    assert seconds(f,'covered_seconds')==60
    f.schedule(Q(188),Q(248))
    assert seconds(f,'covered_seconds')==60 and seconds(s,'covered_seconds')==60
    assert f.lighting_accounting()['scope']=='INHERITED_ACTUAL_PREFIX_ONLY_NO_FORECAST_CONSUMPTION'
    with pytest.raises(ValueError,match='FORECAST'):f.consume_support(Q(188),Q(248))


@pytest.mark.parametrize('kind',('sum','end','units','method','scope','commits','negative'))
def test_corrupt_tally_snapshot_is_rejected(kind):
    s=source();s.schedule(Q(128),Q(188));s.consume_support(Q(128),Q(188));data=deepcopy(s.to_data())
    t=data['lighting_consumption']
    if kind=='sum':t['covered_seconds']=['0x0','0x1']
    elif kind=='end':t['end_seconds']=['0x0','0x1']
    elif kind=='units':t['units']='day'
    elif kind=='method':t['method']='CONTINUOUS'
    elif kind=='scope':t['scope']='FORECAST'
    elif kind=='commits':t['selected_commits']=True
    else:t['occulted_seconds']=['-0x1','0x1']
    with pytest.raises(ValueError):AcquiredLifecycleWorld.from_data(s.environment,s.provider,data)
