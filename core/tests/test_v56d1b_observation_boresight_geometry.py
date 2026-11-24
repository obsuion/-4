"""Real D1a composition and independent inertial-ray/legacy compatibility checks."""

from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from ops_sim.v5.adcs import CommonFrameBoresightDirection, compute_boresight_angular_separation
from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.ids import ADCSBoresightFrameId
from ops_sim.v5.observation_feasibility import ObservationManeuverCandidate
from ops_sim.v5.orbit import TwoBodyTrajectory
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION
from ops_sim.v5.orbit_config import FrameKind, GeometryInstant
import ops_sim.v5.orbit_observation_opportunity as d1a
import ops_sim.v5.orbit_observation_boresight as adapter
from test_v50d1_time_engine import _context as generic_context
from test_v56a_time_frame_contracts import _parameter
from test_v56c1_ground_point_contracts import _state
from test_v56c2c_grid_projection_contracts import _inputs
from test_v56d1a_observation_opportunity_contracts import _target
from test_v56d1a_observation_opportunity_geometry import _projection_seam, _block
from test_v56d1b_observation_boresight_contracts import Binding, Result, derive, _arguments, PlainText


def _components(boresight):
    return boresight.x, boresight.y, boresight.z


def _assert_evidence(result, args):
    observation = result.orbit_observation
    frame = result.boresight_frame.frame
    state, ray = observation.spacecraft_state, observation.geometry.spacecraft_to_ground
    assert frame.kind is FrameKind.MODEL_INERTIAL
    assert frame == state.position.frame == state.velocity.frame == ray.frame
    assert state.position.instant == state.velocity.instant == ray.instant
    assert ray.instant.elapsed_seconds == args["step_start_seconds"]
    assert ray.instant.epoch == args["inputs"].coast_orbit.trajectory.initial_state.position.instant.epoch
    assert type(result.common_frame_boresight) is CommonFrameBoresightDirection
    assert _components(result.common_frame_boresight) == ray.components
    assert result.boresight_frame.frame_id is args["boresight_frame"].frame_id
    assert result.common_frame_boresight.frame_id is args["boresight_frame"].frame_id
    assert type(result.maneuver_candidate) is ObservationManeuverCandidate
    assert result.maneuver_candidate.opportunity is observation.opportunity
    assert result.maneuver_candidate.common_frame_boresight is result.common_frame_boresight
    for name in list(args)[:10]:
        assert getattr(result, name) is getattr(observation, name)


def test_real_hidden_pass_one_d1a_and_no_second_orbit_visibility_geometry(monkeypatch):
    calls, returned = [], {}
    for module, name in ((adapter, "derive_observation_opportunity_for_engine_step"),
                         (d1a, "project_ground_visibility_to_engine_grid"),
                         (d1a, "evaluate_two_body_state"), (d1a, "evaluate_ground_point_geometry")):
        owner = getattr(module, name)
        def spy(*values, _name=name, _owner=owner):
            calls.append((_name, values))
            result = _owner(*values)
            returned[_name] = result
            return result
        monkeypatch.setattr(module, name, spy)
    args = _arguments()
    result = derive(**args)
    assert [name for name, _ in calls] == ["derive_observation_opportunity_for_engine_step",
        "project_ground_visibility_to_engine_grid", "evaluate_two_body_state", "evaluate_ground_point_geometry"]
    assert all(a is b for a, b in zip(calls[0][1], list(args.values())[:10]))
    observation = result.orbit_observation
    assert observation is returned["derive_observation_opportunity_for_engine_step"]
    assert observation.spacecraft_state is returned["evaluate_two_body_state"]
    assert observation.geometry is returned["evaluate_ground_point_geometry"]
    assert observation.inputs.coast_orbit.trajectory.initial_state.position.instant.elapsed_seconds == 10.
    assert observation.spacecraft_state.position.instant == GeometryInstant(
        args["boresight_frame"].frame.rotation.epoch, 9)
    opportunity = result.maneuver_candidate.opportunity
    assert (opportunity.window_start_seconds, opportunity.window_end_seconds, opportunity.imaging_duration_seconds) == (9, 12, 3)
    _assert_evidence(result, args)
    for name in ("evaluate_two_body_state", "evaluate_ground_point_geometry", "project_ground_visibility_to_engine_grid",
                 "compute_boresight_transition", "evaluate_observation_sequence_feasibility", "ObservationOpportunityCatalog"):
        assert not hasattr(adapter, name)
    assert not any(hasattr(result, name) for name in ("feasible", "scheduled", "slew", "attitude", "catalog"))


