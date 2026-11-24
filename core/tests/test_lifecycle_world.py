"""Independent-grid and bounded-world checks for the opt-in B52 nominal family."""
from dataclasses import replace
from fractions import Fraction as Q
from functools import lru_cache
from copy import deepcopy
from math import isclose, hypot
import json
import pytest

from examples.m3_long_mission_demo import make_inputs
from ops_sim.v5.orbit_config import GeometryInstant, TTEpoch
from ops_sim.v5.orbit_j2 import evaluate_j2_cartesian_state, J2RK4SolverConfig
from ops_sim.v5.lifecycle_orbit import (LifecycleOrbitPolicy, LifecycleOrbitProvider,
    MAX_DURATION_SECONDS)
from ops_sim.v5.lifecycle_world import (LifecycleWorld, AcquiredLifecycleWorld,
    ReducedSunPolicy, SUN_METHOD)
from ops_sim.v5.long_nominal_provider import LongNominalProvider
from ops_sim.v5.long_environment import AcquiredLongEnvironment
from ops_sim.v5.orbit_geometry import evaluate_ground_point_geometry
from ops_sim.v5.orbit_visibility import evaluate_ground_visibility
from ops_sim.v5.ids import GroundStationId


@lru_cache(maxsize=1)
def base():
    return make_inputs(duration=600)


def world(*, duration=600, table=False, **kw):
    e = base().environment
    end = e.start_seconds+duration
    profile = tuple(replace(p, end_seconds=end if i == len(e.profile)-1 else p.end_seconds)
                    for i, p in enumerate(e.profile))
    return LifecycleWorld(e.trajectory, e.start_seconds, end, e.node_ids, profile,
                          sun_table=e.table if table else None, **kw)


def provider(**kw):
    return LifecycleOrbitProvider(base().environment.trajectory, LifecycleOrbitPolicy(**kw))


@pytest.mark.parametrize('seconds', (128, 129, 139, 158, 159, 200, 727, 728))
def test_same_original_rk4_grid_matches_independent_f2(seconds):
    trajectory = base().environment.trajectory
    p = provider()
    actual = p.at_seconds(Q(seconds))
    expected = evaluate_j2_cartesian_state(trajectory, actual.position.instant,
                                          J2RK4SolverConfig(10.0, 1024))
    assert actual == expected
    assert tuple(x.hex() for x in actual.position.components_m+actual.velocity.components_m_per_s) == tuple(
        x.hex() for x in expected.position.components_m+expected.velocity.components_m_per_s)


def test_tail_queries_never_seed_original_grid_and_tail_cache_is_bounded():
    p = provider(max_tail_records=2)
    for seconds in (139, 143, 159, 167):
        p.at_seconds(Q(seconds))
    actual = p.at_seconds(Q(168))
    expected = evaluate_j2_cartesian_state(p.trajectory, actual.position.instant,
                                          J2RK4SolverConfig(10.0, 1024))
    assert actual == expected
    assert p.work.full_steps == 4
    assert len(p._tails) == 2 and sorted(p._tails) == [Q(159), Q(167)]
    assert p.work.tail_evictions == 2


def test_many_chronological_queries_evict_without_prefix_reconstruction():
    p = provider(max_retained_grid=8, max_tail_records=2)
    for index in range(1, 33):
        time = Q(128+index*10)
        p.retain_from(max(Q(128), time-40))
        actual = p.at_seconds(time)
        assert len(p._grid_states) <= 8 and len(p._tails) <= 2
    expected = evaluate_j2_cartesian_state(p.trajectory, actual.position.instant,
                                          J2RK4SolverConfig(10.0, 1024))
    assert actual == expected
    assert p.work.full_steps == 32
    assert p.work.force_reserved == p.work.force_completed == 129
    assert p.work.grid_evictions == p._low and p._low > 0
    with pytest.raises(ValueError, match='EVICTED'):
        p.at_seconds(Q(138))


def test_old_knowledge_pin_refuses_before_work_instead_of_dropping_seed():
    p = provider(max_retained_grid=3)
    p.at_seconds(Q(148))
    before = p.to_data()
    with pytest.raises(ValueError, match='RETAINED_SEED_CAPACITY_BEFORE_WORK'):
        p.at_seconds(Q(158))
    assert p.to_data() == before
    p.retain_from(Q(138))
    assert p.at_seconds(Q(158)).position.instant.elapsed_seconds == 158.0


def test_snapshot_restores_exact_data_without_gravity_or_rk4(monkeypatch):
    import ops_sim.v5.lifecycle_orbit as owner
    p = provider(max_retained_grid=8)
    p.at_seconds(Q(159))
    p.retain_from(Q(138))
    packet = json.loads(json.dumps(p.to_data()))
    def forbidden(*args, **kw):
        raise AssertionError('restore invoked scientific owner')
    monkeypatch.setattr(owner, '_gravity', forbidden)
    monkeypatch.setattr(owner, '_rk4_step', forbidden)
    restored = LifecycleOrbitProvider.from_data(p.trajectory, p.policy, packet)
    assert restored.to_data() == packet
    before = restored.work.force_completed
    assert restored.at_seconds(Q(159)).position == p.at_seconds(Q(159)).position
    assert restored.work.force_completed == before


