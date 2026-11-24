"""Immutable parameter-provenance metadata for the V5 domain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Real

from .ids import ParameterId, SourceRecordId


class ProvenanceClass(str, Enum):
    PUBLIC_SPECIFICATION = "PUBLIC_SPECIFICATION"
    LITERATURE_VALUE = "LITERATURE_VALUE"
    DERIVED_VALUE = "DERIVED_VALUE"
    EXPLICIT_MODEL_ASSUMPTION = "EXPLICIT_MODEL_ASSUMPTION"


class ProvenanceStatus(str, Enum):
    TO_RESEARCH = "TO_RESEARCH"
    TO_VERIFY = "TO_VERIFY"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


def _validate_finite_real(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite")


def _validate_exact_text(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if value != value.strip():
        raise ValueError(
            f"{name} must not have leading or trailing whitespace"
        )


@dataclass(frozen=True, slots=True)
class SensitivityRange:
    """Inclusive sensitivity bounds in the parent parameter's units."""

    lower: float
    upper: float

    def __post_init__(self) -> None:
        _validate_finite_real("lower", self.lower)
        _validate_finite_real("upper", self.upper)
        if self.lower > self.upper:
            raise ValueError("lower must be less than or equal to upper")


@dataclass(frozen=True, slots=True)
class ParameterProvenance:
    """Machine-readable scientific provenance without a parameter value."""

    parameter_id: ParameterId
    classification: ProvenanceClass
    units: str
    source_ids: tuple[SourceRecordId, ...]
    status: ProvenanceStatus
    rationale: str | None = None
    derivation: str | None = None
    sensitivity_range: SensitivityRange | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.parameter_id, ParameterId):
            raise TypeError("parameter_id must be a ParameterId")
        if not isinstance(self.classification, ProvenanceClass):
            raise TypeError("classification must be a ProvenanceClass")
        if not isinstance(self.status, ProvenanceStatus):
            raise TypeError("status must be a ProvenanceStatus")
        _validate_exact_text("units", self.units)

        if not isinstance(self.source_ids, tuple):
            raise TypeError("source_ids must be a tuple")
        if not all(
            isinstance(source_id, SourceRecordId)
            for source_id in self.source_ids
        ):
            raise TypeError(
                "source_ids must contain only SourceRecordId values"
            )
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must not contain duplicates")

        if self.rationale is not None:
            _validate_exact_text("rationale", self.rationale)
        if self.derivation is not None:
            _validate_exact_text("derivation", self.derivation)
        if (
            self.sensitivity_range is not None
            and not isinstance(self.sensitivity_range, SensitivityRange)
        ):
            raise TypeError(
                "sensitivity_range must be a SensitivityRange or None"
            )

        externally_sourced = self.classification in {
            ProvenanceClass.PUBLIC_SPECIFICATION,
            ProvenanceClass.LITERATURE_VALUE,
        }
        source_required = self.status in {
            ProvenanceStatus.VERIFIED,
            ProvenanceStatus.TO_VERIFY,
        }
        if externally_sourced and source_required and not self.source_ids:
            raise ValueError(
                f"{self.classification.value} with {self.status.value} "
                "requires at least one source ID"
            )

        if (
            self.classification is ProvenanceClass.DERIVED_VALUE
            and self.derivation is None
        ):
            raise ValueError("derived values require a derivation")
        if (
            self.classification
            is ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
            and self.rationale is None
        ):
            raise ValueError("explicit model assumptions require a rationale")


__all__ = [
    "ParameterProvenance",
    "ProvenanceClass",
    "ProvenanceStatus",
    "SensitivityRange",
]
