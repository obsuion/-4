from dataclasses import replace, asdict
from fractions import Fraction as Q
import pytest
from examples.m3_general_earth_mission_demo import make_inputs
from ops_sim.v5 import environment_mission_3d as mission
from ops_sim.v5.environment_mission_3d_document import mission_input_digest
from ops_sim.v5.mission_continuous_geometry import _bind_acquired_source
from ops_sim.v5.checkpoint import CheckpointState


@pytest.fixture(scope='module')
def initial(): return mission.start_environment_mission(make_inputs())


def fresh(s, inputs=None):
    d = s.inputs if inputs is None else inputs
    return replace(s, inputs=d, context=d.initial_checkpoint.restore(d.simulation_inputs),
        cursor=0, outcomes=(), acquisitions=(), runtime_work=mission.RuntimeWork(**asdict(s.runtime_work)),
        input_digest=mission_input_digest(d), source_authority=_bind_acquired_source(s.source_result, d.environment))


def run(s, n=5):
    while s.cursor < n: s = mission.advance_environment_mission(s)
    return s


def test_real_general_acquisition_storage_delivery(initial):
    s = run(fresh(initial)); point, capture, wait, contact, finish = s.outcomes
    assert all(o.status == 'completed' for o in s.outcomes)
    assert s.assessment().credited_products == 1 and len(s.acquisitions) == 1
    assert len(s.context.ground_data_delivery_state.completed_deliveries) == 1
    assert not s.context.spacecraft_state.data_storage.stored_records
    assert capture.continuous_geometry.status == contact.continuous_geometry.status == 'VISIBLE'
    assert capture.continuous_geometry.point.latitude_rad.value != 0
    assert capture.continuous_geometry.frame.ellipsoid.flattening.value > 0
    assert capture.continuous_geometry.frame.rotation.angular_velocity_rad_per_s.value != 0
    assert capture.continuous_geometry.end_ray.at_seconds == capture.end_seconds
    assert capture.continuous_geometry.end_ray.forward_ellipsoid_intersection == 'VISIBLE'
    assert point.slew.duration_seconds > 0 and any(c.actuator_draw_w > 0 for c in point.cuts)
    assert s.runtime_work.geometry_queries == 2 and s.attitude.at_seconds == Q(192)


def test_mount_only_causal_time_energy(initial):
    compact = run(fresh(initial)); other = replace(initial.inputs, assembly=make_inputs('outboard').assembly)
    outboard = run(fresh(initial, other))
    assert compact.outcomes[0].slew.duration_seconds != outboard.outcomes[0].slew.duration_seconds
    assert compact.inputs.environment == outboard.inputs.environment
    assert compact.inputs.actions == outboard.inputs.actions and compact.inputs.actuator == outboard.inputs.actuator
    assert compact.context.spacecraft_state.battery != outboard.context.spacecraft_state.battery


def test_buried_capture_precedes_physical_custody(initial):
    d = initial.inputs; point = d.catalog[0].point
    catalog = (replace(d.catalog[0], point=replace(point,
        ellipsoidal_height_m=replace(point.ellipsoidal_height_m, value=-100.))), *d.catalog[1:])
    d = replace(d, catalog=catalog, actions=(mission.MissionAction('capture-only', 'CAPTURE', 'target', 4),))
    s = fresh(initial, d); before = CheckpointState.from_context(s.context).to_dict()
    denied = mission.advance_environment_mission(s)
    assert denied.outcomes[-1].status != 'completed' and denied.outcomes[-1].continuous_geometry.status == 'BLOCKED'
    assert CheckpointState.from_context(denied.context).to_dict() == before
    assert not denied.acquisitions and denied.runtime_work.physical_reserved_calls == 0


def test_late_primitive_failure_atomic_paid(initial, monkeypatch):
    s = fresh(initial); original = mission._physical_substep; calls = []
    before = CheckpointState.from_context(s.context).to_dict()
    def failure(*a, **k):
        calls.append(1)
        if len(calls) == 2: raise RuntimeError('B43 injected late primitive failure')
        return original(*a, **k)
    monkeypatch.setattr(mission, '_physical_substep', failure)
    with pytest.raises(RuntimeError, match='injected'): mission.advance_environment_mission(s)
    assert s.runtime_work.physical_completed_calls == 1 and s.runtime_work.physical_work_unknown_events == 1
    assert CheckpointState.from_context(s.context).to_dict() == before and s.outcomes == ()


def test_actual_interior_trap_rolls_back_contact_only():
    s = mission.start_environment_mission(make_inputs(case='trap')); s = run(s, 3)
    assert s.acquisitions and s.context.spacecraft_state.data_storage.stored_records
    before = CheckpointState.from_context(s.context).to_dict(); physical = s.runtime_work.physical_reserved_calls
    denied = mission.advance_environment_mission(s); outcome = denied.outcomes[-1]
    assert outcome.status != 'completed' and outcome.continuous_geometry.status in ('BLOCKED', 'UNRESOLVED')
    entry=s.inputs.catalog[2]
    assert all(mission._observations(s,entry,t,t)[0].visible for t in (148,188))
    assert any(c.los == 'BLOCKED' for c in outcome.continuous_geometry.cells)
    assert CheckpointState.from_context(denied.context).to_dict() == before
    assert s.runtime_work.physical_reserved_calls == physical and not s.context.ground_data_delivery_state.completed_deliveries
