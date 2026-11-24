"""Pure Level-1 onboard acquisition-data equivalent-volume semantics."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .ids import (
    AcquisitionDataRecordId,
    ImagingRequestId,
    ObservationOpportunityId,
)
from .payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionResult,
)


def _revalidate_acquisition_result(
    acquisition_result: OpticalAcquisitionResult,
) -> None:
    OpticalAcquisitionResult(
        acquisition_result.footprint_area_m2,
        acquisition_result.panchromatic_equivalent_samples,
        acquisition_result.multispectral_equivalent_samples_per_band,
        acquisition_result.multispectral_equivalent_samples_total,
        acquisition_result.total_equivalent_samples,
        acquisition_result.uncompressed_equivalent_bits,
        acquisition_result.uncompressed_equivalent_bytes,
        acquisition_result.requested_acquisition_power_w,
        acquisition_result.acquisition_energy_wh,
    )


def _validate_positive_builtin_float(name: str, value: object) -> None:
    if type(value) is not float:
        raise TypeError(f"{name} must be a built-in float")
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True, slots=True)
class OnboardAcquisitionDataVolumeProposal:
    """Continuous equivalent-bit bookkeeping for one acquisition result."""

    acquisition_result: OpticalAcquisitionResult
    uncompressed_equivalent_bits: float
    stored_equivalent_bits: float

    def __post_init__(self) -> None:
        if type(self.acquisition_result) is not OpticalAcquisitionResult:
            raise TypeError(
                "acquisition_result must be an OpticalAcquisitionResult"
            )
        _revalidate_acquisition_result(self.acquisition_result)
        _validate_positive_builtin_float(
            "uncompressed_equivalent_bits",
            self.uncompressed_equivalent_bits,
        )
        _validate_positive_builtin_float(
            "stored_equivalent_bits",
            self.stored_equivalent_bits,
        )
        if self.uncompressed_equivalent_bits != (
            self.acquisition_result.uncompressed_equivalent_bits
        ):
            raise ValueError(
                "uncompressed_equivalent_bits must equal the acquisition "
                "result value exactly"
            )
        if self.stored_equivalent_bits != self.uncompressed_equivalent_bits:
            raise ValueError(
                "stored_equivalent_bits must equal "
                "uncompressed_equivalent_bits exactly"
            )


@dataclass(frozen=True, slots=True)
class OnboardAcquisitionDataRecord:
    """One immutable Level-1 acquisition-data record description."""

    record_id: AcquisitionDataRecordId
    imaging_request_id: ImagingRequestId
    observation_opportunity_id: ObservationOpportunityId
    scheduled_start_seconds: int
    acquisition_duration_seconds: int
    channel_selection: OpticalAcquisitionChannelSelection
    uncompressed_equivalent_bits: float
    stored_equivalent_bits: float

    def __post_init__(self) -> None:
        if type(self.record_id) is not AcquisitionDataRecordId:
            raise TypeError(
                "record_id must be an AcquisitionDataRecordId"
            )
        AcquisitionDataRecordId(self.record_id.value)
        if type(self.imaging_request_id) is not ImagingRequestId:
            raise TypeError(
                "imaging_request_id must be an ImagingRequestId"
            )
        ImagingRequestId(self.imaging_request_id.value)
        if type(self.observation_opportunity_id) is not (
            ObservationOpportunityId
        ):
            raise TypeError(
                "observation_opportunity_id must be an "
                "ObservationOpportunityId"
            )
        ObservationOpportunityId(self.observation_opportunity_id.value)
        if type(self.scheduled_start_seconds) is not int:
            raise TypeError(
                "scheduled_start_seconds must be a built-in int"
            )
        if self.scheduled_start_seconds < 0:
            raise ValueError(
                "scheduled_start_seconds must be greater than or equal to zero"
            )
        if type(self.acquisition_duration_seconds) is not int:
            raise TypeError(
                "acquisition_duration_seconds must be a built-in int"
            )
        if self.acquisition_duration_seconds <= 0:
            raise ValueError(
                "acquisition_duration_seconds must be greater than zero"
            )
        if type(self.channel_selection) is not (
            OpticalAcquisitionChannelSelection
        ):
            raise TypeError(
                "channel_selection must be an "
                "OpticalAcquisitionChannelSelection"
            )
        _validate_positive_builtin_float(
            "uncompressed_equivalent_bits",
            self.uncompressed_equivalent_bits,
        )
        _validate_positive_builtin_float(
            "stored_equivalent_bits",
            self.stored_equivalent_bits,
        )
        if self.stored_equivalent_bits != self.uncompressed_equivalent_bits:
            raise ValueError(
                "stored_equivalent_bits must equal "
                "uncompressed_equivalent_bits exactly"
            )


def compute_onboard_acquisition_data_volume_proposal(
    acquisition_result: OpticalAcquisitionResult,
) -> OnboardAcquisitionDataVolumeProposal:
    """Copy one reviewed acquisition bit quantity into an identity proposal."""
    if type(acquisition_result) is not OpticalAcquisitionResult:
        raise TypeError(
            "acquisition_result must be an OpticalAcquisitionResult"
        )
    _revalidate_acquisition_result(acquisition_result)
    equivalent_bits = acquisition_result.uncompressed_equivalent_bits
    return OnboardAcquisitionDataVolumeProposal(
        acquisition_result,
        equivalent_bits,
        equivalent_bits,
    )


__all__ = [
    "OnboardAcquisitionDataVolumeProposal",
    "OnboardAcquisitionDataRecord",
    "compute_onboard_acquisition_data_volume_proposal",
]
