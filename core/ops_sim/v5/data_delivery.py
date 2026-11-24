"""Persistent acquisition-data transfer progress and completed delivery truth."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .communications import ServiceableGroundContact
from .ids import AcquisitionDataRecordId
from .onboard_data import OnboardAcquisitionDataRecord


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


def _validate_acquisition_completed_by(
    record: OnboardAcquisitionDataRecord,
    time_seconds: int,
    *,
    boundary: str,
) -> None:
    """Compare already revalidated acquisition and boundary times exactly.

    A standalone record can describe a future acquisition. Custody and service
    owners supply the time by which that acquisition must have completed.
    """
    acquisition_end_seconds = (
        record.scheduled_start_seconds + record.acquisition_duration_seconds
    )
    if acquisition_end_seconds > time_seconds:
        raise ValueError(f"acquisition must end no later than {boundary}")


def _revalidate_contact(contact: ServiceableGroundContact) -> None:
    ServiceableGroundContact(
        contact.contact_id,
        contact.ground_station_id,
        contact.start_time_seconds,
        contact.end_time_seconds,
    )


@dataclass(frozen=True, slots=True)
class DownlinkTransferProgress:
    """Strictly positive transmitted progress for one onboard record."""

    record_id: AcquisitionDataRecordId
    transmitted_equivalent_bits: float

    def __post_init__(self) -> None:
        if type(self.record_id) is not AcquisitionDataRecordId:
            raise TypeError("record_id must be an AcquisitionDataRecordId")
        AcquisitionDataRecordId(self.record_id.value)
        if type(self.transmitted_equivalent_bits) is not float:
            raise TypeError(
                "transmitted_equivalent_bits must be a built-in float"
            )
        if not isfinite(self.transmitted_equivalent_bits):
            raise ValueError("transmitted_equivalent_bits must be finite")
        if self.transmitted_equivalent_bits <= 0.0:
            raise ValueError(
                "transmitted_equivalent_bits must be strictly greater than zero"
            )


@dataclass(frozen=True, slots=True)
class CompletedAcquisitionDelivery:
    """One immutable acquisition record and its completing ground contact."""

    record: OnboardAcquisitionDataRecord
    completing_contact: ServiceableGroundContact

    def __post_init__(self) -> None:
        if type(self.record) is not OnboardAcquisitionDataRecord:
            raise TypeError(
                "record must be an OnboardAcquisitionDataRecord"
            )
        _revalidate_record(self.record)
        if type(self.completing_contact) is not ServiceableGroundContact:
            raise TypeError(
                "completing_contact must be a ServiceableGroundContact"
            )
        _revalidate_contact(self.completing_contact)


@dataclass(slots=True)
class GroundDataDeliveryState:
    """Authoritative ordered transfer progress and completed deliveries."""

    partial_transfers: tuple[DownlinkTransferProgress, ...]
    completed_deliveries: tuple[CompletedAcquisitionDelivery, ...]

    def __post_init__(self) -> None:
        if type(self.partial_transfers) is not tuple:
            raise TypeError("partial_transfers must be a built-in tuple")
        if not all(
            type(progress) is DownlinkTransferProgress
            for progress in self.partial_transfers
        ):
            raise TypeError(
                "partial_transfers must contain only "
                "DownlinkTransferProgress values"
            )
        for progress in self.partial_transfers:
            DownlinkTransferProgress(
                progress.record_id,
                progress.transmitted_equivalent_bits,
            )
        partial_record_ids = tuple(
            progress.record_id for progress in self.partial_transfers
        )
        if len(set(partial_record_ids)) != len(partial_record_ids):
            raise ValueError("partial-transfer record IDs must be unique")

        if type(self.completed_deliveries) is not tuple:
            raise TypeError("completed_deliveries must be a built-in tuple")
        if not all(
            type(delivery) is CompletedAcquisitionDelivery
            for delivery in self.completed_deliveries
        ):
            raise TypeError(
                "completed_deliveries must contain only "
                "CompletedAcquisitionDelivery values"
            )
        for delivery in self.completed_deliveries:
            CompletedAcquisitionDelivery(
                delivery.record,
                delivery.completing_contact,
            )
        completed_record_ids = tuple(
            delivery.record.record_id
            for delivery in self.completed_deliveries
        )
        if len(set(completed_record_ids)) != len(completed_record_ids):
            raise ValueError("completed-delivery record IDs must be unique")


def _validate_delivery_state_against_storage_and_time(
    state: GroundDataDeliveryState,
    stored_records: tuple[OnboardAcquisitionDataRecord, ...],
    simulation_time_seconds: int,
) -> None:
    """Apply cross-domain custody, progress, and chronology invariants."""
    if type(state) is not GroundDataDeliveryState:
        raise TypeError("state must be a GroundDataDeliveryState")
    GroundDataDeliveryState(
        state.partial_transfers,
        state.completed_deliveries,
    )
    if type(stored_records) is not tuple:
        raise TypeError("stored_records must be a built-in tuple")
    if not all(
        type(record) is OnboardAcquisitionDataRecord
        for record in stored_records
    ):
        raise TypeError(
            "stored_records must contain only OnboardAcquisitionDataRecord values"
        )
    for record in stored_records:
        _revalidate_record(record)
    if type(simulation_time_seconds) is not int:
        raise TypeError("simulation_time_seconds must be a built-in int")
    if simulation_time_seconds < 0:
        raise ValueError(
            "simulation_time_seconds must be greater than or equal to zero"
        )

    for record in stored_records:
        _validate_acquisition_completed_by(
            record, simulation_time_seconds, boundary="simulation time"
        )

    stored_by_id = {record.record_id: record for record in stored_records}
    partial_ids = {
        progress.record_id for progress in state.partial_transfers
    }
    completed_ids = {
        delivery.record.record_id
        for delivery in state.completed_deliveries
    }
    if partial_ids & completed_ids:
        raise ValueError(
            "completed record IDs must be disjoint from partial-transfer IDs"
        )

    for progress in state.partial_transfers:
        record = stored_by_id.get(progress.record_id)
        if record is None:
            raise ValueError(
                "each partial-transfer record ID must identify one currently "
                "onboard record"
            )
        if progress.transmitted_equivalent_bits >= (
            record.stored_equivalent_bits
        ):
            raise ValueError(
                "partial transmitted_equivalent_bits must be strictly less "
                "than the onboard record stored_equivalent_bits"
            )

    stored_ids = set(stored_by_id)
    if completed_ids & stored_ids:
        raise ValueError(
            "completed record IDs must be disjoint from currently onboard "
            "record IDs"
        )
    for delivery in state.completed_deliveries:
        _validate_acquisition_completed_by(
            delivery.record,
            delivery.completing_contact.start_time_seconds,
            boundary="completing contact start",
        )
        if delivery.completing_contact.end_time_seconds > (
            simulation_time_seconds
        ):
            raise ValueError(
                "completing contact end must not exceed simulation time"
            )


__all__ = [
    "DownlinkTransferProgress",
    "CompletedAcquisitionDelivery",
    "GroundDataDeliveryState",
]
