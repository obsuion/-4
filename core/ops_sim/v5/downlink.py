"""Pure partial/complete downlink transmission arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import fsum, isfinite

from .communications import (
    DownlinkCapacityProposal,
    ServiceableGroundContact,
    compute_downlink_capacity,
)
from .configuration import CommunicationsConfig
from .data_delivery import (
    DownlinkTransferProgress,
    _validate_acquisition_completed_by,
)
from .onboard_data import OnboardAcquisitionDataRecord


class DownlinkTransmissionStatus(str, Enum):
    """Pure selected-record transmission classifications."""

    PARTIAL = "partial"
    COMPLETE = "complete"


def _revalidate_record(record: OnboardAcquisitionDataRecord) -> None:
    OnboardAcquisitionDataRecord(
        record.record_id,
        record.imaging_request_id,
        record.observation_opportunity_id,
        record.scheduled_start_seconds,
        record.acquisition_duration_seconds,
        record.channel_selection,
        record.uncompressed_equivalent_bits,
        record.stored_equivalent_bits,
    )


def _revalidate_capacity_proposal(
    proposal: DownlinkCapacityProposal,
) -> None:
    DownlinkCapacityProposal(
        proposal.contact,
        proposal.nominal_downlink_data_rate_bps,
        proposal.serviceable_contact_duration_seconds,
        proposal.nominal_contact_capacity_bits,
    )


def _require_finite_float(name: str, value: object) -> float:
    if type(value) is not float:
        raise TypeError(f"{name} must be a built-in float")
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _finite_difference(name: str, minuend: float, subtrahend: float) -> float:
    difference = minuend - subtrahend
    if type(difference) is not float or not isfinite(difference):
        raise ValueError(f"{name} must be a finite built-in float")
    return difference


def _finite_ratio(name: str, numerator: float, denominator: float) -> float:
    ratio = numerator / denominator
    if type(ratio) is not float or not isfinite(ratio):
        raise ValueError(f"{name} must be a finite built-in float")
    return ratio


@dataclass(frozen=True, slots=True)
class DownlinkTransmissionResult:
    """Transient evidence for one record serviced by one ground contact."""

    record: OnboardAcquisitionDataRecord
    capacity_proposal: DownlinkCapacityProposal
    status: DownlinkTransmissionStatus
    transmitted_equivalent_bits_this_service: float
    progress_before_equivalent_bits: float
    progress_after_equivalent_bits: float
    remaining_before_equivalent_bits: float
    remaining_after_equivalent_bits: float
    unused_contact_capacity_bits: float
    utilization_ratio: float
    storage_freed_equivalent_bits: float

    def __post_init__(self) -> None:
        if type(self.record) is not OnboardAcquisitionDataRecord:
            raise TypeError("record must be an OnboardAcquisitionDataRecord")
        _revalidate_record(self.record)
        if type(self.capacity_proposal) is not DownlinkCapacityProposal:
            raise TypeError(
                "capacity_proposal must be a DownlinkCapacityProposal"
            )
        _revalidate_capacity_proposal(self.capacity_proposal)
        _validate_acquisition_completed_by(
            self.record,
            self.capacity_proposal.contact.start_time_seconds,
            boundary="serviced contact start",
        )
        if type(self.status) is not DownlinkTransmissionStatus:
            raise TypeError("status must be a DownlinkTransmissionStatus")

        numeric_fields = (
            (
                "transmitted_equivalent_bits_this_service",
                self.transmitted_equivalent_bits_this_service,
            ),
            (
                "progress_before_equivalent_bits",
                self.progress_before_equivalent_bits,
            ),
            (
                "progress_after_equivalent_bits",
                self.progress_after_equivalent_bits,
            ),
            (
                "remaining_before_equivalent_bits",
                self.remaining_before_equivalent_bits,
            ),
            (
                "remaining_after_equivalent_bits",
                self.remaining_after_equivalent_bits,
            ),
            (
                "unused_contact_capacity_bits",
                self.unused_contact_capacity_bits,
            ),
            ("utilization_ratio", self.utilization_ratio),
            (
                "storage_freed_equivalent_bits",
                self.storage_freed_equivalent_bits,
            ),
        )
        for name, value in numeric_fields:
            _require_finite_float(name, value)

        total = self.record.stored_equivalent_bits
        before = self.progress_before_equivalent_bits
        service = self.transmitted_equivalent_bits_this_service
        capacity = self.capacity_proposal.nominal_contact_capacity_bits
        if not 0.0 <= before < total:
            raise ValueError(
                "progress_before_equivalent_bits must satisfy "
                "0 <= progress_before < stored total"
            )
        expected_remaining_before = _finite_difference(
            "remaining_before_equivalent_bits",
            total,
            before,
        )
        if expected_remaining_before <= 0.0:
            raise ValueError(
                "remaining_before_equivalent_bits must be strictly positive"
            )
        if self.remaining_before_equivalent_bits != expected_remaining_before:
            raise ValueError(
                "remaining_before_equivalent_bits must equal stored total "
                "minus progress_before"
            )
        if not 0.0 < service <= expected_remaining_before:
            raise ValueError(
                "transmitted_equivalent_bits_this_service must satisfy "
                "0 < service <= remaining_before"
            )

        expected_unused = _finite_difference(
            "unused_contact_capacity_bits",
            capacity,
            service,
        )
        if expected_unused < 0.0:
            raise ValueError(
                "unused_contact_capacity_bits must be greater than or equal "
                "to zero"
            )
        if self.unused_contact_capacity_bits != expected_unused:
            raise ValueError(
                "unused_contact_capacity_bits must equal capacity minus service"
            )
        expected_utilization = _finite_ratio(
            "utilization_ratio",
            service,
            capacity,
        )
        if not 0.0 < expected_utilization <= 1.0:
            raise ValueError("utilization_ratio must satisfy 0 < value <= 1")
        if self.utilization_ratio != expected_utilization:
            raise ValueError(
                "utilization_ratio must equal service divided by capacity"
            )

        if self.status is DownlinkTransmissionStatus.PARTIAL:
            if not capacity < expected_remaining_before:
                raise ValueError(
                    "PARTIAL requires capacity below remaining_before"
                )
            if service != capacity:
                raise ValueError("PARTIAL service must equal contact capacity")
            if self.unused_contact_capacity_bits != 0.0:
                raise ValueError("PARTIAL requires zero unused capacity")
            try:
                expected_after = fsum((before, service))
            except (OverflowError, ValueError) as error:
                raise ValueError(
                    "partial progress_after must be representable"
                ) from error
            _require_finite_float(
                "progress_after_equivalent_bits",
                expected_after,
            )
            if not before < expected_after < total:
                raise ValueError(
                    "PARTIAL requires before < progress_after < stored total"
                )
            expected_remaining_after = _finite_difference(
                "remaining_after_equivalent_bits",
                total,
                expected_after,
            )
            if not (
                0.0
                < expected_remaining_after
                < expected_remaining_before
            ):
                raise ValueError(
                    "PARTIAL requires 0 < remaining_after < remaining_before"
                )
            if self.progress_after_equivalent_bits != expected_after:
                raise ValueError(
                    "PARTIAL progress_after must equal fsum of before and service"
                )
            if self.remaining_after_equivalent_bits != expected_remaining_after:
                raise ValueError(
                    "PARTIAL remaining_after must equal total minus progress_after"
                )
            if self.storage_freed_equivalent_bits != 0.0:
                raise ValueError("PARTIAL requires zero storage freed")
            return

        if capacity < expected_remaining_before:
            raise ValueError(
                "COMPLETE requires capacity at least remaining_before"
            )
        if service != expected_remaining_before:
            raise ValueError("COMPLETE service must equal remaining_before")
        if self.progress_after_equivalent_bits != total:
            raise ValueError("COMPLETE progress_after must equal stored total")
        if self.remaining_after_equivalent_bits != 0.0:
            raise ValueError("COMPLETE requires zero remaining_after")
        if self.storage_freed_equivalent_bits != total:
            raise ValueError("COMPLETE storage freed must equal stored total")


def evaluate_downlink_transmission(
    communications_config: CommunicationsConfig,
    contact: ServiceableGroundContact,
    record: OnboardAcquisitionDataRecord,
    progress: DownlinkTransferProgress | None,
) -> DownlinkTransmissionResult:
    """Evaluate one contact's pure service of one acquisition-data record."""
    if type(communications_config) is not CommunicationsConfig:
        raise TypeError(
            "communications_config must be a CommunicationsConfig"
        )
    CommunicationsConfig(
        communications_config.configuration_id,
        communications_config.nominal_downlink_data_rate_bps,
    )
    if type(contact) is not ServiceableGroundContact:
        raise TypeError("contact must be a ServiceableGroundContact")
    ServiceableGroundContact(
        contact.contact_id,
        contact.ground_station_id,
        contact.start_time_seconds,
        contact.end_time_seconds,
    )
    if type(record) is not OnboardAcquisitionDataRecord:
        raise TypeError("record must be an OnboardAcquisitionDataRecord")
    _revalidate_record(record)
    _validate_acquisition_completed_by(
        record, contact.start_time_seconds, boundary="serviced contact start"
    )
    if progress is not None and type(progress) is not DownlinkTransferProgress:
        raise TypeError(
            "progress must be a DownlinkTransferProgress or None"
        )
    if progress is not None:
        DownlinkTransferProgress(
            progress.record_id,
            progress.transmitted_equivalent_bits,
        )
        if progress.record_id != record.record_id:
            raise ValueError("progress record_id must equal record.record_id")

    total = record.stored_equivalent_bits
    before = (
        0.0
        if progress is None
        else progress.transmitted_equivalent_bits
    )
    if not 0.0 <= before < total:
        raise ValueError(
            "progress must satisfy 0 < transmitted bits < stored total"
        )
    remaining_before = _finite_difference(
        "remaining_before_equivalent_bits",
        total,
        before,
    )
    if remaining_before <= 0.0:
        raise ValueError(
            "remaining_before_equivalent_bits must be strictly positive"
        )

    capacity_proposal = compute_downlink_capacity(
        communications_config,
        contact,
    )
    if type(capacity_proposal) is not DownlinkCapacityProposal:
        raise TypeError("capacity evaluator must return DownlinkCapacityProposal")
    _revalidate_capacity_proposal(capacity_proposal)
    capacity = capacity_proposal.nominal_contact_capacity_bits
    service = min(capacity, remaining_before)
    _require_finite_float(
        "transmitted_equivalent_bits_this_service",
        service,
    )
    if service <= 0.0:
        raise ValueError(
            "transmitted_equivalent_bits_this_service must be strictly positive"
        )

    if capacity >= remaining_before:
        status = DownlinkTransmissionStatus.COMPLETE
        after = total
        remaining_after = 0.0
        storage_freed = total
    else:
        status = DownlinkTransmissionStatus.PARTIAL
        try:
            after = fsum((before, service))
        except (OverflowError, ValueError) as error:
            raise ValueError("partial progress must be representable") from error
        _require_finite_float("progress_after_equivalent_bits", after)
        remaining_after = _finite_difference(
            "remaining_after_equivalent_bits",
            total,
            after,
        )
        if not before < after < total:
            raise ValueError(
                "PARTIAL requires before < progress_after < stored total"
            )
        if not 0.0 < remaining_after < remaining_before:
            raise ValueError(
                "PARTIAL requires 0 < remaining_after < remaining_before"
            )
        storage_freed = 0.0

    unused_capacity = _finite_difference(
        "unused_contact_capacity_bits",
        capacity,
        service,
    )
    if unused_capacity < 0.0:
        raise ValueError(
            "unused_contact_capacity_bits must be greater than or equal to zero"
        )
    utilization = _finite_ratio(
        "utilization_ratio",
        service,
        capacity,
    )
    if not 0.0 < utilization <= 1.0:
        raise ValueError("utilization_ratio must satisfy 0 < value <= 1")

    return DownlinkTransmissionResult(
        record,
        capacity_proposal,
        status,
        service,
        before,
        after,
        remaining_before,
        remaining_after,
        unused_capacity,
        utilization,
        storage_freed,
    )


__all__ = [
    "DownlinkTransmissionStatus",
    "DownlinkTransmissionResult",
    "evaluate_downlink_transmission",
]
