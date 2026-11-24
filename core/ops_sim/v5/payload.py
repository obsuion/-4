"""Pure Level-1 optical acquisition power and sample-grid physics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Integral, Real

from .payload_config import OpticalAcquisitionConfig


_SECONDS_PER_HOUR = 3600
_BITS_PER_BYTE = 8


class OpticalAcquisitionChannelSelection(str, Enum):
    """Physical detector-family selection for one optical acquisition."""

    PANCHROMATIC_ONLY = "panchromatic-only"
    MULTISPECTRAL_ONLY = "multispectral-only"
    PAN_AND_MULTISPECTRAL = "pan-and-multispectral"


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


def _normalized_nonnegative_real(name: str, value: object) -> int | float:
    normalized = _normalized_real(name, value)
    if normalized < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return normalized


def _normalized_positive_real(name: str, value: object) -> int | float:
    normalized = _normalized_real(name, value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return normalized


def _checked_sum(name: str, *values: object) -> int | float:
    """Add finite values using ordinary built-in arithmetic."""
    total: int | float = 0
    for index, value in enumerate(values):
        addend = _normalized_real(f"{name} addend {index}", value)
        try:
            total = total + addend
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented as finite"
            ) from error
        total = _normalized_real(name, total)
    return total


def _checked_product(name: str, *values: object) -> int | float:
    """Multiply finite values and reject nonzero representational underflow."""
    product: int | float = 1
    for index, value in enumerate(values):
        factor = _normalized_real(f"{name} factor {index}", value)
        prior_product = product
        try:
            product = product * factor
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented as finite"
            ) from error
        product = _normalized_real(name, product)
        if prior_product != 0 and factor != 0 and product == 0:
            raise ValueError(f"{name} cannot represent a nonzero product")
    return product


def _checked_quotient(
    name: str,
    numerator: object,
    denominator: object,
) -> int | float:
    """Divide finite values and reject nonzero representational underflow."""
    numerator_value = _normalized_real(f"{name} numerator", numerator)
    denominator_value = _normalized_real(f"{name} denominator", denominator)
    if denominator_value == 0:
        raise ValueError(f"{name} denominator must not be zero")
    try:
        quotient = numerator_value / denominator_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    normalized = _normalized_real(name, quotient)
    if numerator_value != 0 and normalized == 0:
        raise ValueError(f"{name} cannot represent a nonzero quotient")
    return normalized


@dataclass(frozen=True, slots=True)
class OpticalAcquisitionInput:
    """Explicit effective footprint, duration, and physical channel selection."""

    effective_cross_track_width_m: float
    effective_along_track_length_m: float
    imaging_duration_seconds: int
    channel_selection: OpticalAcquisitionChannelSelection

    def __post_init__(self) -> None:
        _normalized_positive_real(
            "effective_cross_track_width_m",
            self.effective_cross_track_width_m,
        )
        _normalized_positive_real(
            "effective_along_track_length_m",
            self.effective_along_track_length_m,
        )
        if type(self.imaging_duration_seconds) is not int:
            raise TypeError("imaging_duration_seconds must be an integer")
        if self.imaging_duration_seconds <= 0:
            raise ValueError(
                "imaging_duration_seconds must be greater than zero"
            )
        if type(self.channel_selection) is not (
            OpticalAcquisitionChannelSelection
        ):
            raise TypeError(
                "channel_selection must be an "
                "OpticalAcquisitionChannelSelection"
            )


@dataclass(frozen=True, slots=True)
class OpticalAcquisitionResult:
    """Uncompressed ground-sample-equivalent acquisition ledger."""

    footprint_area_m2: float
    panchromatic_equivalent_samples: float
    multispectral_equivalent_samples_per_band: float
    multispectral_equivalent_samples_total: float
    total_equivalent_samples: float
    uncompressed_equivalent_bits: float
    uncompressed_equivalent_bytes: float
    requested_acquisition_power_w: float
    acquisition_energy_wh: float

    def __post_init__(self) -> None:
        _normalized_positive_real("footprint_area_m2", self.footprint_area_m2)
        panchromatic = _normalized_nonnegative_real(
            "panchromatic_equivalent_samples",
            self.panchromatic_equivalent_samples,
        )
        multispectral_per_band = _normalized_nonnegative_real(
            "multispectral_equivalent_samples_per_band",
            self.multispectral_equivalent_samples_per_band,
        )
        multispectral_total = _normalized_nonnegative_real(
            "multispectral_equivalent_samples_total",
            self.multispectral_equivalent_samples_total,
        )
        total = _normalized_positive_real(
            "total_equivalent_samples",
            self.total_equivalent_samples,
        )
        bits = _normalized_positive_real(
            "uncompressed_equivalent_bits",
            self.uncompressed_equivalent_bits,
        )
        byte_count = _normalized_positive_real(
            "uncompressed_equivalent_bytes",
            self.uncompressed_equivalent_bytes,
        )
        _normalized_positive_real(
            "requested_acquisition_power_w",
            self.requested_acquisition_power_w,
        )
        _normalized_positive_real(
            "acquisition_energy_wh",
            self.acquisition_energy_wh,
        )

        if (multispectral_per_band == 0) != (multispectral_total == 0):
            raise ValueError(
                "multispectral per-band and total samples must both be zero "
                "or both be positive"
            )
        expected_total = _checked_sum(
            "total_equivalent_samples",
            panchromatic,
            multispectral_total,
        )
        if total != expected_total:
            raise ValueError(
                "total_equivalent_samples must equal panchromatic plus total "
                "multispectral equivalent samples"
            )
        expected_bytes = _checked_quotient(
            "uncompressed_equivalent_bytes",
            bits,
            _BITS_PER_BYTE,
        )
        if byte_count != expected_bytes:
            raise ValueError(
                "uncompressed_equivalent_bytes must equal uncompressed "
                "equivalent bits divided by eight"
            )


def _validate_channel_selection(
    config: OpticalAcquisitionConfig,
    selection: OpticalAcquisitionChannelSelection,
) -> None:
    combined = OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL
    if config.simultaneous_pan_and_multispectral:
        if selection is not combined:
            raise ValueError(
                "a simultaneous PAN and multispectral configuration requires "
                "PAN_AND_MULTISPECTRAL channel selection"
            )
    elif selection is combined:
        raise ValueError(
            "a non-simultaneous configuration does not admit "
            "PAN_AND_MULTISPECTRAL channel selection"
        )


def compute_optical_acquisition(
    config: OpticalAcquisitionConfig,
    acquisition_input: OpticalAcquisitionInput,
) -> OpticalAcquisitionResult:
    """Compute a pure requested-power and continuous sample-grid proposal.

    The footprint and duration are explicit inputs. This calculation neither
    derives them from orbit or pointing nor treats the reference nadir swath as
    a feasibility bound. Data quantities exclude packet and file overhead.
    """
    if type(config) is not OpticalAcquisitionConfig:
        raise TypeError("config must be an OpticalAcquisitionConfig")
    if type(acquisition_input) is not OpticalAcquisitionInput:
        raise TypeError(
            "acquisition_input must be an OpticalAcquisitionInput"
        )

    OpticalAcquisitionConfig(
        config.reference_nadir_swath_width_m,
        config.panchromatic_reference_sample_spacing_m,
        config.multispectral_reference_sample_spacing_m,
        config.multispectral_band_count,
        config.acquisition_bits_per_sample,
        config.acquisition_power_w,
        config.simultaneous_pan_and_multispectral,
    )
    OpticalAcquisitionInput(
        acquisition_input.effective_cross_track_width_m,
        acquisition_input.effective_along_track_length_m,
        acquisition_input.imaging_duration_seconds,
        acquisition_input.channel_selection,
    )
    selection = acquisition_input.channel_selection
    _validate_channel_selection(config, selection)

    width_m = _normalized_positive_real(
        "effective_cross_track_width_m",
        acquisition_input.effective_cross_track_width_m,
    )
    length_m = _normalized_positive_real(
        "effective_along_track_length_m",
        acquisition_input.effective_along_track_length_m,
    )
    area_m2 = _checked_product("footprint_area_m2", width_m, length_m)

    pan_spacing_m = _normalized_positive_real(
        "panchromatic_reference_sample_spacing_m",
        config.panchromatic_reference_sample_spacing_m.value,
    )
    pan_sample_area_m2 = _checked_product(
        "panchromatic reference sample area",
        pan_spacing_m,
        pan_spacing_m,
    )
    potential_pan_samples = _checked_quotient(
        "panchromatic equivalent samples",
        area_m2,
        pan_sample_area_m2,
    )

    ms_spacing_m = _normalized_positive_real(
        "multispectral_reference_sample_spacing_m",
        config.multispectral_reference_sample_spacing_m.value,
    )
    ms_sample_area_m2 = _checked_product(
        "multispectral reference sample area",
        ms_spacing_m,
        ms_spacing_m,
    )
    potential_ms_samples_per_band = _checked_quotient(
        "multispectral equivalent samples per band",
        area_m2,
        ms_sample_area_m2,
    )
    ms_band_count = _normalized_positive_real(
        "multispectral_band_count",
        config.multispectral_band_count.value,
    )
    potential_ms_samples_total = _checked_product(
        "multispectral equivalent samples total",
        ms_band_count,
        potential_ms_samples_per_band,
    )

    if selection is OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY:
        panchromatic_samples = potential_pan_samples
        multispectral_samples_per_band: int | float = 0
        multispectral_samples_total: int | float = 0
    elif selection is OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY:
        panchromatic_samples = 0
        multispectral_samples_per_band = potential_ms_samples_per_band
        multispectral_samples_total = potential_ms_samples_total
    else:
        panchromatic_samples = potential_pan_samples
        multispectral_samples_per_band = potential_ms_samples_per_band
        multispectral_samples_total = potential_ms_samples_total

    total_samples = _checked_sum(
        "total_equivalent_samples",
        panchromatic_samples,
        multispectral_samples_total,
    )
    bits_per_sample = _normalized_positive_real(
        "acquisition_bits_per_sample",
        config.acquisition_bits_per_sample.value,
    )
    uncompressed_bits = _checked_product(
        "uncompressed_equivalent_bits",
        total_samples,
        bits_per_sample,
    )
    uncompressed_bytes = _checked_quotient(
        "uncompressed_equivalent_bytes",
        uncompressed_bits,
        _BITS_PER_BYTE,
    )
    requested_power_w = _normalized_positive_real(
        "requested_acquisition_power_w",
        config.acquisition_power_w.value,
    )
    requested_energy_w_seconds = _checked_product(
        "requested acquisition energy in watt-seconds",
        requested_power_w,
        acquisition_input.imaging_duration_seconds,
    )
    acquisition_energy_wh = _checked_quotient(
        "acquisition_energy_wh",
        requested_energy_w_seconds,
        _SECONDS_PER_HOUR,
    )

    return OpticalAcquisitionResult(
        area_m2,
        panchromatic_samples,
        multispectral_samples_per_band,
        multispectral_samples_total,
        total_samples,
        uncompressed_bits,
        uncompressed_bytes,
        requested_power_w,
        acquisition_energy_wh,
    )


__all__ = [
    "OpticalAcquisitionChannelSelection",
    "OpticalAcquisitionInput",
    "OpticalAcquisitionResult",
    "compute_optical_acquisition",
]
