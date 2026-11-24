"""Provenance-coupled scalar parameters for immutable V5 configuration."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from .ids import ParameterId
from .provenance import ParameterProvenance, ProvenanceStatus


@dataclass(frozen=True, slots=True)
class ScalarParameter:
    """One finite scalar value inseparably coupled to its provenance."""

    value: float
    provenance: ParameterProvenance

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, Real):
            raise TypeError("value must be a real finite number")
        try:
            finite = isfinite(self.value)
        except (OverflowError, TypeError):
            finite = False
        if not finite:
            raise ValueError("value must be finite")

        if type(self.provenance) is not ParameterProvenance:
            raise TypeError("provenance must be a ParameterProvenance")
        if self.provenance.status in {
            ProvenanceStatus.REJECTED,
            ProvenanceStatus.SUPERSEDED,
        }:
            raise ValueError(
                "REJECTED and SUPERSEDED provenance is not admissible"
            )

        sensitivity_range = self.provenance.sensitivity_range
        if sensitivity_range is not None and not (
            sensitivity_range.lower <= self.value <= sensitivity_range.upper
        ):
            raise ValueError("value must be within the sensitivity range")

    @property
    def parameter_id(self) -> ParameterId:
        """Return the semantic parameter identity from provenance."""
        return self.provenance.parameter_id

    @property
    def units(self) -> str:
        """Return the physical units from provenance."""
        return self.provenance.units


__all__ = ["ScalarParameter"]
