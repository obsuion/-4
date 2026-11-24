"""Pure onboard-storage capacity and whole-record admission semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import fsum, isfinite

from .configuration import StorageConfig
from .onboard_data import OnboardAcquisitionDataRecord


_BITS_PER_DECIMAL_GIGABYTE = 8_000_000_000.0


class StorageAdmissionStatus(str, Enum):
    """Whole-record storage-admission classifications."""

    ADMISSIBLE = "admissible"
    INSUFFICIENT_CAPACITY = "insufficient-capacity"


def _revalidate_storage_config(storage_config: StorageConfig) -> None:
    StorageConfig(
        storage_config.configuration_id,
        storage_config.usable_capacity_gb,
    )


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


def _validate_finite_builtin_float(name: str, value: object) -> None:
    if type(value) is not float:
        raise TypeError(f"{name} must be a built-in float")
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _finite_fsum(name: str, values: tuple[float, ...]) -> float:
    try:
        total = fsum(values)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    if type(total) is not float or not isfinite(total):
        raise ValueError(f"{name} cannot be represented as finite")
    return total


def _configured_capacity_bits(storage_config: StorageConfig) -> float:
    try:
        capacity_bits = float(
            storage_config.usable_capacity_gb.value
            * _BITS_PER_DECIMAL_GIGABYTE
        )
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            "configured usable capacity cannot be represented as finite bits"
        ) from error
    if type(capacity_bits) is not float or not isfinite(capacity_bits):
        raise ValueError(
            "configured usable capacity cannot be represented as finite bits"
        )
    if capacity_bits <= 0:
        raise ValueError(
            "configured usable capacity bits must be greater than zero"
        )
    return capacity_bits


def _validated_storage_occupancy(
    storage_config: StorageConfig,
    stored_records: tuple[OnboardAcquisitionDataRecord, ...],
) -> tuple[float, float, tuple[float, ...]]:
    if type(storage_config) is not StorageConfig:
        raise TypeError("storage_config must be a StorageConfig")
    _revalidate_storage_config(storage_config)
    if type(stored_records) is not tuple:
        raise TypeError("stored_records must be a built-in tuple")
    for record in stored_records:
        if type(record) is not OnboardAcquisitionDataRecord:
            raise TypeError(
                "stored_records must contain OnboardAcquisitionDataRecord values"
            )
        _revalidate_record(record)

    existing_record_ids = tuple(record.record_id for record in stored_records)
    if len(set(existing_record_ids)) != len(existing_record_ids):
        raise ValueError("stored record IDs must be unique")

    capacity_bits = _configured_capacity_bits(storage_config)
    stored_values = tuple(
        record.stored_equivalent_bits for record in stored_records
    )
    stored_before = _finite_fsum(
        "stored_equivalent_bits_before",
        stored_values,
    )
    if stored_before > capacity_bits:
        raise ValueError(
            "existing stored-equivalent-bit occupancy exceeds configured capacity"
        )
    return capacity_bits, stored_before, stored_values


def validate_storage_records_against_config(
    storage_config: StorageConfig,
    stored_records: tuple[OnboardAcquisitionDataRecord, ...],
) -> None:
    """Validate ordered stored records against configured usable capacity."""
    _validated_storage_occupancy(storage_config, stored_records)


@dataclass(frozen=True, slots=True)
class StorageAdmissionResult:
    """Pure whole-record admission evidence without storage mutation."""

    proposed_record: OnboardAcquisitionDataRecord
    configured_usable_capacity_bits: float
    stored_equivalent_bits_before: float
    available_capacity_bits_before: float
    stored_equivalent_bits_after_if_admitted: float
    status: StorageAdmissionStatus

    def __post_init__(self) -> None:
        if type(self.proposed_record) is not OnboardAcquisitionDataRecord:
            raise TypeError(
                "proposed_record must be an OnboardAcquisitionDataRecord"
            )
        _revalidate_record(self.proposed_record)

        for name in (
            "configured_usable_capacity_bits",
            "stored_equivalent_bits_before",
            "available_capacity_bits_before",
            "stored_equivalent_bits_after_if_admitted",
        ):
            _validate_finite_builtin_float(name, getattr(self, name))

        capacity = self.configured_usable_capacity_bits
        stored_before = self.stored_equivalent_bits_before
        available_before = self.available_capacity_bits_before
        stored_after = self.stored_equivalent_bits_after_if_admitted

        if capacity <= 0:
            raise ValueError(
                "configured_usable_capacity_bits must be greater than zero"
            )
        if stored_before < 0:
            raise ValueError(
                "stored_equivalent_bits_before must be greater than or equal "
                "to zero"
            )
        if available_before < 0:
            raise ValueError(
                "available_capacity_bits_before must be greater than or equal "
                "to zero"
            )
        if stored_after <= 0:
            raise ValueError(
                "stored_equivalent_bits_after_if_admitted must be greater "
                "than zero"
            )
        if stored_before > capacity:
            raise ValueError(
                "stored_equivalent_bits_before must not exceed configured "
                "usable capacity"
            )

        expected_available = capacity - stored_before
        if available_before != expected_available:
            raise ValueError(
                "available_capacity_bits_before must equal configured capacity "
                "minus stored volume exactly"
            )

        if stored_after <= stored_before:
            raise ValueError(
                "proposed record must increase represented occupancy; "
                "numerical resolution was insufficient"
            )
        if stored_after < self.proposed_record.stored_equivalent_bits:
            raise ValueError(
                "stored_equivalent_bits_after_if_admitted must be greater "
                "than or equal to proposed record volume"
            )

        if type(self.status) is not StorageAdmissionStatus:
            raise TypeError("status must be a StorageAdmissionStatus")
        expected_status = (
            StorageAdmissionStatus.ADMISSIBLE
            if stored_after <= capacity
            else StorageAdmissionStatus.INSUFFICIENT_CAPACITY
        )
        if self.status is not expected_status:
            raise ValueError("status is inconsistent with storage capacity")


def evaluate_storage_admission(
    storage_config: StorageConfig,
    stored_records: tuple[OnboardAcquisitionDataRecord, ...],
    proposed_record: OnboardAcquisitionDataRecord,
) -> StorageAdmissionResult:
    """Evaluate whether one complete acquisition-data record fits."""
    capacity_bits, stored_before, stored_values = _validated_storage_occupancy(
        storage_config,
        stored_records,
    )
    if type(proposed_record) is not OnboardAcquisitionDataRecord:
        raise TypeError(
            "proposed_record must be an OnboardAcquisitionDataRecord"
        )
    _revalidate_record(proposed_record)

    existing_record_ids = tuple(record.record_id for record in stored_records)
    if proposed_record.record_id in existing_record_ids:
        raise ValueError("proposed record ID must not already be stored")

    stored_after = _finite_fsum(
        "stored_equivalent_bits_after_if_admitted",
        stored_values + (proposed_record.stored_equivalent_bits,),
    )
    if stored_after <= stored_before:
        raise ValueError(
            "proposed record must increase represented occupancy; numerical "
            "resolution was insufficient"
        )

    available_before = capacity_bits - stored_before
    if not isfinite(available_before) or available_before < 0:
        raise ValueError(
            "available capacity cannot be represented as finite nonnegative bits"
        )
    status = (
        StorageAdmissionStatus.ADMISSIBLE
        if stored_after <= capacity_bits
        else StorageAdmissionStatus.INSUFFICIENT_CAPACITY
    )
    return StorageAdmissionResult(
        proposed_record,
        capacity_bits,
        stored_before,
        available_before,
        stored_after,
        status,
    )


__all__ = [
    "StorageAdmissionStatus",
    "StorageAdmissionResult",
    "evaluate_storage_admission",
    "validate_storage_records_against_config",
]
