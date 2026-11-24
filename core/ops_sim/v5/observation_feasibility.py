"""Pure observation-view and ADCS transition-time feasibility composition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Integral, Real

from .adcs import (
    BoresightTransitionResult,
    CommonFrameBoresightDirection,
    compute_boresight_transition,
)
from .adcs_config import AgilePointingConfig
from .ids import ImagingRequestId, ObservationOpportunityId
from .observation import ObservationOpportunity


def _normalized_real(name: str, value: object) -> int | float:
    """Return an admitted finite Real as a safe built-in scalar."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = bool(isfinite(value))
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")

    try:
        normalized = int(value) if isinstance(value, Integral) else float(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if type(normalized) not in {int, float}:
        raise ValueError(f"{name} must normalize to a built-in number")
    try:
        normalized_finite = bool(isfinite(normalized))
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if not normalized_finite:
        raise ValueError(f"{name} cannot be represented as a finite number")
    return normalized


def _normalized_nonnegative_real(name: str, value: object) -> int | float:
    normalized = _normalized_real(name, value)
    if normalized < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return normalized


def _normalized_positive_real(name: str, value: object) -> int | float:
    normalized = _normalized_real(name, value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return normalized


def _checked_sum(name: str, *values: object) -> int | float:
    """Add finite values using ordinary built-in arithmetic."""
    total: int | float = 0
    for index, value in enumerate(values):
        addend = _normalized_real(f"{name} addend {index}", value)
        try:
            total = total + addend
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented as finite"
            ) from error
        total = _normalized_real(name, total)
    return total


def _revalidate_opportunity(opportunity: ObservationOpportunity) -> None:
    ObservationOpportunity(
        opportunity.opportunity_id,
        opportunity.request_id,
        opportunity.window_start_seconds,
        opportunity.window_end_seconds,
        opportunity.imaging_duration_seconds,
        opportunity.pointing,
    )
    ObservationOpportunityId(opportunity.opportunity_id.value)
    ImagingRequestId(opportunity.request_id.value)


def _revalidate_config(config: AgilePointingConfig) -> None:
    AgilePointingConfig(
        config.maximum_view_angle_from_nadir_deg,
        config.post_slew_settling_time_seconds,
        config.slew_time_anchors,
    )


def _revalidate_transition_result(result: BoresightTransitionResult) -> None:
    BoresightTransitionResult(
        result.angular_separation_deg,
        result.lower_anchor_id,
        result.upper_anchor_id,
        result.interpolation_fraction,
        result.slew_elapsed_time_seconds,
        result.settling_time_seconds,
        result.total_transition_time_seconds,
    )


@dataclass(frozen=True, slots=True)
class ObservationManeuverCandidate:
    """One opportunity paired with its explicit common-frame boresight."""

    opportunity: ObservationOpportunity
    common_frame_boresight: CommonFrameBoresightDirection

    def __post_init__(self) -> None:
        if type(self.opportunity) is not ObservationOpportunity:
            raise TypeError("opportunity must be an ObservationOpportunity")
        if type(self.common_frame_boresight) is not CommonFrameBoresightDirection:
            raise TypeError(
                "common_frame_boresight must be a "
                "CommonFrameBoresightDirection"
            )
        _revalidate_opportunity(self.opportunity)
        CommonFrameBoresightDirection(
            self.common_frame_boresight.frame_id,
            self.common_frame_boresight.x,
            self.common_frame_boresight.y,
            self.common_frame_boresight.z,
        )


@dataclass(frozen=True, slots=True)
class ScheduledObservationExecution:
    """One candidate with an explicit legal acquisition start time."""

    candidate: ObservationManeuverCandidate
    scheduled_start_seconds: int

    def __post_init__(self) -> None:
        if type(self.candidate) is not ObservationManeuverCandidate:
            raise TypeError(
                "candidate must be an ObservationManeuverCandidate"
            )
        ObservationManeuverCandidate(
            self.candidate.opportunity,
            self.candidate.common_frame_boresight,
        )
        if type(self.scheduled_start_seconds) is not int:
            raise TypeError("scheduled_start_seconds must be an integer")
        if self.scheduled_start_seconds < 0:
            raise ValueError(
                "scheduled_start_seconds must be greater than or equal to zero"
            )

        opportunity = self.candidate.opportunity
        if self.scheduled_start_seconds < opportunity.window_start_seconds:
            raise ValueError(
                "scheduled_start_seconds must not precede the opportunity "
                "window"
            )
        end_seconds = (
            self.scheduled_start_seconds
            + opportunity.imaging_duration_seconds
        )
        if end_seconds > opportunity.window_end_seconds:
            raise ValueError(
                "scheduled acquisition must fit inside its opportunity window"
            )


@dataclass(frozen=True, slots=True)
class ObservationViewFeasibilityResult:
    """Inspectable local view-envelope feasibility for one opportunity."""

    opportunity_id: ObservationOpportunityId
    requested_view_angle_from_nadir_deg: float
    maximum_view_angle_from_nadir_deg: float
    feasible: bool

    def __post_init__(self) -> None:
        if type(self.opportunity_id) is not ObservationOpportunityId:
            raise TypeError(
                "opportunity_id must be an ObservationOpportunityId"
            )
        ObservationOpportunityId(self.opportunity_id.value)
        requested = _normalized_nonnegative_real(
            "requested_view_angle_from_nadir_deg",
            self.requested_view_angle_from_nadir_deg,
        )
        maximum = _normalized_positive_real(
            "maximum_view_angle_from_nadir_deg",
            self.maximum_view_angle_from_nadir_deg,
        )
        if type(self.feasible) is not bool:
            raise TypeError("feasible must be a boolean")
        if self.feasible is not (requested <= maximum):
            raise ValueError(
                "feasible must equal requested view angle less than or equal "
                "to maximum view angle"
            )


class ObservationSequenceFeasibilityReason(str, Enum):
    """Reason for one supported two-observation feasibility classification."""

    FEASIBLE = "feasible"
    PREVIOUS_VIEW_LIMIT_EXCEEDED = "previous-view-limit-exceeded"
    NEXT_VIEW_LIMIT_EXCEEDED = "next-view-limit-exceeded"
    INSUFFICIENT_TRANSITION_TIME = "insufficient-transition-time"


@dataclass(frozen=True, slots=True)
class ObservationSequenceFeasibilityResult:
    """Inspectable view, transition, and window-fit feasibility result."""

    previous_opportunity_id: ObservationOpportunityId
    next_opportunity_id: ObservationOpportunityId
    previous_end_seconds: int
    next_latest_start_seconds: int
    previous_view: ObservationViewFeasibilityResult
    next_view: ObservationViewFeasibilityResult
    transition_result: BoresightTransitionResult | None
    transition_ready_seconds: int | float | None
    candidate_next_start_seconds: int | float | None
    feasible: bool
    reason: ObservationSequenceFeasibilityReason

    def __post_init__(self) -> None:
        for field_name, opportunity_id in (
            ("previous_opportunity_id", self.previous_opportunity_id),
            ("next_opportunity_id", self.next_opportunity_id),
        ):
            if type(opportunity_id) is not ObservationOpportunityId:
                raise TypeError(
                    f"{field_name} must be an ObservationOpportunityId"
                )
            ObservationOpportunityId(opportunity_id.value)

        for field_name, value in (
            ("previous_end_seconds", self.previous_end_seconds),
            ("next_latest_start_seconds", self.next_latest_start_seconds),
        ):
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(
                    f"{field_name} must be greater than or equal to zero"
                )

        for field_name, view in (
            ("previous_view", self.previous_view),
            ("next_view", self.next_view),
        ):
            if type(view) is not ObservationViewFeasibilityResult:
                raise TypeError(
                    f"{field_name} must be an "
                    "ObservationViewFeasibilityResult"
                )
            ObservationViewFeasibilityResult(
                view.opportunity_id,
                view.requested_view_angle_from_nadir_deg,
                view.maximum_view_angle_from_nadir_deg,
                view.feasible,
            )
        if self.previous_view.opportunity_id != self.previous_opportunity_id:
            raise ValueError(
                "previous_view opportunity ID must match previous_opportunity_id"
            )
        if self.next_view.opportunity_id != self.next_opportunity_id:
            raise ValueError(
                "next_view opportunity ID must match next_opportunity_id"
            )

        if self.transition_result is not None:
            if type(self.transition_result) is not BoresightTransitionResult:
                raise TypeError(
                    "transition_result must be a BoresightTransitionResult or "
                    "None"
                )
            _revalidate_transition_result(self.transition_result)
        ready = None
        if self.transition_ready_seconds is not None:
            ready = _normalized_nonnegative_real(
                "transition_ready_seconds",
                self.transition_ready_seconds,
            )
        candidate_start = None
        if self.candidate_next_start_seconds is not None:
            candidate_start = _normalized_nonnegative_real(
                "candidate_next_start_seconds",
                self.candidate_next_start_seconds,
            )

        if type(self.feasible) is not bool:
            raise TypeError("feasible must be a boolean")
        if type(self.reason) is not ObservationSequenceFeasibilityReason:
            raise TypeError(
                "reason must be an ObservationSequenceFeasibilityReason"
            )
        if self.feasible is not (
            self.reason is ObservationSequenceFeasibilityReason.FEASIBLE
        ):
            raise ValueError("feasible must be true exactly for FEASIBLE reason")

        transition_values = (
            self.transition_result,
            ready,
            candidate_start,
        )
        view_failure_reasons = {
            ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED,
            ObservationSequenceFeasibilityReason.NEXT_VIEW_LIMIT_EXCEEDED,
        }
        if self.reason in view_failure_reasons:
            if any(value is not None for value in transition_values):
                raise ValueError(
                    "view-limit failure requires null transition and timing "
                    "fields"
                )
            if self.reason is (
                ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED
            ):
                if self.previous_view.feasible:
                    raise ValueError(
                        "previous-view failure requires infeasible previous view"
                    )
            elif not self.previous_view.feasible or self.next_view.feasible:
                raise ValueError(
                    "next-view failure requires feasible previous view and "
                    "infeasible next view"
                )
            return

        if any(value is None for value in transition_values):
            raise ValueError(
                "time classification requires transition and timing fields"
            )
        if not self.previous_view.feasible or not self.next_view.feasible:
            raise ValueError(
                "time classification requires both views to be feasible"
            )
        expected_ready = _checked_sum(
            "transition_ready_seconds",
            self.previous_end_seconds,
            self.transition_result.total_transition_time_seconds,
        )
        if ready != expected_ready:
            raise ValueError(
                "transition_ready_seconds must equal previous end plus total "
                "transition time"
            )
        if candidate_start < ready:
            raise ValueError(
                "candidate_next_start_seconds must not precede transition "
                "readiness"
            )
        if self.reason is ObservationSequenceFeasibilityReason.FEASIBLE:
            if candidate_start > self.next_latest_start_seconds:
                raise ValueError(
                    "FEASIBLE requires candidate start no later than latest "
                    "legal start"
                )
        elif self.reason is (
            ObservationSequenceFeasibilityReason.INSUFFICIENT_TRANSITION_TIME
        ):
            if candidate_start <= self.next_latest_start_seconds:
                raise ValueError(
                    "INSUFFICIENT_TRANSITION_TIME requires candidate start "
                    "after latest legal start"
                )


def evaluate_observation_view_feasibility(
    config: AgilePointingConfig,
    opportunity: ObservationOpportunity,
) -> ObservationViewFeasibilityResult:
    """Evaluate one local off-nadir request against configured view limit."""
    if type(config) is not AgilePointingConfig:
        raise TypeError("config must be an AgilePointingConfig")
    if type(opportunity) is not ObservationOpportunity:
        raise TypeError("opportunity must be an ObservationOpportunity")
    _revalidate_config(config)
    _revalidate_opportunity(opportunity)

    requested = _normalized_nonnegative_real(
        "requested_view_angle_from_nadir_deg",
        opportunity.pointing.view_angle_from_nadir_deg,
    )
    maximum = _normalized_positive_real(
        "maximum_view_angle_from_nadir_deg",
        config.maximum_view_angle_from_nadir_deg.value,
    )
    return ObservationViewFeasibilityResult(
        opportunity.opportunity_id,
        requested,
        maximum,
        requested <= maximum,
    )


def evaluate_observation_sequence_feasibility(
    config: AgilePointingConfig,
    previous_execution: ScheduledObservationExecution,
    next_candidate: ObservationManeuverCandidate,
) -> ObservationSequenceFeasibilityResult:
    """Evaluate one specified next opportunity after a scheduled acquisition."""
    if type(config) is not AgilePointingConfig:
        raise TypeError("config must be an AgilePointingConfig")
    if type(previous_execution) is not ScheduledObservationExecution:
        raise TypeError(
            "previous_execution must be a ScheduledObservationExecution"
        )
    if type(next_candidate) is not ObservationManeuverCandidate:
        raise TypeError(
            "next_candidate must be an ObservationManeuverCandidate"
        )
    _revalidate_config(config)
    ScheduledObservationExecution(
        previous_execution.candidate,
        previous_execution.scheduled_start_seconds,
    )
    ObservationManeuverCandidate(
        next_candidate.opportunity,
        next_candidate.common_frame_boresight,
    )

    previous_opportunity = previous_execution.candidate.opportunity
    next_opportunity = next_candidate.opportunity
    previous_end_seconds = (
        previous_execution.scheduled_start_seconds
        + previous_opportunity.imaging_duration_seconds
    )
    next_latest_start_seconds = (
        next_opportunity.window_end_seconds
        - next_opportunity.imaging_duration_seconds
    )
    previous_view = evaluate_observation_view_feasibility(
        config,
        previous_opportunity,
    )
    next_view = evaluate_observation_view_feasibility(
        config,
        next_opportunity,
    )

    if not previous_view.feasible:
        return ObservationSequenceFeasibilityResult(
            previous_opportunity.opportunity_id,
            next_opportunity.opportunity_id,
            previous_end_seconds,
            next_latest_start_seconds,
            previous_view,
            next_view,
            None,
            None,
            None,
            False,
            ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED,
        )
    if not next_view.feasible:
        return ObservationSequenceFeasibilityResult(
            previous_opportunity.opportunity_id,
            next_opportunity.opportunity_id,
            previous_end_seconds,
            next_latest_start_seconds,
            previous_view,
            next_view,
            None,
            None,
            None,
            False,
            ObservationSequenceFeasibilityReason.NEXT_VIEW_LIMIT_EXCEEDED,
        )

    transition_result = compute_boresight_transition(
        config,
        previous_execution.candidate.common_frame_boresight,
        next_candidate.common_frame_boresight,
    )
    transition_ready_seconds = _checked_sum(
        "transition_ready_seconds",
        previous_end_seconds,
        transition_result.total_transition_time_seconds,
    )
    candidate_next_start_seconds = max(
        next_opportunity.window_start_seconds,
        transition_ready_seconds,
    )
    feasible = candidate_next_start_seconds <= next_latest_start_seconds
    reason = (
        ObservationSequenceFeasibilityReason.FEASIBLE
        if feasible
        else ObservationSequenceFeasibilityReason.INSUFFICIENT_TRANSITION_TIME
    )
    return ObservationSequenceFeasibilityResult(
        previous_opportunity.opportunity_id,
        next_opportunity.opportunity_id,
        previous_end_seconds,
        next_latest_start_seconds,
        previous_view,
        next_view,
        transition_result,
        transition_ready_seconds,
        candidate_next_start_seconds,
        feasible,
        reason,
    )


__all__ = [
    "ObservationManeuverCandidate",
    "ObservationSequenceFeasibilityReason",
    "ObservationSequenceFeasibilityResult",
    "ObservationViewFeasibilityResult",
    "ScheduledObservationExecution",
    "evaluate_observation_sequence_feasibility",
    "evaluate_observation_view_feasibility",
]