# TEST-ONLY conditioned states on a synthetic unit sphere. The C2c seam below
# supplies one interval only to isolate the vector mapping, not certify physics.
# B1 at its initial instant and C1/D1a remain real production owners.
CASES = [
    pytest.param(.1, .2, (2., 0., 0.), (0., 1., 0.), 0., 0., 0, id="off-axis"),
    pytest.param(.1, math.pi/2+.2, (-.5, 1.8, .7), (-1., -.2, .1), 0., 0., 0, id="quadrant-2"),
    pytest.param(-.1, -math.pi+.2, (-1.8, -.6, .4), (.2, -1., .3), 0., 0., 0, id="quadrant-3"),
    pytest.param(-.1, -math.pi/2+.2, (0., -2., 0.), (1., 0., 0.), 0., 0., 0, id="quadrant-4"),
    pytest.param(0., 0., (2., 0., 0.), (0., 1., 0.), 0., 0., 0, id="exact-nadir"),
    pytest.param(1e-10, .2, (2., 0., 0.), (0., 1., 0.), 0., 0., 0, id="near-wrap-below"),
    pytest.param(-1e-10, .2, (2., 0., 0.), (0., 1., 0.), 0., 0., 0, id="near-wrap-above"),
    pytest.param(.1, .2, (2., 0., 0.), (0., 1., 0.), .1, .02, 3, id="rotating-earth"),
]


