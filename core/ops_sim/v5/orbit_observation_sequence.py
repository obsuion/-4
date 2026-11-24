"""Frame-safe orbit-derived composition of historical V5.3 C3 feasibility.

Both public local-view prechecks precede conditional D1c admission. A view
failure asserts no pairwise frame compatibility because no transition is needed.
When both views pass, D1c must succeed before C3's transition-bearing path.
C3 owns all sequence/window timing and necessarily repeats its own C2 call:
its frozen API accepts no precomputed transition. See D315/S006.

D1a's full-step duration makes the next step start its latest legal start.
This consequence is evaluated by C3, never reimplemented here. These transient
values neither schedule/select nor execute observations and add no persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from numbers import Integral

from .adcs import CommonFrameBoresightDirection
from .adcs_config import AgilePointingConfig
from .observation_feasibility import (
    ObservationManeuverCandidate,
    ObservationSequenceFeasibilityReason,
    ObservationSequenceFeasibilityResult,
    ScheduledObservationExecution,
    evaluate_observation_sequence_feasibility,
    evaluate_observation_view_feasibility,
)
from .orbit_observation_boresight import OrbitBoundObservationManeuverCandidate
from .orbit_observation_transition import (
    OrbitBoundObservationTransition,
    evaluate_orbit_bound_observation_transition,
)
from .parameters import ScalarParameter
from .provenance import ParameterProvenance, SensitivityRange


def _same_text(left, right) -> bool:
    return (isinstance(left, str) and isinstance(right, str)
            and str.__eq__(left, right) is True)


def _same_optional_text(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return _same_text(left, right)


def _same_id(left, right) -> bool:
    """Compare represented legacy identity without caller equality or hashing."""
    return type(left) is type(right) and _same_text(left.value, right.value)


def _represented_real(value) -> int | float:
    """Local equality representation of an owner-admitted finite Real.

    Base descriptors preserve int/float payloads without subclass dispatch.
    Wider Real values use ADCS's Integral -> int, otherwise -> float rule.
    This neither rewrites retained evidence nor changes physical admission.
    """
    if isinstance(value, int):
        return int.__int__(value)
    if isinstance(value, float):
        return float.__float__(value)
    return int(value) if isinstance(value, Integral) else float(value)


def _same_real(left, right) -> bool:
    return _represented_real(left) == _represented_real(right)


def _same_sensitivity_range(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return (type(left) is type(right) and isinstance(left, SensitivityRange)
            and _same_real(left.lower, right.lower) and _same_real(left.upper, right.upper))


def _same_provenance(left, right) -> bool:
    return (type(left) is ParameterProvenance and type(right) is ParameterProvenance
            and _same_id(left.parameter_id, right.parameter_id)
            and left.classification is right.classification
            and _same_text(left.units, right.units)
            and len(left.source_ids) == len(right.source_ids)
            and all(_same_id(a, b) for a, b in zip(left.source_ids, right.source_ids))
            and left.status is right.status
            and _same_optional_text(left.rationale, right.rationale)
            and _same_optional_text(left.derivation, right.derivation)
            and _same_sensitivity_range(left.sensitivity_range, right.sensitivity_range))


def _same_parameter(left, right) -> bool:
    return (type(left) is ScalarParameter and type(right) is ScalarParameter
            and _same_real(left.value, right.value)
            and _same_provenance(left.provenance, right.provenance))


def _same_transition(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return (type(left) is type(right)
            and _same_id(left.lower_anchor_id, right.lower_anchor_id)
            and _same_id(left.upper_anchor_id, right.upper_anchor_id)
            and all(getattr(left, name) == getattr(right, name) for name in (
                "angular_separation_deg", "interpolation_fraction",
                "slew_elapsed_time_seconds", "settling_time_seconds",
                "total_transition_time_seconds")))


def _same_config(left, right) -> bool:
    # Compare all retained parameter/provenance evidence after owner admission.
    # Legacy text subclasses keep their actual content, never caller equality.
    return (_same_parameter(left.maximum_view_angle_from_nadir_deg, right.maximum_view_angle_from_nadir_deg)
            and _same_parameter(left.post_slew_settling_time_seconds, right.post_slew_settling_time_seconds)
            and len(left.slew_time_anchors) == len(right.slew_time_anchors)
            and all(_same_id(a.anchor_id, b.anchor_id)
                    and _same_parameter(a.angular_separation_deg, b.angular_separation_deg)
                    and _same_parameter(a.slew_elapsed_time_seconds, b.slew_elapsed_time_seconds)
                    for a, b in zip(left.slew_time_anchors, right.slew_time_anchors)))


def _same_execution(left, right) -> bool:
    a, b = left.candidate.opportunity, right.candidate.opportunity
    u, v = left.candidate.common_frame_boresight, right.candidate.common_frame_boresight
    return (left.scheduled_start_seconds == right.scheduled_start_seconds
            and _same_id(a.opportunity_id, b.opportunity_id)
            and _same_id(a.request_id, b.request_id)
            and a.window_start_seconds == b.window_start_seconds
            and a.window_end_seconds == b.window_end_seconds
            and a.imaging_duration_seconds == b.imaging_duration_seconds
            and a.pointing == b.pointing
            and _same_id(u.frame_id, v.frame_id)
            and (u.x, u.y, u.z) == (v.x, v.y, v.z))


def _same_view(left, right) -> bool:
    return (_same_id(left.opportunity_id, right.opportunity_id)
            and left.requested_view_angle_from_nadir_deg == right.requested_view_angle_from_nadir_deg
            and left.maximum_view_angle_from_nadir_deg == right.maximum_view_angle_from_nadir_deg
            and left.feasible is right.feasible)


def _same_sequence(left, right) -> bool:
    return (_same_id(left.previous_opportunity_id, right.previous_opportunity_id)
            and _same_id(left.next_opportunity_id, right.next_opportunity_id)
            and left.previous_end_seconds == right.previous_end_seconds
            and left.next_latest_start_seconds == right.next_latest_start_seconds
            and _same_view(left.previous_view, right.previous_view)
            and _same_view(left.next_view, right.next_view)
            and _same_transition(left.transition_result, right.transition_result)
            and left.transition_ready_seconds == right.transition_ready_seconds
            and left.candidate_next_start_seconds == right.candidate_next_start_seconds
            and left.feasible is right.feasible
            and left.reason is right.reason)


def _same_transition_evidence(left, right) -> bool:
    if left is None or right is None:
        return left is right
    return (_same_config(left.config, right.config)
            and left.previous == right.previous and left.next == right.next
            and _same_transition(left.transition_result, right.transition_result))


@dataclass(frozen=True, slots=True, eq=False)
class OrbitBoundObservationSequenceFeasibility:
    """Recomputed ordered C3 evidence, with conditional concrete-frame proof."""

    config: AgilePointingConfig
    previous: OrbitBoundObservationManeuverCandidate
    next: OrbitBoundObservationManeuverCandidate
    previous_execution: ScheduledObservationExecution = field(init=False)
    transition_evidence: OrbitBoundObservationTransition | None = field(init=False)
    sequence_result: ObservationSequenceFeasibilityResult = field(init=False)

    __hash__ = None

    def __post_init__(self) -> None:
        if type(self.config) is not AgilePointingConfig:
            raise TypeError("config must be an exact AgilePointingConfig")
        for name in ("previous", "next"):
            if type(getattr(self, name)) is not OrbitBoundObservationManeuverCandidate:
                raise TypeError(f"{name} must be an exact OrbitBoundObservationManeuverCandidate")
        config = AgilePointingConfig(
            self.config.maximum_view_angle_from_nadir_deg,
            self.config.post_slew_settling_time_seconds,
            self.config.slew_time_anchors,
        )
        previous, next = (
            OrbitBoundObservationManeuverCandidate(**{
                item.name: getattr(candidate, item.name)
                for item in fields(OrbitBoundObservationManeuverCandidate) if item.init
            })
            for candidate in (self.previous, self.next)
        )
        previous_execution = ScheduledObservationExecution(
            previous.maneuver_candidate, previous.step_start_seconds
        )
        previous_view = evaluate_observation_view_feasibility(
            config, previous.orbit_observation.opportunity
        )
        next_view = evaluate_observation_view_feasibility(
            config, next.orbit_observation.opportunity
        )
        transition_evidence = None
        view_failure = None
        c3_previous_execution = previous_execution
        c3_next_candidate = next.maneuver_candidate
        if not previous_view.feasible:
            view_failure = ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED
        elif not next_view.feasible:
            view_failure = ObservationSequenceFeasibilityReason.NEXT_VIEW_LIMIT_EXCEEDED
        else:
            transition_evidence = evaluate_orbit_bound_observation_transition(config, previous, next)
            # Only D1c establishes complete binding equality. Reuse its admitted
            # caller-owned ID to bridge C3's redundant bare-ID C2 check safely.
            left, right = transition_evidence.previous, transition_evidence.next
            shared_frame_id = left.boresight_frame.frame_id
            start, end = left.common_frame_boresight, right.common_frame_boresight
            safe_previous_boresight = CommonFrameBoresightDirection(shared_frame_id, start.x, start.y, start.z)
            safe_next_boresight = CommonFrameBoresightDirection(shared_frame_id, end.x, end.y, end.z)
            safe_previous_candidate = ObservationManeuverCandidate(
                left.orbit_observation.opportunity, safe_previous_boresight
            )
            c3_next_candidate = ObservationManeuverCandidate(
                right.orbit_observation.opportunity, safe_next_boresight
            )
            c3_previous_execution = ScheduledObservationExecution(safe_previous_candidate, left.step_start_seconds)
        sequence_result = evaluate_observation_sequence_feasibility(config, c3_previous_execution, c3_next_candidate)
        if view_failure is not None:
            if (sequence_result.reason is not view_failure
                    or any(value is not None for value in (
                        sequence_result.transition_result, sequence_result.transition_ready_seconds,
                        sequence_result.candidate_next_start_seconds))):
                raise ValueError("C3 result contradicts public view-failure precedence")
        elif (sequence_result.transition_result is None
                or not _same_transition(transition_evidence.transition_result, sequence_result.transition_result)):
            raise ValueError("C3 transition result contradicts D1c transition evidence")
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "previous", previous)
        object.__setattr__(self, "next", next)
        object.__setattr__(self, "previous_execution", previous_execution)
        object.__setattr__(self, "transition_evidence", transition_evidence)
        object.__setattr__(self, "sequence_result", sequence_result)

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return (_same_config(self.config, other.config)
                and self.previous == other.previous and self.next == other.next
                and _same_execution(self.previous_execution, other.previous_execution)
                and _same_transition_evidence(self.transition_evidence, other.transition_evidence)
                and _same_sequence(self.sequence_result, other.sequence_result))


def evaluate_orbit_bound_observation_sequence_feasibility(
    config: AgilePointingConfig,
    previous: OrbitBoundObservationManeuverCandidate,
    next: OrbitBoundObservationManeuverCandidate,
) -> OrbitBoundObservationSequenceFeasibility:
    return OrbitBoundObservationSequenceFeasibility(config, previous, next)


__all__ = ["OrbitBoundObservationSequenceFeasibility", "evaluate_orbit_bound_observation_sequence_feasibility"]
