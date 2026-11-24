from dataclasses import replace
from fractions import Fraction as Q
from functools import lru_cache
import pytest
from examples.m3_long_mission_demo import make_inputs
from ops_sim.v5.long_nominal_provider import LongNominalProvider,LongNominalPolicy
from ops_sim.v5.orbit_j2 import evaluate_j2_cartesian_state,J2RK4SolverConfig
from ops_sim.v5.orbit_config import GeometryInstant

@lru_cache(maxsize=1)
def inputs():return make_inputs(duration=600)

@pytest.mark.parametrize('seconds',[128.,127.5,100.,129.5,168.,240.5,728.,86528.])
def test_independent_original_f2_exact(seconds):
    trajectory=inputs().environment.trajectory;p=LongNominalProvider(trajectory)
    instant=GeometryInstant(trajectory.initial_state.position.instant.epoch,seconds)
    actual=p.query(instant)
    reference=evaluate_j2_cartesian_state(trajectory,instant,J2RK4SolverConfig(10.,20000))
    assert actual==reference
    assert tuple(x.hex() for x in actual.position.components_m)==tuple(x.hex() for x in reference.position.components_m)

def test_remainders_never_seed_prefix_and_reads_paid():
    trajectory=inputs().environment.trajectory;p=LongNominalProvider(trajectory)
    p.at_seconds(Q(139));p.at_seconds(Q(143));p.at_seconds(Q(159));a=p.at_seconds(Q(158));p.at_seconds(Q(159))
    reference=evaluate_j2_cartesian_state(trajectory,a.position.instant,J2RK4SolverConfig(10.,20000))
    assert a==reference
    assert p.work.full_steps==3 and p.work.tail_steps==3
    assert p.work.force_reserved==p.work.force_completed==25
    assert p.work.cache_reads==6 and p.work.queries==5

def test_quota_before_force_and_foreign_identity():
    p=LongNominalProvider(inputs().environment.trajectory,replace(LongNominalPolicy(),max_force_reservations=4))
    with pytest.raises(ValueError,match='BEFORE_WORK'):p.at_seconds(Q(138))
    assert p.work.force_reserved==1 and p.work.full_steps==0
    with pytest.raises(ValueError,match='foreign'):p.validate(replace(inputs().environment.trajectory,initial_state=replace(inputs().environment.trajectory.initial_state,
        velocity=replace(inputs().environment.trajectory.initial_state.velocity,components_m_per_s=(0.,7000.,0.)))))

def test_unknown_failed_primitive_not_refunded(monkeypatch):
    import ops_sim.v5.long_nominal_provider as owner
    p=LongNominalProvider(inputs().environment.trajectory)
    def failure(*args):raise ArithmeticError('injected original-call exception')
    monkeypatch.setattr(owner,'_rk4_step',failure)
    with pytest.raises(ArithmeticError):p.at_seconds(Q(138))
    assert p.work.force_reserved==5 and p.work.force_completed==1 and p.work.unknown_primitive_events==1
    with pytest.raises(ValueError,match='FAILED'):p.at_seconds(Q(148))

def test_initial_unreturned_force_visible_to_external_work(monkeypatch):
    import ops_sim.v5.long_nominal_provider as owner
    from ops_sim.v5.long_mission import RuntimeWork,LongMissionLimits
    trajectory=inputs().environment.trajectory;work=RuntimeWork();limits=LongMissionLimits()
    def failure(*a):raise ArithmeticError('injected initial admission failure')
    monkeypatch.setattr(owner,'_gravity',failure)
    with pytest.raises(ArithmeticError,match='initial admission'):
        owner.LongNominalProvider(trajectory,charge=lambda n,c:work.charge(n,c,limits))
    assert work.nominal_force_reserved==1 and work.nominal_force_completed==0
    assert work.nominal_unknown_events==1
