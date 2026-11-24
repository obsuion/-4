"""C3 view precedence, independent exact timing boundaries and real restart."""

from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION, COAST_REPRESENTATION_VERSION
import ops_sim.v5.orbit_observation_sequence as adapter
from test_v50d1_time_engine import _context as generic_context
from test_v56d1a_observation_opportunity_geometry import _projection_seam, _block
from test_v56d1b_observation_boresight_contracts import _arguments
from test_v56d1b_observation_boresight_geometry import _synthetic
from test_v56d1c_observation_transition_geometry import _snapshots, _circular_velocity
from test_v56d1d_observation_sequence_contracts import (
    Candidate, Reason, evaluate, _config, _pair, _trace, _forbidden,
    legacy_config, VIEW_ORDER, PASS_ORDER,
)


@pytest.mark.parametrize("previous_fails", [False, True])
def test_view_failure_wins_over_outside_transition_envelope(monkeypatch, previous_fails):
    previous, next = _pair(monkeypatch)
    if previous_fails: previous, next = next, previous
    # Real rays are orthogonal, hence90deg > this config's final60deg anchor.
    # One real local view is nadir0deg; the other is45deg > maximum5deg.
    config = legacy_config(maximum_view_angle_deg=5.)
    calls, _ = _trace(monkeypatch)
    monkeypatch.setattr(adapter, "evaluate_orbit_bound_observation_transition", _forbidden)
    result = evaluate(config, previous, next)
    assert calls == VIEW_ORDER
    expected = Reason.PREVIOUS_VIEW_LIMIT_EXCEEDED if previous_fails else Reason.NEXT_VIEW_LIMIT_EXCEEDED
    assert result.sequence_result.reason is expected and not result.sequence_result.feasible
    assert result.transition_evidence is None
    assert (result.sequence_result.transition_result, result.sequence_result.transition_ready_seconds,
            result.sequence_result.candidate_next_start_seconds) == (None, None, None)
    assert result.sequence_result.previous_end_seconds == previous.step_start_seconds+1
    assert result.sequence_result.next_latest_start_seconds == next.step_start_seconds


def test_both_views_fail_previous_reason_wins_after_both_prechecks(monkeypatch):
    values = []
    for t, r in ((0, (1., -1., 0.)), (3, (1., 1., 0.))):
        candidate, _ = _synthetic(monkeypatch, 0., 0., r, _circular_velocity(r), t=t)
        values.append(candidate)
    _projection_seam(monkeypatch, (_block(0, 1, 20),))
    previous, next = (replace(value) for value in values)
    calls, _ = _trace(monkeypatch)
    result = evaluate(legacy_config(maximum_view_angle_deg=5.), previous, next)
    assert calls == VIEW_ORDER
    assert not result.sequence_result.previous_view.feasible and not result.sequence_result.next_view.feasible
    assert result.sequence_result.reason is Reason.PREVIOUS_VIEW_LIMIT_EXCEEDED
    assert result.transition_evidence is None and result.sequence_result.transition_result is None


@pytest.mark.parametrize("previous_fails", [False, True])
def test_view_failure_also_precedes_concrete_frame_mismatch(monkeypatch, previous_fails):
    previous, next = _pair(monkeypatch, phase=.125)
    if previous_fails: previous, next = next, previous
    assert previous.boresight_frame != next.boresight_frame
    calls, _ = _trace(monkeypatch)
    monkeypatch.setattr(adapter, "evaluate_orbit_bound_observation_transition", _forbidden)
    monkeypatch.setattr(adapter, "CommonFrameBoresightDirection", _forbidden)
    result = evaluate(_config(maximum=5.), previous, next)
    assert calls == VIEW_ORDER
    expected = Reason.PREVIOUS_VIEW_LIMIT_EXCEEDED if previous_fails else Reason.NEXT_VIEW_LIMIT_EXCEEDED
    assert result.sequence_result.reason is expected
    assert result.transition_evidence is None and result.sequence_result.transition_result is None
    # No frame compatibility claim follows from an already decisive view failure.


def test_both_views_pass_outside_coverage_still_propagates_before_c3(monkeypatch):
    previous, next = _pair(monkeypatch)
    owner, errors = adapter.evaluate_orbit_bound_observation_transition, []
    def spy(*args):
        try: return owner(*args)
        except ValueError as error:
            errors.append(error)
            raise
    monkeypatch.setattr(adapter, "evaluate_orbit_bound_observation_transition", spy)
    monkeypatch.setattr(adapter, "evaluate_observation_sequence_feasibility", _forbidden)
    with pytest.raises(ValueError, match="exceeds the configured slew-time envelope") as caught:
        evaluate(legacy_config(maximum_view_angle_deg=80.), previous, next)
    assert len(errors) == 1 and caught.value is errors[0]


