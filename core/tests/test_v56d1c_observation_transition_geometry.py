"""Independent transition references, ordered snapshots and real JSON restart."""

from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION, COAST_REPRESENTATION_VERSION
import ops_sim.v5.orbit_observation_transition as adapter
from test_v50d1_time_engine import _context as generic_context
from test_v53c2_adcs_boresight_transition import _anchor, _config
from test_v56b1_two_body_contracts import _forge
from test_v56d1a_observation_opportunity_geometry import _projection_seam, _block
from test_v56d1b_observation_boresight_contracts import _arguments
from test_v56d1b_observation_boresight_geometry import _synthetic
from test_v56d1c_observation_transition_contracts import Candidate, Result, evaluate


def _circular_velocity(r):
    # mu=2m^3/s^2; use a perpendicular velocity of circular magnitude so B1's
    # pericentre stays outside the1m sphere, including the radius-sqrt(2) case.
    speed = math.sqrt(2./math.hypot(*r))
    if r[2] == 0.: return (0., 0., speed)
    scale = speed/math.hypot(r[0], r[1])
    return (-r[1]*scale, r[0]*scale, 0.)


def _snapshots(monkeypatch, end_r=(2., -1., 0.), *, times=(0, 0), phase=0.):
    # TEST-ONLY C2c support seam: these cases isolate D1b/C2 interoperability,
    # not visibility. B1 is evaluated at each exact initial instant, and C1 is
    # real. Synthetic sphere radius1m, ground point g=(1,0,0) when phase=0.
    previous, _ = _synthetic(monkeypatch, 0., 0., (2., 0., 0.), (0., 1., 0.), t=times[0])
    next, _ = _synthetic(monkeypatch, 0., 0., end_r, _circular_velocity(end_r), t=times[1], phase=phase)
    # D1c reconstructs BOTH snapshots: the support seam must cover both.
    _projection_seam(monkeypatch, (_block(0, 1, 20),))
    return replace(previous), replace(next)


def _wide_config(*, upper=180., settling=7.):
    return _config(settling_seconds=settling, anchors=(
        _anchor("zero", 0., 0.), _anchor("right", 90., 30.),
        *(() if upper == 90. else (_anchor("upper", upper, 75.),))))


def _independent_angle(previous, next):
    # Test-only direct norm/fsum/cross/atan2; no production C2 helper. Inputs
    # are retained rays, so this independently checks transition composition,
    # not C1's physical model (its vector oracle is in committed D1b tests).
    rays = [candidate.orbit_observation.geometry.spacecraft_to_ground.components
            for candidate in (previous, next)]
    u, v = [tuple(x / math.sqrt(math.fsum(y*y for y in ray)) for x in ray) for ray in rays]
    cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    return math.degrees(math.atan2(math.sqrt(math.fsum(x*x for x in cross)),
                                   math.fsum(a*b for a, b in zip(u, v))))


def _independent_envelope(config, angle):
    anchors = [(a.angular_separation_deg.value, a.slew_elapsed_time_seconds.value, a.anchor_id)
               for a in config.slew_time_anchors]
    if angle == 0.: return anchors[0][2], anchors[0][2], 0., 0., 0., 0.
    settling = config.post_slew_settling_time_seconds.value
    for a, t, identity in anchors:
        if angle == a: return identity, identity, 0., t, settling, t+settling
    for (a, t, lower), (b, s, upper) in zip(anchors, anchors[1:]):
        if a < angle < b:
            fraction = (angle-a)/(b-a)
            elapsed = (1.-fraction)*t+fraction*s  # independent weighted sum
            return lower, upper, fraction, elapsed, settling, elapsed+settling
    raise ValueError("test reference outside envelope")


@pytest.mark.parametrize("r,upper,analytic", [
    pytest.param((2., 0., 0.), 180., 0., id="zero-no-settling"),
    pytest.param((1., -1., 0.), 180., 90., id="exact-interior-anchor"),
    pytest.param((1., -1., 0.), 90., 90., id="upper-supported-anchor"),
    pytest.param((2., -1., 0.), 180., 45., id="interpolation-and-settling"),
    pytest.param((2., -2., .5), 180., None, id="conditioned-three-dimensional"),
    pytest.param((-.5, -1., .5), 180., None, id="second-anchor-interval"),
])
def test_independent_angle_and_anchor_interpolation(monkeypatch, r, upper, analytic):
    previous, next = _snapshots(monkeypatch, r)
    config = _wide_config(upper=upper)
    result = evaluate(config, previous, next).transition_result
    angle = _independent_angle(previous, next)
    if analytic is not None:
        # Exact axis/identical rays give0/90; the diagonal gives pi/4.
        assert angle == analytic
    lower, higher, fraction, slew, settling, total = _independent_envelope(config, angle)
    # All rays are O(1), norm~1; atan2(cross,dot) stays conditioned because
    # cross^2+dot^2~1. 256 binary64 unit roundoffs in radians covers both
    # short normalization/dot/cross chains and degree conversion. No orbit
    # integration error enters: these states are queried at their initial t.
    u = 2.**-53
    angle_bound = math.degrees(256*u)  # degrees, absolute only
    fraction_bound = angle_bound/90. + 16*u  # dimensionless; min gap90deg
    time_bound = .5*angle_bound + 64*u*max(1., total)  # seconds; max slope .5s/deg
    assert result.angular_separation_deg == pytest.approx(angle, rel=0, abs=angle_bound)
    assert (result.lower_anchor_id, result.upper_anchor_id) == (lower, higher)
    assert result.interpolation_fraction == pytest.approx(fraction, rel=0, abs=fraction_bound)
    assert result.slew_elapsed_time_seconds == pytest.approx(slew, rel=0, abs=time_bound)
    assert result.settling_time_seconds == settling
    assert result.total_transition_time_seconds == pytest.approx(total, rel=0, abs=time_bound)
    if angle == 0.: assert (slew, settling, total) == (0., 0., 0.)
    else: assert settling == 7.


