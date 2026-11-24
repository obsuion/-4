"""Externally supplied contacts and pure nominal downlink capacity."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .configuration import CommunicationsConfig
from .ids import GroundContactId, GroundStationId


@dataclass(frozen=True, slots=True)
class ServiceableGroundContact:
    """One externally declared half-open serviceable ground-contact interval."""

    contact_id: GroundContactId
    ground_station_id: GroundStationId
    start_time_seconds: int
    end_time_seconds: int

    def __post_init__(self) -> None:
        if type(self.contact_id) is not GroundContactId:
            raise TypeError("contact_id must be a GroundContactId")
        GroundContactId(self.contact_id.value)
        if type(self.ground_station_id) is not GroundStationId:
            raise TypeError("ground_station_id must be a GroundStationId")
        GroundStationId(self.ground_station_id.value)
        if type(self.start_time_seconds) is not int:
            raise TypeError("start_time_seconds must be a built-in int")
        if type(self.end_time_seconds) is not int:
            raise TypeError("end_time_seconds must be a built-in int")
        if self.start_time_seconds < 0:
            raise ValueError(
                "start_time_seconds must be greater than or equal to zero"
            )
        if self.end_time_seconds <= self.start_time_seconds:
            raise ValueError(
                "end_time_seconds must be greater than start_time_seconds"
            )


def _revalidate_contact(contact: ServiceableGroundContact) -> None:
    ServiceableGroundContact(
        contact.contact_id,
        contact.ground_station_id,
        contact.start_time_seconds,
        contact.end_time_seconds,
    )


def _represented_capacity(rate: float, duration: int) -> float:
    try:
        capacity = float(rate * duration)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError("nominal contact capacity must be representable") from error
    if not isfinite(capacity):
        raise ValueError("nominal contact capacity must be finite")
    if capacity <= 0.0:
        raise ValueError(
            "nominal contact capacity must be strictly greater than zero"
        )
    return capacity


@dataclass(frozen=True, slots=True)
class DownlinkCapacityProposal:
    """Pure nominal data-link capacity evidence for one serviceable contact."""

    contact: ServiceableGroundContact
    nominal_downlink_data_rate_bps: float
    serviceable_contact_duration_seconds: int
    nominal_contact_capacity_bits: float

    def __post_init__(self) -> None:
        if type(self.contact) is not ServiceableGroundContact:
            raise TypeError("contact must be a ServiceableGroundContact")
        _revalidate_contact(self.contact)
        if type(self.nominal_downlink_data_rate_bps) is not float:
            raise TypeError(
                "nominal_downlink_data_rate_bps must be a built-in float"
            )
        if not isfinite(self.nominal_downlink_data_rate_bps):
            raise ValueError("nominal_downlink_data_rate_bps must be finite")
        if self.nominal_downlink_data_rate_bps <= 0.0:
            raise ValueError(
                "nominal_downlink_data_rate_bps must be strictly greater "
                "than zero"
            )
        if type(self.serviceable_contact_duration_seconds) is not int:
            raise TypeError(
                "serviceable_contact_duration_seconds must be a built-in int"
            )
        if self.serviceable_contact_duration_seconds <= 0:
            raise ValueError(
                "serviceable_contact_duration_seconds must be strictly "
                "greater than zero"
            )
        if type(self.nominal_contact_capacity_bits) is not float:
            raise TypeError(
                "nominal_contact_capacity_bits must be a built-in float"
            )
        if not isfinite(self.nominal_contact_capacity_bits):
            raise ValueError("nominal_contact_capacity_bits must be finite")
        if self.nominal_contact_capacity_bits <= 0.0:
            raise ValueError(
                "nominal_contact_capacity_bits must be strictly greater "
                "than zero"
            )

        expected_duration = (
            self.contact.end_time_seconds - self.contact.start_time_seconds
        )
        if self.serviceable_contact_duration_seconds != expected_duration:
            raise ValueError(
                "serviceable_contact_duration_seconds must equal the contact "
                "duration"
            )
        expected_capacity = _represented_capacity(
            self.nominal_downlink_data_rate_bps,
            self.serviceable_contact_duration_seconds,
        )
        if self.nominal_contact_capacity_bits != expected_capacity:
            raise ValueError(
                "nominal_contact_capacity_bits must equal rate times duration"
            )


def compute_downlink_capacity(
    communications_config: CommunicationsConfig,
    contact: ServiceableGroundContact,
) -> DownlinkCapacityProposal:
    """Compute nominal data-link capacity for one serviceable contact."""
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
    _revalidate_contact(contact)

    duration = contact.end_time_seconds - contact.start_time_seconds
    try:
        rate = float(
            communications_config.nominal_downlink_data_rate_bps.value
        )
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            "nominal_downlink_data_rate_bps must be representable as a float"
        ) from error
    if not isfinite(rate):
        raise ValueError("nominal_downlink_data_rate_bps must be finite")
    if rate <= 0.0:
        raise ValueError(
            "nominal_downlink_data_rate_bps must be strictly greater than zero"
        )
    capacity = _represented_capacity(rate, duration)
    return DownlinkCapacityProposal(
        contact,
        rate,
        duration,
        capacity,
    )


__all__ = [
    "ServiceableGroundContact",
    "DownlinkCapacityProposal",
    "compute_downlink_capacity",
]
