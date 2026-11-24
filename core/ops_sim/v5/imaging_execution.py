"""Immutable scheduled optical-acquisition domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .imaging_feasibility import ObservationAcquisitionCandidate
from .observation_feasibility import ScheduledObservationExecution


class ImagingExecutionAuthorizationStatus(str, Enum):
    """Vocabulary reserved for later pure runtime authorization."""

    AUTHORIZED = "authorized"
    SEQUENCE_INFEASIBLE = "sequence-infeasible"
    ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED = (
        "electrical-full-service-not-established"
    )


@dataclass(frozen=True, slots=True)
class ScheduledObservationAcquisitionExecution:
    """One selected acquisition with a legal opportunity-local start."""

    candidate: ObservationAcquisitionCandidate
    scheduled_start_seconds: int

    def __post_init__(self) -> None:
        if type(self.candidate) is not ObservationAcquisitionCandidate:
            raise TypeError(
                "candidate must be an ObservationAcquisitionCandidate"
            )
        ObservationAcquisitionCandidate(
            self.candidate.maneuver_candidate,
            self.candidate.acquisition_input,
        )
        if type(self.scheduled_start_seconds) is not int:
            raise TypeError("scheduled_start_seconds must be an integer")
        if self.scheduled_start_seconds < 0:
            raise ValueError(
                "scheduled_start_seconds must be greater than or equal to zero"
            )
        ScheduledObservationExecution(
            self.candidate.maneuver_candidate,
            self.scheduled_start_seconds,
        )


__all__ = [
    "ImagingExecutionAuthorizationStatus",
    "ScheduledObservationAcquisitionExecution",
]