def test_outside_last_anchor_propagates_actual_c2_exception_identity(monkeypatch):
    previous, next = _snapshots(monkeypatch, (1., -1., 0.))
    caught_errors, owner = [], adapter.compute_boresight_transition
    def spy(*args):
        try: return owner(*args)
        except ValueError as error:
            caught_errors.append(error)
            raise
    monkeypatch.setattr(adapter, "compute_boresight_transition", spy)
    with pytest.raises(ValueError, match="exceeds the configured slew-time envelope") as caught:
        evaluate(_config(), previous, next)  # final anchor60deg, exact separation90deg
    assert len(caught_errors) == 1 and caught.value is caught_errors[0]


def test_same_label_different_complete_frames_rejects_at_pair_gate(monkeypatch):
    previous, next = _snapshots(monkeypatch, phase=.125)
    assert previous.boresight_frame.frame_id == next.boresight_frame.frame_id
    assert previous.boresight_frame != next.boresight_frame
    def forbidden(*args): pytest.fail("unequal concrete frames reached shim or C2")
    monkeypatch.setattr(adapter, "CommonFrameBoresightDirection", forbidden)
    monkeypatch.setattr(adapter, "compute_boresight_transition", forbidden)
    with pytest.raises(ValueError, match="equal concrete boresight-frame bindings"):
        evaluate(_wide_config(), previous, next)


@pytest.mark.parametrize("times", [(0, 0), (0, 3), (3, 0)])
def test_ordered_evidence_without_time_or_window_feasibility(monkeypatch, times):
    previous, next = _snapshots(monkeypatch, times=times)
    forward = evaluate(_wide_config(), previous, next)
    reverse = evaluate(_wide_config(), next, previous)
    assert (forward.previous.step_start_seconds, forward.next.step_start_seconds) == times
    assert forward.previous == previous and forward.next == next
    assert reverse.previous == next and reverse.next == previous
    assert forward != reverse and forward.transition_result == reverse.transition_result
    assert forward.previous.boresight_frame == forward.next.boresight_frame
    assert forward.previous.orbit_observation.geometry.spacecraft_to_ground.instant.elapsed_seconds == times[0]
    assert forward.next.orbit_observation.geometry.spacecraft_to_ground.instant.elapsed_seconds == times[1]
    # Config's5deg view limit is deliberately below this next view. It is
    # irrelevant to D1c, and the distinct intervals need not fit a transition.
    assert next.orbit_observation.opportunity.pointing.view_angle_from_nadir_deg > 5.


def test_semantic_evidence_changes_with_ray_or_config_and_replace(monkeypatch):
    previous, next = _snapshots(monkeypatch)
    result = evaluate(_wide_config(), previous, next)
    alternate, _ = _synthetic(monkeypatch, 0., 0., (1., -1., 0.), _circular_velocity((1., -1., 0.)))
    _projection_seam(monkeypatch, (_block(0, 1, 20),))
    changed = replace(result, next=alternate)
    assert changed != result and changed.transition_result.angular_separation_deg != result.transition_result.angular_separation_deg
    altered = replace(result, config=_wide_config(settling=9.))
    assert altered != result and altered.transition_result.total_transition_time_seconds == result.transition_result.total_transition_time_seconds+2.
    assert _forge(result, "previous.common_frame_boresight.x", .1) != result
    assert _forge(result, "next.common_frame_boresight.z", .1) != result


def test_real_schema5_json_restart_rebuilds_pair_from_independent_b2_inputs():
    # No search seam: real C2c/D1a/D1b composition on the committed hidden pass.
    args = _arguments()
    context = replace(generic_context(), inputs=args["inputs"])
    before = deepcopy(context)
    payload = CheckpointState.from_context(context).to_dict()
    coast_payload = context.inputs.coast_orbit.to_dict()
    recovered = CheckpointState.from_dict(json.loads(json.dumps(payload, allow_nan=False)))
    decoded = CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_payload, allow_nan=False)))
    restored = recovered.restore(with_coast_orbit(context.inputs, decoded))
    assert decoded == context.inputs.coast_orbit and decoded is not context.inputs.coast_orbit
    first = Candidate(**args)
    second_args = dict(args, request=replace(args["request"], priority_weight=2.))
    second = Candidate(**second_args)
    config = _wide_config()
    original = evaluate(config, first, second)
    resumed = evaluate(config, Candidate(**dict(args, inputs=restored.inputs)),
        Candidate(**dict(second_args, inputs=restored.inputs)))
    assert resumed == original and resumed.previous is not first and resumed.next is not second
    assert original.previous != original.next
    assert context == before == restored
    assert CheckpointState.from_context(context).to_dict() == CheckpointState.from_context(restored).to_dict() == payload
    assert context.inputs.coast_orbit.to_dict() == coast_payload
    assert (payload["schema_version"], CURRENT_CHECKPOINT_SCHEMA_VERSION,
        COAST_BINDING_VERSION, COAST_REPRESENTATION_VERSION) == (5, 5, 1, 1)
    assert tuple(payload) == ("schema_version", "simulation_time_seconds", "input_ids", "spacecraft",
        "ground_knowledge", "ground_data_delivery", "mission", "controller", "diagnostics")
    encoded = json.dumps(payload, sort_keys=True)
    assert not any(name in encoded for name in ("transition_result", "boresight_frame", "common_frame_boresight", "caller-axes"))
