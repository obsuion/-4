"""Observation-window and ADCS transition feasibility for V5.3C3."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from inspect import signature
from math import cos, isfinite, radians, sin
from pathlib import Path
import subprocess

import numpy as np
import pytest

import ops_sim.v5.observation_feasibility as feasibility_module
from ops_sim.v5.adcs import (
    BoresightTransitionResult,
    CommonFrameBoresightDirection,
)
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
)
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
    ObservationSequenceFeasibilityReason,
    ObservationSequenceFeasibilityResult,
    ObservationViewFeasibilityResult,
    ScheduledObservationExecution,
    evaluate_observation_sequence_feasibility,
    evaluate_observation_view_feasibility,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)


ROOT = Path(__file__).resolve().parents[1]
FEASIBILITY_PATH = ROOT / "ops_sim" / "v5" / "observation_feasibility.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by a focused unit test.",
        ),
    )


def _anchor(
    anchor_value: str,
    angle_deg: object,
    elapsed_seconds: object,
) -> BoresightSlewTimeAnchor:
    prefix = f"adcs.slew-envelope.{anchor_value}"
    return BoresightSlewTimeAnchor(
        ADCSSlewAnchorId(anchor_value),
        _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
        _parameter(f"{prefix}.elapsed-time", "s", elapsed_seconds),
    )


def _config(
    *,
    maximum_view_angle_deg: object = 35.0,
    settling_seconds: object = 5.0,
    anchors: tuple[BoresightSlewTimeAnchor, ...] | None = None,
) -> AgilePointingConfig:
    active_anchors = (
        (
            _anchor("zero", 0.0, 0.0),
            _anchor("thirty", 30.0, 20.0),
            _anchor("ninety", 90.0, 80.0),
        )
        if anchors is None
        else anchors
    )
    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir",
            "deg",
            maximum_view_angle_deg,
        ),
        _parameter(
            "adcs.pointing.post-slew-settling-time",
            "s",
            settling_seconds,
        ),
        active_anchors,
    )


def _opportunity(
    value: str,
    *,
    window_start_seconds: int = 0,
    window_end_seconds: int = 100,
    imaging_duration_seconds: int = 20,
    view_angle_deg: object = 10.0,
    view_azimuth_deg: object = 0.0,
) -> ObservationOpportunity:
    return ObservationOpportunity(
        ObservationOpportunityId(value),
        ImagingRequestId(f"request-{value}"),
        window_start_seconds,
        window_end_seconds,
        imaging_duration_seconds,
        ObservationPointing(view_angle_deg, view_azimuth_deg),
    )


def _direction(
    x: object,
    y: object,
    z: object,
    *,
    frame_value: str = "test-common-frame",
) -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId(frame_value),
        x,
        y,
        z,
    )


def _look_direction(
    view_angle_deg: float,
    *,
    azimuth_sign: int,
    frame_value: str = "test-common-frame",
) -> CommonFrameBoresightDirection:
    angle_rad = radians(view_angle_deg)
    return _direction(
        azimuth_sign * sin(angle_rad),
        0.0,
        cos(angle_rad),
        frame_value=frame_value,
    )


def _candidate(
    opportunity: ObservationOpportunity,
    direction: CommonFrameBoresightDirection | None = None,
) -> ObservationManeuverCandidate:
    return ObservationManeuverCandidate(
        opportunity,
        _direction(0.0, 0.0, 1.0) if direction is None else direction,
    )


def _transition(total_seconds: float) -> BoresightTransitionResult:
    anchor_id = ADCSSlewAnchorId("synthetic")
    if total_seconds == 0:
        return BoresightTransitionResult(
            0.0,
            anchor_id,
            anchor_id,
            0.0,
            0.0,
            0.0,
            0.0,
        )
    return BoresightTransitionResult(
        10.0,
        anchor_id,
        anchor_id,
        0.0,
        total_seconds,
        0.0,
        total_seconds,
    )


def _patched_sequence(
    monkeypatch,
    transition_seconds: float,
    *,
    previous_start_seconds: int = 40,
    previous_window_end_seconds: int = 100,
    next_window_start_seconds: int = 100,
    next_window_end_seconds: int = 180,
) -> tuple[ObservationSequenceFeasibilityResult, int]:
    calls = 0

    def transition(config, start, end):
        nonlocal calls
        calls += 1
        assert type(config) is AgilePointingConfig
        assert type(start) is CommonFrameBoresightDirection
        assert type(end) is CommonFrameBoresightDirection
        return _transition(transition_seconds)

    monkeypatch.setattr(
        feasibility_module,
        "compute_boresight_transition",
        transition,
    )
    previous = _candidate(
        _opportunity(
            "previous",
            window_end_seconds=previous_window_end_seconds,
        ),
        _direction(1.0, 0.0, 0.0),
    )
    next_candidate = _candidate(
        _opportunity(
            "next",
            window_start_seconds=next_window_start_seconds,
            window_end_seconds=next_window_end_seconds,
        ),
        _direction(0.0, 1.0, 0.0),
    )
    result = evaluate_observation_sequence_feasibility(
        _config(),
        ScheduledObservationExecution(previous, previous_start_seconds),
        next_candidate,
    )
    return result, calls


def test_c3_records_have_exact_frozen_slotted_required_fields() -> None:
    previous_id = ObservationOpportunityId("previous")
    next_id = ObservationOpportunityId("next")
    previous_view = ObservationViewFeasibilityResult(
        previous_id, 10.0, 35.0, True
    )
    next_view = ObservationViewFeasibilityResult(next_id, 10.0, 35.0, True)
    transition = _transition(30.0)
    contracts = {
        ObservationManeuverCandidate: ("opportunity", "common_frame_boresight"),
        ScheduledObservationExecution: ("candidate", "scheduled_start_seconds"),
        ObservationViewFeasibilityResult: (
            "opportunity_id",
            "requested_view_angle_from_nadir_deg",
            "maximum_view_angle_from_nadir_deg",
            "feasible",
        ),
        ObservationSequenceFeasibilityResult: (
            "previous_opportunity_id",
            "next_opportunity_id",
            "previous_end_seconds",
            "next_latest_start_seconds",
            "previous_view",
            "next_view",
            "transition_result",
            "transition_ready_seconds",
            "candidate_next_start_seconds",
            "feasible",
            "reason",
        ),
    }
    candidate = _candidate(_opportunity("candidate"))
    instances = (
        candidate,
        ScheduledObservationExecution(candidate, 0),
        previous_view,
        ObservationSequenceFeasibilityResult(
            previous_id,
            next_id,
            60,
            160,
            previous_view,
            next_view,
            transition,
            90.0,
            100.0,
            True,
            ObservationSequenceFeasibilityReason.FEASIBLE,
        ),
    )

    for domain_type, instance in zip(contracts, instances):
        assert tuple(field.name for field in fields(domain_type)) == contracts[
            domain_type
        ]
        assert domain_type.__dataclass_params__.frozen
        assert not hasattr(instance, "__dict__")
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(domain_type)
        )
        with pytest.raises(FrozenInstanceError):
            setattr(instance, fields(domain_type)[0].name, None)


def test_candidate_pairs_existing_inputs_without_transforming_them() -> None:
    opportunity = _opportunity("pair", view_angle_deg=27.0, view_azimuth_deg=123.0)
    direction = _direction(-4.0, 2.0, 7.0)
    candidate = ObservationManeuverCandidate(opportunity, direction)

    assert candidate.opportunity is opportunity
    assert candidate.common_frame_boresight is direction
    assert candidate.opportunity.pointing.view_angle_from_nadir_deg == 27.0
    assert candidate.common_frame_boresight.x == -4.0


def test_candidate_requires_exact_types_and_revalidates_nested_inputs() -> None:
    opportunity = _opportunity("candidate-validation")
    direction = _direction(1.0, 0.0, 0.0)
    with pytest.raises(TypeError, match="opportunity"):
        ObservationManeuverCandidate(object(), direction)
    with pytest.raises(TypeError, match="common_frame_boresight"):
        ObservationManeuverCandidate(opportunity, object())

    object.__setattr__(direction, "x", float("nan"))
    with pytest.raises(ValueError, match="x"):
        ObservationManeuverCandidate(opportunity, direction)

    corrupted_opportunity = _opportunity("corrupted-candidate-id")
    object.__setattr__(
        corrupted_opportunity.opportunity_id,
        "value",
        "UPPERCASE",
    )
    with pytest.raises(ValueError, match="lowercase ASCII"):
        ObservationManeuverCandidate(
            corrupted_opportunity,
            _direction(1.0, 0.0, 0.0),
        )


def test_scheduled_execution_accepts_exact_window_boundaries() -> None:
    candidate = _candidate(
        _opportunity(
            "scheduled-boundaries",
            window_start_seconds=10,
            window_end_seconds=100,
            imaging_duration_seconds=20,
        )
    )

    assert ScheduledObservationExecution(candidate, 10).scheduled_start_seconds == 10
    assert ScheduledObservationExecution(candidate, 80).scheduled_start_seconds == 80


@pytest.mark.parametrize("scheduled_start", (9, 81, -1))
def test_scheduled_execution_rejects_start_outside_own_window(
    scheduled_start,
) -> None:
    candidate = _candidate(
        _opportunity(
            "scheduled-outside",
            window_start_seconds=10,
            window_end_seconds=100,
            imaging_duration_seconds=20,
        )
    )

    with pytest.raises(ValueError):
        ScheduledObservationExecution(candidate, scheduled_start)


@pytest.mark.parametrize("scheduled_start", (True, 10.0, np.int64(10)))
def test_scheduled_execution_requires_exact_python_int(scheduled_start) -> None:
    with pytest.raises(TypeError, match="integer"):
        ScheduledObservationExecution(
            _candidate(_opportunity("scheduled-type")),
            scheduled_start,
        )


def test_scheduled_execution_requires_exact_candidate_and_revalidates_it() -> None:
    with pytest.raises(TypeError, match="candidate"):
        ScheduledObservationExecution(object(), 0)

    candidate = _candidate(_opportunity("corrupted-execution"))
    object.__setattr__(candidate.opportunity, "window_end_seconds", 10)
    with pytest.raises(ValueError, match="duration"):
        ScheduledObservationExecution(candidate, 0)


def test_view_limit_exact_boundary_is_feasible() -> None:
    result = evaluate_observation_view_feasibility(
        _config(maximum_view_angle_deg=35.0),
        _opportunity("view-boundary", view_angle_deg=35.0),
    )

    assert result.requested_view_angle_from_nadir_deg == 35.0
    assert result.maximum_view_angle_from_nadir_deg == 35.0
    assert result.feasible is True


def test_view_just_above_limit_is_infeasible_without_tolerance() -> None:
    result = evaluate_observation_view_feasibility(
        _config(maximum_view_angle_deg=35.0),
        _opportunity("view-over", view_angle_deg=35.0001),
    )

    assert result.feasible is False


def test_view_function_requires_exact_types_and_revalidates_inputs() -> None:
    config = _config()
    opportunity = _opportunity("view-validation")
    with pytest.raises(TypeError, match="config"):
        evaluate_observation_view_feasibility(object(), opportunity)
    with pytest.raises(TypeError, match="opportunity"):
        evaluate_observation_view_feasibility(config, object())

    object.__setattr__(opportunity.pointing, "view_angle_from_nadir_deg", -1.0)
    with pytest.raises(ValueError, match="view_angle"):
        evaluate_observation_view_feasibility(config, opportunity)


def test_view_result_validates_domains_and_feasibility_identity() -> None:
    opportunity_id = ObservationOpportunityId("view-result")
    with pytest.raises(TypeError, match="opportunity_id"):
        ObservationViewFeasibilityResult(ImagingRequestId("wrong"), 1, 2, True)
    for invalid in (True, -0.1, float("nan"), float("inf")):
        with pytest.raises((TypeError, ValueError)):
            ObservationViewFeasibilityResult(opportunity_id, invalid, 35, True)
    for invalid in (True, 0, -0.1, float("nan"), float("inf")):
        with pytest.raises((TypeError, ValueError)):
            ObservationViewFeasibilityResult(opportunity_id, 1, invalid, True)
    with pytest.raises(TypeError, match="feasible"):
        ObservationViewFeasibilityResult(opportunity_id, 1, 35, 1)
    with pytest.raises(ValueError, match="feasible"):
        ObservationViewFeasibilityResult(opportunity_id, 36, 35, True)


def test_previous_view_failure_short_circuits_transition(monkeypatch) -> None:
    def forbidden_transition(*args):
        raise AssertionError("C2 transition must not be called")

    monkeypatch.setattr(
        feasibility_module,
        "compute_boresight_transition",
        forbidden_transition,
    )
    previous = _candidate(
        _opportunity("previous-invalid-view", view_angle_deg=35.0001)
    )
    next_candidate = _candidate(
        _opportunity(
            "next-valid-view",
            window_start_seconds=100,
            window_end_seconds=180,
        )
    )
    result = evaluate_observation_sequence_feasibility(
        _config(), ScheduledObservationExecution(previous, 40), next_candidate
    )

    assert result.reason is (
        ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED
    )
    assert result.feasible is False
    assert result.next_view.feasible is True
    assert result.transition_result is None
    assert result.transition_ready_seconds is None
    assert result.candidate_next_start_seconds is None


def test_next_view_failure_short_circuits_transition(monkeypatch) -> None:
    def forbidden_transition(*args):
        raise AssertionError("C2 transition must not be called")

    monkeypatch.setattr(
        feasibility_module,
        "compute_boresight_transition",
        forbidden_transition,
    )
    previous = _candidate(_opportunity("previous-valid-view"))
    next_candidate = _candidate(
        _opportunity(
            "next-invalid-view",
            window_start_seconds=100,
            window_end_seconds=180,
            view_angle_deg=35.0001,
        )
    )
    result = evaluate_observation_sequence_feasibility(
        _config(), ScheduledObservationExecution(previous, 40), next_candidate
    )

    assert result.reason is (
        ObservationSequenceFeasibilityReason.NEXT_VIEW_LIMIT_EXCEEDED
    )
    assert result.previous_view.feasible is True
    assert result.next_view.feasible is False
    assert result.transition_result is None


def test_both_view_failures_retain_previous_failure_precedence(monkeypatch) -> None:
    monkeypatch.setattr(
        feasibility_module,
        "compute_boresight_transition",
        lambda *args: pytest.fail("C2 transition must not be called"),
    )
    previous = _candidate(_opportunity("previous-over", view_angle_deg=36.0))
    next_candidate = _candidate(
        _opportunity(
            "next-over",
            window_start_seconds=100,
            window_end_seconds=180,
            view_angle_deg=36.0,
        )
    )

    result = evaluate_observation_sequence_feasibility(
        _config(), ScheduledObservationExecution(previous, 40), next_candidate
    )

    assert result.previous_view.feasible is False
    assert result.next_view.feasible is False
    assert result.reason is (
        ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED
    )


def test_feasible_with_window_wait_matches_hand_calculation(monkeypatch) -> None:
    result, calls = _patched_sequence(monkeypatch, 30.0)

    assert calls == 1
    assert result.previous_end_seconds == 40 + 20 == 60
    assert result.transition_ready_seconds == 60 + 30 == 90
    assert result.candidate_next_start_seconds == max(100, 90) == 100
    assert result.next_latest_start_seconds == 180 - 20 == 160
    assert result.feasible is True
    assert result.reason is ObservationSequenceFeasibilityReason.FEASIBLE


def test_feasible_immediately_after_transition_matches_hand_calculation(
    monkeypatch,
) -> None:
    result, calls = _patched_sequence(
        monkeypatch,
        40.0,
        next_window_start_seconds=70,
    )

    assert calls == 1
    assert result.previous_end_seconds == 60
    assert result.transition_ready_seconds == 100
    assert result.candidate_next_start_seconds == 100
    assert result.next_latest_start_seconds == 160
    assert result.feasible is True


def test_exact_latest_start_boundary_is_feasible(monkeypatch) -> None:
    result, calls = _patched_sequence(
        monkeypatch,
        40.0,
        previous_start_seconds=80,
        previous_window_end_seconds=100,
        next_window_start_seconds=120,
        next_window_end_seconds=160,
    )

    assert calls == 1
    assert result.previous_end_seconds == 100
    assert result.transition_ready_seconds == 140
    assert result.candidate_next_start_seconds == 140
    assert result.next_latest_start_seconds == 140
    assert result.feasible is True


def test_insufficient_time_retains_transition_and_timing(monkeypatch) -> None:
    result, calls = _patched_sequence(
        monkeypatch,
        41.0,
        previous_start_seconds=80,
        previous_window_end_seconds=100,
        next_window_start_seconds=120,
        next_window_end_seconds=160,
    )

    assert calls == 1
    assert result.previous_end_seconds == 100
    assert result.transition_result is not None
    assert result.transition_result.total_transition_time_seconds == 41
    assert result.transition_ready_seconds == 141
    assert result.candidate_next_start_seconds == 141
    assert result.next_latest_start_seconds == 140
    assert result.feasible is False
    assert result.reason is (
        ObservationSequenceFeasibilityReason.INSUFFICIENT_TRANSITION_TIME
    )


def test_earliest_start_retains_fractional_transition_without_rounding(
    monkeypatch,
) -> None:
    result, _ = _patched_sequence(
        monkeypatch,
        40.25,
        next_window_start_seconds=70,
    )

    assert result.transition_ready_seconds == 100.25
    assert result.candidate_next_start_seconds == 100.25
    assert type(result.candidate_next_start_seconds) is float


def test_two_views_and_transition_are_each_evaluated_exactly_once(
    monkeypatch,
) -> None:
    view_calls: list[ObservationOpportunityId] = []
    transition_calls = 0
    original_view = feasibility_module.evaluate_observation_view_feasibility
    original_transition = feasibility_module.compute_boresight_transition

    def view(config, opportunity):
        view_calls.append(opportunity.opportunity_id)
        return original_view(config, opportunity)

    def transition(config, start, end):
        nonlocal transition_calls
        transition_calls += 1
        return original_transition(config, start, end)

    monkeypatch.setattr(
        feasibility_module, "evaluate_observation_view_feasibility", view
    )
    monkeypatch.setattr(
        feasibility_module, "compute_boresight_transition", transition
    )
    previous = _candidate(
        _opportunity("call-previous"), _direction(1.0, 0.0, 0.0)
    )
    next_candidate = _candidate(
        _opportunity(
            "call-next", window_start_seconds=100, window_end_seconds=300
        ),
        _direction(0.0, 1.0, 0.0),
    )

    result = evaluate_observation_sequence_feasibility(
        _config(), ScheduledObservationExecution(previous, 40), next_candidate
    )

    assert view_calls == [
        ObservationOpportunityId("call-previous"),
        ObservationOpportunityId("call-next"),
    ]
    assert transition_calls == 1
    assert result.feasible is True


def test_equal_local_limits_can_require_seventy_degree_transition() -> None:
    previous = _candidate(
        _opportunity("look-positive", view_angle_deg=35.0),
        _look_direction(35.0, azimuth_sign=1),
    )
    next_candidate = _candidate(
        _opportunity(
            "look-negative",
            window_start_seconds=100,
            window_end_seconds=300,
            view_angle_deg=35.0,
        ),
        _look_direction(35.0, azimuth_sign=-1),
    )

    result = evaluate_observation_sequence_feasibility(
        _config(), ScheduledObservationExecution(previous, 40), next_candidate
    )

    assert result.previous_view.feasible is True
    assert result.next_view.feasible is True
    assert result.transition_result is not None
    assert result.transition_result.angular_separation_deg == pytest.approx(70.0)
    assert result.transition_result.angular_separation_deg > 35.0
    assert result.feasible is True


def test_c2_out_of_envelope_error_propagates() -> None:
    config = _config(
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("sixty", 60.0, 70.0),
        )
    )
    previous = _candidate(
        _opportunity("outside-previous", view_angle_deg=35.0),
        _look_direction(35.0, azimuth_sign=1),
    )
    next_candidate = _candidate(
        _opportunity(
            "outside-next",
            window_start_seconds=100,
            window_end_seconds=300,
            view_angle_deg=35.0,
        ),
        _look_direction(35.0, azimuth_sign=-1),
    )

    with pytest.raises(ValueError, match="exceeds.*envelope"):
        evaluate_observation_sequence_feasibility(
            config,
            ScheduledObservationExecution(previous, 40),
            next_candidate,
        )


def test_different_common_frames_error_propagates() -> None:
    previous = _candidate(
        _opportunity("frame-previous"),
        _direction(1.0, 0.0, 0.0, frame_value="frame-a"),
    )
    next_candidate = _candidate(
        _opportunity(
            "frame-next", window_start_seconds=100, window_end_seconds=300
        ),
        _direction(0.0, 1.0, 0.0, frame_value="frame-b"),
    )

    with pytest.raises(ValueError, match="same frame_id"):
        evaluate_observation_sequence_feasibility(
            _config(),
            ScheduledObservationExecution(previous, 40),
            next_candidate,
        )


def test_zero_slew_adds_no_configured_settling() -> None:
    direction = _direction(1.0, 2.0, 3.0)
    previous = _candidate(_opportunity("zero-previous"), direction)
    next_candidate = _candidate(
        _opportunity(
            "zero-next", window_start_seconds=100, window_end_seconds=180
        ),
        direction,
    )

    result = evaluate_observation_sequence_feasibility(
        _config(settling_seconds=17.0),
        ScheduledObservationExecution(previous, 40),
        next_candidate,
    )

    assert result.transition_result is not None
    assert result.transition_result.angular_separation_deg == 0
    assert result.transition_result.settling_time_seconds == 0
    assert result.transition_result.total_transition_time_seconds == 0
    assert result.transition_ready_seconds == 60
    assert result.candidate_next_start_seconds == 100


def test_sequence_function_requires_exact_types_and_revalidates_inputs() -> None:
    config = _config()
    candidate = _candidate(_opportunity("sequence-types"))
    execution = ScheduledObservationExecution(candidate, 0)
    with pytest.raises(TypeError, match="config"):
        evaluate_observation_sequence_feasibility(object(), execution, candidate)
    with pytest.raises(TypeError, match="previous_execution"):
        evaluate_observation_sequence_feasibility(config, object(), candidate)
    with pytest.raises(TypeError, match="next_candidate"):
        evaluate_observation_sequence_feasibility(config, execution, object())

    object.__setattr__(candidate.common_frame_boresight, "x", float("nan"))
    with pytest.raises(ValueError, match="x"):
        evaluate_observation_sequence_feasibility(config, execution, candidate)


def test_sequence_result_validates_required_cross_field_invariants(
    monkeypatch,
) -> None:
    result, _ = _patched_sequence(monkeypatch, 30.0)
    with pytest.raises(TypeError, match="previous_opportunity_id"):
        replace(result, previous_opportunity_id=ImagingRequestId("wrong"))
    with pytest.raises(TypeError, match="previous_end_seconds"):
        replace(result, previous_end_seconds=True)
    with pytest.raises(TypeError, match="next_latest_start_seconds"):
        replace(result, next_latest_start_seconds=160.0)
    with pytest.raises(TypeError, match="previous_view"):
        replace(result, previous_view=object())
    with pytest.raises(TypeError, match="feasible"):
        replace(result, feasible=1)
    with pytest.raises(TypeError, match="reason"):
        replace(result, reason="feasible")
    with pytest.raises(ValueError, match="true exactly"):
        replace(result, feasible=False)
    with pytest.raises(ValueError, match="transition_ready_seconds"):
        replace(result, transition_ready_seconds=91.0)
    with pytest.raises(ValueError, match="must not precede"):
        replace(result, candidate_next_start_seconds=89.0)


def test_sequence_result_enforces_null_and_present_transition_fields(
    monkeypatch,
) -> None:
    feasible, _ = _patched_sequence(monkeypatch, 30.0)
    with pytest.raises(ValueError, match="requires transition"):
        replace(feasible, transition_result=None)

    failed_view = ObservationViewFeasibilityResult(
        feasible.previous_opportunity_id,
        36.0,
        35.0,
        False,
    )
    view_failure = ObservationSequenceFeasibilityResult(
        feasible.previous_opportunity_id,
        feasible.next_opportunity_id,
        feasible.previous_end_seconds,
        feasible.next_latest_start_seconds,
        failed_view,
        feasible.next_view,
        None,
        None,
        None,
        False,
        ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED,
    )
    with pytest.raises(ValueError, match="null transition"):
        replace(view_failure, transition_result=_transition(30.0))
    with pytest.raises(ValueError, match="requires transition"):
        replace(
            feasible,
            feasible=False,
            reason=(
                ObservationSequenceFeasibilityReason
                .INSUFFICIENT_TRANSITION_TIME
            ),
            transition_ready_seconds=None,
        )


def test_insufficient_result_requires_candidate_after_latest_start(
    monkeypatch,
) -> None:
    feasible, _ = _patched_sequence(monkeypatch, 30.0)
    with pytest.raises(ValueError, match="INSUFFICIENT_TRANSITION_TIME"):
        replace(
            feasible,
            feasible=False,
            reason=(
                ObservationSequenceFeasibilityReason
                .INSUFFICIENT_TRANSITION_TIME
            ),
        )


def test_numpy_view_inputs_produce_finite_builtin_outputs() -> None:
    result = evaluate_observation_view_feasibility(
        _config(maximum_view_angle_deg=np.float64(35.0)),
        _opportunity("numpy-view", view_angle_deg=np.float64(20.0)),
    )

    for value in (
        result.requested_view_angle_from_nadir_deg,
        result.maximum_view_angle_from_nadir_deg,
    ):
        assert type(value) in {int, float}
        assert isfinite(value)


def test_compute_functions_are_pure_and_mutate_no_inputs() -> None:
    config = _config()
    previous = _candidate(
        _opportunity("pure-previous"), _direction(1.0, 0.0, 0.0)
    )
    next_candidate = _candidate(
        _opportunity(
            "pure-next", window_start_seconds=100, window_end_seconds=300
        ),
        _direction(0.0, 1.0, 0.0),
    )
    execution = ScheduledObservationExecution(previous, 40)
    before = deepcopy((config, execution, next_candidate))

    evaluate_observation_view_feasibility(config, previous.opportunity)
    evaluate_observation_sequence_feasibility(config, execution, next_candidate)

    assert (config, execution, next_candidate) == before


def test_sequence_api_has_no_external_transition_result_input() -> None:
    parameters = tuple(
        signature(evaluate_observation_sequence_feasibility).parameters
    )

    assert parameters == ("config", "previous_execution", "next_candidate")


def test_production_has_only_required_pure_domain_dependencies() -> None:
    source = FEASIBILITY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FEASIBILITY_PATH))
    imported_modules = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert imported_modules <= {
        "__future__",
        "adcs",
        "adcs_config",
        "dataclasses",
        "enum",
        "ids",
        "math",
        "numbers",
        "observation",
    }
    lower = source.lower()
    for prohibited in (
        "numpy",
        "payload",
        "eps",
        "thermal",
        "storage",
        "battery",
        "solar",
        "controller",
        "engine",
        "checkpoint",
    ):
        assert prohibited not in lower


def test_production_has_no_observation_to_frame_trig_or_time_rounding() -> None:
    source = FEASIBILITY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FEASIBILITY_PATH))
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert identifiers.isdisjoint(
        {
            "sin",
            "cos",
            "tan",
            "radians",
            "degrees",
            "ceil",
            "floor",
            "round",
            "isclose",
            "clip",
            "clamp",
        }
    )
    assert "frame transform" not in source.lower()


def test_production_adds_no_scheduler_or_resource_optimization() -> None:
    source = FEASIBILITY_PATH.read_text(encoding="utf-8").lower()

    for prohibited in (
        "rank_opportunit",
        "select_opportunit",
        "maximize_priority",
        "reserve_resource",
        "insert_command",
        "update_mission",
    ):
        assert prohibited not in source


def test_prior_non_engine_production_sources_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/observation.py",
        "ops_sim/v5/adcs.py",
        "ops_sim/v5/adcs_config.py",
        "ops_sim/v5/configuration.py",
        "ops_sim/v5/ids.py",
        "ops_sim/v5/payload.py",
        "ops_sim/v5/payload_config.py",
        "ops_sim/v5/state.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/mission.py",
        "ops_sim/v5/world.py",
    ):
        before_slice = subprocess.run(
            [
                "git",
                "show",
                f"8d1f97acb1404ad1c88901d4420ac8328518524e:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        after_slice = subprocess.run(
            [
                "git",
                "show",
                f"8fe59097ccee59d5eb2d50d56327791cc294df4c:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_reason_enum_has_exact_values() -> None:
    assert tuple(ObservationSequenceFeasibilityReason) == (
        ObservationSequenceFeasibilityReason.FEASIBLE,
        ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED,
        ObservationSequenceFeasibilityReason.NEXT_VIEW_LIMIT_EXCEEDED,
        ObservationSequenceFeasibilityReason.INSUFFICIENT_TRANSITION_TIME,
    )
    assert tuple(reason.value for reason in ObservationSequenceFeasibilityReason) == (
        "feasible",
        "previous-view-limit-exceeded",
        "next-view-limit-exceeded",
        "insufficient-transition-time",
    )


def test_observation_feasibility_module_has_exact_exports() -> None:
    assert feasibility_module.__all__ == [
        "ObservationManeuverCandidate",
        "ObservationSequenceFeasibilityReason",
        "ObservationSequenceFeasibilityResult",
        "ObservationViewFeasibilityResult",
        "ScheduledObservationExecution",
        "evaluate_observation_sequence_feasibility",
        "evaluate_observation_view_feasibility",
    ]


def test_d198_through_d207_and_c3_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s006 = sources.partition("### S006 ")[2].partition("### S007 ")[0]
    lower = s006.lower()
    normalized = " ".join(lower.split())

    for number in range(198, 208):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D197 ") < decisions.index("## D198 ")
    assert "view_angle_from_nadir_deg <= maximum_view_angle_from_nadir_deg" in s006
    assert "t_previous,end" in s006 and "t_transition,ready" in s006
    assert "max(t_next,window-start, t_transition,ready)" in s006
    assert "unsupported timing coverage" in normalized
    assert "different-frame" in lower and "invalid composition" in lower
    assert "no new physical source or value" in normalized
    assert "no opportunity-to-frame transformation" in normalized
