"""Pure degradation-aware EPS capability and capacity reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real

from .configuration import BatteryConfig, EPSConfig
from .state import DegradationState


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


def _normalized_retention(name: str, value: object) -> int | float:
    normalized = _normalized_positive_real(name, value)
    if normalized > 1:
        raise ValueError(f"{name} must be less than or equal to one")
    return normalized


def _checked_product(name: str, *values: object) -> int | float:
    """Multiply using ordinary built-in arithmetic with finite checks."""
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


def _checked_difference(
    name: str,
    minuend: object,
    subtrahend: object,
) -> int | float:
    """Subtract using ordinary built-in arithmetic with finite checks."""
    left = _normalized_real(f"{name} minuend", minuend)
    right = _normalized_real(f"{name} subtrahend", subtrahend)
    try:
        difference = left - right
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _normalized_real(name, difference)


@dataclass(frozen=True, slots=True)
class EPSCapabilityResult:
    """Start-of-interval EPS energy and generation capability."""

    battery_capacity_retention: float
    battery_usable_capacity_wh: float
    solar_generation_retention: float
    solar_nominal_generation_capability_w: float

    def __post_init__(self) -> None:
        _normalized_retention(
            "battery_capacity_retention",
            self.battery_capacity_retention,
        )
        _normalized_positive_real(
            "battery_usable_capacity_wh",
            self.battery_usable_capacity_wh,
        )
        _normalized_retention(
            "solar_generation_retention",
            self.solar_generation_retention,
        )
        _normalized_positive_real(
            "solar_nominal_generation_capability_w",
            self.solar_nominal_generation_capability_w,
        )


@dataclass(frozen=True, slots=True)
class BatteryCapacityReconciliationResult:
    """Observable reconciliation of stored energy to an aged endpoint cap."""

    proposed_end_energy_wh: float
    end_capacity_retention: float
    end_usable_capacity_wh: float
    unavailable_energy_wh: float
    authoritative_end_energy_wh: float

    def __post_init__(self) -> None:
        proposed = _normalized_nonnegative_real(
            "proposed_end_energy_wh",
            self.proposed_end_energy_wh,
        )
        _normalized_retention(
            "end_capacity_retention",
            self.end_capacity_retention,
        )
        capacity = _normalized_positive_real(
            "end_usable_capacity_wh",
            self.end_usable_capacity_wh,
        )
        unavailable = _normalized_nonnegative_real(
            "unavailable_energy_wh",
            self.unavailable_energy_wh,
        )
        authoritative = _normalized_nonnegative_real(
            "authoritative_end_energy_wh",
            self.authoritative_end_energy_wh,
        )

        if proposed <= capacity:
            if unavailable != 0:
                raise ValueError(
                    "unavailable_energy_wh must be zero when proposed energy "
                    "does not exceed endpoint capacity"
                )
            if authoritative != proposed:
                raise ValueError(
                    "authoritative_end_energy_wh must equal proposed energy "
                    "when reconciliation is inactive"
                )
        else:
            expected_unavailable = _checked_difference(
                "unavailable_energy_wh",
                proposed,
                capacity,
            )
            if unavailable != expected_unavailable:
                raise ValueError(
                    "unavailable_energy_wh must equal proposed energy minus "
                    "endpoint capacity"
                )
            if authoritative != capacity:
                raise ValueError(
                    "authoritative_end_energy_wh must equal endpoint capacity "
                    "when reconciliation is active"
                )


def compute_eps_capability(
    eps_config: EPSConfig,
    degradation_state: DegradationState,
) -> EPSCapabilityResult:
    """Derive current EPS capability from immutable config and runtime truth."""
    if type(eps_config) is not EPSConfig:
        raise TypeError("eps_config must be an EPSConfig")
    if type(degradation_state) is not DegradationState:
        raise TypeError("degradation_state must be a DegradationState")

    EPSConfig(
        eps_config.configuration_id,
        eps_config.battery,
        eps_config.solar_array,
    )
    DegradationState(
        degradation_state.battery,
        degradation_state.solar,
    )
    battery_retention = _normalized_retention(
        "battery_capacity_retention",
        degradation_state.battery.usable_capacity_retention,
    )
    solar_retention = _normalized_retention(
        "solar_generation_retention",
        degradation_state.solar.generation_retention,
    )
    battery_capacity = _checked_product(
        "battery_usable_capacity_wh",
        eps_config.battery.nominal_energy_wh.value,
        battery_retention,
    )
    solar_capability = _checked_product(
        "solar_nominal_generation_capability_w",
        eps_config.solar_array.nominal_generation_w.value,
        solar_retention,
    )
    return EPSCapabilityResult(
        battery_retention,
        battery_capacity,
        solar_retention,
        solar_capability,
    )


def validate_eps_capability_for_config(
    capability: EPSCapabilityResult,
    eps_config: EPSConfig,
) -> None:
    """Require one capability result to match the supplied EPS config."""
    if type(capability) is not EPSCapabilityResult:
        raise TypeError("capability must be an EPSCapabilityResult")
    if type(eps_config) is not EPSConfig:
        raise TypeError("eps_config must be an EPSConfig")

    EPSCapabilityResult(
        capability.battery_capacity_retention,
        capability.battery_usable_capacity_wh,
        capability.solar_generation_retention,
        capability.solar_nominal_generation_capability_w,
    )
    EPSConfig(
        eps_config.configuration_id,
        eps_config.battery,
        eps_config.solar_array,
    )

    battery_retention = _normalized_retention(
        "battery_capacity_retention",
        capability.battery_capacity_retention,
    )
    solar_retention = _normalized_retention(
        "solar_generation_retention",
        capability.solar_generation_retention,
    )
    expected_battery_capacity = _checked_product(
        "expected_battery_usable_capacity_wh",
        eps_config.battery.nominal_energy_wh.value,
        battery_retention,
    )
    expected_solar_capability = _checked_product(
        "expected_solar_nominal_generation_capability_w",
        eps_config.solar_array.nominal_generation_w.value,
        solar_retention,
    )
    actual_battery_capacity = _normalized_positive_real(
        "battery_usable_capacity_wh",
        capability.battery_usable_capacity_wh,
    )
    actual_solar_capability = _normalized_positive_real(
        "solar_nominal_generation_capability_w",
        capability.solar_nominal_generation_capability_w,
    )

    if actual_battery_capacity != expected_battery_capacity:
        raise ValueError(
            "battery_usable_capacity_wh must equal nominal battery energy "
            "multiplied by battery_capacity_retention"
        )
    if actual_solar_capability != expected_solar_capability:
        raise ValueError(
            "solar_nominal_generation_capability_w must equal nominal solar "
            "generation multiplied by solar_generation_retention"
        )


def compute_battery_capacity_reconciliation(
    proposed_end_energy_wh: float,
    battery_config: BatteryConfig,
    end_capacity_retention: float,
) -> BatteryCapacityReconciliationResult:
    """Reconcile a valid EPS proposal against the new endpoint energy cap."""
    if type(battery_config) is not BatteryConfig:
        raise TypeError("battery_config must be a BatteryConfig")
    BatteryConfig(
        battery_config.configuration_id,
        battery_config.nominal_energy_wh,
        battery_config.charge_efficiency,
        battery_config.discharge_efficiency,
        battery_config.max_charge_input_power_w,
        battery_config.max_discharge_output_power_w,
    )
    proposed = _normalized_nonnegative_real(
        "proposed_end_energy_wh",
        proposed_end_energy_wh,
    )
    retention = _normalized_retention(
        "end_capacity_retention",
        end_capacity_retention,
    )
    capacity = _checked_product(
        "end_usable_capacity_wh",
        battery_config.nominal_energy_wh.value,
        retention,
    )

    if proposed <= capacity:
        unavailable: int | float = 0.0
        authoritative = proposed
    else:
        unavailable = _checked_difference(
            "unavailable_energy_wh",
            proposed,
            capacity,
        )
        authoritative = capacity

    return BatteryCapacityReconciliationResult(
        proposed,
        retention,
        capacity,
        unavailable,
        authoritative,
    )


__all__ = [
    "BatteryCapacityReconciliationResult",
    "EPSCapabilityResult",
    "compute_battery_capacity_reconciliation",
    "compute_eps_capability",
    "validate_eps_capability_for_config",
]