def _synthetic(monkeypatch, latitude, longitude, r, v, phase=0., rate=0., t=0):
    point = _target(latitude=latitude, longitude=longitude)
    state = _state(point, r=r, v=v, phase=phase, rate=rate, t=t)
    trajectory = TwoBodyTrajectory(state, _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", 2.))
    inputs = _inputs(1, trajectory=trajectory)
    _projection_seam(monkeypatch, (_block(t, 1, 1),))
    args = _arguments(inputs=inputs, target=point, search_start_seconds=float(t),
        search_end_seconds=float(t+1), first_step_start_seconds=t, step_start_seconds=t)
    return derive(**args), args


def _independent_ray(latitude, longitude, r, phase, rate, t):
    # Analytic sphere longitude advance: no production geodesy, transforms,
    # propagation, C1 helpers, local angles or returned ground state in oracle.
    longitude_inertial = longitude + phase + rate*t
    ground = (math.cos(latitude)*math.cos(longitude_inertial),
              math.cos(latitude)*math.sin(longitude_inertial), math.sin(latitude))
    delta = tuple(g - x for g, x in zip(ground, r))
    length = math.sqrt(math.fsum(x*x for x in delta))
    return tuple(x/length for x in delta), ground


@pytest.mark.parametrize("latitude,longitude,r,v,phase,rate,t", CASES)
def test_independent_inertial_ray_and_local_pointing_consistency(monkeypatch, latitude, longitude, r, v, phase, rate, t):
    result, args = _synthetic(monkeypatch, latitude, longitude, r, v, phase, rate, t)
    _assert_evidence(result, args)
    expected, ground = _independent_ray(latitude, longitude, r, phase, rate, t)
    q = _components(result.common_frame_boresight)
    # Dimensionless components; 1.9m<|r|<=2m, |ground|=1m, LOS>0.9m. Short O(1)
    # trig/subtraction/normalization chains are conditioned here. 128u covers
    # operation roundoff and normalization; add 8u*(1+|phase|+|omega*t|) for
    # phase formation/reduction, amplified <=4 through subtraction+unit map.
    # No propagation error: the queried state is at the exact initial instant.
    u = 2.**-53
    component_bound = 128*u + 32*u*(1+abs(phase)+abs(rate*t))
    assert q == pytest.approx(expected, rel=0, abs=component_bound)
    if rate:
        fixed = (math.cos(latitude)*math.cos(longitude), math.cos(latitude)*math.sin(longitude), math.sin(latitude))
        assert math.dist(ground, fixed) > .1
    geometry = result.orbit_observation.geometry
    # TEST-ONLY projection onto the retained local basis; production does not
    # reconstruct a vector from these angles or rotate through this basis.
    axes = (geometry.orbital_x, geometry.orbital_y, geometry.orbital_z)
    qx, qy, qz = (math.fsum(a*b for a, b in zip(q, axis.components)) for axis in axes)
    pointing = result.orbit_observation.opportunity.pointing
    if latitude == longitude == 0:
        assert q == (-1., 0., 0.)
        assert geometry.orbital_azimuth_status == "zero_projection"
        assert pointing.view_angle_from_nadir_deg == pointing.view_azimuth_deg == 0.
    else:
        projection = math.hypot(qx, qy)
        assert projection > .15  # Explicit conditioning for these cases.
        off_deg = math.degrees(math.atan2(projection, qz))
        az_deg = math.degrees(math.atan2(qy, qx)) % 360.
        # Dot products + atan2: reciprocal transverse projection sensitivity.
        # Degrees, zero relative tolerance; periodic azimuth difference handles
        # the coordinate wrap without clipping or declaring physical accuracy.
        angular_bound = 256*u*(1+1/projection)*180/math.pi + 2*math.ulp(360.)
        assert pointing.view_angle_from_nadir_deg == pytest.approx(off_deg, rel=0, abs=angular_bound)
        assert math.remainder(pointing.view_azimuth_deg-az_deg, 360.) == pytest.approx(0., rel=0, abs=angular_bound)
        if latitude == 1e-10:
            assert 359.999 < pointing.view_azimuth_deg < 360.
        if latitude == -1e-10:
            assert 0. < pointing.view_azimuth_deg < .001


def test_same_complete_binding_v53_angular_separation_compatibility(monkeypatch):
    first, _ = _synthetic(monkeypatch, .1, .2, (2., 0., 0.), (0., 1., 0.))
    second, _ = _synthetic(monkeypatch, -.1, -.2, (2., 0., 0.), (0., 1., 0.), t=3)
    assert first.boresight_frame == second.boresight_frame
    assert first.orbit_observation.geometry.spacecraft_to_ground.instant != second.orbit_observation.geometry.spacecraft_to_ground.instant
    # Different instants share the fixed complete MODEL_INERTIAL axes. This is
    # a test of existing V5.3 interoperability, not a D1b transition evaluator.
    a, b = _components(first.common_frame_boresight), _components(second.common_frame_boresight)
    cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    expected = math.degrees(math.atan2(math.sqrt(math.fsum(x*x for x in cross)), math.fsum(x*y for x, y in zip(a, b))))
    actual = compute_boresight_angular_separation(first.maneuver_candidate.common_frame_boresight,
                                                 second.maneuver_candidate.common_frame_boresight)
    # Unit-scale vectors; cross/dot atan2 has nonvanishing combined norm.
    # 128u radians plus degree conversion accommodates both short formulations.
    bound_deg = 128*2.**-53*180/math.pi + 2*math.ulp(180.)
    assert actual.angular_separation_deg == pytest.approx(expected, rel=0, abs=bound_deg)


@pytest.mark.parametrize("latitude,longitude,r,v", [
    (.1, math.pi/2+.2, (0., 2., 0.), (-1., 0., 0.)),
    (-.1, -math.pi+.2, (-2., 0., 0.), (0., -1., 0.)),
])
def test_real_c1_unresolved_cancellation_is_not_repaired_by_bridge(monkeypatch, latitude, longitude, r, v):
    # These axis-aligned cases reach C1's existing exact-product cancellation
    # guard in an incidence cross component. Keep that boundary as a rejection;
    # conditioned vector-reference cases above avoid this separate degeneracy.
    def forbidden(*values): pytest.fail("C1 rejection reached candidate construction")
    monkeypatch.setattr(adapter, "ObservationManeuverCandidate", forbidden)
    with pytest.raises(ValueError, match="geometry cancellation is numerically unresolved"):
        _synthetic(monkeypatch, latitude, longitude, r, v)


def test_schema5_json_restart_and_independent_b2_decode_keep_binding_external():
    args = _arguments(); inputs = args["inputs"]
    context = replace(generic_context(), inputs=inputs)
    before = deepcopy(context)
    coast_payload = inputs.coast_orbit.to_dict()
    payload = CheckpointState.from_context(context).to_dict()
    recovered = CheckpointState.from_dict(json.loads(json.dumps(payload, allow_nan=False)))
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_payload, allow_nan=False)))
    restored = recovered.restore(with_coast_orbit(inputs, coast))
    assert coast == inputs.coast_orbit and coast is not inputs.coast_orbit
    assert restored == context
    original = derive(**args)
    recomputed = derive(**dict(args, inputs=restored.inputs))
    assert recomputed == original and recomputed.orbit_observation is not original.orbit_observation
    binding = args["boresight_frame"]
    equal_representation = Binding(ADCSBoresightFrameId(PlainText(binding.frame_id.value)), deepcopy(binding.frame))
    another_label = Binding(ADCSBoresightFrameId("another-external-label"), binding.frame)
    for external in (equal_representation, another_label):
        changed = derive(**dict(args, boresight_frame=external))
        restarted = derive(**dict(args, inputs=restored.inputs, boresight_frame=external))
        assert changed == restarted
        assert (changed == original) is (external == binding)
        assert changed.orbit_observation == original.orbit_observation
        assert changed.inputs.model_manifest == original.inputs.model_manifest
        assert changed.inputs.coast_orbit.to_dict() == coast_payload
    assert payload["schema_version"] == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5 and COAST_BINDING_VERSION == 1
    assert tuple(payload) == ("schema_version", "simulation_time_seconds", "input_ids", "spacecraft",
        "ground_knowledge", "ground_data_delivery", "mission", "controller", "diagnostics")
    assert context == before
    assert CheckpointState.from_context(context).to_dict() == CheckpointState.from_context(restored).to_dict() == payload
    encoded = json.dumps(payload, sort_keys=True)
    assert not any(name in encoded for name in ("boresight_frame", "common_frame_boresight", "maneuver_candidate", "caller-axes"))
