"""Immutable Level-1 battery-ageing model configuration for V5."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real

from .ids import ParameterId
from .parameters import ScalarParameter


def _normalized_real(name: str, value: object) -> int | float:
    """Return an admitted finite Real as a safe built-in scalar."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = bool(isfinite(value))
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")

    try:
        normalized = int(value) if isinstance(value, Integral) else float(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if type(normalized) not in {int, float}:
        raise ValueError(f"{name} must normalize to a built-in number")
    try:
        normalized_finite = bool(isfinite(normalized))
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if not normalized_finite:
        raise ValueError(f"{name} cannot be represented as a finite number")
    return normalized


def _validate_parameter(
    field_name: str,
    parameter: object,
    *,
    parameter_id: str,
    units: str,
    strictly_positive: bool,
) -> int | float:
    if type(parameter) is not ScalarParameter:
        raise TypeError(f"{field_name} must be a ScalarParameter")
    if (
        type(parameter.parameter_id) is not ParameterId
        or parameter.parameter_id.value != parameter_id
    ):
        raise ValueError(
            f"{field_name} must use ParameterId {parameter_id!r}"
        )
    if parameter.units != units:
        raise ValueError(f"{field_name} must use units {units!r}")
    value = _normalized_real(field_name, parameter.value)
    if strictly_positive and value <= 0:
        raise ValueError(f"{field_name} must be strictly greater than zero")
    if not strictly_positive and value < 0:
        raise ValueError(
            f"{field_name} must be greater than or equal to zero"
        )
    return value


@dataclass(frozen=True, slots=True)
class BatteryAgeingModelConfig:
    """Provenance-backed immutable Level-1 battery damage parameters."""

    reference_temperature_k: ScalarParameter
    calendar_damage_rate_per_second_at_reference: ScalarParameter
    calendar_activation_energy_j_per_mol: ScalarParameter
    cycling_damage_per_normalized_energy_throughput_at_reference: ScalarParameter
    cycling_activation_energy_j_per_mol: ScalarParameter

    def __post_init__(self) -> None:
        _validate_parameter(
            "reference_temperature_k",
            self.reference_temperature_k,
            parameter_id="degradation.battery.reference-temperature",
            units="K",
            strictly_positive=True,
        )
        _validate_parameter(
            "calendar_damage_rate_per_second_at_reference",
            self.calendar_damage_rate_per_second_at_reference,
            parameter_id=(
                "degradation.battery.calendar-damage-rate-at-reference"
            ),
            units="1/s",
            strictly_positive=False,
        )
        _validate_parameter(
            "calendar_activation_energy_j_per_mol",
            self.calendar_activation_energy_j_per_mol,
            parameter_id="degradation.battery.calendar-activation-energy",
            units="J/mol",
            strictly_positive=False,
        )
        _validate_parameter(
            "cycling_damage_per_normalized_energy_throughput_at_reference",
            self.cycling_damage_per_normalized_energy_throughput_at_reference,
            parameter_id=(
                "degradation.battery.cycling-damage-per-normalized-"
                "throughput-at-reference"
            ),
            units="1",
            strictly_positive=False,
        )
        _validate_parameter(
            "cycling_activation_energy_j_per_mol",
            self.cycling_activation_energy_j_per_mol,
            parameter_id="degradation.battery.cycling-activation-energy",
            units="J/mol",
            strictly_positive=False,
        )


__all__ = ["BatteryAgeingModelConfig"]
