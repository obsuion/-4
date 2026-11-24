"""Immutable optical-payload acquisition configuration for V5."""

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
    require_integral: bool,
) -> None:
    if type(parameter) is not ScalarParameter:
        raise TypeError(f"{field_name} must be a ScalarParameter")
    ScalarParameter(parameter.value, parameter.provenance)
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
    if value <= 0:
        raise ValueError(f"{field_name} must be strictly greater than zero")
    if require_integral and not (
        type(value) is int or (type(value) is float and value.is_integer())
    ):
        raise ValueError(f"{field_name} must have an exact integral value")


@dataclass(frozen=True, slots=True)
class OpticalAcquisitionConfig:
    """Own optical acquisition semantics without runtime execution physics.

    Reference sample spacings are Level-1 sampling proxies, not claims of
    exact detector pitch, raw GSD, readout cadence, or off-nadir sampling.
    Acquisition power is payload electrical demand only and is not retained
    thermal heat or power for the platform, ADCS, communications, or storage.
    """

    reference_nadir_swath_width_m: ScalarParameter
    panchromatic_reference_sample_spacing_m: ScalarParameter
    multispectral_reference_sample_spacing_m: ScalarParameter
    multispectral_band_count: ScalarParameter
    acquisition_bits_per_sample: ScalarParameter
    acquisition_power_w: ScalarParameter
    simultaneous_pan_and_multispectral: bool

    def __post_init__(self) -> None:
        contracts = (
            (
                "reference_nadir_swath_width_m",
                self.reference_nadir_swath_width_m,
                "payload.optical.reference-nadir-swath-width",
                "m",
                False,
            ),
            (
                "panchromatic_reference_sample_spacing_m",
                self.panchromatic_reference_sample_spacing_m,
                "payload.optical.panchromatic-reference-sample-spacing",
                "m",
                False,
            ),
            (
                "multispectral_reference_sample_spacing_m",
                self.multispectral_reference_sample_spacing_m,
                "payload.optical.multispectral-reference-sample-spacing",
                "m",
                False,
            ),
            (
                "multispectral_band_count",
                self.multispectral_band_count,
                "payload.optical.multispectral-band-count",
                "1",
                True,
            ),
            (
                "acquisition_bits_per_sample",
                self.acquisition_bits_per_sample,
                "payload.optical.acquisition-bits-per-sample",
                "bit/sample",
                True,
            ),
            (
                "acquisition_power_w",
                self.acquisition_power_w,
                "payload.optical.acquisition-power",
                "W",
                False,
            ),
        )
        for field_name, parameter, parameter_id, units, integral in contracts:
            _validate_parameter(
                field_name,
                parameter,
                parameter_id=parameter_id,
                units=units,
                require_integral=integral,
            )
        if type(self.simultaneous_pan_and_multispectral) is not bool:
            raise TypeError(
                "simultaneous_pan_and_multispectral must be a boolean"
            )


__all__ = ["OpticalAcquisitionConfig"]