def test_restored_suffix_has_same_future_binary_state_and_paid_ledger():
    p = provider(max_retained_grid=8)
    p.at_seconds(Q(159))
    p.retain_from(Q(138))
    restored = LifecycleOrbitProvider.from_data(p.trajectory, p.policy, p.to_data())
    for seconds in (168, 177, 188):
        assert restored.at_seconds(Q(seconds)) == p.at_seconds(Q(seconds))
    assert restored.to_data() == p.to_data()


def test_actual_forecast_clones_have_separate_state_and_keep_inherited_costs():
    p = provider()
    p.at_seconds(Q(148))
    saved = p.to_data()
    forecast = p.fork('FORECAST')
    assert forecast.identity != p.identity
    assert forecast.authority_identity == p.authority_identity
    assert forecast.work.force_reserved == p.work.force_reserved
    forecast.at_seconds(Q(188))
    assert p.to_data() == saved
    assert forecast._grid_states is not p._grid_states
    assert forecast.work is not p.work


def test_failed_force_is_charged_and_not_published_as_completed(monkeypatch):
    import ops_sim.v5.lifecycle_orbit as owner
    p = provider()
    before = p.to_data()
    def failure(*args):
        raise ArithmeticError('SYNTHETIC_INJECTED_RK4_FAILURE')
    monkeypatch.setattr(owner, '_rk4_step', failure)
    with pytest.raises(ArithmeticError, match='SYNTHETIC_INJECTED'):
        p.at_seconds(Q(138))
    assert p.work.force_reserved == before['work']['force_reserved']+4
    assert p.work.force_completed == before['work']['force_completed']
    assert p.work.full_steps == 0 and p._high == 0
    assert p.work.unknown_primitive_events == 1 and p.failed
    with pytest.raises(ValueError, match='FAILED_NO_CONTINUATION'):
        p.at_seconds(Q(148))


def test_finite_force_quota_rejects_before_new_query_or_force():
    p = provider(max_force_reservations=4)
    before = p.to_data()
    with pytest.raises(ValueError, match='QUOTA_BEFORE_WORK'):
        p.at_seconds(Q(138))
    assert p.to_data() == before


@pytest.mark.parametrize('mutation', ('float', 'gap', 'work', 'floor', 'identity', 'bool'))
def test_snapshot_strict_data_guards(mutation):
    p = provider()
    p.at_seconds(Q(148))
    packet = deepcopy(p.to_data())
    if mutation == 'float':
        packet['grid'][0]['r'][0] = 'nan'
    elif mutation == 'gap':
        packet['grid'][1]['index'] = 90
    elif mutation == 'work':
        packet['work']['force_completed'] += 1
    elif mutation == 'floor':
        packet['retention_floor'] = ['0x1', '0x0']
    elif mutation == 'identity':
        packet['identity'] = '0'*64
    else:
        packet['high'] = True
    with pytest.raises(ValueError):
        LifecycleOrbitProvider.from_data(p.trajectory, p.policy, packet)


def test_foreign_epoch_and_backward_watermark_are_explicit():
    p = provider()
    when = p.anchor.instant
    foreign = GeometryInstant(TTEpoch(when.epoch.julian_day+1, when.epoch.fractional_day), 138.0)
    with pytest.raises(ValueError, match='TT epoch'):
        p.query(foreign)
    p.retain_from(Q(138))
    with pytest.raises(ValueError, match='WATERMARK'):
        p.retain_from(Q(128))


def test_full_15_julian_year_admission_is_data_only_not_a_run():
    # No orbit/world query: this checks finite declared capability, not coverage.
    e = world(duration=MAX_DURATION_SECONDS)
    assert e.end_seconds-e.start_seconds == 473364000
    assert LifecycleOrbitPolicy().max_duration_seconds == MAX_DURATION_SECONDS
    with pytest.raises(ValueError, match='15 Julian year'):
        world(duration=MAX_DURATION_SECONDS+1)


def test_sun_table_is_full_domain_authority_and_never_clamped_or_repeated():
    e = world(table=True)
    p = provider()
    acquired = AcquiredLifecycleWorld(e, p)
    from ops_sim.v5.sun_table import evaluate_sun_position
    instant = GeometryInstant(p.anchor.instant.epoch, 200.0)
    assert acquired.sun_position(instant) == evaluate_sun_position(e.sun_table, instant)
    with pytest.raises(ValueError, match='WHOLE_DOMAIN'):
        world(duration=86400, table=True)


