"""Owned differential checks for compiled current-world forcing.

These tests use the existing short fixture; they are not a long campaign,
an eclipse/event-time certificate or a performance measurement.
"""
from copy import copy, deepcopy
from dataclasses import asdict, replace
from fractions import Fraction as Q
from pathlib import Path
import json
import pickle
import sys

import pytest

from lifetime_support import root_for
from ops_sim.v5 import _lifecycle_typed as native
from ops_sim.v5.lifecycle_backend import current_source_binding
from ops_sim.v5.lifecycle_document import dumps_root, loads_root
from ops_sim.v5.lifecycle_execution import start_lifecycle
from ops_sim.v5.lifecycle_job_prepared import admit_job_root
from ops_sim.v5.lifecycle_physics import PendingLifecycleAction, _forcing
from ops_sim.v5.long_mission import LongMissionAction
from ops_sim.v5.long_mission_continuation import _scientific


SOURCE = Path(__file__).resolve().parents[1]


def encoded(value):
    return json.dumps(_scientific(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pair(table=False):
    root = root_for(600)
    if table:
        root = replace(root, sun_mode='BOUND_SHORT_TABLE_V1', reduced_sun_policy=None)
    raw = dumps_root(root)
    build = json.loads((SOURCE/'ops_sim/v5/lifecycle_typed_build_receipt.json').read_bytes())
    source = current_source_binding()
    actual, token = admit_job_root(raw, source, build_binding=build)
    state = start_lifecycle(actual, backend=build['execution_domain'], source_binding=source,
                            backend_build=build, job_admission=token)
    reference = start_lifecycle(loads_root(raw))
    action = LongMissionAction('compiled-world-short-hold', 'HOLD_UNTIL', until_seconds=188)
    pending = PendingLifecycleAction(action, 128, 188, state.physical.attitude)
    return state, reference, pending


def owner_data(physical):
    source = physical.source_authority
    return dict(orbit=physical.nominal_provider.to_data(),
        world={name:getattr(source, name) for name in ('controls', 'lookups', 'guards', 'sun_queries',
            'lighting_evaluations', 'lighting_evictions', 'peak_lighting_records')},
        lighting=deepcopy(source._lighting), runtime=asdict(physical.runtime_work))


@pytest.mark.parametrize('table', (False, True))
def test_compiled_world_full_forcing_and_original_paid_caches_match_reference(table):
    state, reference, pending = pair(table)
    physical, old = state.physical, reference.physical
    with state.backend_context.transaction():
        before = native.native_entry_counts()
        plan = native.prepare_world(physical, physical.harness.hardware, pending)
        assert native.native_entry_counts() == before  # pure admission, no numerical entry
        points = native.world_support_points(plan, Q(128), Q(148))
        schedule = old.source_authority.schedule(Q(128), Q(148))
        assert points == tuple(sorted({Q(128), Q(148)} | {
            x for cell in schedule.cells for x in (cell.start_seconds, cell.end_seconds)}))
        for left, right in ((128, 129), (129, 133), (133, 138), (138, 148), (138, 148)):
            data = native.world_forcing(plan, Q(left), Q(right))
            forcing, eps = native.materialize_world_forcing(plan, data)
            old_forcing, old_eps, camera, panel, supports = _forcing(
                old, old.harness.hardware, Q(left), Q(right), old.attitude.quaternion)
            assert encoded((forcing, eps)) == encoded((old_forcing, old_eps))
            assert encoded((data['camera'], data['panel'], data['supports'])) == encoded((camera, panel, supports))
            assert encoded(data['quaternion']) == encoded(old.attitude.quaternion)
            assert owner_data(physical) == owner_data(old)
        assert plan.snapshot()['forcing_returned'] == 5
        assert plan.snapshot()['support_returned'] == 1


def test_selected_forcing_batch_matches_single_materialization_without_queries():
    state, _, pending = pair()
    with state.backend_context.transaction():
        plan = native.prepare_world(state.physical, state.physical.harness.hardware, pending)
        data = tuple(native.world_forcing(plan, Q(a), Q(b)) for a, b in ((128, 129), (129, 130)))
        before = owner_data(state.physical)
        expected = tuple(native.materialize_world_forcing(plan, item) for item in data)
        assert encoded(native.materialize_world_forcings(plan, data)) == encoded(expected)
        assert owner_data(state.physical) == before
        with pytest.raises(ValueError, match='exact selected forcing batch'):
            native.materialize_world_forcings(plan, list(data))


def test_compiled_world_executes_no_python_orbit_schedule_pose_or_case_callbacks():
    state, _, pending = pair()
    forbidden = {
        ('lifecycle_orbit.py', 'at_seconds'), ('lifecycle_orbit.py', 'query'),
        ('orbit_j2.py', '_rk4_step'), ('orbit_j2_gravity.py', '_gravity'),
        ('lifecycle_world.py', 'schedule'), ('lifecycle_world.py', '_nominal_light'),
        ('lifecycle_world.py', 'sun_position'), ('lifecycle_world.py', 'orientation_inputs'),
        ('assembly_attitude_3d.py', 'direction'), ('environment_forcing.py', '_case'),
    }
    observed = []
    def watch(frame, event, unused):
        if event == 'call':
            identity = (Path(frame.f_code.co_filename).name, frame.f_code.co_name)
            if identity in forbidden: observed.append(identity)
    with state.backend_context.transaction():
        plan = native.prepare_world(state.physical, state.physical.harness.hardware, pending)
        previous = sys.getprofile()
        try:
            sys.setprofile(watch)
            native.world_support_points(plan, Q(128), Q(148))
            data = native.world_forcing(plan, Q(128), Q(138))
            native.materialize_world_forcing(plan, data)
        finally: sys.setprofile(previous)
    assert observed == []


def test_world_plan_and_forcing_data_have_owned_noncopyable_authority():
    state, _, pending = pair()
    with state.backend_context.transaction():
        plan = native.prepare_world(state.physical, state.physical.harness.hardware, pending)
        other = native.prepare_world(state.physical, state.physical.harness.hardware, pending)
        data = native.world_forcing(plan, Q(128), Q(129))
        for value in (plan, data):
            for action in (copy, deepcopy, pickle.dumps):
                with pytest.raises(TypeError): action(value)
        with pytest.raises(TypeError): data['sunlit'] = False
        with pytest.raises((TypeError, AttributeError)): data._values = {}
        with pytest.raises(ValueError, match='foreign'):
            native.materialize_world_forcing(other, data)
        with pytest.raises(ValueError, match='foreign'):
            native.materialize_world_forcing(plan, dict(sunlit=True))
    with state.backend_context.transaction():
        before = owner_data(state.physical)
        with pytest.raises(ValueError, match='inactive|foreign'):
            native.world_forcing(plan, Q(129), Q(130))
        assert owner_data(state.physical) == before


def test_public_world_boundary_refuses_policy_and_hardware_mutation_before_query():
    state, _, pending = pair()
    physical = state.physical
    with state.backend_context.transaction():
        plan = native.prepare_world(physical, physical.harness.hardware, pending)
        provider = physical.nominal_provider; old_policy = provider.policy
        try:
            provider.policy = replace(old_policy, max_queries=old_policy.max_queries-1)
            before = owner_data(physical)
            with pytest.raises(ValueError, match='drift'):
                native.world_forcing(plan, Q(128), Q(129))
            assert owner_data(physical) == before
        finally: provider.policy = old_policy
        hardware = physical.harness.hardware.base_hardware; old_axis = hardware.panel_body_normal
        try:
            object.__setattr__(hardware, 'panel_body_normal', tuple(-x for x in old_axis))
            before = owner_data(physical)
            with pytest.raises(ValueError, match='drift'):
                native.world_forcing(plan, Q(128), Q(129))
            assert owner_data(physical) == before
        finally: object.__setattr__(hardware, 'panel_body_normal', old_axis)


def test_world_admission_rejects_mutated_policy_foreign_hardware_and_active_scope():
    state, _, pending = pair()
    physical = state.physical
    with pytest.raises(ValueError, match='transaction'):
        native.prepare_world(physical, physical.harness.hardware, pending)
    with state.backend_context.transaction():
        before = owner_data(physical)
        with pytest.raises(ValueError, match='foreign'):
            native.prepare_world(physical, deepcopy(physical.harness.hardware), pending)
        assert owner_data(physical) == before
        old_policy = physical.nominal_provider.policy
        try:
            physical.nominal_provider.policy = replace(old_policy, max_queries=old_policy.max_queries-1)
            with pytest.raises(ValueError, match='authority'):
                native.prepare_world(physical, physical.harness.hardware, pending)
        finally: physical.nominal_provider.policy = old_policy
        with pytest.raises(TypeError, match='stationary'):
            native.prepare_world(physical, physical.harness.hardware, replace(pending, payload_w=1.))


@pytest.mark.parametrize('mutation',('replacement','code'))
def test_compiled_world_admission_callable_is_pinned_before_any_side_effect(monkeypatch,mutation):
    from ops_sim.v5 import lifecycle_typed_world as boundary
    state,_,pending=pair();physical=state.physical
    def forbidden(physical,hardware,pending):
        raise AssertionError('foreign admission executed')
    with state.backend_context.transaction():
        before=owner_data(physical)
        with monkeypatch.context()as changes:
            if mutation=='replacement':changes.setattr(boundary,'admit_world_plan',forbidden)
            else:changes.setattr(boundary.admit_world_plan,'__code__',forbidden.__code__)
            with pytest.raises(ValueError,match='admission callable drift'):
                native.prepare_world(physical,physical.harness.hardware,pending)
        assert owner_data(physical)==before


@pytest.mark.parametrize('left,right', ((Q(127), Q(128)), (128., Q(129)), (Q(130), Q(129))))
def test_compiled_world_invalid_time_refuses_before_paid_scientific_work(left, right):
    state, _, pending = pair()
    with state.backend_context.transaction():
        plan = native.prepare_world(state.physical, state.physical.harness.hardware, pending)
        before = owner_data(state.physical)
        with pytest.raises(ValueError): native.world_forcing(plan, left, right)
        assert owner_data(state.physical) == before