@pytest.mark.parametrize("times,duration,ready,candidate_start,reason", [
    pytest.param((0, 5), 2., 3., 5, Reason.FEASIBLE, id="sufficient-gap"),
    pytest.param((0, 3), 2., 3., 3, Reason.FEASIBLE, id="exact-readiness-boundary"),
    pytest.param((0, 3), math.nextafter(2., math.inf), math.nextafter(3., math.inf),
        math.nextafter(3., math.inf), Reason.INSUFFICIENT_TRANSITION_TIME, id="one-ulp-late"),
    pytest.param((0, 3), 1.5, 2.5, 3, Reason.FEASIBLE, id="fractional-readiness"),
    pytest.param((0, 3), 2.25, 3.25, 3.25, Reason.INSUFFICIENT_TRANSITION_TIME, id="fractional-too-late"),
    pytest.param((3, 0), 2., 6., 6., Reason.INSUFFICIENT_TRANSITION_TIME, id="reversed-time-order"),
    pytest.param((0, 0), 2., 3., 3., Reason.INSUFFICIENT_TRANSITION_TIME, id="same-time"),
])
def test_independent_exact_anchor_timing_and_one_step_window_consequence(
        monkeypatch, times, duration, ready, candidate_start, reason):
    previous, next = _pair(monkeypatch, times=times)
    result = evaluate(_config(duration=duration), previous, next)
    sequence = result.sequence_result
    # Independent hand reference: exact orthogonal rays ->90deg anchor, dt1s,
    # no settling. Listed readiness values are previous start +1s +duration.
    # Every listed operand/sum is exactly binary-representable; compare exactly,
    # not with geometric tolerances or relative epsilon. One ULP at3s=2**-51s.
    assert result.transition_evidence.transition_result.angular_separation_deg == 90.
    assert sequence.transition_result == result.transition_evidence.transition_result
    assert sequence.transition_result.total_transition_time_seconds == duration
    assert sequence.previous_end_seconds == times[0]+1
    assert sequence.next_latest_start_seconds == next.step_start_seconds == times[1]
    assert sequence.transition_ready_seconds == ready
    assert sequence.candidate_next_start_seconds == candidate_start
    assert sequence.reason is reason and sequence.feasible is (reason is Reason.FEASIBLE)
    assert result.previous == previous and result.next == next
    assert result.previous_execution.scheduled_start_seconds == times[0]
    if duration == math.nextafter(2., math.inf):
        assert ready-3. == 2.**-51
        assert sequence.transition_ready_seconds != int(sequence.transition_ready_seconds)


def test_adjacent_zero_transition_suppresses_configured_settling(monkeypatch):
    previous, next = _snapshots(monkeypatch, (2., 0., 0.), times=(0, 1))
    result = evaluate(_config(settling=7.), previous, next)
    sequence = result.sequence_result
    assert sequence.reason is Reason.FEASIBLE
    assert sequence.previous_end_seconds == sequence.transition_ready_seconds == sequence.next_latest_start_seconds == 1
    assert sequence.candidate_next_start_seconds == 1
    transition = sequence.transition_result
    assert (transition.angular_separation_deg, transition.slew_elapsed_time_seconds,
            transition.settling_time_seconds, transition.total_transition_time_seconds) == (0., 0., 0., 0.)
    assert transition == result.transition_evidence.transition_result


def test_nonzero_settling_is_owned_by_c2_and_c3(monkeypatch):
    previous, next = _pair(monkeypatch, times=(0, 5))
    result = evaluate(_config(duration=2., settling=2.), previous, next)
    assert result.sequence_result.transition_result.total_transition_time_seconds == 4.
    assert result.sequence_result.transition_ready_seconds == 5.
    assert result.sequence_result.reason is Reason.FEASIBLE
    assert result.sequence_result.transition_result == result.transition_evidence.transition_result


@pytest.mark.parametrize("maximum", [5., 80.])
def test_real_schema5_json_restart_recomputes_sequence_with_external_arguments(maximum):
    # Real certified hidden pass: no search or result seams in this test.
    args = _arguments()
    context = replace(generic_context(), inputs=args["inputs"])
    before = deepcopy(context)
    payload = CheckpointState.from_context(context).to_dict()
    coast_payload = context.inputs.coast_orbit.to_dict()
    recovered = CheckpointState.from_dict(json.loads(json.dumps(payload, allow_nan=False)))
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_payload, allow_nan=False)))
    restored = recovered.restore(with_coast_orbit(context.inputs, coast))
    assert coast == context.inputs.coast_orbit and coast is not context.inputs.coast_orbit
    next_args = dict(args, request=replace(args["request"], priority_weight=2.))
    previous, next = Candidate(**args), Candidate(**next_args)
    original = evaluate(_config(maximum=maximum), previous, next)
    restarted = evaluate(_config(maximum=maximum),
        Candidate(**dict(args, inputs=restored.inputs)), Candidate(**dict(next_args, inputs=restored.inputs)))
    assert restarted == original and restarted.previous is not original.previous
    assert restarted.next is not original.next and original.previous != original.next
    if maximum == 5.:
        assert original.transition_evidence is None
        assert original.sequence_result.reason is Reason.PREVIOUS_VIEW_LIMIT_EXCEEDED
    else:
        assert original.transition_evidence is not None
        assert original.sequence_result.reason is Reason.INSUFFICIENT_TRANSITION_TIME
    assert before == context == restored
    assert CheckpointState.from_context(context).to_dict() == CheckpointState.from_context(restored).to_dict() == payload
    assert context.inputs.coast_orbit.to_dict() == coast_payload
    assert (CURRENT_CHECKPOINT_SCHEMA_VERSION, payload["schema_version"], COAST_BINDING_VERSION,
            COAST_REPRESENTATION_VERSION) == (5, 5, 1, 1)
    assert tuple(payload) == ("schema_version", "simulation_time_seconds", "input_ids", "spacecraft",
        "ground_knowledge", "ground_data_delivery", "mission", "controller", "diagnostics")
    encoded = json.dumps(payload, sort_keys=True)
    assert not any(s in encoded for s in ("previous_execution", "transition_evidence", "sequence_result",
        "common_frame_boresight", "caller-axes"))