def test_assumed_generated_sun_varies_and_covers_declared_day_without_orbit_query():
    e = world(duration=86400)
    p = provider()
    a = AcquiredLifecycleWorld(e, p)
    before = p.work.force_completed
    first = a.sun_position(GeometryInstant(p.anchor.instant.epoch, 128.0))
    final = a.sun_position(GeometryInstant(p.anchor.instant.epoch, 86528.0))
    assert first.components_m != final.components_m
    assert first.components_m == (e.sun.distance_m, 0.0, 0.0)
    assert isclose(hypot(*final.components_m), e.sun.distance_m, rel_tol=2**-50)
    assert p.work.force_completed == before
    assert a.accounting()['sun_authority'] == SUN_METHOD
    with pytest.raises(ValueError, match='ASSUMED'):
        ReducedSunPolicy(provenance='FLIGHT_CALIBRATED')


def test_common_short_table_and_sample_policy_match_accepted_forcing_cells():
    old = base().environment
    old_p = LongNominalProvider(old.trajectory)
    old_source = AcquiredLongEnvironment(old, old_p)
    e = world(table=True, lighting_step_seconds=old.lighting_step_seconds)
    source = AcquiredLifecycleWorld(e, provider())
    assert source.schedule(Q(128), Q(188)).cells == old_source.schedule(Q(128), Q(188)).cells


def test_schedule_always_cuts_original_lighting_grid_and_is_contiguous():
    source = AcquiredLifecycleWorld(world(lighting_step_seconds=60), provider())
    schedule = source.schedule(Q(136), Q(260))
    assert tuple((c.start_seconds, c.end_seconds) for c in schedule.cells) == (
        (Q(136), Q(188)), (Q(188), Q(248)), (Q(248), Q(260)))
    assert source.next_boundary_after(Q(188)) == Q(248)
    assert all(c.assessment in ('ILLUMINATED', 'OCCULTED', 'UNRESOLVED') for c in schedule.cells)


def test_lighting_eviction_and_data_only_restore_keep_paid_work(monkeypatch):
    import ops_sim.v5.lifecycle_world as owner
    e = world(duration=1200, lighting_step_seconds=60, max_lighting_records=2)
    source = AcquiredLifecycleWorld(e, provider(max_retained_grid=16))
    for index in range(8):
        start = Q(128+index*60)
        source.retain_from(start)
        source.schedule(start, start+60)
        assert len(source._lighting) <= 2
    orbit_data, world_data = source.provider.to_data(), source.to_data()
    def forbidden(*args, **kwargs):
        raise AssertionError('snapshot materialization performed geometry')
    monkeypatch.setattr(owner, 'nominal_parallel_ray', forbidden)
    restored_p = LifecycleOrbitProvider.from_data(source.provider.trajectory, source.provider.policy, orbit_data)
    restored = AcquiredLifecycleWorld.from_data(e, restored_p, world_data)
    assert restored.to_data() == world_data
    assert source.lighting_evictions > 0
    assert source.provider.work.grid_evictions > 0


def test_world_snapshot_rejects_counters_foreign_scope_and_unordered_lighting():
    source = AcquiredLifecycleWorld(world(), provider())
    source.schedule(Q(128), Q(188))
    for change in ('counter', 'role', 'order'):
        data = deepcopy(source.to_data())
        if change == 'counter':
            data['controls'] = -1
        elif change == 'role':
            data['role'] = 'FORECAST'
        else:
            data['lighting'] = data['lighting']+data['lighting']
        with pytest.raises(ValueError):
            AcquiredLifecycleWorld.from_data(source.environment, source.provider, data)


def test_rotating_ground_geometry_and_declared_service_are_actual_functions():
    source = AcquiredLifecycleWorld(world(), provider())
    station = next(e for e in base().catalog if type(e.point.point_id) is GroundStationId)
    samples = source.observations(station, Q(128), Q(188), base().sampling)
    for sample in samples:
        state = source.provider.at_seconds(sample.requested_seconds)
        assert sample.geometry == evaluate_ground_point_geometry(station.point, state)
        assert sample.visibility == evaluate_ground_visibility(station.point, state, station.visibility_policy)
        assert sample.station_available is station.station_available
        assert sample.rf_admitted is station.rf_admitted
    assert samples[0].geometry.ground_state.position.components_m != samples[-1].geometry.ground_state.position.components_m
    unavailable = replace(station, station_available=False)
    rejected = source.observations(unavailable, Q(128), Q(128), base().sampling)[0]
    assert not rejected.serviceable_nominal


def test_schedule_capacity_refusal_is_before_force_and_keeps_paid_admission():
    source = AcquiredLifecycleWorld(world(max_schedule_cells=1), provider())
    before = source.provider.work.force_reserved
    with pytest.raises(ValueError, match='CELL_CAPACITY_BEFORE_WORK'):
        source.schedule(Q(128), Q(308))
    assert source.provider.work.force_reserved == before
    assert source.controls > 512
