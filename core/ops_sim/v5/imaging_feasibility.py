"""Pure sequenced observation and optical-acquisition composition."""

from __future__ import annotations

from dataclasses import dataclass

from .adcs_config import AgilePointingConfig
from .observation_feasibility import (
    ObservationManeuverCandidate,
    ObservationSequenceFeasibilityResult,
    ScheduledObservationExecution,
    evaluate_observation_sequence_feasibility,
)
from .payload import (
    OpticalAcquisitionInput,
    OpticalAcquisitionResult,
    compute_optical_acquisition,
)
from .payload_config import OpticalAcquisitionConfig


def _revalidate_agile_pointing_config(config: AgilePointingConfig) -> None:
    AgilePointingConfig(
        config.maximum_view_angle_from_nadir_deg,
        config.post_slew_settling_time_seconds,
        config.slew_time_anchors,
    )


def _revalidate_optical_acquisition_config(
    config: OpticalAcquisitionConfig,
) -> None:
    OpticalAcquisitionConfig(
        config.reference_nadir_swath_width_m,
        config.panchromatic_reference_sample_spacing_m,
        config.multispectral_reference_sample_spacing_m,
        config.multispectral_band_count,
        config.acquisition_bits_per_sample,
        config.acquisition_power_w,
        config.simultaneous_pan_and_multispectral,
    )


def _revalidate_sequence_result(
    result: ObservationSequenceFeasibilityResult,
) -> None:
    ObservationSequenceFeasibilityResult(
        result.previous_opportunity_id,
        result.next_opportunity_id,
        result.previous_end_seconds,
        result.next_latest_start_seconds,
        result.previous_view,
        result.next_view,
        result.transition_result,
        result.transition_ready_seconds,
        result.candidate_next_start_seconds,
        result.feasible,
        result.reason,
    )


def _revalidate_acquisition_result(result: OpticalAcquisitionResult) -> None:
    OpticalAcquisitionResult(
        result.footprint_area_m2,
        result.panchromatic_equivalent_samples,
        result.multispectral_equivalent_samples_per_band,
        result.multispectral_equivalent_samples_total,
        result.total_equivalent_samples,
        result.uncompressed_equivalent_bits,
        result.uncompressed_equivalent_bytes,
        result.requested_acquisition_power_w,
        result.acquisition_energy_wh,
    )


@dataclass(frozen=True, slots=True)
class ObservationAcquisitionCandidate:
    """Pair one maneuver candidate with its explicit acquisition input."""

    maneuver_candidate: ObservationManeuverCandidate
    acquisition_input: OpticalAcquisitionInput

    def __post_init__(self) -> None:
        if type(self.maneuver_candidate) is not ObservationManeuverCandidate:
            raise TypeError(
                "maneuver_candidate must be an ObservationManeuverCandidate"
            )
        if type(self.acquisition_input) is not OpticalAcquisitionInput:
            raise TypeError(
                "acquisition_input must be an OpticalAcquisitionInput"
            )
        ObservationManeuverCandidate(
            self.maneuver_candidate.opportunity,
            self.maneuver_candidate.common_frame_boresight,
        )
        OpticalAcquisitionInput(
            self.acquisition_input.effective_cross_track_width_m,
            self.acquisition_input.effective_along_track_length_m,
            self.acquisition_input.imaging_duration_seconds,
            self.acquisition_input.channel_selection,
        )
        if (
            self.acquisition_input.imaging_duration_seconds
            != self.maneuver_candidate.opportunity.imaging_duration_seconds
        ):
            raise ValueError(
                "acquisition input and observation opportunity imaging "
                "durations must match exactly"
            )


@dataclass(frozen=True, slots=True)
class ObservationAcquisitionEvaluationResult:
    """Reviewed sequence result and conditional optical-acquisition demand."""

    sequence_result: ObservationSequenceFeasibilityResult
    acquisition_result: OpticalAcquisitionResult | None
    feasible: bool

    def __post_init__(self) -> None:
        if type(self.sequence_result) is not ObservationSequenceFeasibilityResult:
            raise TypeError(
                "sequence_result must be an "
                "ObservationSequenceFeasibilityResult"
            )
        _revalidate_sequence_result(self.sequence_result)
        if self.acquisition_result is not None:
            if type(self.acquisition_result) is not OpticalAcquisitionResult:
                raise TypeError(
                    "acquisition_result must be an OpticalAcquisitionResult "
                    "or None"
                )
            _revalidate_acquisition_result(self.acquisition_result)
        if type(self.feasible) is not bool:
            raise TypeError("feasible must be a boolean")
        if self.feasible is not self.sequence_result.feasible:
            raise ValueError("feasible must equal sequence_result.feasible")
        if self.sequence_result.feasible:
            if self.acquisition_result is None:
                raise ValueError(
                    "a feasible sequence requires an acquisition_result"
                )
        elif self.acquisition_result is not None:
            raise ValueError(
                "an infeasible sequence requires acquisition_result to be None"
            )


def evaluate_observation_acquisition(
    agile_pointing_config: AgilePointingConfig,
    optical_acquisition_config: OpticalAcquisitionConfig,
    previous_execution: ScheduledObservationExecution,
    next_candidate: ObservationAcquisitionCandidate,
) -> ObservationAcquisitionEvaluationResult:
    """Compose reviewed sequence feasibility and acquisition demand."""
    if type(agile_pointing_config) is not AgilePointingConfig:
        raise TypeError(
            "agile_pointing_config must be an AgilePointingConfig"
        )
    if type(optical_acquisition_config) is not OpticalAcquisitionConfig:
        raise TypeError(
            "optical_acquisition_config must be an OpticalAcquisitionConfig"
        )
    if type(previous_execution) is not ScheduledObservationExecution:
        raise TypeError(
            "previous_execution must be a ScheduledObservationExecution"
        )
    if type(next_candidate) is not ObservationAcquisitionCandidate:
        raise TypeError(
            "next_candidate must be an ObservationAcquisitionCandidate"
        )

    _revalidate_agile_pointing_config(agile_pointing_config)
    _revalidate_optical_acquisition_config(optical_acquisition_config)
    ScheduledObservationExecution(
        previous_execution.candidate,
        previous_execution.scheduled_start_seconds,
    )
    ObservationAcquisitionCandidate(
        next_candidate.maneuver_candidate,
        next_candidate.acquisition_input,
    )

    sequence_result = evaluate_observation_sequence_feasibility(
        agile_pointing_config,
        previous_execution,
        next_candidate.maneuver_candidate,
    )
    if not sequence_result.feasible:
        return ObservationAcquisitionEvaluationResult(
            sequence_result,
            None,
            False,
        )

    acquisition_result = compute_optical_acquisition(
        optical_acquisition_config,
        next_candidate.acquisition_input,
    )
    return ObservationAcquisitionEvaluationResult(
        sequence_result,
        acquisition_result,
        True,
    )


__all__ = [
    "ObservationAcquisitionCandidate",
    "ObservationAcquisitionEvaluationResult",
    "evaluate_observation_acquisition",
]
